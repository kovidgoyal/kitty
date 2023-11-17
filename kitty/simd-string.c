/*
 * simd-string.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define SIMDE_ENABLE_NATIVE_ALIASES
#include "data-types.h"
#include "charsets.h"
#include "simd-string.h"
#ifdef __clang__
_Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wbitwise-instead-of-logical\"")
#endif
#include <simde/x86/avx2.h>
#ifdef __clang__
_Pragma("clang diagnostic pop")
#endif

static bool has_sse4_2 = false, has_avx2 = false;

// find_either_of_two_bytes {{{
static const uint8_t*
find_either_of_two_bytes_scalar(const uint8_t *haystack, const size_t sz, const uint8_t x, const uint8_t y) {
    for (const uint8_t *limit = haystack + sz; haystack < limit; haystack++) {
        if (*haystack == x || *haystack == y) return haystack;
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
    either_of_two(128, find_either_of_two_bytes_scalar(haystack, es, a, b));
}


static const uint8_t*
find_either_of_two_bytes_avx2(const uint8_t *haystack, size_t sz, const uint8_t a, const uint8_t b) {
    either_of_two(256, (has_sse4_2 && es > 15) ? find_either_of_two_bytes_sse4_2(haystack, es, a, b) : find_either_of_two_bytes_scalar(haystack, es, a, b));
}


static const uint8_t* (*find_either_of_two_bytes_impl)(const uint8_t*, const size_t, const uint8_t, const uint8_t) = find_either_of_two_bytes_scalar;

const uint8_t*
find_either_of_two_bytes(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    return (uint8_t*)find_either_of_two_bytes_impl(haystack, sz, a, b);
}
// }}}

// UTF-8 {{{

static unsigned
utf8_decode_to_sentinel_scalar(UTF8Decoder *d, const uint8_t *src, const size_t src_sz, const uint8_t sentinel) {
    unsigned num_consumed = 0, num_output = 0;
    while (num_consumed < src_sz && num_output < arraysz(d->output)) {
        const uint8_t ch = src[num_consumed++];
        if (ch < ' ') {
            zero_at_ptr(&d->state);
            if (num_output) { d->output_chars_callback(d->callback_data, d->output, num_output); num_output = 0; }
            d->control_byte_callback(d->callback_data, ch);
            if (ch == sentinel) break;
        } else {
            switch(decode_utf8(&d->state.cur, &d->state.codep, ch)) {
                case UTF8_ACCEPT:
                    d->output[num_output++] = d->state.codep;
                    break;
                case UTF8_REJECT: {
                    const bool prev_was_accept = d->state.prev == UTF8_ACCEPT;
                    zero_at_ptr(&d->state);
                    d->output[num_output++] = 0xfffd;
                    if (!prev_was_accept) {
                        num_consumed--;
                        continue; // so that prev is correct
                    }
                } break;
            }
        }
        d->state.prev = d->state.cur;
    }
    if (num_output) d->output_chars_callback(d->callback_data, d->output, num_output);
    return num_consumed;
}

unsigned
utf8_decode_to_sentinel(UTF8Decoder *d, const uint8_t *src, const size_t src_sz, const uint8_t sentinel) {
    return utf8_decode_to_sentinel_scalar(d, src, src_sz, sentinel);
}

// }}}
bool
init_simd(void *x) {
    PyObject *module = (PyObject*)x;
#define A(x, val) { Py_INCREF(Py_##val); if (0 != PyModule_AddObject(module, #x, Py_##val)) return false; }
#ifdef __APPLE__
#ifdef __arm64__
    // simde takes care of NEON on Apple Silicon
    has_sse4_2 = true; has_avx2 = true;
#else
    has_sse4_2 = __builtin_cpu_supports("sse4.2") != 0; has_avx2 = __builtin_cpu_supports("avx2");
#endif
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
        find_either_of_two_bytes_impl = find_either_of_two_bytes_avx2;
    } else {
        A(has_avx2, False);
    }
    if (has_sse4_2) {
        A(has_sse4_2, True);
        if (find_either_of_two_bytes_impl == find_either_of_two_bytes_scalar) find_either_of_two_bytes_impl = find_either_of_two_bytes_sse4_2;
    } else {
        A(has_sse4_2, False);
    }
#undef A
    return true;
}
