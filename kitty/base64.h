/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>

bool base64_decode8(const uint8_t *src, size_t src_sz, uint8_t *dest, size_t *dest_sz);
bool base64_encode8(const unsigned char *src, size_t src_len, unsigned char *out, size_t *out_len, bool add_padding);
static inline size_t required_buffer_size_for_base64_decode(size_t src_sz) { return (src_sz / 4 * 3 + 2); }
static inline size_t required_buffer_size_for_base64_encode(size_t src_sz) { return ((src_sz + 2) / 3 * 4); }
