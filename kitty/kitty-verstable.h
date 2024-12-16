/*
 * kitty-verstable.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "../3rdparty/verstable.h"
#include <stdint.h>
#include <xxhash.h>

#ifndef __kitty_verstable_extra_hash_functions__
#define __kitty_verstable_extra_hash_functions__

#define vt_hash_bytes XXH3_64bits

static inline uint64_t vt_hash_float(float x) { return vt_hash_integer((uint64_t)x); }
static inline bool vt_cmpr_float(float a, float b) { return a == b; }
#define vt_create_for_loop(itr_type, itr, table) for (itr_type itr = vt_first(table); !vt_is_end(itr); itr = vt_next(itr))

#endif
