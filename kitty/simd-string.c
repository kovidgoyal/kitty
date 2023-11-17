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

static unsigned
utf8_decode_to_sentinel_sse4_2(UTF8Decoder *d, const uint8_t *src, const size_t src_sz, const uint8_t sentinel) {
    (void)d; (void)src; (void)src_sz; (void)sentinel;
    return 0;
}

static unsigned (*utf8_decode_to_sentinel_impl)(UTF8Decoder *d, const uint8_t *src, const size_t src_sz, const uint8_t sentinel) = utf8_decode_to_sentinel_scalar;

unsigned
utf8_decode_to_sentinel(UTF8Decoder *d, const uint8_t *src, const size_t src_sz, const uint8_t sentinel) {
    return utf8_decode_to_sentinel_impl(d, src, src_sz, sentinel);
}

// }}}

// Boilerplate {{{
static void
test_control_byte_callback(void *l, uint8_t ch) {
    if (!PyErr_Occurred()) {
        RAII_PyObject(c, PyLong_FromUnsignedLong((unsigned long)ch));
        if (c) PyList_Append((PyObject*)l, c);
    }
}

static void
test_output_chars_callback(void *l, const uint32_t *chars, unsigned sz) {
    if (!PyErr_Occurred()) {
        RAII_PyObject(c, PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, chars, (Py_ssize_t)sz));
        if (c) PyList_Append((PyObject*)l, c);
    }
}

static PyObject*
test_utf8_decode_to_sentinel(PyObject *self UNUSED, PyObject *args) {
    const uint8_t *src; Py_ssize_t src_sz;
    int which_function = 0;
    static UTF8Decoder d = {0};
    unsigned char sentinel = 0x1b;
    if (!PyArg_ParseTuple(args, "s#|iB", &src, &src_sz, &which_function, &sentinel)) return NULL;
    RAII_PyObject(ans, PyList_New(0));
    d.callback_data = ans;
    d.control_byte_callback = test_control_byte_callback;
    d.output_chars_callback = test_output_chars_callback;
    unsigned long consumed;
    switch(which_function) {
        case -1:
            zero_at_ptr(&d); Py_RETURN_NONE;
        case 1:
            consumed = utf8_decode_to_sentinel_scalar(&d, src, src_sz, sentinel); break;
        case 2:
            consumed = utf8_decode_to_sentinel_sse4_2(&d, src, src_sz, sentinel); break;
        default:
            consumed = utf8_decode_to_sentinel(&d, src, src_sz, sentinel); break;
    }
    return Py_BuildValue("kO", consumed, ans);
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
    } else {
        A(has_avx2, False);
    }
    if (has_sse4_2) {
        A(has_sse4_2, True);
        if (find_either_of_two_bytes_impl == find_either_of_two_bytes_scalar) find_either_of_two_bytes_impl = find_either_of_two_bytes_128;
        /* if (utf8_decode_to_sentinel_impl == utf8_decode_to_sentinel_scalar) utf8_decode_to_sentinel_impl = utf8_decode_to_sentinel_sse4_2; */
    } else {
        A(has_sse4_2, False);
    }
#undef A
    return true;
}
