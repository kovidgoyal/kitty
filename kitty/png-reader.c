/*
 * png-reader.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "png-reader.h"
#include "cleanup.h"
#include "state.h"
#include <lcms2.h>


static cmsHPROFILE srgb_profile = NULL;
struct fake_file { const uint8_t *buf; size_t sz, cur; };

static void
read_png_from_buffer(png_structp png, png_bytep out, png_size_t length) {
    struct fake_file *f = png_get_io_ptr(png);
    if (f) {
        size_t amt = MIN(length, f->sz - f->cur);
        memcpy(out, f->buf + f->cur, amt);
        f->cur += amt;
    }
}

struct custom_error_handler {
    jmp_buf jb;
    png_read_data *d;
};

static void
read_png_error_handler(png_structp png_ptr, png_const_charp msg) {
    struct custom_error_handler *eh;
    eh = png_get_error_ptr(png_ptr);
    if (eh == NULL) fatal("read_png_error_handler: could not retrieve error handler");
    if(eh->d->err_handler) eh->d->err_handler(eh->d, "EBADPNG", msg);
    longjmp(eh->jb, 1);
}

static void
read_png_warn_handler(png_structp UNUSED png_ptr, png_const_charp msg) {
    if (global_state.debug_rendering) log_error("libpng WARNING: %s", msg);
}

#define ABRT(code, msg) { if(d->err_handler) d->err_handler(d, #code, msg); goto err; }

void
inflate_png_inner(png_read_data *d, const uint8_t *buf, size_t bufsz) {
    struct fake_file f = {.buf = buf, .sz = bufsz};
    png_structp png = NULL;
    png_infop info = NULL;
    struct custom_error_handler eh = {.d = d};
    png = png_create_read_struct(PNG_LIBPNG_VER_STRING, &eh, read_png_error_handler, read_png_warn_handler);
    if (!png) ABRT(ENOMEM, "Failed to create PNG read structure");
    info = png_create_info_struct(png);
    if (!info) ABRT(ENOMEM, "Failed to create PNG info structure");

    if (setjmp(eh.jb)) goto err;

    png_set_read_fn(png, &f, read_png_from_buffer);
    png_read_info(png, info);
    png_byte color_type, bit_depth;
    d->width      = png_get_image_width(png, info);
    d->height     = png_get_image_height(png, info);
    color_type = png_get_color_type(png, info);
    bit_depth  = png_get_bit_depth(png, info);
    double image_gamma;
    int intent;
    cmsHPROFILE input_profile = NULL;
    cmsHTRANSFORM colorspace_transform = NULL;
    if (png_get_sRGB(png, info, &intent)) {
        // do nothing since we output sRGB
    } else if (png_get_gAMA(png, info, &image_gamma)) {
        if (image_gamma != 0 && fabs(image_gamma - 1.0/2.2) > 0.0001) png_set_gamma(png, 2.2, image_gamma);
    } else {
        // Look for an embedded color profile
        png_charp name;
        int compression_type;
        png_bytep profdata;
        png_uint_32 proflen;
        if (png_get_iCCP(png, info, &name, &compression_type, &profdata, &proflen) & PNG_INFO_iCCP) {
            input_profile = cmsOpenProfileFromMem(profdata, proflen);
            if (input_profile) {
                if (!srgb_profile) {
                    srgb_profile = cmsCreate_sRGBProfile();
                    if (!srgb_profile) ABRT(ENOMEM, "Out of memory allocating sRGB colorspace profile");
                }
                colorspace_transform = cmsCreateTransform(
                    input_profile, TYPE_RGBA_8, srgb_profile, TYPE_RGBA_8, INTENT_PERCEPTUAL, 0);

            }
        }
    }

    // Ensure we get RGBA data out of libpng
    if (bit_depth == 16) png_set_strip_16(png);
    if (color_type == PNG_COLOR_TYPE_PALETTE) png_set_palette_to_rgb(png);
    // PNG_COLOR_TYPE_GRAY_ALPHA is always 8 or 16bit depth.
    if (color_type == PNG_COLOR_TYPE_GRAY && bit_depth < 8) png_set_expand_gray_1_2_4_to_8(png);

    if (png_get_valid(png, info, PNG_INFO_tRNS)) png_set_tRNS_to_alpha(png);

    // These color_type don't have an alpha channel then fill it with 0xff.
    if (color_type == PNG_COLOR_TYPE_RGB || color_type == PNG_COLOR_TYPE_GRAY || color_type == PNG_COLOR_TYPE_PALETTE) png_set_filler(png, 0xFF, PNG_FILLER_AFTER);

    if (color_type == PNG_COLOR_TYPE_GRAY || color_type == PNG_COLOR_TYPE_GRAY_ALPHA) png_set_gray_to_rgb(png);
    png_read_update_info(png, info);

    png_uint_32 rowbytes = png_get_rowbytes(png, info);
    d->sz = sizeof(png_byte) * rowbytes * d->height;
    d->decompressed = malloc(d->sz + 16);
    if (d->decompressed == NULL) ABRT(ENOMEM, "Out of memory allocating decompression buffer for PNG");
    d->row_pointers = malloc(d->height * sizeof(png_bytep));
    if (d->row_pointers == NULL) ABRT(ENOMEM, "Out of memory allocating row_pointers buffer for PNG");
    for (size_t i = 0; i < (size_t)d->height; i++) d->row_pointers[i] = d->decompressed + i * rowbytes * sizeof(png_byte);
    png_read_image(png, d->row_pointers);

    if (colorspace_transform) {
        for (int i = 0; i < d->height; i++) {
            cmsDoTransform(colorspace_transform, d->row_pointers[i], d->row_pointers[i], d->width);
        }
        cmsDeleteTransform(colorspace_transform);
    }
    if (input_profile) cmsCloseProfile(input_profile);

    d->ok = true;
err:
    if (png) png_destroy_read_struct(&png, info ? &info : NULL, NULL);
    return;
}

static void
png_error_handler(png_read_data *d UNUSED, const char *code, const char *msg) {
    if (!PyErr_Occurred()) PyErr_Format(PyExc_ValueError, "[%s] %s", code, msg);
}

static PyObject*
load_png_data(PyObject *self UNUSED, PyObject *args) {
    Py_ssize_t sz;
    const char *data;
    if (!PyArg_ParseTuple(args, "s#", &data, &sz)) return NULL;
    png_read_data d = {.err_handler=png_error_handler};
    inflate_png_inner(&d, (const uint8_t*)data, sz);
    PyObject *ans = NULL;
    if (d.ok && !PyErr_Occurred()) {
        ans = Py_BuildValue("y#ii", d.decompressed, (int)d.sz, d.width, d.height);
    } else {
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "Unknown error while reading PNG data");
    }
    free(d.decompressed);
    free(d.row_pointers);
    return ans;
}

static PyMethodDef module_methods[] = {
    METHODB(load_png_data, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


static void
unload(void) {
    if (srgb_profile) cmsCloseProfile(srgb_profile);
    srgb_profile = NULL;
}

bool
init_png_reader(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    register_at_exit_cleanup_func(PNG_READER_CLEANUP_FUNC, unload);
    return true;
}
