/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#include <stddef.h>
#include <stdalign.h>

typedef void (*control_byte_callback)(void *data, uint8_t ch);
typedef void (*output_chars_callback)(void *data, const uint32_t *chars, unsigned count);

typedef struct UTF8Decoder {
    alignas(512/8) uint32_t output[512/8];  // we can process at most 512 bits of input (AVX512) so we get at most 64 chars of output
    unsigned output_sz, num_consumed;

    struct { uint32_t cur, prev, codep; } state;
} UTF8Decoder;
static inline void utf8_decoder_reset(UTF8Decoder *self) { zero_at_ptr(&self->state); }
bool utf8_decode_to_esc(UTF8Decoder *d, const uint8_t *src, size_t src_sz);

// Pass a PyModule PyObject* as the argument. Must be called once at application startup
bool init_simd(void* module);

// Requires 31 bytes to the right of haystack to be readable. Returns pointer to
// first position in haystack that contains either of the two chars or NULL if
// not found.
const uint8_t* find_either_of_two_bytes(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);

// SIMD implementations, internal use
bool utf8_decode_to_esc_128(UTF8Decoder *d, const uint8_t *src, size_t src_sz);
bool utf8_decode_to_esc_256(UTF8Decoder *d, const uint8_t *src, size_t src_sz);
const uint8_t* find_either_of_two_bytes_128(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);
const uint8_t* find_either_of_two_bytes_256(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);
