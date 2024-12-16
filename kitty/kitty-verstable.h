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
    for (size_t i = 0; i < size; i++) hash = ( (uint64_t)(((unsigned char*)data)[i] ^ hash )) * 0x100000001b3ull;
    return hash;
}

static inline uint64_t vt_hash_float(float x) { return vt_hash_integer((uint64_t)x); }
static inline bool vt_cmpr_float(float a, float b) { return a == b; }
#define vt_create_for_loop(itr_type, itr, table) for (itr_type itr = vt_first(table); !vt_is_end(itr); itr = vt_next(itr))

#endif
