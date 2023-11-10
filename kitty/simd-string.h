/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>
#include <stddef.h>

#define BYTE_LOADER_T unsigned long long
typedef struct ByteLoader {
    BYTE_LOADER_T m;
    unsigned sz_of_next_load, digits_left, num_left;
    const uint8_t *next_load_at;
} ByteLoader;


uint8_t byte_loader_peek(const ByteLoader *self);
void byte_loader_init(ByteLoader *self, const uint8_t *buf, unsigned int sz);
uint8_t byte_loader_next(ByteLoader *self);

// Requires haystack[sz] to be writable and 7 bytes to the left of haystack to
// be readable. Returns pointer to first position in haystack that contains
// either of the two chars or NULL if not found.
uint8_t* find_either_of_two_bytes(uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);
