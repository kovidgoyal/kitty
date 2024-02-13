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
    struct { uint32_t *storage; unsigned pos, capacity; } output;
    struct { uint32_t cur, prev, codep; } state;
    unsigned num_consumed;
} UTF8Decoder;

static inline void utf8_decoder_reset(UTF8Decoder *self) { zero_at_ptr(&self->state); }

bool utf8_decode_to_esc(UTF8Decoder *d, const uint8_t *src, size_t src_sz);
bool utf8_decode_to_esc_scalar(UTF8Decoder *d, const uint8_t *src, const size_t src_sz);

static inline void utf8_decoder_ensure_capacity(UTF8Decoder *d, unsigned sz) {
    if (d->output.pos + sz > d->output.capacity) {
        d->output.capacity = d->output.pos + sz + 4096;
        // allow for overwrite of upto 64 bytes
        d->output.storage = realloc(d->output.storage, d->output.capacity * sizeof(d->output.storage[0]) + 64);
        if (!d->output.storage) fatal("Out of memory for UTF8Decoder output buffer at capacity: %u", d->output.capacity);
    }
}

static inline void utf8_decoder_free(UTF8Decoder *d) {
    free(d->output.storage);
    zero_at_ptr(&(d->output));
}


// Pass a PyModule PyObject* as the argument. Must be called once at application startup
bool init_simd(void* module);

// Returns pointer to first position in haystack that contains either of the
// two chars or NULL if not found.
const uint8_t* find_either_of_two_bytes(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);

// XOR data with the 64 byte key
void xor_data64(const uint8_t key[64], uint8_t* data, const size_t data_sz);

// SIMD implementations, internal use
bool utf8_decode_to_esc_128(UTF8Decoder *d, const uint8_t *src, size_t src_sz);
bool utf8_decode_to_esc_256(UTF8Decoder *d, const uint8_t *src, size_t src_sz);
const uint8_t* find_either_of_two_bytes_128(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);
const uint8_t* find_either_of_two_bytes_256(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);
void xor_data64_128(const uint8_t key[64], uint8_t* data, const size_t data_sz);
void xor_data64_256(const uint8_t key[64], uint8_t* data, const size_t data_sz);
