/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>
#include <stddef.h>
#include <stdbool.h>
#include <stdalign.h>
#include "data-types.h"

#define BYTE_LOADER_T unsigned long long
typedef struct ByteLoader {
    BYTE_LOADER_T m;
    unsigned sz_of_next_load, digits_left, num_left;
    const uint8_t *next_load_at;
} ByteLoader;
uint8_t byte_loader_peek(const ByteLoader *self);
void byte_loader_init(ByteLoader *self, const uint8_t *buf, unsigned int sz);
uint8_t byte_loader_next(ByteLoader *self);

typedef void (*control_byte_callback)(void *data, uint8_t ch);
typedef void (*output_chars_callback)(void *data, const uint32_t *chars, unsigned count);

typedef struct UTF8Decoder {
    struct { uint32_t cur, prev, codep; } state;
    alignas(64) uint32_t output[64];

    void *callback_data;
    control_byte_callback control_byte_callback;
    output_chars_callback output_chars_callback;
} UTF8Decoder;
static inline void utf8_decoder_reset(UTF8Decoder *self) { zero_at_ptr(&self->state); }
unsigned utf8_decode_to_sentinel(UTF8Decoder *d, const uint8_t *src, const size_t src_sz, const uint8_t sentinel);

// Pass a PyModule PyObject* as the argument. Must be called once at application startup
bool init_simd(void* module);

// Requires 7 bytes to the left of haystack to be readable. Returns pointer to
// first position in haystack that contains either of the two chars or NULL if
// not found.
const uint8_t* find_either_of_two_bytes(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);

// Requires 7 bytes to the left of haystack to be readable. Returns pointer to
// first position in haystack that contains a char that is not in [a, b].
// a must be <= b
const uint8_t* find_byte_not_in_range(const uint8_t *haystack, const size_t sz, const uint8_t a1, const uint8_t b);
