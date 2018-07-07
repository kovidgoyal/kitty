/*
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#include <png.h>
typedef void(*png_error_handler_func)(const char*, const char*);
typedef struct {
    uint8_t *decompressed;
    bool ok;
    png_bytep *row_pointers;
    int width, height;
    size_t sz;
    png_error_handler_func err_handler;
} png_read_data;

void inflate_png_inner(png_read_data *d, const uint8_t *buf, size_t bufsz);
