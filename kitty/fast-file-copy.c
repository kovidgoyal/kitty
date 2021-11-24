/*
 * fast-file-copy.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#if __linux__
#define HAS_SENDFILE
#endif

#ifdef HAS_SENDFILE
#include <sys/sendfile.h>
#endif

bool
copy_between_files(int infd, int outfd, off_t in_pos, size_t len, uint8_t *buf, size_t bufsz) {
#ifdef HAS_SENDFILE
    (void)buf; (void)bufsz;
    unsigned num_of_consecutive_zero_returns = 128;
    while (len) {
        off_t r = in_pos;
        ssize_t n = sendfile(outfd, infd, &r, len);
        if (n < 0) {
            if (errno != EAGAIN) return false;
            continue;
        }
        if (n == 0) {
            // happens if input file is truncated
            if (!--num_of_consecutive_zero_returns) return false;
            continue;
        };
        num_of_consecutive_zero_returns = 128;
        in_pos += n; len -= n;
    }
#else
    while (len) {
        ssize_t amt_read = pread(infd, buf, MIN(len, bufsz), in_pos);
        if (amt_read < 0) {
            if (errno == EINTR || errno == EAGAIN) continue;
            return false;
        }
        if (amt_read == 0) {
            errno = EIO;
            return false;
        }
        len -= amt_read;
        in_pos += amt_read;
        uint8_t *p = buf;
        while(amt_read) {
            ssize_t amt_written = write(outfd, p, amt_read);
            if (amt_written < 0) {
                if (errno == EINTR || errno == EAGAIN) continue;
                return false;
            }
            if (amt_written == 0) {
                errno = EIO;
                return false;
            }
            amt_read -= amt_written;
            p += amt_written;
        }
    }
#endif
    return true;
}
