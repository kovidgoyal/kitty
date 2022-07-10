/*
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#include <fcntl.h>
#include <unistd.h>
#include <signal.h>

#ifdef __has_include
#if __has_include(<sys/signalfd.h>)
#define HAS_SIGNAL_FD
#include <sys/signalfd.h>
#endif

#if __has_include(<sys/eventfd.h>)
#define HAS_EVENT_FD
#include <sys/eventfd.h>
#endif
#else
#define HAS_SIGNAL_FD
#include <sys/signalfd.h>
#define HAS_EVENT_FD
#include <sys/eventfd.h>
#endif

typedef struct {
#ifndef HAS_EVENT_FD
    int wakeup_fds[2];
#endif
#ifndef HAS_SIGNAL_FD
    int signal_fds[2];
#endif
    sigset_t signals;
    int wakeup_read_fd;
    int signal_read_fd;
    int handled_signals[16];
    size_t num_handled_signals;
} LoopData;
typedef bool(*handle_signal_func)(const siginfo_t* siginfo, void *data);

bool init_loop_data(LoopData *ld, ...);
void free_loop_data(LoopData *ld);
void wakeup_loop(LoopData *ld, bool in_signal_handler, const char*);
void read_signals(int fd, handle_signal_func callback, void *data);

static inline bool
self_pipe(int fds[2], bool nonblock) {
#ifdef __APPLE__
    int flags;
    flags = pipe(fds);
    if (flags != 0) return false;
    for (int i = 0; i < 2; i++) {
        flags = fcntl(fds[i], F_GETFD);
        if (flags == -1) {  return false; }
        if (fcntl(fds[i], F_SETFD, flags | FD_CLOEXEC) == -1) { return false; }
        if (nonblock) {
            flags = fcntl(fds[i], F_GETFL);
            if (flags == -1) { return false; }
            if (fcntl(fds[i], F_SETFL, flags | O_NONBLOCK) == -1) { return false; }
        }
    }
    return true;
#else
    int flags = O_CLOEXEC;
    if (nonblock) flags |= O_NONBLOCK;
    return pipe2(fds, flags) == 0;
#endif
}

static inline void
drain_fd(int fd) {
    static uint8_t drain_buf[1024];
    while(true) {
        ssize_t len = read(fd, drain_buf, sizeof(drain_buf));
        if (len < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (len > 0) continue;
        break;
    }
}
