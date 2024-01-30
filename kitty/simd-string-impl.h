/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"
#include "simd-string.h"

#ifndef KITTY_SIMD_LEVEL
#define KITTY_SIMD_LEVEL 128
#endif
#define CONCAT(A, B) A##B
#define CONCAT_EXPAND(A, B) CONCAT(A,B)
#define FUNC(name) CONCAT_EXPAND(name##_, KITTY_SIMD_LEVEL)

#ifdef KITTY_NO_SIMD
#define NOSIMD { fatal("No SIMD implementations for this CPU"); }
bool FUNC(utf8_decode_to_esc)(UTF8Decoder *d UNUSED, const uint8_t *src UNUSED, size_t src_sz UNUSED) NOSIMD
const uint8_t* FUNC(find_either_of_two_bytes)(const uint8_t *haystack UNUSED, const size_t sz UNUSED, const uint8_t a UNUSED, const uint8_t b UNUSED) NOSIMD
#undef NOSIMD
#else

#include "charsets.h"

// Boilerplate {{{
#if  defined(__clang__) && __clang_major__ > 12
_Pragma("clang diagnostic push")
_Pragma("clang diagnostic ignored \"-Wbitwise-instead-of-logical\"")
#endif
#include <simde/x86/avx2.h>
#if  defined(__clang__) && __clang_major__ > 12
_Pragma("clang diagnostic pop")
#endif


#ifndef _MM_SHUFFLE
#define _MM_SHUFFLE(z, y, x, w) (((z) << 6) | ((y) << 4) | ((x) << 2) | (w))
#endif
#define integer_t CONCAT_EXPAND(CONCAT_EXPAND(simde__m, KITTY_SIMD_LEVEL), i)
#define shift_right_by_bytes128 simde_mm_srli_si128
#define zero_last_n_bytes FUNC(zero_last_n_bytes)
#define is_zero FUNC(is_zero)

#if KITTY_SIMD_LEVEL == 128
#define set1_epi8(x) simde_mm_set1_epi8((char)(x))
#define set_epi8 simde_mm_set_epi8
#define add_epi8 simde_mm_add_epi8
#define load_unaligned simde_mm_loadu_si128
#define load_aligned simde_mm_load_si128
#define store_aligned simde_mm_store_si128
#define cmpeq_epi8 simde_mm_cmpeq_epi8
#define cmplt_epi8 simde_mm_cmplt_epi8
#define cmpgt_epi8 simde_mm_cmpgt_epi8
#define or_si simde_mm_or_si128
#define and_si simde_mm_and_si128
#define andnot_si simde_mm_andnot_si128
#define movemask_epi8 simde_mm_movemask_epi8
#define extract_lower_quarter_as_chars simde_mm_cvtepu8_epi32
#define shift_right_by_one_byte(x) simde_mm_slli_si128(x, 1)
#define shift_right_by_two_bytes(x) simde_mm_slli_si128(x, 2)
#define shift_right_by_four_bytes(x) simde_mm_slli_si128(x, 4)
#define shift_right_by_eight_bytes(x) simde_mm_slli_si128(x, 8)
#define shift_right_by_sixteen_bytes(x) simde_mm_slli_si128(x, 16)
#define shift_left_by_one_byte(x) simde_mm_srli_si128(x, 1)
#define shift_left_by_two_bytes(x) simde_mm_srli_si128(x, 2)
#define shift_left_by_four_bytes(x) simde_mm_srli_si128(x, 4)
#define shift_left_by_eight_bytes(x) simde_mm_srli_si128(x, 8)
#define shift_left_by_sixteen_bytes(x) simde_mm_srli_si128(x, 16)
#define blendv_epi8 simde_mm_blendv_epi8
#define shift_left_by_bits16 simde_mm_slli_epi16
#define shift_right_by_bits32 simde_mm_srli_epi32
#define shuffle_epi8 simde_mm_shuffle_epi8
#define numbered_bytes() set_epi8(15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0)
#define reverse_numbered_bytes() simde_mm_setr_epi8(15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0)
// output[i] = MAX(0, a[i] - b[1i])
#define subtract_saturate_epu8 simde_mm_subs_epu8
#define subtract_epi8 simde_mm_sub_epi8
#define create_zero_integer simde_mm_setzero_si128
#define sum_bytes sum_bytes_128

static inline int
FUNC(is_zero)(const integer_t a) { return simde_mm_testz_si128(a, a); }

#else

#define set1_epi8(x) simde_mm256_set1_epi8((char)(x))
#define set_epi8 simde_mm256_set_epi8
#define add_epi8 simde_mm256_add_epi8
#define load_unaligned simde_mm256_loadu_si256
#define load_aligned simde_mm256_load_si256
#define store_aligned simde_mm256_store_si256
#define cmpeq_epi8 simde_mm256_cmpeq_epi8
#define cmpgt_epi8 simde_mm256_cmpgt_epi8
#define cmplt_epi8(a, b) cmpgt_epi8(b, a)
#define or_si simde_mm256_or_si256
#define and_si simde_mm256_and_si256
#define andnot_si simde_mm256_andnot_si256
#define movemask_epi8 simde_mm256_movemask_epi8
#define extract_lower_half_as_chars simde_mm256_cvtepu8_epi32
#define blendv_epi8 simde_mm256_blendv_epi8
#define subtract_saturate_epu8 simde_mm256_subs_epu8
#define subtract_epi8 simde_mm256_sub_epi8
#define shift_left_by_bits16 simde_mm256_slli_epi16
#define shift_right_by_bits32 simde_mm256_srli_epi32
#define create_zero_integer simde_mm256_setzero_si256
#define numbered_bytes() set_epi8(31,30,29,28,27,26,25,24,23,22,21,20,19,18,17,16,15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0)
#define reverse_numbered_bytes() simde_mm256_setr_epi8(31,30,29,28,27,26,25,24,23,22,21,20,19,18,17,16,15,14,13,12,11,10,9,8,7,6,5,4,3,2,1,0)

static inline int
FUNC(is_zero)(const integer_t a) { return simde_mm256_testz_si256(a, a); }

static inline integer_t
shift_right_by_one_byte(const integer_t A) {
    return simde_mm256_alignr_epi8(A, simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0)), 16 - 1);
}

static inline integer_t
shift_right_by_two_bytes(const integer_t A) {
    return simde_mm256_alignr_epi8(A, simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0)), 16 - 2);
}

static inline integer_t
shift_right_by_four_bytes(const integer_t A) {
    return simde_mm256_alignr_epi8(A, simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0)), 16 - 4);
}

static inline integer_t
shift_right_by_eight_bytes(const integer_t A) {
    return simde_mm256_alignr_epi8(A, simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0)), 16 - 8);
}

static inline integer_t
shift_right_by_sixteen_bytes(const integer_t A) {
    return simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(0, 0, 2, 0));
}

static inline integer_t
shift_left_by_one_byte(const integer_t A) {
    return simde_mm256_alignr_epi8(simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1)), A, 1);
}

static inline integer_t
shift_left_by_two_bytes(const integer_t A) {
    return simde_mm256_alignr_epi8(simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1)), A, 2);
}

static inline integer_t
shift_left_by_four_bytes(const integer_t A) {
    return simde_mm256_alignr_epi8(simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1)), A, 4);
}

static inline integer_t
shift_left_by_eight_bytes(const integer_t A) {
    return simde_mm256_alignr_epi8(simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1)), A, 8);
}

static inline integer_t
shift_left_by_sixteen_bytes(const integer_t A) {
    return simde_mm256_permute2x128_si256(A, A, _MM_SHUFFLE(2, 0, 0, 1));
}



static inline integer_t shuffle_impl256(const integer_t value, const integer_t shuffle) {
#define K0 simde_mm256_setr_epi8( \
        0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, \
        -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16)

#define K1 simde_mm256_setr_epi8( \
        -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, -16, \
        0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70, 0x70)

    return or_si(
            simde_mm256_shuffle_epi8(value, add_epi8(shuffle, K0)),
            simde_mm256_shuffle_epi8(simde_mm256_permute4x64_epi64(value, 0x4E), simde_mm256_add_epi8(shuffle, K1))
    );
#undef K0
#undef K1
}

#define shuffle_epi8 shuffle_impl256
#define sum_bytes(x) (sum_bytes_128(simde_mm256_extracti128_si256(x, 0)) + sum_bytes_128(simde_mm256_extracti128_si256(x, 1)))
#endif

#define print_register_as_bytes(r) { \
    printf("%s:\n", #r); \
    alignas(64) uint8_t data[sizeof(r)]; \
    store_aligned((integer_t*)data, r); \
    for (unsigned i = 0; i < sizeof(integer_t); i++) { \
        uint8_t ch = data[i]; \
        if (' ' <= ch && ch < 0x7f) printf("_%c ", ch); else printf("%.2x ", ch); \
    } \
    printf("\n"); \
}

#if 0
#define debug_register print_register_as_bytes
#define debug printf
#else
#define debug_register(...)
#define debug(...)
#endif


typedef int32_t find_mask_t;
static inline find_mask_t
mask_for_find(const integer_t a) { return movemask_epi8(a); }

static inline unsigned
bytes_to_first_match(const find_mask_t m) { return __builtin_ctz(m); }


// }}}

static inline integer_t
FUNC(zero_last_n_bytes)(integer_t vec, char n) {
    const integer_t threshold = set1_epi8(n);
    const integer_t index = reverse_numbered_bytes();
    const integer_t mask = cmpgt_epi8(threshold, index);
    return andnot_si(mask, vec);
}

const uint8_t*
FUNC(find_either_of_two_bytes)(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    const integer_t a_vec = set1_epi8(a), b_vec = set1_epi8(b);
    const uint8_t* limit = haystack + sz;
    integer_t chunk; find_mask_t mask;

#define check_chunk() { \
    const integer_t matches = or_si(cmpeq_epi8(chunk, a_vec), cmpeq_epi8(chunk, b_vec)); \
    if ((mask = mask_for_find(matches))) { \
        const uint8_t *ans = haystack + bytes_to_first_match(mask); \
        return ans < limit ? ans : NULL; \
    }}

    // check the first possibly unaligned chunk
    chunk = load_unaligned(haystack);
    check_chunk();
    const uintptr_t unaligned_leading_count = sizeof(integer_t) - (((uintptr_t)haystack) & (sizeof(integer_t) - 1));
    haystack += unaligned_leading_count; // advance to the first aligned chunk

    // Iterate over aligned chunks, this repeats checking of
    // (sizeof(integer_t) - unaligned_leading_count) bytes, but better than a branch
    for (; haystack < limit; haystack += sizeof(integer_t)) {
        chunk = load_aligned((integer_t*)haystack);
        check_chunk();
    }
    return NULL;
}

#define output_increment sizeof(integer_t)/sizeof(uint32_t)

static inline void
FUNC(output_plain_ascii)(UTF8Decoder *d, integer_t vec, size_t src_sz) {
#if KITTY_SIMD_LEVEL == 128
    for (const uint32_t *limit = d->output + src_sz, *p = d->output; p < limit; p += output_increment) {
        const integer_t unpacked = extract_lower_quarter_as_chars(vec);
        store_aligned((integer_t*)p, unpacked);
        vec = shift_right_by_bytes128(vec, output_increment);
    }
#else
    const uint32_t *limit = d->output + src_sz, *p = d->output;
    simde__m128i x = simde_mm256_extracti128_si256(vec, 0);
    integer_t unpacked = extract_lower_half_as_chars(x);
    store_aligned((integer_t*)p, unpacked); p += output_increment;
    if (p < limit) {
        x = shift_right_by_bytes128(x, output_increment);
        unpacked = extract_lower_half_as_chars(x);
        store_aligned((integer_t*)p, unpacked); p += output_increment;
        if (p < limit) {
            x = simde_mm256_extracti128_si256(vec, 1);
            unpacked = extract_lower_half_as_chars(x);
            store_aligned((integer_t*)p, unpacked); p += output_increment;
            if (p < limit) {
                x = shift_right_by_bytes128(x, output_increment);
                unpacked = extract_lower_half_as_chars(x);
                store_aligned((integer_t*)p, unpacked); p += output_increment;
            }
        }
    }
#endif
    d->output_sz += src_sz;
}

static inline void
FUNC(output_unicode)(UTF8Decoder *d, integer_t output1, integer_t output2, integer_t output3, const size_t num_codepoints) {
#if KITTY_SIMD_LEVEL == 128
    for (const uint32_t *limit = d->output + num_codepoints, *p = d->output; p < limit; p += output_increment) {
        const integer_t unpacked1 = extract_lower_quarter_as_chars(output1);
        const integer_t unpacked2 = shift_right_by_one_byte(extract_lower_quarter_as_chars(output2));
        const integer_t unpacked3 = shift_right_by_two_bytes(extract_lower_quarter_as_chars(output3));
        const integer_t unpacked = or_si(or_si(unpacked1, unpacked2), unpacked3);
        store_aligned((integer_t*)p, unpacked);
        output1 = shift_right_by_bytes128(output1, output_increment);
        output2 = shift_right_by_bytes128(output2, output_increment);
        output3 = shift_right_by_bytes128(output3, output_increment);
    }
#else
    const uint32_t *limit = d->output + num_codepoints;
    uint32_t *p = d->output;
    simde__m128i x1, x2, x3;
#define chunk() { \
        const integer_t unpacked1 = extract_lower_half_as_chars(x1); \
        const integer_t unpacked2 = shift_right_by_one_byte(extract_lower_half_as_chars(x2)); \
        const integer_t unpacked3 = shift_right_by_two_bytes(extract_lower_half_as_chars(x3)); \
        store_aligned((integer_t*)p, or_si(or_si(unpacked1, unpacked2), unpacked3)); \
        p += output_increment; \
}
#define extract(which) x1 = simde_mm256_extracti128_si256(output1, which); x2 = simde_mm256_extracti128_si256(output2, which); x3 = simde_mm256_extracti128_si256(output3, which);
#define shift() x1 = shift_right_by_bytes128(x1, output_increment); x2 = shift_right_by_bytes128(x2, output_increment); x3 = shift_right_by_bytes128(x3, output_increment);
    extract(0); chunk();
    if (p < limit) {
        shift(); chunk();
        if (p < limit) {
            extract(1); chunk();
            if (p < limit) {
                shift(); chunk();
            }
        }
    }
#undef chunk
#undef extract
#undef shift
#endif
    d->output_sz += num_codepoints;
}
#undef output_increment

static inline unsigned
sum_bytes_128(simde__m128i v) {
    // Use _mm_sad_epu8 to perform a sum of absolute differences against zero
    // This sums up all 8-bit integers in the 128-bit vector and packs the result into a 64-bit integer
    simde__m128i sum = simde_mm_sad_epu8(v, simde_mm_setzero_si128());

    // At this point, the sum of the first half is in the lower 64 bits, and the sum of the second half is in the upper 64 bits.
    // Extract the lower and upper 64-bit sums and add them together.
    const unsigned lower_sum = simde_mm_cvtsi128_si32(sum); // Extracts the lower 32 bits
    const unsigned upper_sum = simde_mm_cvtsi128_si32(simde_mm_srli_si128(sum, 8)); // Extracts the upper 32 bits

    return lower_sum + upper_sum; // Final sum of all bytes
}

#define do_one_byte \
    const uint8_t ch = src[pos++]; \
    switch (decode_utf8(&d->state.cur, &d->state.codep, ch)) { \
        case UTF8_ACCEPT: \
            d->output[d->output_sz++] = d->state.codep; \
            break; \
        case UTF8_REJECT: { \
                const bool prev_was_accept = d->state.prev == UTF8_ACCEPT; \
                zero_at_ptr(&d->state); \
                d->output[d->output_sz++] = 0xfffd; \
                if (!prev_was_accept) { \
                    pos--; \
                    continue; /* so that prev is correct */ \
                } \
        } break; \
    } \
    d->state.prev = d->state.cur;

static inline size_t
scalar_decode_to_accept(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    size_t pos = 0;
    while (pos < src_sz && d->output_sz < arraysz(d->output) && d->state.cur != UTF8_ACCEPT) {
        do_one_byte
    }
    return pos;
}

static inline size_t
scalar_decode_all(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    size_t pos = 0;
    while (pos < src_sz && d->output_sz < arraysz(d->output)) {
        do_one_byte
    }
    return pos;
}
#undef do_one_byte

bool
FUNC(utf8_decode_to_esc)(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    // Based on the algorithm described in: https://woboq.com/blog/utf-8-processing-using-simd.html

    d->output_sz = 0; d->num_consumed = 0;
    if (d->state.cur != UTF8_ACCEPT) {
        // Finish the trailing sequence only, we will be called again to process the rest allows use of aligned stores since output
        // is not pre-filled.
        d->num_consumed = scalar_decode_to_accept(d, src, src_sz);
        src += d->num_consumed; src_sz -= d->num_consumed;
        return false;
    }
    src_sz = MIN(src_sz, sizeof(integer_t));
    integer_t vec = load_unaligned((integer_t*)src);

    const integer_t esc_vec = set1_epi8(0x1b);
    const integer_t esc_cmp = cmpeq_epi8(vec, esc_vec);
    const find_mask_t esc_test_mask = mask_for_find(esc_cmp);
    bool sentinel_found = false;
    unsigned short num_of_bytes_to_first_esc;
    if (esc_test_mask && (num_of_bytes_to_first_esc = bytes_to_first_match(esc_test_mask)) < src_sz) {
        sentinel_found = true;
        src_sz = num_of_bytes_to_first_esc;
        d->num_consumed += src_sz + 1;  // esc is also consumed
    } else d->num_consumed += src_sz;

    // use scalar decode for short input
    if (src_sz < 4) {
        scalar_decode_all(d, src, src_sz); return sentinel_found;
    }
    if (src_sz < sizeof(integer_t)) vec = zero_last_n_bytes(vec, sizeof(integer_t) - src_sz);

    unsigned num_of_trailing_bytes = 0;
    bool check_for_trailing_bytes = true;

    // Check if we have pure ASCII and use fast path
    debug_register(vec);
    find_mask_t ascii_mask;
start_classification:
    ascii_mask = mask_for_find(vec);
    if (!ascii_mask) { // no bytes with high bit (0x80) set, so just plain ASCII
        FUNC(output_plain_ascii)(d, vec, src_sz);
        if (num_of_trailing_bytes) scalar_decode_all(d, src + src_sz, num_of_trailing_bytes);
        return sentinel_found;
    }
    // Classify the bytes
    integer_t state = set1_epi8(0x80);
    const integer_t vec_signed = add_epi8(vec, state); // needed because cmplt_epi8 works only on signed chars

    const integer_t bytes_indicating_start_of_two_byte_sequence = cmplt_epi8(set1_epi8(0xc0 - 1 - 0x80), vec_signed);
    state = blendv_epi8(state, set1_epi8(0xc2), bytes_indicating_start_of_two_byte_sequence);
    // state now has 0xc2 on all bytes that start a 2 or more byte sequence and 0x80 on the rest
    const integer_t bytes_indicating_start_of_three_byte_sequence = cmplt_epi8(set1_epi8(0xe0 - 1 - 0x80), vec_signed);
    state = blendv_epi8(state, set1_epi8(0xe3), bytes_indicating_start_of_three_byte_sequence);
    const integer_t bytes_indicating_start_of_four_byte_sequence = cmplt_epi8(set1_epi8(0xf0 - 1 - 0x80), vec_signed);
    state = blendv_epi8(state, set1_epi8(0xf4), bytes_indicating_start_of_four_byte_sequence);
    // state now has 0xc2 on all bytes that start a 2 byte sequence, 0xe3 on start of 3-byte sequence, 0xf4 on 4-byte start and 0x80 on rest
    debug_register(state);
    integer_t mask = and_si(state, set1_epi8(0xf8));  // keep upper 5 bits of state
    debug_register(mask);
    integer_t count = and_si(state, set1_epi8(0x7));  // keep lower 3 bits of state
    debug_register(count);
    const integer_t zero = create_zero_integer(), one = set1_epi8(1), two = set1_epi8(2), three = set1_epi8(3);
    // count contains the number of bytes in the sequence for the start byte of every sequence and zero elsewhere
    // shift 02 bytes by 1 and subtract 1
    integer_t count_subs1 = subtract_saturate_epu8(count, one);
    integer_t counts = add_epi8(count, shift_right_by_one_byte(count_subs1));
    // shift 03 and 04 bytes by 2 and subtract 2
    counts = add_epi8(counts, shift_right_by_two_bytes(subtract_saturate_epu8(counts, two)));
    // counts now contains the number of bytes remaining in each utf-8 sequence of 2 or more bytes
    debug_register(counts);
    // check for an incomplete trailing utf8 sequence
    if (check_for_trailing_bytes && mask_for_find(cmplt_epi8(one, and_si(counts, cmpeq_epi8(numbered_bytes(), set1_epi8(src_sz - 1)))))) {
        // The value of counts at the last byte is > 1 indicating we have a trailing incomplete sequence
        check_for_trailing_bytes = false;
        if (src[src_sz-1] >= 0xc0) num_of_trailing_bytes = 1;      // 2-, 3- and 4-byte characters with only 1 byte left
        else if (src_sz > 1 && src[src_sz-2] >= 0xe0) num_of_trailing_bytes = 2; // 3- and 4-byte characters with only 1 byte left
        else if (src_sz > 2 && src[src_sz-3] >= 0xf0) num_of_trailing_bytes = 3; // 4-byte characters with only 3 bytes left
        src_sz -= num_of_trailing_bytes;
        vec = zero_last_n_bytes(vec, sizeof(integer_t) - src_sz);
        goto start_classification;
    }
    // Only ASCII chars should have corresponding byte of counts == 0
    if (ascii_mask != mask_for_find(cmpgt_epi8(counts, zero))) goto invalid_utf8;
    // The difference between a byte in counts and the next one should be negative,
    // zero, or one. Any other value means there is not enough continuation bytes.
    if (mask_for_find(cmpgt_epi8(subtract_epi8(shift_right_by_one_byte(counts), counts), one))) goto invalid_utf8;

    // Process the bytes storing the three resulting bytes that make up the unicode codepoint
    // mask all control bits so that we have only useful bits left
    vec = andnot_si(mask, vec);
    debug_register(vec);

    // Now calculate the three output vectors

    // The lowest byte is made up of 6 bits from locations with counts == 1 and the lowest two bits from locations with count == 2
    // In addition, the ASCII bytes are copied unchanged from vec
    integer_t vec_non_ascii = andnot_si(cmpeq_epi8(counts, zero), vec);
    debug_register(vec_non_ascii);
    integer_t output1 = blendv_epi8(vec,
            or_si(
                // there are no count == 1 locations without a count == 2 location to its left so we dont need to AND with count2_locations
                vec, and_si(shift_left_by_bits16(shift_right_by_one_byte(vec_non_ascii), 6), set1_epi8(0xc0))
            ),
            cmpeq_epi8(counts, one)
    );
    debug_register(output1);

    // The next byte is made up of 4 bits (5, 4, 3, 2) from locations with count == 2 and the first 4 bits from locations with count == 3
    integer_t count2_locations = cmpeq_epi8(counts, two), count3_locations = cmpeq_epi8(counts, three);
    integer_t output2 = and_si(vec, count2_locations);
    output2 = shift_right_by_bits32(output2, 2);  // selects the bits 5, 4, 3, 2
    // select the first 4 bits from locs with count == 3 by shifting count 3 locations right by one byte and left by 4 bits
    output2 = or_si(output2,
        and_si(set1_epi8(0xf0),
            shift_left_by_bits16(shift_right_by_one_byte(and_si(count3_locations, vec_non_ascii)), 4)
        )
    );
    output2 = and_si(output2, count2_locations); // keep only the count2 bytes
    output2 = shift_right_by_one_byte(output2);
    debug_register(output2);

    // The last byte is made up of bits 5 and 6 from count == 3 and 3 bits from count == 4
    integer_t output3 = and_si(three, shift_right_by_bits32(vec, 4));  // bits 5 and 6 from count == 3
    integer_t count4_locations = cmpeq_epi8(counts, set1_epi8(4));
    // 3 bits from count == 4 locations, placed at count == 3 locations shifted left by 2 bits
    output3 = or_si(output3,
        and_si(set1_epi8(0xfc),
            shift_left_by_bits16(shift_right_by_one_byte(and_si(count4_locations, vec_non_ascii)), 2)
        )
    );
    output3 = and_si(output3, count3_locations);  // keep only count3 bytes
    output3 = shift_right_by_two_bytes(output3);
    debug_register(output3);

    // Shuffle bytes to remove continuation bytes
    integer_t shifts = count_subs1;  // number of bytes we need to skip for each UTF-8 sequence
    // propagate the shifts to all subsequent bytes by shift and add
    shifts = add_epi8(shifts, shift_right_by_one_byte(shifts));
    shifts = add_epi8(shifts, shift_right_by_two_bytes(shifts));
    shifts = add_epi8(shifts, shift_right_by_four_bytes(shifts));
    shifts = add_epi8(shifts, shift_right_by_eight_bytes(shifts));
#if KITTY_SIMD_LEVEL == 256
    shifts = add_epi8(shifts, shift_right_by_sixteen_bytes(shifts));
#endif
    // zero the shifts for discarded continuation bytes
    shifts = and_si(shifts, cmplt_epi8(counts, two));
    // now we need to convert shifts into a mask for the shuffle. The mask has each byte of the
    // form 0000xxxx the lower four bits indicating the destination location for the byte. For 256 bit shuffle we use lower 5 bits.
    // First we move the numbers in shifts to discard the unwanted UTF-8 sequence bytes. We note that the numbers
    // are bounded by sizeof(integer_t) and so we need at most 4 (for 128 bit) or 5 (for 256 bit) moves. The numbers are
    // monotonic from left to right and change value only at the end of a UTF-8 sequence. We move them leftwards, accumulating the
    // moves bit-by-bit.
#define move(shifts, amt, which_bit) blendv_epi8(shifts, shift_left_by_##amt(shifts), shift_left_by_##amt(shift_left_by_bits16(shifts, 8 - which_bit)))
    shifts = move(shifts, one_byte, 1);
    shifts = move(shifts, two_bytes, 2);
    shifts = move(shifts, four_bytes, 3);
    shifts = move(shifts, eight_bytes, 4);
#if KITTY_SIMD_LEVEL == 256
    shifts = move(shifts, sixteen_bytes, 5);
#endif
#undef move
    // convert the shifts into a suitable mask for shuffle by adding the byte number to each byte
    shifts = add_epi8(shifts, numbered_bytes());
    debug_register(shifts);

    output1 = shuffle_epi8(output1, shifts);
    output2 = shuffle_epi8(output2, shifts);
    output3 = shuffle_epi8(output3, shifts);
    debug_register(output1);
    debug_register(output2);
    debug_register(output3);

    const unsigned num_of_discarded_bytes = sum_bytes(count_subs1);
    const unsigned num_codepoints = src_sz - num_of_discarded_bytes;
    debug("num_of_discarded_bytes: %u num_codepoints: %u\n", num_of_discarded_bytes, num_codepoints);
    FUNC(output_unicode)(d, output1, output2, output3, num_codepoints);
    if (num_of_trailing_bytes) scalar_decode_all(d, src + src_sz, num_of_trailing_bytes);
    return sentinel_found;
invalid_utf8:
    scalar_decode_all(d, src, src_sz + num_of_trailing_bytes);
    return sentinel_found;
}


#undef FUNC
#undef integer_t
#undef set1_epi8
#undef set_epi8
#undef load_unaligned
#undef load_aligned
#undef store_aligned
#undef cmpeq_epi8
#undef cmplt_epi8
#undef cmpgt_epi8
#undef or_si
#undef and_si
#undef andnot_si
#undef movemask_epi8
#undef CONCAT
#undef CONCAT_EXPAND
#undef KITTY_SIMD_LEVEL
#undef shift_right_by_one_byte
#undef shift_right_by_two_bytes
#undef shift_right_by_four_bytes
#undef shift_right_by_eight_bytes
#undef shift_right_by_sixteen_bytes
#undef shift_left_by_one_byte
#undef shift_left_by_two_bytes
#undef shift_left_by_four_bytes
#undef shift_left_by_eight_bytes
#undef shift_left_by_sixteen_bytes
#undef shift_left_by_bits16
#undef shift_right_by_bits32
#undef shift_right_by_bytes128
#undef extract_lower_quarter_as_chars
#undef extract_lower_half_as_chars
#undef blendv_epi8
#undef add_epi8
#undef subtract_saturate_epu8
#undef subtract_epi8
#undef create_zero_integer
#undef shuffle_epi8
#undef numbered_bytes
#undef reverse_numbered_bytes
#undef zero_last_n_bytes
#undef sum_bytes
#undef is_zero
#undef print_register_as_bytes
#endif // KITTY_NO_SIMD
