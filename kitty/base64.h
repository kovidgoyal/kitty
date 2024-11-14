/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include "../3rdparty/base64/include/libbase64.h"

static inline size_t required_buffer_size_for_base64_decode(size_t src_sz) { return (src_sz / 4 * 3 + 2); }
static inline size_t required_buffer_size_for_base64_encode(size_t src_sz) { return ((src_sz + 2) / 3 * 4); }


static inline bool
base64_decode8(const uint8_t *src, size_t src_sz, uint8_t *dest, size_t *dest_sz) {
    if (*dest_sz < required_buffer_size_for_base64_decode(src_sz)) return false;
    // we ignore the return value of base64_decode as it returns non-zero when it is
    // waiting for padding bytes
    base64_decode((const char*)src, src_sz, (char*)dest, dest_sz, 0);
    return true;
}

static inline bool
base64_encode8(const unsigned char *src, size_t src_len, unsigned char *out, size_t *out_len, bool add_padding) {
    if (*out_len < required_buffer_size_for_base64_encode(src_len)) return false;
    base64_encode((const char*)src, src_len, (char*)out, out_len, 0);
    if (!add_padding) {
        while(*out_len && out[*out_len - 1] == '=') *out_len -= 1;
    }
    return true;
}
