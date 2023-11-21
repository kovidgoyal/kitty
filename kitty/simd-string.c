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
#include "simd-string-impl.h"
#undef BITS
#define BITS 256
#include "simd-string-impl.h"
static bool has_sse4_2 = false, has_avx2 = false;

// find_either_of_two_bytes {{{
static const uint8_t*
find_either_of_two_bytes_scalar(const uint8_t *haystack, const size_t sz, const uint8_t x, const uint8_t y) {
    for (const uint8_t *limit = haystack + sz; haystack < limit; haystack++) {
        if (*haystack == x || *haystack == y) return haystack;
    }
    return NULL;
}

static const uint8_t* (*find_either_of_two_bytes_impl)(const uint8_t*, const size_t, const uint8_t, const uint8_t) = find_either_of_two_bytes_scalar;

const uint8_t*
find_either_of_two_bytes(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    return (uint8_t*)find_either_of_two_bytes_impl(haystack, sz, a, b);
}
// }}}

// UTF-8 {{{

static bool
utf8_decode_to_esc_scalar(UTF8Decoder *d, const uint8_t *src, const size_t src_sz) {
    d->output_sz = 0; d->num_consumed = 0;
    while (d->num_consumed < src_sz && d->output_sz < arraysz(d->output)) {
        const uint8_t ch = src[d->num_consumed++];
        if (ch == 0x1b) {
            if (d->state.cur != UTF8_ACCEPT) d->output[d->output_sz++] = 0xfffd;
            zero_at_ptr(&d->state);
            return true;
        } else {
            switch(decode_utf8(&d->state.cur, &d->state.codep, ch)) {
                case UTF8_ACCEPT:
                    d->output[d->output_sz++] = d->state.codep;
                    break;
                case UTF8_REJECT: {
                    const bool prev_was_accept = d->state.prev == UTF8_ACCEPT;
                    zero_at_ptr(&d->state);
                    d->output[d->output_sz++] = 0xfffd;
                    if (!prev_was_accept && d->num_consumed) {
                        d->num_consumed--;
                        continue; // so that prev is correct
                    }
                } break;
            }
        }
        d->state.prev = d->state.cur;
    }
    return false;
}

static bool (*utf8_decode_to_esc_impl)(UTF8Decoder *d, const uint8_t *src, size_t src_sz) = utf8_decode_to_esc_scalar;

bool
utf8_decode_to_esc(UTF8Decoder *d, const uint8_t *src, size_t src_sz) {
    return utf8_decode_to_esc_impl(d, src, src_sz);
}

// }}}

// Boilerplate {{{
static PyObject*
test_utf8_decode_to_sentinel(PyObject *self UNUSED, PyObject *args) {
    const uint8_t *src; Py_ssize_t src_sz;
    int which_function = 0;
    static UTF8Decoder d = {0};
    if (!PyArg_ParseTuple(args, "s#|i", &src, &src_sz, &which_function)) return NULL;
    bool found_sentinel = false;
    bool(*func)(UTF8Decoder*, const uint8_t*, size_t sz) = utf8_decode_to_esc;
    switch(which_function) {
        case -1:
            zero_at_ptr(&d); Py_RETURN_NONE;
        case 1:
            func = utf8_decode_to_esc_scalar; break;
        case 2:
            func = utf8_decode_to_esc_128; break;
        case 3:
            func = utf8_decode_to_esc_256; break;
    }
    RAII_PyObject(ans, PyUnicode_FromString(""));
    ssize_t p = 0;
    while(p < src_sz && !found_sentinel) {
        found_sentinel = func(&d, src + p, src_sz - p);
        p += d.num_consumed;
        if (d.output_sz) {
            RAII_PyObject(temp, PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, d.output, d.output_sz));
            PyObject *t = PyUnicode_Concat(ans, temp);
            Py_DECREF(ans);
            ans = t;
        }
    }
    return Py_BuildValue("OO", found_sentinel ? Py_True : Py_False, ans);
}
// }}}

static PyMethodDef module_methods[] = {
    METHODB(test_utf8_decode_to_sentinel, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_simd(void *x) {
    PyObject *module = (PyObject*)x;
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
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
        find_either_of_two_bytes_impl = find_either_of_two_bytes_256;
        /* utf8_decode_to_sentinel_impl = utf8_decode_to_sentinel_256; */
    } else {
        A(has_avx2, False);
    }
    if (has_sse4_2) {
        A(has_sse4_2, True);
        if (find_either_of_two_bytes_impl == find_either_of_two_bytes_scalar) find_either_of_two_bytes_impl = find_either_of_two_bytes_128;
        /* if (utf8_decode_to_sentinel_impl == utf8_decode_to_sentinel_scalar) utf8_decode_to_sentinel_impl = utf8_decode_to_sentinel_128; */
    } else {
        A(has_sse4_2, False);
    }
#undef A
    return true;
}
