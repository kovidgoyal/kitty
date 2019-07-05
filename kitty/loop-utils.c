/*
 * loop-utils.c
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "loop-utils.h"
#include <signal.h>

bool
init_loop_data(LoopData *ld) {
    if (!self_pipe(ld->wakeup_fds, true)) return false;
    ld->wakeup_read_fd = ld->wakeup_fds[0];
    ld->signal_fds[0] = -1; ld->signal_fds[1] = -1; ld->signal_read_fd = -1;
    return true;
}

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


void
free_loop_data(LoopData *ld) {
#define CLOSE(which, idx) if (ld->which[idx] > -1) close(ld->which[idx]); ld->which[idx] = -1;
    CLOSE(wakeup_fds, 0); CLOSE(wakeup_fds, 1);
    CLOSE(signal_fds, 0); CLOSE(signal_fds, 1);
#undef CLOSE
    if (ld->signal_read_fd) {
        signal_write_fd = -1;
        signal(SIGINT, SIG_DFL);
        signal(SIGTERM, SIG_DFL);
        signal(SIGCHLD, SIG_DFL);
    }
    ld->signal_read_fd = -1; ld->wakeup_read_fd = -1;
}


void
wakeup_loop(LoopData *ld, bool in_signal_handler) {
    while(true) {
        ssize_t ret = write(ld->wakeup_fds[1], "w", 1);
        if (ret < 0) {
            if (errno == EINTR) continue;
            if (!in_signal_handler) log_error("Failed to write to loop wakeup fd with error: %s", strerror(errno));
        }
        break;
    }
}



bool
install_signal_handlers(LoopData *ld) {
    if (!self_pipe(ld->signal_fds, true)) return false;
    signal_write_fd = ld->signal_fds[1];
    struct sigaction act = {.sa_handler=handle_signal};
#define SA(which) { if (sigaction(which, &act, NULL) != 0) return false; if (siginterrupt(which, false) != 0) return false; }
    SA(SIGINT); SA(SIGTERM); SA(SIGCHLD);
#undef SA
    ld->signal_read_fd = ld->signal_fds[0];
    return true;
}

static inline void
read_signals_from_pipe_fd(int fd, handle_signal_func callback, void *data) {
    static char buf[256];
    while(true) {
        ssize_t len = read(fd, buf, sizeof(buf));
        if (len < 0) {
            if (errno == EINTR) continue;
            if (errno != EIO && errno != EAGAIN) log_error("Call to read() from read_signals_from_pipe_fd() failed with error: %s", strerror(errno));
            break;
        }
        for (ssize_t i = 0; i < len; i++) callback(buf[i], data);
        if (len == 0) break;
    }
}

void
read_signals(int fd, handle_signal_func callback, void *data) {
    read_signals_from_pipe_fd(fd, callback, data);
}
