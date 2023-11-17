/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#ifndef BITS
#define BITS 128
#endif

#ifdef __clang__
_Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wbitwise-instead-of-logical\"")
#endif
#include <simde/x86/avx2.h>
#ifdef __clang__
_Pragma("clang diagnostic pop")
#endif


#if BITS == 128
#define FUNC(name) name##_##128
#define integer_t __m128i
#define set1_epi8 simde_mm_set1_epi8
#define load_unaligned simde_mm_loadu_si128
#define cmpeq_epi8 simde_mm_cmpeq_epi8
#define or_si simde_mm_or_si128
#define movemask_epi8 simde_mm_movemask_epi8
#else
#define FUNC(name) name##_##256
#define integer_t __m256i
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


#undef FUNC
#undef integer_t
#undef set1_epi8
#undef load_unaligned
#undef cmpeq_epi8
#undef or_si
#undef movemask_epi8
