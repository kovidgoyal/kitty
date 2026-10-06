/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <sys/types.h>
#include <time.h>
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
wait_for_pending_connect(int socket_fd) {
    // Wait for a connect() that is continuing in the background to complete,
    // honoring any send timeout set on the socket, as a blocking connect() would.
    struct timeval tv = {0};
    socklen_t sz = sizeof(tv);
    int64_t deadline = 0;
    if (getsockopt(socket_fd, SOL_SOCKET, SO_SNDTIMEO, &tv, &sz) == 0 && (tv.tv_sec > 0 || tv.tv_usec > 0)) {
        struct timespec now;
        if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return -1;
        deadline = (int64_t)now.tv_sec * 1000000000ll + now.tv_nsec + (int64_t)tv.tv_sec * 1000000000ll + (int64_t)tv.tv_usec * 1000ll;
    }
    struct pollfd pfd = {.fd = socket_fd, .events = POLLOUT};
    while (true) {
        int timeout_ms = -1;
        if (deadline) {
            struct timespec now;
            if (clock_gettime(CLOCK_MONOTONIC, &now) != 0) return -1;
            int64_t remaining = deadline - ((int64_t)now.tv_sec * 1000000000ll + now.tv_nsec);
            if (remaining <= 0) {
                errno = ETIMEDOUT;
                return -1;
            }
            remaining = (remaining + 999999ll) / 1000000ll;
            timeout_ms = remaining > INT_MAX ? INT_MAX : (int)remaining;
        }
        int ret = poll(&pfd, 1, timeout_ms);
        if (ret > 0) break;
        if (ret < 0 && errno != EINTR) return -1;
    }
    int err = 0;
    socklen_t errlen = sizeof(err);
    if (getsockopt(socket_fd, SOL_SOCKET, SO_ERROR, &err, &errlen) < 0) return -1;
    if (err != 0) {
        errno = err;
        return -1;
    }
    return 0;
}

static inline int
safe_connect(int socket_fd, struct sockaddr *addr, socklen_t addrlen) {
    /* What happens after connect() is interrupted by EINTR depends on the
     * socket type. AF_UNIX sockets on Linux are left unconnected and connect()
     * must simply be retried. For TCP the connection continues in the
     * background, so a retry fails with EALREADY while it is in progress or
     * EISCONN once it has succeeded. */
    bool interrupted = false;
    while (true) {
        if (connect(socket_fd, addr, addrlen) == 0) return 0;
        switch (errno) {
            case EINTR: interrupted = true; continue;
            case EAGAIN: continue;
            case EISCONN: return interrupted ? 0 : -1;
            case EALREADY: return interrupted ? wait_for_pending_connect(socket_fd) : -1;
            default: return -1;
        }
    }
}

static inline int
safe_bind(int socket_fd, struct sockaddr *addr, socklen_t addrlen) {
    while (true) {
        int ret = bind(socket_fd, addr, addrlen);
        if (ret < 0 && errno == EINTR) continue;
        return ret;
    }
}

static inline int
safe_accept(int socket_fd, struct sockaddr *addr, socklen_t *addrlen) {
    while (true) {
        int ret = accept(socket_fd, addr, addrlen);
        if (ret < 0 && errno == EINTR) continue;
        return ret;
    }
}

static inline int
safe_mkstemp(char *template) {
    /* mkostemp() replaces the trailing X characters of the template in place.
     * Restore them if it is interrupted by EINTR, otherwise the retry fails
     * with EINVAL. */
    size_t len = strlen(template), num_x = 0;
    while (num_x < len && template[len - 1 - num_x] == 'X') num_x++;
    while (true) {
        int fd = mkostemp(template, O_CLOEXEC);
        if (fd == -1 && errno == EINTR) {
            memset(template + len - num_x, 'X', num_x);
            continue;
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
    /* On Linux, macOS, FreeBSD, and OpenBSD, the file descriptor table entry is
     * released before handling signal interruptions. Retrying close() when
     * interrupted by EINTR is hazardous in multithreaded applications because
     * it can inadvertently close a descriptor reallocated by another thread. */
    (void)close(fd);
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
    while ((ret = write(fd, buf, nbyte)) < 0 && errno == EINTR);
    return ret;
}

// Write all of buf, returns 0 on success and -1 on failure with errno set
static inline int
safe_write_all(int fd, const void *buf, size_t nbyte) {
    const char *p = buf;
    while (nbyte > 0) {
        ssize_t ret = safe_write(fd, p, nbyte);
        if (ret < 0) return -1;
        if (ret == 0) {
            errno = EIO;
            return -1;
        }
        p += ret;
        nbyte -= (size_t)ret;
    }
    return 0;
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
