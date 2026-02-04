/*
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

typedef struct jxl_read_data jxl_read_data;

typedef void(*jxl_error_handler_func)(jxl_read_data *d, const char*, const char*);

typedef struct jxl_read_data {
    uint8_t *decompressed;
    bool ok;
    int width, height;
    size_t sz;
    jxl_error_handler_func err_handler;
    struct {
        char *buf;
        size_t used, capacity;
    } error;
} jxl_read_data;

void inflate_jxl_inner(jxl_read_data *d, const uint8_t *buf, size_t bufsz, int max_image_dimension);
bool jxl_from_data(void *jxl_data, size_t jxl_data_sz, const char *path_for_error_messages, uint8_t** data, unsigned int* width, unsigned int* height, size_t* sz);
