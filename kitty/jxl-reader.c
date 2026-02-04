/*
 * jxl-reader.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "jxl-reader.h"
#include "cleanup.h"
#include "state.h"

#include <jxl/decode.h>
#include <jxl/thread_parallel_runner.h>

#define ABRT(code, msg) { if(d->err_handler) d->err_handler(d, #code, msg); goto err; }

void
inflate_jxl_inner(jxl_read_data *d, const uint8_t *buf, size_t bufsz, int max_image_dimension) {
    JxlDecoder *dec = NULL;
    void *runner = NULL;
    JxlBasicInfo info;
    JxlPixelFormat format = {4, JXL_TYPE_UINT8, JXL_NATIVE_ENDIAN, 0};

    dec = JxlDecoderCreate(NULL);
    if (!dec) ABRT(ENOMEM, "Failed to create JXL decoder");

    runner = JxlThreadParallelRunnerCreate(NULL, JxlThreadParallelRunnerDefaultNumWorkerThreads());
    if (!runner) ABRT(ENOMEM, "Failed to create JXL parallel runner");

    if (JxlDecoderSetParallelRunner(dec, JxlThreadParallelRunner, runner) != JXL_DEC_SUCCESS) {
        ABRT(EINVAL, "Failed to set JXL parallel runner");
    }

    if (JxlDecoderSubscribeEvents(dec, JXL_DEC_BASIC_INFO | JXL_DEC_FULL_IMAGE) != JXL_DEC_SUCCESS) {
        ABRT(EINVAL, "Failed to subscribe to JXL events");
    }

    if (JxlDecoderSetInput(dec, buf, bufsz) != JXL_DEC_SUCCESS) {
        ABRT(EINVAL, "Failed to set JXL input");
    }
    JxlDecoderCloseInput(dec);

    JxlDecoderStatus status;
    while ((status = JxlDecoderProcessInput(dec)) != JXL_DEC_SUCCESS) {
        switch (status) {
            case JXL_DEC_ERROR:
                ABRT(EBADMSG, "JXL decoding error");
            case JXL_DEC_NEED_MORE_INPUT:
                ABRT(EINVAL, "JXL decoder needs more input (incomplete file?)");
            case JXL_DEC_BASIC_INFO:
                if (JxlDecoderGetBasicInfo(dec, &info) != JXL_DEC_SUCCESS) {
                    ABRT(EINVAL, "Failed to get JXL basic info");
                }
                d->width = info.xsize;
                d->height = info.ysize;
                if (d->width > max_image_dimension || d->height > max_image_dimension) {
                    ABRT(ENOMEM, "JXL image is too large");
                }
                break;
            case JXL_DEC_NEED_IMAGE_OUT_BUFFER: {
                size_t buffer_size;
                if (JxlDecoderImageOutBufferSize(dec, &format, &buffer_size) != JXL_DEC_SUCCESS) {
                    ABRT(EINVAL, "Failed to get JXL output buffer size");
                }
                d->sz = buffer_size;
                d->decompressed = malloc(d->sz + 16);
                if (d->decompressed == NULL) {
                    ABRT(ENOMEM, "Out of memory allocating decompression buffer for JXL");
                }
                if (JxlDecoderSetImageOutBuffer(dec, &format, d->decompressed, d->sz) != JXL_DEC_SUCCESS) {
                    ABRT(EINVAL, "Failed to set JXL output buffer");
                }
                break;
            }
            case JXL_DEC_FULL_IMAGE:
                // Image is ready
                break;
            default:
                // Continue processing
                break;
        }
    }

    d->ok = true;
err:
    if (runner) JxlThreadParallelRunnerDestroy(runner);
    if (dec) JxlDecoderDestroy(dec);
    return;
}

#undef ABRT

static void
print_jxl_read_error(jxl_read_data *d, const char *code, const char* msg) {
    if (d->error.used >= d->error.capacity) {
        size_t cap = MAX(2 * d->error.capacity, 1024 + d->error.used);
        d->error.buf = realloc(d->error.buf, cap);
        if (!d->error.buf) return;
        d->error.capacity = cap;
    }
    d->error.used += snprintf(d->error.buf + d->error.used, d->error.capacity - d->error.used, "%s: %s ", code, msg);
}

bool
jxl_from_data(void *jxl_data, size_t jxl_data_sz, const char *path_for_error_messages, uint8_t** data, unsigned int* width, unsigned int* height, size_t* sz) {
    jxl_read_data d = {.err_handler=print_jxl_read_error};
    inflate_jxl_inner(&d, jxl_data, jxl_data_sz, 10000);
    if (!d.ok) {
        log_error("Failed to decode JXL image at: %s with error: %s", path_for_error_messages, d.error.used > 0 ? d.error.buf : "unknown");
        free(d.decompressed); free(d.error.buf);
        return false;
    }
    *data = d.decompressed;
    free(d.error.buf);
    *sz = d.sz;
    *height = d.height; *width = d.width;
    return true;
}

static void
jxl_error_handler(jxl_read_data *d UNUSED, const char *code, const char *msg) {
    if (!PyErr_Occurred()) PyErr_Format(PyExc_ValueError, "[%s] %s", code, msg);
}

static PyObject*
load_jxl_data(PyObject *self UNUSED, PyObject *args) {
    Py_ssize_t sz;
    const char *data;
    if (!PyArg_ParseTuple(args, "s#", &data, &sz)) return NULL;
    jxl_read_data d = {.err_handler=jxl_error_handler};
    inflate_jxl_inner(&d, (const uint8_t*)data, sz, 10000);
    PyObject *ans = NULL;
    if (d.ok && !PyErr_Occurred()) {
        ans = Py_BuildValue("y#ii", d.decompressed, (int)d.sz, d.width, d.height);
    } else {
        if (!PyErr_Occurred()) PyErr_SetString(PyExc_ValueError, "Unknown error while reading JXL data");
    }
    free(d.decompressed);
    return ans;
}

static PyMethodDef jxl_module_methods[] = {
    METHODB(load_jxl_data, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_jxl_reader(PyObject *module) {
    if (PyModule_AddFunctions(module, jxl_module_methods) != 0) return false;
    return true;
}
