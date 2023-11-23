/*
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <png.h>

typedef struct png_read_data png_read_data;

typedef void(*png_error_handler_func)(png_read_data *d, const char*, const char*);

typedef struct png_read_data {
    uint8_t *decompressed;
    bool ok;
    png_bytep *row_pointers;
    int width, height;
    size_t sz;
    png_error_handler_func err_handler;
    struct {
        char *buf;
        size_t used, capacity;
    } error;
} png_read_data;

void inflate_png_inner(png_read_data *d, const uint8_t *buf, size_t bufsz);
