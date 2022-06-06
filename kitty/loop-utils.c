/*
 * loop-utils.c
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "loop-utils.h"
#include "safe-wrappers.h"

#ifndef HAS_SIGNAL_FD
static int signal_write_fd = -1;

static void
handle_signal(int sig_num UNUSED, siginfo_t *si, void *ucontext UNUSED) {
    int save_err = errno;
    char *buf = (char*)si;
    size_t sz = sizeof(siginfo_t);
    while (signal_write_fd != -1 && sz) {
        // as long as sz is less than PIPE_BUF write will either write all or return -1 with EAGAIN
        // so we are guaranteed atomic writes
        ssize_t ret = write(signal_write_fd, buf, sz);
        if (ret <= 0) {
            if (errno == EINTR) continue;
            break;
        }
        sz -= ret;
        buf += ret;
    }
    errno = save_err;
}
#endif


bool
init_loop_data(LoopData *ld, size_t num_signals, ...) {
    ld->num_handled_signals = num_signals;
    va_list valist;
    va_start(valist, num_signals);
    for (size_t i = 0; i < ld->num_handled_signals; i++) {
        ld->handled_signals[i] = va_arg(valist, int);
    }
    va_end(valist);
#ifdef HAS_EVENT_FD
    ld->wakeup_read_fd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    if (ld->wakeup_read_fd < 0) return false;
#else
    if (!self_pipe(ld->wakeup_fds, true)) return false;
    ld->wakeup_read_fd = ld->wakeup_fds[0];
#endif
    ld->signal_read_fd = -1;
#ifdef HAS_SIGNAL_FD
    sigemptyset(&ld->signals);
    if (ld->num_handled_signals) {
        for (size_t i = 0; i < ld->num_handled_signals; i++) sigaddset(&ld->signals, ld->handled_signals[i]);
        if (sigprocmask(SIG_BLOCK, &ld->signals, NULL) == -1) return false;
        ld->signal_read_fd = signalfd(-1, &ld->signals, SFD_NONBLOCK | SFD_CLOEXEC);
        if (ld->signal_read_fd == -1) return false;
    }
#else
    ld->signal_fds[0] = -1; ld->signal_fds[1] = -1;
    if (ld->num_handled_signals) {
        if (!self_pipe(ld->signal_fds, true)) return false;
        signal_write_fd = ld->signal_fds[1];
        ld->signal_read_fd = ld->signal_fds[0];
        struct sigaction act = {.sa_sigaction=handle_signal, .sa_flags=SA_SIGINFO | SA_RESTART};
        for (size_t i = 0; i < ld->num_handled_signals; i++) { if (sigaction(ld->handled_signals[i], &act, NULL) != 0) return false; }
    }
#endif
    return true;
}


void
free_loop_data(LoopData *ld) {
#define CLOSE(which, idx) if (ld->which[idx] > -1) safe_close(ld->which[idx], __FILE__, __LINE__); ld->which[idx] = -1;
#ifndef HAS_EVENT_FD
    CLOSE(wakeup_fds, 0); CLOSE(wakeup_fds, 1);
#endif
#ifndef HAS_SIGNAL_FD
    signal_write_fd = -1;
    CLOSE(signal_fds, 0); CLOSE(signal_fds, 1);
#endif
#undef CLOSE
    if (ld->signal_read_fd > -1) {
#ifdef HAS_SIGNAL_FD
        safe_close(ld->signal_read_fd, __FILE__, __LINE__);
        sigprocmask(SIG_UNBLOCK, &ld->signals, NULL);
#endif
        for (size_t i = 0; i < ld->num_handled_signals; i++) signal(ld->num_handled_signals, SIG_DFL);
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


void
read_signals(int fd, handle_signal_func callback, void *data) {
#ifdef HAS_SIGNAL_FD
    static struct signalfd_siginfo fdsi[32];
    siginfo_t si;
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
        for (size_t i = 0; i < num_signals; i++) {
            si.si_signo = fdsi[i].ssi_signo;
            si.si_code = fdsi[i].ssi_code;
            si.si_pid = fdsi[i].ssi_pid;
            si.si_uid = fdsi[i].ssi_uid;
            si.si_addr = (void*)(uintptr_t)fdsi[i].ssi_addr;
            si.si_status = fdsi[i].ssi_status;
            si.si_value.sival_int = fdsi[i].ssi_int;
            callback(&si, data);
        }
    }
#else
    static char buf[sizeof(siginfo_t) * 8];
    static size_t buf_pos = 0;
    while(true) {
        ssize_t len = read(fd, buf + buf_pos, sizeof(buf) - buf_pos);
        if (len < 0) {
            if (errno == EINTR) continue;
            if (errno != EIO && errno != EAGAIN) log_error("Call to read() from read_signals() failed with error: %s", strerror(errno));
            break;
        }
        buf_pos += len;
        while (buf_pos >= sizeof(siginfo_t)) {
            callback((siginfo_t*)buf, data);
            memmove(buf, buf + sizeof(siginfo_t), sizeof(siginfo_t));
            buf_pos -= sizeof(siginfo_t);
        }
        if (len == 0) break;
    }
#endif
}
