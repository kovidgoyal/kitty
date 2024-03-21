/*
 * simd-string.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "charsets.h"
#include "simd-string.h"
static bool has_sse4_2 = false, has_avx2 = false;

// xor_data64 {{{
static void xor_data64_scalar(const uint8_t key[64], uint8_t* data, const size_t data_sz) { for (size_t i = 0; i < data_sz; i++) data[i] ^= key[i & 63]; }
static void (*xor_data64_impl)(const uint8_t key[64], uint8_t* data, const size_t data_sz) = xor_data64_scalar;
void xor_data64(const uint8_t key[64], uint8_t* data, const size_t data_sz) { xor_data64_impl(key, data, data_sz); }
// }}}

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

bool
utf8_decode_to_esc_scalar(UTF8Decoder *d, const uint8_t *src, const size_t src_sz) {
    d->output.pos = 0; d->num_consumed = 0;
    utf8_decoder_ensure_capacity(d, src_sz);
    while (d->num_consumed < src_sz) {
        const uint8_t ch = src[d->num_consumed++];
        if (ch == 0x1b) {
            if (d->state.cur != UTF8_ACCEPT) d->output.storage[d->output.pos++] = 0xfffd;
            zero_at_ptr(&d->state);
            return true;
        } else {
            switch(decode_utf8(&d->state.cur, &d->state.codep, ch)) {
                case UTF8_ACCEPT:
                    d->output.storage[d->output.pos++] = d->state.codep;
                    break;
                case UTF8_REJECT: {
                    const bool prev_was_accept = d->state.prev == UTF8_ACCEPT;
                    zero_at_ptr(&d->state);
                    d->output.storage[d->output.pos++] = 0xfffd;
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
    switch (which_function) {
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
    while (p < src_sz && !found_sentinel) {
        found_sentinel = func(&d, src + p, src_sz - p);
        p += d.num_consumed;
        if (d.output.pos) {
            RAII_PyObject(temp, PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, d.output.storage, d.output.pos));
            PyObject *t = PyUnicode_Concat(ans, temp);
            Py_DECREF(ans);
            ans = t;
        }
    }
    utf8_decoder_free(&d);
    return Py_BuildValue("OOi", found_sentinel ? Py_True : Py_False, ans, p);
}

static PyObject*
test_find_either_of_two_bytes(PyObject *self UNUSED, PyObject *args) {
    RAII_PY_BUFFER(buf);
    int which_function = 0, align_offset = 0;
    const uint8_t*(*func)(const uint8_t*, const size_t sz, const uint8_t, const uint8_t) = find_either_of_two_bytes;
    unsigned char a, b;
    if (!PyArg_ParseTuple(args, "s*BB|ii", &buf, &a, &b, &which_function, &align_offset)) return NULL;
    switch (which_function) {
        case 1:
            func = find_either_of_two_bytes_scalar; break;
        case 2:
            func = find_either_of_two_bytes_128; break;
        case 3:
            func = find_either_of_two_bytes_256; break;
        case 0: break;
        default:
            PyErr_SetString(PyExc_ValueError, "Unknown which_function");
            return NULL;
    }
    uint8_t *abuf;
    if (posix_memalign((void**)&abuf, 64, 256 + buf.len) != 0) {
        return PyErr_NoMemory();
    }
    uint8_t *p = abuf;
    memset(p, '<', 64 + align_offset); p += 64 + align_offset;
    memcpy(p, buf.buf, buf.len);
    memset(p + buf.len, '>', 64);
    const uint8_t *ans = func(p, buf.len, a, b);
    free(abuf);
    if (ans == NULL) return PyLong_FromLong(-1);
    unsigned long long n = ans - p;
    return PyLong_FromUnsignedLongLong(n);
}

static PyObject*
test_xor64(PyObject *self UNUSED, PyObject *args) {
    RAII_PY_BUFFER(buf);
    RAII_PY_BUFFER(key);
    int which_function = 0, align_offset = 0;
    void (*func)(const uint8_t key[64], uint8_t* data, const size_t data_sz) = xor_data64;
    if (!PyArg_ParseTuple(args, "s*s*|ii", &key, &buf, &which_function, &align_offset)) return NULL;
    switch (which_function) {
        case 1:
            func = xor_data64_scalar; break;
        case 2:
            func = xor_data64_128; break;
        case 3:
            func = xor_data64_256; break;
        case 0: break;
        default:
            PyErr_SetString(PyExc_ValueError, "Unknown which_function");
            return NULL;
    }
    uint8_t *abuf;
    if (posix_memalign((void**)&abuf, 64, 256 + buf.len) != 0) {
        return PyErr_NoMemory();
    }
    uint8_t *p = abuf;
    memset(p, '<', 64 + align_offset); p += 64 + align_offset;
    memcpy(p, buf.buf, buf.len);
    memset(p + buf.len, '>', 64);
    func(key.buf, p, buf.len);
    PyObject *ans = NULL;
    for (int i = 0; i < 64 + align_offset; i++) if (abuf[i] != '<') { PyErr_SetString(PyExc_SystemError, "xor wrote before start of data region"); }
    for (int i = 0; i < 64; i++) if (p[i + buf.len] != '>') { PyErr_SetString(PyExc_SystemError, "xor wrote after end of data region"); }
    if (!PyErr_Occurred()) ans = PyBytes_FromStringAndSize((const char*)p, buf.len);
    free(abuf);
    return ans;
}


// }}}

static PyMethodDef module_methods[] = {
    METHODB(test_utf8_decode_to_sentinel, METH_VARARGS),
    METHODB(test_find_either_of_two_bytes, METH_VARARGS),
    METHODB(test_xor64, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_simd(void *x) {
    PyObject *module = (PyObject*)x;
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
#define A(x, val) { Py_INCREF(Py_##val); if (0 != PyModule_AddObject(module, #x, Py_##val)) return false; }
#define do_check() { has_sse4_2 = __builtin_cpu_supports("sse4.2") != 0; has_avx2 = __builtin_cpu_supports("avx2") != 0; }

#ifdef __APPLE__
#ifdef __arm64__
    // simde takes care of NEON on Apple Silicon
    // ARM has only 128 bit registers but using the avx2 code is still slightly faster
    has_sse4_2 = true; has_avx2 = true;
#else
    do_check();
    // On GitHub actions there are some weird macOS machines which report avx2 not available but sse4.2 is available and then
    // SIGILL when using basic sse instructions
    if (!has_avx2 && has_sse4_2) {
        const char *ci = getenv("CI");
        if (ci && strcmp(ci, "true") == 0) has_sse4_2 = false;
    }
#endif
#else
#ifdef __aarch64__
    // no idea how to probe ARM cpu for NEON support. This file uses pretty
    // basic AVX2 and SSE4.2 intrinsics, so hopefully they work on ARM
    // ARM has only 128 bit registers but using the avx2 code is still slightly faster
    has_sse4_2 = true; has_avx2 = true;
#elif !defined(KITTY_NO_SIMD)
    do_check();
#endif
#endif
    const char *simd_env = getenv("KITTY_SIMD");
    if (simd_env) {
        has_sse4_2 = strcmp(simd_env, "128") == 0;
        has_avx2 = strcmp(simd_env, "256") == 0;
    }

#undef do_check
    if (has_avx2) {
        A(has_avx2, True);
        find_either_of_two_bytes_impl = find_either_of_two_bytes_256;
        utf8_decode_to_esc_impl = utf8_decode_to_esc_256;
        xor_data64_impl = xor_data64_256;
    } else {
        A(has_avx2, False);
    }
    if (has_sse4_2) {
        A(has_sse4_2, True);
        if (find_either_of_two_bytes_impl == find_either_of_two_bytes_scalar) find_either_of_two_bytes_impl = find_either_of_two_bytes_128;
        if (utf8_decode_to_esc_impl == utf8_decode_to_esc_scalar) utf8_decode_to_esc_impl = utf8_decode_to_esc_128;
        if (xor_data64_impl == xor_data64_scalar) xor_data64_impl = xor_data64_128;
    } else {
        A(has_sse4_2, False);
    }
#undef A
    return true;
}
