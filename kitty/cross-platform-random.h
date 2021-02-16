/*
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include <stdlib.h>
#include <stdbool.h>

#if __linux__
#include <errno.h>
#if __has_include(<sys/random.h>)
#include <sys/random.h>

static inline bool
secure_random_bytes(void *buf, size_t nbytes) {
    unsigned char* p = buf;
    ssize_t left = nbytes;
    while(1) {
        ssize_t n = getrandom(p, left, 0);
        if (n >= left) return true;
        if (n < 0) {
            if (errno != EINTR) return false;  // should never happen but if it does, we fail without any feedback
            continue;
        }
        left -= n; p += n;
    }
}
#else
#include "safe-wrappers.h"
static inline bool
secure_random_bytes(void *buf, size_t nbytes) {
    int fd = safe_open("/dev/urandom", O_RDONLY, 0);
    if (fd < 0) return false;
    size_t bytes_read = 0;
    while (bytes_read < nbytes) {
        ssize_t n = read(fd, (uint8_t*)buf + bytes_read, nbytes - bytes_read);
        if (n < 0) {
            if (errno == EINTR) continue;
            break;
        }
        bytes_read += n;
    }
    safe_close(fd, __FILE__, __LINE__);
    return bytes_read == nbytes;
}
#endif
#else
static inline bool
secure_random_bytes(void *buf, size_t nbytes) {
    arc4random_buf(buf, nbytes);
    return true;
}
#endif
