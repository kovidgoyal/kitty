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
#define integer_t CONCAT_EXPAND(CONCAT_EXPAND(__m, BITS), i)

#if BITS == 128
#define set1_epi8 simde_mm_set1_epi8
#define load_unaligned simde_mm_loadu_si128
#define cmpeq_epi8 simde_mm_cmpeq_epi8
#define or_si simde_mm_or_si128
#define movemask_epi8 simde_mm_movemask_epi8
#else
#define set1_epi8 simde_mm256_set1_epi8
#define load_unaligned simde_mm256_loadu_si256
#define cmpeq_epi8 simde_mm256_cmpeq_epi8
#define or_si simde_mm256_or_si256
#define movemask_epi8 simde_mm256_movemask_epi8
#endif

static inline const uint8_t*
FUNC(find_either_of_two_bytes)(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    integer_t a_vec = set1_epi8(a), b_vec = set1_epi8(b);
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

static inline unsigned
FUNC(utf8_decode_to_esc)(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    (void)d; (void)src; (void)src_sz;
    return 0;
}


#undef FUNC
#undef integer_t
#undef set1_epi8
#undef load_unaligned
#undef cmpeq_epi8
#undef or_si
#undef movemask_epi8
#undef CONCAT
#undef CONCAT_EXPAND
