/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"

typedef struct {
    unsigned char action, transmission_type, compressed;
    uint32_t format, more, id, data_sz, data_offset;
    uint32_t width, height, x_offset, y_offset, data_height, data_width, num_cells, num_lines;
    int32_t z_index;
    size_t payload_sz;
} GraphicsCommand;

typedef struct {
    uint8_t *buf;
    size_t buf_capacity, buf_used;

    uint8_t *mapped_file;
    size_t mapped_file_sz;

    size_t data_sz;
    uint8_t *data;
    bool is_4byte_aligned;
} LoadData;

typedef struct {
    uint32_t texture_id, client_id, width, height;
    size_t internal_id, refcnt;

    bool data_loaded;
    LoadData load_data;
} Image;


typedef struct {
    PyObject_HEAD

    index_type lines, columns;
    size_t image_count, images_capacity, loading_image;
    Image *images;
} GraphicsManager;
PyTypeObject GraphicsManager_Type;


GraphicsManager* grman_realloc(GraphicsManager *, index_type lines, index_type columns);
void grman_clear(GraphicsManager*);
const char* grman_handle_command(GraphicsManager *self, const GraphicsCommand *g, const uint8_t *payload);
