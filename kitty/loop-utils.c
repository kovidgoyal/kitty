/*
 * loop-utils.c
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "loop-utils.h"
#include "safe-wrappers.h"
#include <signal.h>

bool
init_loop_data(LoopData *ld) {
#ifdef HAS_EVENT_FD
    ld->wakeup_read_fd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    if (ld->wakeup_read_fd < 0) return false;
#else
    if (!self_pipe(ld->wakeup_fds, true)) return false;
    ld->wakeup_read_fd = ld->wakeup_fds[0];
#endif
    ld->signal_read_fd = -1;
#ifndef HAS_SIGNAL_FD
    ld->signal_fds[0] = -1; ld->signal_fds[1] = -1;
#endif
    return true;
}

#ifndef HAS_SIGNAL_FD
static int signal_write_fd = -1;

static void
handle_signal(int sig_num) {
    int save_err = errno;
    unsigned char byte = (unsigned char)sig_num;
    while(signal_write_fd != -1) {
        ssize_t ret = write(signal_write_fd, &byte, 1);
        if (ret < 0 && errno == EINTR) continue;
        break;
    }
    errno = save_err;
}
#endif


#define SIGNAL_SET \
    sigset_t signals = {0}; \
    sigemptyset(&signals); \
    sigaddset(&signals, SIGINT); sigaddset(&signals, SIGTERM); sigaddset(&signals, SIGCHLD); \

void
free_loop_data(LoopData *ld) {
#define CLOSE(which, idx) if (ld->which[idx] > -1) safe_close(ld->which[idx], __FILE__, __LINE__); ld->which[idx] = -1;
#ifndef HAS_EVENT_FD
    CLOSE(wakeup_fds, 0); CLOSE(wakeup_fds, 1);
#endif
#ifndef HAS_SIGNAL_FD
    CLOSE(signal_fds, 0); CLOSE(signal_fds, 1);
#endif
#undef CLOSE
    if (ld->signal_read_fd > -1) {
#ifdef HAS_SIGNAL_FD
        safe_close(ld->signal_read_fd, __FILE__, __LINE__);
        SIGNAL_SET
        sigprocmask(SIG_UNBLOCK, &signals, NULL);
#else
        signal_write_fd = -1;
#endif
        signal(SIGINT, SIG_DFL);
        signal(SIGTERM, SIG_DFL);
        signal(SIGCHLD, SIG_DFL);
    }
#ifdef HAS_EVENT_FD
    safe_close(ld->wakeup_read_fd, __FILE__, __LINE__);
#endif
    ld->signal_read_fd = -1; ld->wakeup_read_fd = -1;
}


void
wakeup_loop(LoopData *ld, bool in_signal_handler, const char *loop_name) {
    while(true) {
#ifdef HAS_EVENT_FD
        static const int64_t value = 1;
        ssize_t ret = write(ld->wakeup_read_fd, &value, sizeof value);
#else
        ssize_t ret = write(ld->wakeup_fds[1], "w", 1);
#endif
        if (ret < 0) {
            if (errno == EINTR) continue;
            if (!in_signal_handler) log_error("Failed to write to %s wakeup fd with error: %s", loop_name, strerror(errno));
        }
        break;
    }
}


bool
install_signal_handlers(LoopData *ld) {
#ifdef HAS_SIGNAL_FD
    SIGNAL_SET
    if (sigprocmask(SIG_BLOCK, &signals, NULL) == -1) return false;
    ld->signal_read_fd = signalfd(-1, &signals, SFD_NONBLOCK | SFD_CLOEXEC);
    if (ld->signal_read_fd == -1) return false;
#else
    if (!self_pipe(ld->signal_fds, true)) return false;
    signal_write_fd = ld->signal_fds[1];
    struct sigaction act = {.sa_handler=handle_signal};
#define SA(which) { if (sigaction(which, &act, NULL) != 0) return false; if (siginterrupt(which, false) != 0) return false; }
    SA(SIGINT); SA(SIGTERM); SA(SIGCHLD);
#undef SA
    ld->signal_read_fd = ld->signal_fds[0];
#endif
    return true;
}


void
read_signals(int fd, handle_signal_func callback, void *data) {
#ifdef HAS_SIGNAL_FD
    static struct signalfd_siginfo fdsi[32];
    while (true) {
        ssize_t s = read(fd, &fdsi, sizeof(fdsi));
        if (s < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN) break;
            log_error("Call to read() from read_signals() failed with error: %s", strerror(errno));
            break;
        }
        if (s == 0) break;
        size_t num_signals = s / sizeof(struct signalfd_siginfo);
        if (num_signals == 0 || num_signals * sizeof(struct signalfd_siginfo) != (size_t)s) {
            log_error("Incomplete signal read from signalfd");
            break;
        }
        for (size_t i = 0; i < num_signals; i++) callback(fdsi[i].ssi_signo, data);
    }
#else
    static char buf[256];
    while(true) {
        ssize_t len = read(fd, buf, sizeof(buf));
        if (len < 0) {
            if (errno == EINTR) continue;
            if (errno != EIO && errno != EAGAIN) log_error("Call to read() from read_signals() failed with error: %s", strerror(errno));
            break;
        }
        for (ssize_t i = 0; i < len; i++) callback(buf[i], data);
        if (len == 0) break;
    }
#endif
}
