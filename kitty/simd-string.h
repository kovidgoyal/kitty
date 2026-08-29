/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#include <stddef.h>
#include <stdalign.h>
#include <math.h>

typedef void (*control_byte_callback)(void *data, uint8_t ch);
typedef void (*output_chars_callback)(void *data, const uint32_t *chars, unsigned count);

typedef struct UTF8Decoder {
    struct {
        uint32_t *storage;
        unsigned pos, capacity;
    } output;
    struct {
        uint32_t cur, prev, codep;
    } state;
    unsigned num_consumed;
} UTF8Decoder;

static inline void
utf8_decoder_reset(UTF8Decoder *self) {
    zero_at_ptr(&self->state);
}

bool utf8_decode_to_esc(UTF8Decoder *d, const uint8_t *src, size_t src_sz);
bool utf8_decode_to_esc_scalar(UTF8Decoder *d, const uint8_t *src, const size_t src_sz);

static inline void
utf8_decoder_ensure_capacity(UTF8Decoder *d, unsigned sz) {
    if (d->output.pos + sz > d->output.capacity) {
        d->output.capacity = d->output.pos + sz + 4096;
        // allow for overwrite of upto 64 bytes
        d->output.storage = realloc(d->output.storage, d->output.capacity * sizeof(d->output.storage[0]) + 64);
        if (!d->output.storage) fatal("Out of memory for UTF8Decoder output buffer at capacity: %u", d->output.capacity);
    }
}

static inline void
utf8_decoder_free(UTF8Decoder *d) {
    free(d->output.storage);
    zero_at_ptr(&(d->output));
}


// Pass a PyModule PyObject* as the argument. Must be called once at application startup
bool init_simd(void *module);

// Returns pointer to first position in haystack that contains either of the
// two chars or NULL if not found.
const uint8_t *find_either_of_two_bytes(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);

// XOR data with the 64 byte key
void xor_data64(const uint8_t key[64], uint8_t *data, const size_t data_sz);

// Returns the length of the prefix of chars that contains only printable ASCII codepoints (32 <= ch <= 126)
size_t printable_ascii_run_length(const uint32_t *chars, const size_t sz);

// Composite src over dst in place (Porter-Duff over with straight, aka non-premultiplied, alpha).
// Both are arrays of num_pixels 4-byte RGBA pixels, alpha in the fourth byte of each pixel.
void blend_over_straight(uint8_t *dst, const uint8_t *src, size_t num_pixels);

// As above, but dst is treated as fully opaque so no tracking of dst alpha is needed. dst_bpp must
// be 4 (RGBA pixels whose alpha bytes are set to 255) or 3 (RGB pixels).
void blend_over_opaque(uint8_t *dst, unsigned dst_bpp, const uint8_t *src, size_t num_pixels);

// Composite an 8-bit alpha mask onto 32-bit pixels of the form (r << 24) | (g << 16) | (b << 8) | alpha:
// dst[i] = ((color_rgb << 8) & 0xffffff00) | MAX(mask[i], dst[i] & 0xff)
void composite_alpha_mask(uint32_t *dst, const uint8_t *mask, size_t num_pixels, uint32_t color_rgb);

// Scalar per-pixel helpers shared by the scalar implementations and the tail handling of the SIMD
// implementations, which must produce bit identical results to them.

static inline uint32_t
div255_round(const uint32_t x) {
    // rounding division by 255, exact for x <= 65407 which covers x <= 255 * 255
    const uint32_t y = x + 128;
    return (y + (y >> 8)) >> 8;
}

static inline void
blend_pixel_over_opaque(uint8_t *dst, const uint8_t *src, const unsigned dst_bpp) {
    const uint32_t alpha = src[3], inv_alpha = 255 - alpha;
    for (unsigned c = 0; c < 3; c++) dst[c] = (uint8_t)div255_round(src[c] * alpha + dst[c] * inv_alpha);
    if (dst_bpp == 4) dst[3] = 255;
}

static inline void
blend_pixel_over_straight(uint8_t *dst, const uint8_t *src) {
    const uint32_t alpha = src[3], dst_alpha = dst[3], inv_alpha = 255 - alpha;
    // The over operator on straight alpha in 8-bit integer arithmetic. Multiplying out the
    // normalizations by 255, the output alpha and color channels are:
    // out_alpha = (alpha * 255 + dst_alpha * (255 - alpha)) / 255
    // out_c = (src_c * alpha * 255 + dst_c * dst_alpha * (255 - alpha)) / (alpha * 255 + dst_alpha * (255 - alpha))
    const uint32_t denom = alpha * 255 + dst_alpha * inv_alpha;
    if (!denom) return; // both src and dst fully transparent, leave dst unchanged
    for (unsigned c = 0; c < 3; c++) {
        const uint32_t num = src[c] * alpha * 255 + dst[c] * dst_alpha * inv_alpha;
        // float division and round to nearest, matching the SIMD implementations bit for bit
        dst[c] = (uint8_t)lrintf((float)num / (float)denom);
    }
    dst[3] = (uint8_t)div255_round(denom);
}

// SIMD implementations, internal use
bool utf8_decode_to_esc_128(UTF8Decoder *d, const uint8_t *src, size_t src_sz);
bool utf8_decode_to_esc_256(UTF8Decoder *d, const uint8_t *src, size_t src_sz);
bool utf8_decode_to_esc_512(UTF8Decoder *d, const uint8_t *src, size_t src_sz);
const uint8_t *find_either_of_two_bytes_128(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);
const uint8_t *find_either_of_two_bytes_256(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);
const uint8_t *find_either_of_two_bytes_512(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b);
void xor_data64_128(const uint8_t key[64], uint8_t *data, const size_t data_sz);
void xor_data64_256(const uint8_t key[64], uint8_t *data, const size_t data_sz);
void xor_data64_512(const uint8_t key[64], uint8_t *data, const size_t data_sz);
size_t printable_ascii_run_length_128(const uint32_t *chars, const size_t sz);
size_t printable_ascii_run_length_256(const uint32_t *chars, const size_t sz);
size_t printable_ascii_run_length_512(const uint32_t *chars, const size_t sz);
void blend_over_straight_128(uint8_t *dst, const uint8_t *src, size_t num_pixels);
void blend_over_straight_256(uint8_t *dst, const uint8_t *src, size_t num_pixels);
void blend_over_straight_512(uint8_t *dst, const uint8_t *src, size_t num_pixels);
void blend_over_opaque_128(uint8_t *dst, unsigned dst_bpp, const uint8_t *src, size_t num_pixels);
void blend_over_opaque_256(uint8_t *dst, unsigned dst_bpp, const uint8_t *src, size_t num_pixels);
void blend_over_opaque_512(uint8_t *dst, unsigned dst_bpp, const uint8_t *src, size_t num_pixels);
void composite_alpha_mask_128(uint32_t *dst, const uint8_t *mask, size_t num_pixels, uint32_t color_rgb);
void composite_alpha_mask_256(uint32_t *dst, const uint8_t *mask, size_t num_pixels, uint32_t color_rgb);
void composite_alpha_mask_512(uint32_t *dst, const uint8_t *mask, size_t num_pixels, uint32_t color_rgb);
