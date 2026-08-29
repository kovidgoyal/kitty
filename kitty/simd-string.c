/*
 * simd-string.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "charsets.h"
#include "simd-string.h"
static bool has_sse4_2 = false, has_avx2 = false, has_avx512 = false;

// xor_data64 {{{
static void
xor_data64_scalar(const uint8_t key[64], uint8_t *data, const size_t data_sz) {
    for (size_t i = 0; i < data_sz; i++) data[i] ^= key[i & 63];
}
static void (*xor_data64_impl)(const uint8_t key[64], uint8_t *data, const size_t data_sz) = xor_data64_scalar;
void
xor_data64(const uint8_t key[64], uint8_t *data, const size_t data_sz) {
    xor_data64_impl(key, data, data_sz);
}
// }}}

// find_either_of_two_bytes {{{
static const uint8_t *
find_either_of_two_bytes_scalar(const uint8_t *haystack, const size_t sz, const uint8_t x, const uint8_t y) {
    for (const uint8_t *limit = haystack + sz; haystack < limit; haystack++) {
        if (*haystack == x || *haystack == y) return haystack;
    }
    return NULL;
}

static const uint8_t *(*find_either_of_two_bytes_impl)(const uint8_t *, const size_t, const uint8_t, const uint8_t) = find_either_of_two_bytes_scalar;

const uint8_t *
find_either_of_two_bytes(const uint8_t *haystack, const size_t sz, const uint8_t a, const uint8_t b) {
    return (uint8_t *)find_either_of_two_bytes_impl(haystack, sz, a, b);
}
// }}}

// pixel compositing {{{
static void
blend_over_straight_scalar(uint8_t *dst, const uint8_t *src, const size_t num_pixels) {
    for (size_t i = 0; i < num_pixels; i++) blend_pixel_over_straight(dst + 4 * i, src + 4 * i);
}
static void (*blend_over_straight_impl)(uint8_t *, const uint8_t *, size_t) = blend_over_straight_scalar;
void
blend_over_straight(uint8_t *dst, const uint8_t *src, size_t num_pixels) {
    blend_over_straight_impl(dst, src, num_pixels);
}

static void
blend_over_opaque_scalar(uint8_t *dst, const unsigned dst_bpp, const uint8_t *src, const size_t num_pixels) {
    for (size_t i = 0; i < num_pixels; i++) blend_pixel_over_opaque(dst + dst_bpp * i, src + 4 * i, dst_bpp);
}
static void (*blend_over_opaque_impl)(uint8_t *, unsigned, const uint8_t *, size_t) = blend_over_opaque_scalar;
void
blend_over_opaque(uint8_t *dst, unsigned dst_bpp, const uint8_t *src, size_t num_pixels) {
    blend_over_opaque_impl(dst, dst_bpp, src, num_pixels);
}

static void
composite_alpha_mask_scalar(uint32_t *dst, const uint8_t *mask, const size_t num_pixels, const uint32_t color_rgb) {
    const uint32_t col = (color_rgb << 8) & 0xffffff00;
    for (size_t i = 0; i < num_pixels; i++) {
        const uint32_t dst_alpha = dst[i] & 0xff, mask_alpha = mask[i];
        dst[i] = col | MAX(mask_alpha, dst_alpha);
    }
}
static void (*composite_alpha_mask_impl)(uint32_t *, const uint8_t *, size_t, uint32_t) = composite_alpha_mask_scalar;
void
composite_alpha_mask(uint32_t *dst, const uint8_t *mask, size_t num_pixels, uint32_t color_rgb) {
    composite_alpha_mask_impl(dst, mask, num_pixels, color_rgb);
}
// }}}

// printable_ascii_run_length {{{
static size_t
printable_ascii_run_length_scalar(const uint32_t *chars, const size_t sz) {
    size_t n = 0;
    while (n < sz && (chars[n] - 32u) < 95u) n++;
    return n;
}

static size_t (*printable_ascii_run_length_impl)(const uint32_t *, const size_t) = printable_ascii_run_length_scalar;

size_t
printable_ascii_run_length(const uint32_t *chars, const size_t sz) {
    return printable_ascii_run_length_impl(chars, sz);
}
// }}}

// UTF-8 {{{

bool
utf8_decode_to_esc_scalar(UTF8Decoder *d, const uint8_t *src, const size_t src_sz) {
    d->output.pos = 0;
    d->num_consumed = 0;
    utf8_decoder_ensure_capacity(d, src_sz);
    while (d->num_consumed < src_sz) {
        const uint8_t ch = src[d->num_consumed++];
        if (ch == 0x1b) {
            if (d->state.cur != UTF8_ACCEPT) d->output.storage[d->output.pos++] = 0xfffd;
            zero_at_ptr(&d->state);
            return true;
        } else {
            switch (decode_utf8(&d->state.cur, &d->state.codep, ch)) {
                case UTF8_ACCEPT: d->output.storage[d->output.pos++] = d->state.codep; break;
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
static PyObject *
test_utf8_decode_to_sentinel(PyObject *self UNUSED, PyObject *args) {
    const uint8_t *src;
    Py_ssize_t src_sz;
    int which_function = 0;
    static UTF8Decoder d = {0};
    if (!PyArg_ParseTuple(args, "s#|i", &src, &src_sz, &which_function)) return NULL;
    bool found_sentinel = false;
    bool (*func)(UTF8Decoder *, const uint8_t *, size_t sz) = utf8_decode_to_esc;
    switch (which_function) {
        case -1: zero_at_ptr(&d); Py_RETURN_NONE;
        case 1: func = utf8_decode_to_esc_scalar; break;
        case 2: func = utf8_decode_to_esc_128; break;
        case 3: func = utf8_decode_to_esc_256; break;
        case 4: func = utf8_decode_to_esc_512; break;
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

static PyObject *
test_find_either_of_two_bytes(PyObject *self UNUSED, PyObject *args) {
    RAII_PY_BUFFER(buf);
    int which_function = 0, align_offset = 0;
    const uint8_t *(*func)(const uint8_t *, const size_t sz, const uint8_t, const uint8_t) = find_either_of_two_bytes;
    unsigned char a, b;
    if (!PyArg_ParseTuple(args, "s*BB|ii", &buf, &a, &b, &which_function, &align_offset)) return NULL;
    switch (which_function) {
        case 1: func = find_either_of_two_bytes_scalar; break;
        case 2: func = find_either_of_two_bytes_128; break;
        case 3: func = find_either_of_two_bytes_256; break;
        case 4: func = find_either_of_two_bytes_512; break;
        case 0: break;
        default: PyErr_SetString(PyExc_ValueError, "Unknown which_function"); return NULL;
    }
    uint8_t *abuf;
    if (posix_memalign((void **)&abuf, 64, 256 + buf.len) != 0) { return PyErr_NoMemory(); }
    uint8_t *p = abuf;
    memset(p, '<', 64 + align_offset);
    p += 64 + align_offset;
    memcpy(p, buf.buf, buf.len);
    memset(p + buf.len, '>', 64);
    const uint8_t *ans = func(p, buf.len, a, b);
    free(abuf);
    if (ans == NULL) return PyLong_FromLong(-1);
    unsigned long long n = ans - p;
    return PyLong_FromUnsignedLongLong(n);
}

static PyObject *
test_printable_ascii_run_length(PyObject *self UNUSED, PyObject *args) {
    PyObject *text;
    int which_function = 0;
    size_t (*func)(const uint32_t *, const size_t) = printable_ascii_run_length;
    if (!PyArg_ParseTuple(args, "U|i", &text, &which_function)) return NULL;
    switch (which_function) {
        case 1: func = printable_ascii_run_length_scalar; break;
        case 2: func = printable_ascii_run_length_128; break;
        case 3: func = printable_ascii_run_length_256; break;
        case 4: func = printable_ascii_run_length_512; break;
        case 0: break;
        default: PyErr_SetString(PyExc_ValueError, "Unknown which_function"); return NULL;
    }
    Py_UCS4 *chars = PyUnicode_AsUCS4Copy(text);
    if (!chars) return NULL;
    const size_t ans = func(chars, PyUnicode_GET_LENGTH(text));
    PyMem_Free(chars);
    return PyLong_FromSize_t(ans);
}

static PyObject *
test_xor64(PyObject *self UNUSED, PyObject *args) {
    RAII_PY_BUFFER(buf);
    RAII_PY_BUFFER(key);
    int which_function = 0, align_offset = 0;
    void (*func)(const uint8_t key[64], uint8_t *data, const size_t data_sz) = xor_data64;
    if (!PyArg_ParseTuple(args, "s*s*|ii", &key, &buf, &which_function, &align_offset)) return NULL;
    switch (which_function) {
        case 1: func = xor_data64_scalar; break;
        case 2: func = xor_data64_128; break;
        case 3: func = xor_data64_256; break;
        case 4: func = xor_data64_512; break;
        case 0: break;
        default: PyErr_SetString(PyExc_ValueError, "Unknown which_function"); return NULL;
    }
    uint8_t *abuf;
    if (posix_memalign((void **)&abuf, 64, 256 + buf.len) != 0) { return PyErr_NoMemory(); }
    uint8_t *p = abuf;
    memset(p, '<', 64 + align_offset);
    p += 64 + align_offset;
    memcpy(p, buf.buf, buf.len);
    memset(p + buf.len, '>', 64);
    func(key.buf, p, buf.len);
    PyObject *ans = NULL;
    for (int i = 0; i < 64 + align_offset; i++)
        if (abuf[i] != '<') { PyErr_SetString(PyExc_SystemError, "xor wrote before start of data region"); }
    for (int i = 0; i < 64; i++)
        if (p[i + buf.len] != '>') { PyErr_SetString(PyExc_SystemError, "xor wrote after end of data region"); }
    if (!PyErr_Occurred()) ans = PyBytes_FromStringAndSize((const char *)p, buf.len);
    free(abuf);
    return ans;
}

static PyObject *
test_blend_pixels(PyObject *self UNUSED, PyObject *args) {
    const char *kind;
    RAII_PY_BUFFER(dst);
    RAII_PY_BUFFER(src);
    int which_function = 0, align_offset = 0;
    unsigned long color = 0xffffff;
    if (!PyArg_ParseTuple(args, "ss*s*|iki", &kind, &dst, &src, &which_function, &color, &align_offset)) return NULL;
    align_offset &= 63;
    void (*straight)(uint8_t *, const uint8_t *, size_t) = NULL;
    void (*opaque)(uint8_t *, unsigned, const uint8_t *, size_t) = NULL;
    void (*mask)(uint32_t *, const uint8_t *, size_t, uint32_t) = NULL;
    unsigned dst_bpp = 4;
    size_t num_pixels;
    if (strcmp(kind, "straight") == 0) {
        num_pixels = (size_t)src.len / 4;
        switch (which_function) {
            case 0: straight = blend_over_straight; break;
            case 1: straight = blend_over_straight_scalar; break;
            case 2: straight = blend_over_straight_128; break;
            case 3: straight = blend_over_straight_256; break;
            case 4: straight = blend_over_straight_512; break;
        }
    } else if (strcmp(kind, "opaque") == 0 || strcmp(kind, "opaque3") == 0) {
        if (strcmp(kind, "opaque3") == 0) dst_bpp = 3;
        num_pixels = (size_t)src.len / 4;
        switch (which_function) {
            case 0: opaque = blend_over_opaque; break;
            case 1: opaque = blend_over_opaque_scalar; break;
            case 2: opaque = blend_over_opaque_128; break;
            case 3: opaque = blend_over_opaque_256; break;
            case 4: opaque = blend_over_opaque_512; break;
        }
    } else if (strcmp(kind, "mask") == 0) {
        num_pixels = (size_t)src.len;
        switch (which_function) {
            case 0: mask = composite_alpha_mask; break;
            case 1: mask = composite_alpha_mask_scalar; break;
            case 2: mask = composite_alpha_mask_128; break;
            case 3: mask = composite_alpha_mask_256; break;
            case 4: mask = composite_alpha_mask_512; break;
        }
    } else {
        PyErr_Format(PyExc_KeyError, "Unknown kind: %s", kind);
        return NULL;
    }
    if (!straight && !opaque && !mask) {
        PyErr_SetString(PyExc_ValueError, "Unknown which_function");
        return NULL;
    }
    const size_t expected_dst_sz = num_pixels * (mask ? 4 : dst_bpp);
    if ((size_t)dst.len != expected_dst_sz) {
        PyErr_Format(PyExc_ValueError, "dst must be %zu bytes not %zd", expected_dst_sz, dst.len);
        return NULL;
    }
    uint8_t *abuf;
    if (posix_memalign((void **)&abuf, 64, 192 + dst.len) != 0) return PyErr_NoMemory();
    uint8_t *p = abuf + 64 + align_offset;
    memset(abuf, '<', 64 + align_offset);
    memcpy(p, dst.buf, dst.len);
    memset(p + dst.len, '>', 64);
    if (straight) straight(p, src.buf, num_pixels);
    else if (opaque) opaque(p, dst_bpp, src.buf, num_pixels);
    else mask((uint32_t *)p, src.buf, num_pixels, (uint32_t)color);
    PyObject *ans = NULL;
    for (int i = 0; i < 64 + align_offset; i++)
        if (abuf[i] != '<') {
            PyErr_SetString(PyExc_SystemError, "blend wrote before start of data region");
            break;
        }
    for (int i = 0; i < 64; i++)
        if (p[i + dst.len] != '>') {
            PyErr_SetString(PyExc_SystemError, "blend wrote after end of data region");
            break;
        }
    if (!PyErr_Occurred()) ans = PyBytes_FromStringAndSize((const char *)p, dst.len);
    free(abuf);
    return ans;
}

// }}}

static PyMethodDef module_methods[] = {
    METHODB(test_utf8_decode_to_sentinel, METH_VARARGS),
    METHODB(test_find_either_of_two_bytes, METH_VARARGS),
    METHODB(test_printable_ascii_run_length, METH_VARARGS),
    METHODB(test_xor64, METH_VARARGS),
    METHODB(test_blend_pixels, METH_VARARGS),
    {NULL, NULL, 0, NULL} /* Sentinel */
};

bool
init_simd(void *x) {
    PyObject *module = (PyObject *)x;
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
#define A(x, val)                                                        \
    {                                                                    \
        Py_INCREF(Py_##val);                                             \
        if (0 != PyModule_AddObject(module, #x, Py_##val)) return false; \
    }
#define do_check()                                                                                                                    \
    {                                                                                                                                 \
        has_sse4_2 = __builtin_cpu_supports("sse4.2") != 0;                                                                           \
        has_avx2 = __builtin_cpu_supports("avx2") != 0;                                                                               \
        has_avx512 = __builtin_cpu_supports("avx512f") && __builtin_cpu_supports("avx512bw") && __builtin_cpu_supports("avx512vl") && \
                     __builtin_cpu_supports("avx512vbmi2");                                                                           \
    }

#ifdef __APPLE__
#ifdef __arm64__
    // simde takes care of NEON on Apple Silicon
    // ARM has only 128 bit registers but using the avx2 code is still slightly faster
    has_sse4_2 = true;
    has_avx2 = true;
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
    has_sse4_2 = true;
    has_avx2 = true;
#elif !defined(KITTY_NO_SIMD)
    do_check();
#endif
#endif
    const char *simd_env = getenv("KITTY_SIMD");
    if (simd_env) {
        has_sse4_2 = strcmp(simd_env, "128") == 0;
        has_avx2 = strcmp(simd_env, "256") == 0;
        has_avx512 = strcmp(simd_env, "512") == 0;
    }

#undef do_check
    if (has_avx512) {
        A(has_avx512, True);
        utf8_decode_to_esc_impl = utf8_decode_to_esc_512;
        find_either_of_two_bytes_impl = find_either_of_two_bytes_512;
        xor_data64_impl = xor_data64_512;
        printable_ascii_run_length_impl = printable_ascii_run_length_512;
        blend_over_straight_impl = blend_over_straight_512;
        blend_over_opaque_impl = blend_over_opaque_512;
        composite_alpha_mask_impl = composite_alpha_mask_512;
    } else {
        A(has_avx512, False);
    }
    if (has_avx2) {
        A(has_avx2, True);
        if (find_either_of_two_bytes_impl == find_either_of_two_bytes_scalar) find_either_of_two_bytes_impl = find_either_of_two_bytes_256;
        if (utf8_decode_to_esc_impl == utf8_decode_to_esc_scalar) utf8_decode_to_esc_impl = utf8_decode_to_esc_256;
        if (xor_data64_impl == xor_data64_scalar) xor_data64_impl = xor_data64_256;
        if (printable_ascii_run_length_impl == printable_ascii_run_length_scalar) printable_ascii_run_length_impl = printable_ascii_run_length_256;
        if (blend_over_straight_impl == blend_over_straight_scalar) blend_over_straight_impl = blend_over_straight_256;
        if (blend_over_opaque_impl == blend_over_opaque_scalar) blend_over_opaque_impl = blend_over_opaque_256;
        if (composite_alpha_mask_impl == composite_alpha_mask_scalar) composite_alpha_mask_impl = composite_alpha_mask_256;
    } else {
        A(has_avx2, False);
    }
    if (has_sse4_2) {
        A(has_sse4_2, True);
        if (find_either_of_two_bytes_impl == find_either_of_two_bytes_scalar) find_either_of_two_bytes_impl = find_either_of_two_bytes_128;
        if (utf8_decode_to_esc_impl == utf8_decode_to_esc_scalar) utf8_decode_to_esc_impl = utf8_decode_to_esc_128;
        if (xor_data64_impl == xor_data64_scalar) xor_data64_impl = xor_data64_128;
        if (printable_ascii_run_length_impl == printable_ascii_run_length_scalar) printable_ascii_run_length_impl = printable_ascii_run_length_128;
        if (blend_over_straight_impl == blend_over_straight_scalar) blend_over_straight_impl = blend_over_straight_128;
        if (blend_over_opaque_impl == blend_over_opaque_scalar) blend_over_opaque_impl = blend_over_opaque_128;
        if (composite_alpha_mask_impl == composite_alpha_mask_scalar) composite_alpha_mask_impl = composite_alpha_mask_128;
    } else {
        A(has_sse4_2, False);
    }
#undef A
    return true;
}
