/*
 * simd-string.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "simd-string.h"
#include <immintrin.h>

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

static uint8_t*
find_either_of_two_bytes_simple(uint8_t *haystack, const size_t sz, const uint8_t x, const uint8_t y) {
    ByteLoader it; byte_loader_init(&it, (uint8_t*)haystack, sz);

    // first align by testing the first few bytes one at a time
    while (it.num_left && it.digits_left < sizeof(BYTE_LOADER_T)) {
        const uint8_t ch = byte_loader_next(&it);
        if (ch == x || ch == y) return haystack + sz - it.num_left - 1;
    }

    const BYTE_LOADER_T a = prepare_for_hasvalue(x), b = prepare_for_hasvalue(y);
    while (it.num_left) {
        if (hasvalue(it.m, a) || hasvalue(it.m, b)) {
            uint8_t *ans = haystack + sz - it.num_left, q = hasvalue(it.m, a) ? x : y;
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

static uint8_t*
find_either_of_two_bytes_sse4_2_impl(uint8_t *haystack, const uint8_t* needle_, size_t sz) {
    const size_t extra = (uintptr_t)haystack % sizeof(__m128i);
    if (extra) { // need aligned loads for performance so search first few bytes by hand
        const size_t es = MIN(sz, sizeof(__m128i) - extra);
        uint8_t *ans = find_either_of_two_bytes_simple(haystack, es, needle_[0], needle_[1]);
        if (ans) return ans;
        sz -= es;
        haystack += es;
        if (!sz) return NULL;
    }
    const __m128i needle = _mm_load_si128((const __m128i *)needle_);
    for (const uint8_t* limit = haystack + sz; haystack < limit; haystack += 16) {
        const __m128i h = _mm_load_si128((const __m128i *)haystack);
        int c = _mm_cmpistri(needle, h, _SIDD_CMP_EQUAL_ANY);
        if (c != 16 && haystack + c < limit) {
            return haystack + c;
        }
    }
    return NULL;
}

static uint8_t*
find_either_of_two_bytes_sse4_2(uint8_t *haystack, const size_t sz, const uint8_t x, const uint8_t y) {
    uint8_t before = haystack[sz];
    haystack[sz] = 0;
    uint8_t needle[16] = {x, y, 0,0,0,0,0,0,0,0,0,0,0,0,0,0};
    uint8_t *ans = find_either_of_two_bytes_sse4_2_impl(haystack, needle, sz);
    haystack[sz] = before;
    return ans;
}

#define start_simd2(bits, aligner) \
    const size_t extra = (uintptr_t)haystack % sizeof(__m##bits##i); \
    if (extra) { /* do aligned loading */ \
        size_t es = MIN(sz, sizeof(__m##bits##i) - extra); \
        uint8_t *ans = aligner; \
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

static uint8_t*
find_either_of_two_bytes_avx2(uint8_t *haystack, size_t sz, const uint8_t a, const uint8_t b) {
    either_of_two(256, (has_sse4_2 && es > 15) ? find_either_of_two_bytes_sse4_2(haystack, es, a, b) : find_either_of_two_bytes_simple(haystack, es, a, b));
}


static uint8_t* (*find_either_of_two_bytes_impl)(uint8_t*, const size_t, const uint8_t, const uint8_t) = find_either_of_two_bytes_simple;

uint8_t*
find_either_of_two_bytes(uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    return (uint8_t*)find_either_of_two_bytes_impl(haystack, sz, a, b);
}
// }}}

// find_byte_not_in_range {{{
static uint8_t*
find_byte_not_in_range_simple(uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    ByteLoader it; byte_loader_init(&it, haystack, sz);
    while (it.num_left) {
        const uint8_t ch = byte_loader_next(&it);
        if (ch < a || ch > b) return haystack + sz - it.num_left - 1;
    }
    return NULL;
}

static uint8_t*
find_byte_not_in_range_sse4_2_impl(uint8_t *haystack, const uint8_t* needle_, size_t sz) {
    const size_t extra = (uintptr_t)haystack % sizeof(__m128i);
    if (extra) { // need aligned loads for performance so search first few bytes by hand
        size_t es = MIN(sz, sizeof(__m128i) - extra);
        uint8_t *ans = find_byte_not_in_range_simple(haystack, es, needle_[0], needle_[1]);
        if (ans) return ans;
        sz -= es;
        haystack += es;
        if (!sz) return NULL;
    }
    const __m128i needle = _mm_load_si128((const __m128i *)needle_);
    for (const uint8_t* limit = haystack + sz; haystack < limit; haystack += sizeof(__m128i)) {
        const __m128i h = _mm_load_si128((const __m128i *)haystack);
        int c = _mm_cmpistri(needle, h, _SIDD_CMP_RANGES | _SIDD_NEGATIVE_POLARITY);
        if (c != 16 && haystack + c < limit) {
            return haystack + c;
        }
    }
    return NULL;
}


static uint8_t*
find_byte_not_in_range_sse4_2(uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    uint8_t before = haystack[sz];
    haystack[sz] = 0;
    uint8_t needle[16] = {a, b, 0, 0, 0,0,0,0,0,0,0,0,0,0,0,0};
    uint8_t *ans = (uint8_t*)find_byte_not_in_range_sse4_2_impl((uint8_t*)haystack, needle, sz);
    haystack[sz] = before;
    return ans;

}

#define not_in_range(bits, aligner) \
    start_simd2(bits, aligner) { \
        __m256i chunk = _mm256_load_si256((__m256i*)(haystack)); \
        __m256i above_lower = _mm256_cmpgt_epi8(chunk, a_vec); \
        __m256i below_upper = _mm256_cmpgt_epi8(b_vec, chunk); \
        __m256i in_range = _mm256_and_si256(above_lower, below_upper); \
        const int mask = ~_mm256_movemask_epi8(in_range); /* ~ as we want not in range */ \
        end_simd2; \
    } return NULL;

static uint8_t*
find_byte_not_in_range_avx2(uint8_t *haystack, size_t sz, const uint8_t a, const uint8_t b) {
    not_in_range(256, (has_sse4_2 && extra > 15) ? find_byte_not_in_range_sse4_2(haystack, es, a, b) : find_byte_not_in_range_simple(haystack, es, a, b));
}

static uint8_t* (*find_byte_not_in_range_impl)(uint8_t *haystack, size_t sz, const uint8_t a, const uint8_t b) = find_byte_not_in_range_simple;

uint8_t*
find_byte_not_in_range(uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    return (uint8_t*)find_byte_not_in_range_impl(haystack, sz, a, b);
}
// }}}

bool
init_simd(void *x) {
    PyObject *module = (PyObject*)x;
#define A(x, val) { Py_INCREF(Py_##val); if (0 != PyModule_AddObject(module, #x, Py_##val)) return false; }
    has_sse4_2 = __builtin_cpu_supports("sse4.2") != 0; has_avx2 = __builtin_cpu_supports("avx2");
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
