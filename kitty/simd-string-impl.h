/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#ifndef BITS
#define BITS 128
#endif

#include "simd-string.h"

#ifdef __clang__
_Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wbitwise-instead-of-logical\"")
#endif
#include <simde/x86/avx2.h>
#ifdef __clang__
_Pragma("clang diagnostic pop")
#endif


#define CONCAT(A, B) A##B
#define CONCAT_EXPAND(A, B) CONCAT(A,B)
#define FUNC(name) CONCAT_EXPAND(name##_, BITS)
#define integer_t CONCAT_EXPAND(CONCAT_EXPAND(simde__m, BITS), i)
#define shift_right_by_bytes128 simde_mm_srli_si128
#define count_trailing_zeros __builtin_ctz

#if BITS == 128
#define set1_epi8 simde_mm_set1_epi8
#define add_epi8 simde_mm_add_epi8
#define load_unaligned simde_mm_loadu_si128
#define store_aligned simde_mm_store_si128
#define cmpeq_epi8 simde_mm_cmpeq_epi8
#define cmplt_epi8 simde_mm_cmplt_epi8
#define or_si simde_mm_or_si128
#define and_si simde_mm_and_si128
#define movemask_epi8 simde_mm_movemask_epi8
#define extract_lower_quarter_as_chars simde_mm_cvtepu8_epi32
#define shift_left_by_chars simde_mm_slli_epi32
#define shift_left_by_bytes simde_mm_slli_si128
#define blendv_epi8 simde_mm_blendv_epi8
// output[i] = MAX(0, a[i] - b[1i])
#define subtract_saturate_epu8 simde_mm_subs_epu8
#else
#define set1_epi8 simde_mm256_set1_epi8
#define add_epi8 simde_mm256_add_epi8
#define load_unaligned simde_mm256_loadu_si256
#define store_aligned simde_mm256_store_si256
#define cmpeq_epi8 simde_mm256_cmpeq_epi8
#define cmplt_epi8(a, b) simde_mm256_cmpgt_epi8(b, a)
#define or_si simde_mm256_or_si256
#define and_si simde_mm256_and_si256
#define movemask_epi8 simde_mm256_movemask_epi8
#define extract_lower_half_as_chars simde_mm256_cvtepu8_epi32
#define shift_left_by_chars simde_mm256_slli_epi32
#define shift_left_by_bytes simde_mm256_slli_si256
#define blendv_epi8 simde_mm256_blendv_epi8
#define subtract_saturate_epu8 simde_mm256_subs_epu8
#endif

static inline const uint8_t*
FUNC(find_either_of_two_bytes)(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    const integer_t a_vec = set1_epi8(a), b_vec = set1_epi8(b);
    for (const uint8_t* limit = haystack + sz; haystack < limit; haystack += sizeof(integer_t)) {
        const integer_t chunk = load_unaligned((integer_t*)haystack);
        const integer_t a_cmp = cmpeq_epi8(chunk, a_vec);
        const integer_t b_cmp = cmpeq_epi8(chunk, b_vec);
        const integer_t matches = or_si(a_cmp, b_cmp);
        const int mask = movemask_epi8(matches);
        if (mask != 0) {
            size_t pos = count_trailing_zeros(mask);
            const uint8_t *ans = haystack + pos;
            if (ans < limit) return ans;
        }
    }
    return NULL;
}

#define print_register_as_bytes(r) { \
        alignas(64) uint8_t data[sizeof(r)]; \
        store_aligned((integer_t*)data, r); \
        for (unsigned i = 0; i < sizeof(integer_t); i++) { \
            uint8_t ch = data[i]; \
            if (' ' <= ch && ch < 0x7f) printf(" %c ", ch); else printf("%.2x ", ch); \
        } \
        printf("\n"); \
}

static inline void
FUNC(output_plain_ascii)(UTF8Decoder *d, integer_t vec, size_t src_sz) {
#if BITS == 128
        for (const uint32_t *limit = d->output + src_sz, *p = d->output; p < limit; p += sizeof(integer_t)/sizeof(uint32_t)) {
            const integer_t unpacked = extract_lower_quarter_as_chars(vec);
            store_aligned((integer_t*)p, unpacked);
            vec = shift_right_by_bytes128(vec, sizeof(integer_t)/sizeof(uint32_t));
        }
#else
        const uint32_t *limit = d->output + src_sz, *p = d->output;
        simde__m128i x = simde_mm256_extractf128_si256(vec, 0);
        integer_t unpacked = extract_lower_half_as_chars(x);
        store_aligned((integer_t*)p, unpacked); p += sizeof(integer_t)/sizeof(uint32_t);
        if (p < limit) {
            x = shift_right_by_bytes128(x, sizeof(integer_t)/sizeof(uint32_t));
            unpacked = extract_lower_half_as_chars(x);
            store_aligned((integer_t*)p, unpacked); p += sizeof(integer_t)/sizeof(uint32_t);
            if (p < limit) {
                x = simde_mm256_extractf128_si256(vec, 1);
                unpacked = extract_lower_half_as_chars(x);
                store_aligned((integer_t*)p, unpacked); p += sizeof(integer_t)/sizeof(uint32_t);
                if (p < limit) {
                    x = shift_right_by_bytes128(x, sizeof(integer_t)/sizeof(uint32_t));
                    unpacked = extract_lower_half_as_chars(x);
                    store_aligned((integer_t*)p, unpacked); p += sizeof(integer_t)/sizeof(uint32_t);
                }
            }
        }
#endif
        d->output_sz = src_sz;
}

static inline bool
FUNC(utf8_decode_to_esc)(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    d->output_sz = 0; d->num_consumed = 0;
    src_sz = MIN(src_sz, sizeof(integer_t));
    integer_t vec = load_unaligned((integer_t*)src);

    const integer_t esc_vec = set1_epi8(0x1b);
    const integer_t esc_cmp = cmpeq_epi8(vec, esc_vec);
    const int esc_test_mask = movemask_epi8(esc_cmp);
    bool sentinel_found = false;
    const unsigned num_of_bytes_to_first_esc = count_trailing_zeros(esc_test_mask);
    if (num_of_bytes_to_first_esc < src_sz) {
        sentinel_found = true;
        d->num_consumed = num_of_bytes_to_first_esc + 1;  // esc is also consumed
        src_sz = d->num_consumed - 1;
    } else d->num_consumed = src_sz;

    const int ascii_test_mask = movemask_epi8(vec);
    const unsigned num_of_bytes_to_first_non_ascii_byte = count_trailing_zeros(ascii_test_mask);

    if (num_of_bytes_to_first_non_ascii_byte >= src_sz) {  // no bytes with high bit (0x80) set, so just plain ASCII
        FUNC(output_plain_ascii)(d, vec, src_sz);
        return sentinel_found;
    }

#if 1
    // Classify the bytes
    integer_t state = set1_epi8((char)0x80);
    integer_t vec_signed = add_epi8(vec, state);
    printf("source:\n"); print_register_as_bytes(vec);

    integer_t bytes_indicating_start_of_two_byte_sequence = cmplt_epi8(set1_epi8(0xc0 - 1 - 0x80), vec_signed);
    state = blendv_epi8(state , set1_epi8((char)0xc2),  bytes_indicating_start_of_two_byte_sequence);
    // state now has 0xc2 on all bytes that start a 2 byte sequence and 0x80 on the rest
    integer_t bytes_indicating_start_of_three_byte_sequence = cmplt_epi8(set1_epi8(0xe0 - 1 - 0x80), vec_signed);
    state = blendv_epi8(state , set1_epi8((char)0xe3),  bytes_indicating_start_of_three_byte_sequence);
    integer_t bytes_indicating_start_of_four_byte_sequence = cmplt_epi8(set1_epi8(0xf0 - 1 - 0x80), vec_signed);
    state = blendv_epi8(state , set1_epi8((char)0xf4),  bytes_indicating_start_of_four_byte_sequence);
    // state now has 0xc2 on all bytes that start a 2 byte sequence, 0xe3 on start of 3-byte sequence, 0xf4 on 4-byte start and 0x80 on rest
    print_register_as_bytes(state);
    integer_t mask = and_si(state, set1_epi8((char)0xf8));  // keep upper 5 bits of state
    printf("mask:\n"); print_register_as_bytes(mask);
    integer_t count = and_si(state, set1_epi8(0x7));  // keep lower 3 bits of state
    printf("count:\n"); print_register_as_bytes(count);
    // count contains 0 for ASCII and number of bytes in sequence for other bytes
#define subtract_shift_and_add(target, amt) add_epi8(target, shift_left_by_bytes(subtract_saturate_epu8(target, set1_epi8(amt)), amt))
    integer_t counts = subtract_shift_and_add(count, 1);
    counts = subtract_shift_and_add(counts, 2);
    printf("counts:\n"); print_register_as_bytes(counts);

#endif
    return sentinel_found;
}


#undef FUNC
#undef integer_t
#undef set1_epi8
#undef load_unaligned
#undef store_aligned
#undef cmpeq_epi8
#undef cmplt_epi8
#undef or_si
#undef and_si
#undef movemask_epi8
#undef CONCAT
#undef CONCAT_EXPAND
#undef BITS
#undef shift_left_by_chars
#undef shift_left_by_bytes
#undef shift_right_by_bytes128
#undef extract_lower_quarter_as_chars
#undef extract_lower_half_as_chars
#undef blendv_epi8
#undef add_epi8
#undef subtract_saturate_epu8
