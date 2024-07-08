/*
 * kitty-verstable.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "../3rdparty/verstable.h"
#include <stdint.h>

#ifndef __kitty_verstable_extra_hash_functions__
#define __kitty_verstable_extra_hash_functions__
// FNV-1a (matches vt_hash_string)
static inline uint64_t
vt_hash_bytes(const void *data, const size_t size) {
    uint64_t hash = 0xcbf29ce484222325ull;
    for (size_t i = 0; i < size; i++) hash = ( ((unsigned char*)data)[i] ^ hash ) * 0x100000001b3ull;
    return hash;
}

#define vt_hash_struct(s) vt_hash_bytes(&s, sizeof(s))
#define vt_cmpr_struct(s) memcmp(&s, &s, sizeof(s))

#define vt_hash_ptr(s) vt_hash_bytes(s, sizeof(s[0]))
#define vt_cmpr_ptr(s) memcmp(s, s, sizeof(s[0]))

#endif
