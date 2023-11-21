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

#if BITS == 128
#define set1_epi8 simde_mm_set1_epi8
#define load_unaligned simde_mm_loadu_si128
#define store_aligned simde_mm_store_si128
#define cmpeq_epi8 simde_mm_cmpeq_epi8
#define or_si simde_mm_or_si128
#define movemask_epi8 simde_mm_movemask_epi8
#define extract_lower_quarter_as_chars simde_mm_cvtepu8_epi32
#define shift_left_by_chars simde_mm_slli_epi32
#define shift_left_by_bytes simde_mm_slli_si128
#else
#define set1_epi8 simde_mm256_set1_epi8
#define load_unaligned simde_mm256_loadu_si256
#define store_aligned simde_mm256_store_si256
#define cmpeq_epi8 simde_mm256_cmpeq_epi8
#define or_si simde_mm256_or_si256
#define movemask_epi8 simde_mm256_movemask_epi8
#define extract_lower_half_as_chars simde_mm256_cvtepu8_epi32
#define shift_left_by_chars simde_mm256_slli_epi32
#define shift_left_by_bytes simde_mm256_slli_si256
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
            size_t pos = __builtin_ctz(mask);
            const uint8_t *ans = haystack + pos;
            if (ans < limit) return ans;
        }
    }
    return NULL;
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
    const unsigned num_of_bytes_to_first_esc = __builtin_ctz(esc_test_mask);
    if (num_of_bytes_to_first_esc < src_sz) {
        sentinel_found = true;
        d->num_consumed = num_of_bytes_to_first_esc + 1;  // esc is also consumed
        src_sz = d->num_consumed - 1;
    } else d->num_consumed = src_sz;

    const int ascii_test_mask = movemask_epi8(vec);
    const unsigned num_of_bytes_to_first_non_ascii_byte = __builtin_ctz(ascii_test_mask);

    // Plain ASCII {{{
    if (num_of_bytes_to_first_non_ascii_byte >= src_sz) {  // no bytes with high bit (0x80) set, so just plain ASCII
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
        return sentinel_found;
    } // }}}

    return sentinel_found;
}


#undef FUNC
#undef integer_t
#undef set1_epi8
#undef load_unaligned
#undef store_aligned
#undef cmpeq_epi8
#undef or_si
#undef movemask_epi8
#undef CONCAT
#undef CONCAT_EXPAND
#undef BITS
#undef shift_left_by_chars
#undef shift_left_by_bytes
#undef shift_right_by_bytes128
#undef extract_lower_quarter_as_chars
#undef extract_lower_half_as_chars
