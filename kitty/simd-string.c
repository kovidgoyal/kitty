/*
 * simd-string.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define SIMDE_ENABLE_NATIVE_ALIASES
#include "data-types.h"
#include "simd-string.h"
#include <simde/x86/avx2.h>

static bool has_sse4_2 = false, has_avx2 = false;

// ByteLoader {{{
uint8_t
byte_loader_peek(const ByteLoader *self) {
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
    return self->m & 0xff;
#define SHIFT_OP >>
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
    // no idea if this is correct needs testing
    return (self->m >> ((sizeof(self->m) - 1)*8)) & 0xff;
#define SHIFT_OP <<
#else
#error "Unsupported endianness"
#endif
}

void
byte_loader_init(ByteLoader *self, const uint8_t *buf, unsigned int sz) {
    size_t extra = ((uintptr_t)buf) % sizeof(BYTE_LOADER_T);
    if (extra) { // align loading
        buf -= extra; sz += extra;
    }
    size_t s = MIN(sz, sizeof(self->m));
    self->next_load_at = buf + s;
    self->num_left = sz - extra;
    self->digits_left = sizeof(self->m) - extra;
    self->m = (*((BYTE_LOADER_T*)buf)) SHIFT_OP (8 * extra);
    self->sz_of_next_load = sz - s;
}

uint8_t
byte_loader_next(ByteLoader *self) {
    uint8_t ans = byte_loader_peek(self);
    self->num_left--; self->digits_left--; self->m = self->m SHIFT_OP 8;
    if (!self->digits_left) byte_loader_init(self, self->next_load_at, self->sz_of_next_load);
    return ans;
}

static void
byte_loader_skip(ByteLoader *self) {
    if (self->num_left >= sizeof(BYTE_LOADER_T)) {
        self->m = *(BYTE_LOADER_T*)self->next_load_at;
        self->num_left -= sizeof(BYTE_LOADER_T);
        self->digits_left = sizeof(BYTE_LOADER_T);
        self->next_load_at += sizeof(BYTE_LOADER_T);
    } else {
        self->num_left = 0;
    }
}
// }}}

// find_either_of_two_bytes {{{
#define haszero(v) (((v) - 0x0101010101010101ULL) & ~(v) & 0x8080808080808080ULL)
#define prepare_for_hasvalue(n) (~0ULL/255 * (n))
#define hasvalue(x,n) (haszero((x) ^ (n)))

static const uint8_t*
find_either_of_two_bytes_simple(const uint8_t *haystack, const size_t sz, const uint8_t x, const uint8_t y) {
    ByteLoader it; byte_loader_init(&it, (uint8_t*)haystack, sz);

    // first align by testing the first few bytes one at a time
    while (it.num_left && it.digits_left < sizeof(BYTE_LOADER_T)) {
        const uint8_t ch = byte_loader_next(&it);
        if (ch == x || ch == y) return haystack + sz - it.num_left - 1;
    }

    const BYTE_LOADER_T a = prepare_for_hasvalue(x), b = prepare_for_hasvalue(y);
    while (it.num_left) {
        if (hasvalue(it.m, a) || hasvalue(it.m, b)) {
            const uint8_t *ans = haystack + sz - it.num_left, q = hasvalue(it.m, a) ? x : y;
            while (it.num_left) {
                if (byte_loader_next(&it) == q) return ans;
                ans++;
            }
            return NULL; // happens for final word and it.num_left < sizeof(BYTE_LOADER_T)
        }
        byte_loader_skip(&it);
    }
    return NULL;
}
#undef SHIFT_OP

#define _mm128_set1_epi8 _mm_set1_epi8
#define _mm128_load_si128 _mm_load_si128
#define _mm128_cmpeq_epi8 _mm_cmpeq_epi8
#define _mm128_or_si128 _mm_or_si128
#define _mm128_movemask_epi8 _mm_movemask_epi8
#define _mm128_cmpgt_epi8 _mm_cmpgt_epi8
#define _mm128_and_si128 _mm_and_si128

#define start_simd2(bits, aligner) \
    const size_t extra = (uintptr_t)haystack % sizeof(__m##bits##i); \
    if (extra) { /* do aligned loading */ \
        size_t es = MIN(sz, sizeof(__m##bits##i) - extra); \
        const uint8_t *ans = aligner; \
        if (ans) return ans; \
        sz -= es; \
        haystack += es; \
        if (!sz) return NULL; \
    } \
    __m##bits##i a_vec = _mm##bits##_set1_epi8(a); \
    __m##bits##i b_vec = _mm##bits##_set1_epi8(b); \
    for (const uint8_t* limit = haystack + sz; haystack < limit; haystack += sizeof(__m##bits##i))

#define end_simd2 \
    if (mask != 0) { \
        size_t pos = __builtin_ctz(mask); \
        if (haystack + pos < limit) return haystack + pos; \
    }

#define either_of_two(bits, aligner) \
    start_simd2(bits, aligner) { \
        __m##bits##i chunk = _mm##bits##_load_si##bits((__m##bits##i*)(haystack)); \
        __m##bits##i a_cmp = _mm##bits##_cmpeq_epi8(chunk, a_vec); \
        __m##bits##i b_cmp = _mm##bits##_cmpeq_epi8(chunk, b_vec); \
        __m##bits##i matches = _mm##bits##_or_si##bits(a_cmp, b_cmp); \
        const int mask = _mm##bits##_movemask_epi8(matches); \
        end_simd2; \
    } return NULL;

static const uint8_t*
find_either_of_two_bytes_sse4_2(const uint8_t *haystack, size_t sz, const uint8_t a, const uint8_t b) {
    either_of_two(128, find_either_of_two_bytes_simple(haystack, es, a, b));
}


static const uint8_t*
find_either_of_two_bytes_avx2(const uint8_t *haystack, size_t sz, const uint8_t a, const uint8_t b) {
    either_of_two(256, (has_sse4_2 && es > 15) ? find_either_of_two_bytes_sse4_2(haystack, es, a, b) : find_either_of_two_bytes_simple(haystack, es, a, b));
}


static const uint8_t* (*find_either_of_two_bytes_impl)(const uint8_t*, const size_t, const uint8_t, const uint8_t) = find_either_of_two_bytes_simple;

const uint8_t*
find_either_of_two_bytes(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    return (uint8_t*)find_either_of_two_bytes_impl(haystack, sz, a, b);
}
// }}}

// find_byte_not_in_range {{{
static const uint8_t*
find_byte_not_in_range_simple(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    ByteLoader it; byte_loader_init(&it, haystack, sz);
    while (it.num_left) {
        const uint8_t ch = byte_loader_next(&it);
        if (ch < a || ch > b) return haystack + sz - it.num_left - 1;
    }
    return NULL;
}

#define not_in_range(bits, aligner) \
    start_simd2(bits, aligner) { \
        __m##bits##i chunk = _mm##bits##_load_si##bits((__m##bits##i*)(haystack)); \
        __m##bits##i above_lower = _mm##bits##_cmpgt_epi8(chunk, a_vec); \
        __m##bits##i below_upper = _mm##bits##_cmpgt_epi8(b_vec, chunk); \
        __m##bits##i in_range = _mm##bits##_and_si##bits(above_lower, below_upper); \
        const int mask = ~_mm##bits##_movemask_epi8(in_range); /* ~ as we want not in range */ \
        end_simd2; \
    } return NULL;

static const uint8_t*
find_byte_not_in_range_sse4_2(const uint8_t *haystack, size_t sz, const uint8_t a, const uint8_t b) {
    not_in_range(128, find_byte_not_in_range_simple(haystack, es, a, b));
}


static const uint8_t*
find_byte_not_in_range_avx2(const uint8_t *haystack, size_t sz, const uint8_t a, const uint8_t b) {
    not_in_range(256, (has_sse4_2 && extra > 15) ? find_byte_not_in_range_sse4_2(haystack, es, a, b) : find_byte_not_in_range_simple(haystack, es, a, b));
}

static const uint8_t* (*find_byte_not_in_range_impl)(const uint8_t *haystack, size_t sz, const uint8_t a, const uint8_t b) = find_byte_not_in_range_simple;

const uint8_t*
find_byte_not_in_range(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    return (uint8_t*)find_byte_not_in_range_impl(haystack, sz, a, b);
}
// }}}

bool
init_simd(void *x) {
    PyObject *module = (PyObject*)x;
#define A(x, val) { Py_INCREF(Py_##val); if (0 != PyModule_AddObject(module, #x, Py_##val)) return false; }
#ifdef __APPLE__
    // Modern Apple Intel processors should all support AVX2. And simde takes care of NEON on Apple Silicon
    has_sse4_2 = true; has_avx2 = true;
#else
#ifdef __aarch64__
    // no idea how to probe ARM cpu for NEON support. This file uses pretty
    // basic AVX2 and SSE4.2 intrinsics, so hopefully they work on ARM
    has_sse4_2 = true; has_avx2 = true;
#else
    has_sse4_2 = __builtin_cpu_supports("sse4.2") != 0; has_avx2 = __builtin_cpu_supports("avx2");
#endif
#endif
    if (has_avx2) {
        A(has_avx2, True);
        find_byte_not_in_range_impl = find_byte_not_in_range_avx2;
        find_either_of_two_bytes_impl = find_either_of_two_bytes_avx2;
    } else {
        A(has_avx2, False);
    }
    if (has_sse4_2) {
        A(has_sse4_2, True);
        if (find_byte_not_in_range == find_byte_not_in_range_simple) find_byte_not_in_range_impl = find_byte_not_in_range_sse4_2;
        if (find_either_of_two_bytes_impl == find_either_of_two_bytes_simple) find_either_of_two_bytes_impl = find_either_of_two_bytes_sse4_2;
    } else {
        A(has_sse4_2, False);
    }
#undef A
    return true;
}
