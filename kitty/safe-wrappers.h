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
#include <sys/types.h>
#include <unistd.h>

static inline int
safe_lockf(int fd, int function, off_t size) {
    while (true) {
        int ret = lockf(fd, function, size);
        if (ret != 0 && (errno == EINTR)) continue;
        return ret;
    }
}

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

static inline int
safe_openat(int dirfd, const char *path, int flags, mode_t mode) {
    while (true) {
        int fd = openat(dirfd, path, flags, mode);
        if (fd == -1 && errno == EINTR) continue;
        return fd;
    }
}


static inline FILE *
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
safe_close(int fd, const char *file UNUSED, const int line UNUSED) {
#if 0
    printf("Closing fd: %d from file: %s line: %d\n", fd, file, line);
#endif
    while (close(fd) != 0 && errno == EINTR);
}

static inline int
safe_ftruncate(int fd, off_t length) {
    int ret;
    while ((ret = ftruncate(fd, length)) != 0 && errno == EINTR);
    return ret;
}

static inline ssize_t
safe_write(int fd, const void *buf, size_t nbyte) {
    ssize_t ret;
    while ((ret = write(fd, buf, nbyte)) != 0 && errno == EINTR);
    return ret;
}

static inline int
safe_dup(int a) {
    int ret;
    while ((ret = dup(a)) < 0 && errno == EINTR);
    return ret;
}

static inline int
safe_dup2(int a, int b) {
    int ret;
    while ((ret = dup2(a, b)) < 0 && errno == EINTR);
    return ret;
}

// Get the credentials of the process at the other end of the specified
// connected UNIX socket. Note that these are the credentials the peer had when
// it called connect()/bind() and the uid/gid are translated into the user
// namespace of the calling process, so they can be safely compared with
// geteuid()/getegid().
static inline bool
get_peer_credentials(int fd, uid_t *euid, gid_t *egid) {
#ifdef __linux__
    struct ucred cr;
    socklen_t sz = sizeof(cr);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &cr, &sz) != 0) return false;
    *euid = cr.uid;
    *egid = cr.gid;
#else
    if (getpeereid(fd, euid, egid) != 0) return false;
#endif
    return true;
}

// Can the credentials of processes connecting to the specified listening
// socket be obtained? Only possible for AF_UNIX sockets. Fails closed, i.e. if
// the socket family cannot be determined we claim credentials are available,
// which means peers will be denied since getting their credentials will fail.
static inline bool
peer_credentials_are_available(int fd) {
    struct sockaddr_storage addr = {0};
    socklen_t sz = sizeof(addr);
    if (getsockname(fd, (struct sockaddr *)&addr, &sz) != 0) return true;
    return addr.ss_family == AF_UNIX;
}
