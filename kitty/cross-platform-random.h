/*
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include <stdlib.h>
#include <stdbool.h>

#if __linux__
#include <sys/random.h>
#include <errno.h>

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
static inline bool
secure_random_bytes(void *buf, size_t nbytes) {
    arc4random_buf(buf, nbytes);
    return true;
}
#endif
