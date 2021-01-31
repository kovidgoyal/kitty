/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"
#include <fcntl.h>
#include <sys/mman.h>


static inline int
safe_open(const char *path, int flags, mode_t mode) {
    while (true) {
        int fd = open(path, flags, mode);
        if (fd == -1 && errno == EINTR) continue;
        return fd;
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
