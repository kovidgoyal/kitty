/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <stdlib.h>

static inline int
safe_connect(int socket_fd, struct sockaddr *addr, socklen_t addrlen) {
    while (true) {
        int ret = connect(socket_fd, addr, addrlen);
        if (ret < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        return ret;
    }
}

static inline int
safe_bind(int socket_fd, struct sockaddr *addr, socklen_t addrlen) {
    while (true) {
        int ret = bind(socket_fd, addr, addrlen);
        if (ret < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        return ret;
    }
}

static inline int
safe_accept(int socket_fd, struct sockaddr *addr, socklen_t *addrlen) {
    while (true) {
        int ret = accept(socket_fd, addr, addrlen);
        if (ret < 0 && (errno == EINTR || errno == EAGAIN)) continue;
        return ret;
    }
}

static inline int
safe_mkstemp(char *template) {
    while (true) {
        int fd = mkstemp(template);
        if (fd == -1 && errno == EINTR) continue;
        if (fd > -1) {
            int flags = fcntl(fd, F_GETFD);
            if (flags > -1) fcntl(fd, F_SETFD, flags | FD_CLOEXEC);
        }
        return fd;
    }
}

static inline int
safe_open(const char *path, int flags, mode_t mode) {
    while (true) {
        int fd = open(path, flags, mode);
        if (fd == -1 && errno == EINTR) continue;
        return fd;
    }
}

static inline FILE*
safe_fopen(const char *path, const char *mode) {
    while (true) {
        FILE *f = fopen(path, mode);
        if (f == NULL && (errno == EINTR || errno == EAGAIN)) continue;
        return f;
    }
}


static inline int
safe_shm_open(const char *path, int flags, mode_t mode) {
    while (true) {
        int fd = shm_open(path, flags, mode);
        if (fd == -1 && errno == EINTR) continue;
        return fd;
    }
}


static inline void
safe_close(int fd, const char* file UNUSED, const int line UNUSED) {
#if 0
    printf("Closing fd: %d from file: %s line: %d\n", fd, file, line);
#endif
    while(close(fd) != 0 && errno == EINTR);
}

static inline int
safe_dup2(int a, int b) {
    int ret;
    while((ret = dup2(a, b)) < 0 && errno == EINTR);
    return ret;
}
