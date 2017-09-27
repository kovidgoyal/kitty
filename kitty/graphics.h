/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"

typedef struct {
    unsigned char action, transmission_type;
    uint32_t format, more, id;
    uint32_t width, height, x_offset, y_offset, data_height, data_width, num_cells, num_lines;
    int32_t z_index;
    size_t payload_sz;
} GraphicsCommand;


typedef struct {
    uint32_t gl_id, client_id, width, height;
    size_t internal_id, refcnt;
    uint8_t *load_buf;
} Image;


typedef struct {
    PyObject_HEAD

    index_type lines, columns;
    size_t image_count, images_capacity;
    Image *images;
} GraphicsManager;
PyTypeObject GraphicsManager_Type;


GraphicsManager* grman_realloc(GraphicsManager *, index_type lines, index_type columns);
void grman_clear(GraphicsManager*);
GraphicsManager* grman_free(GraphicsManager*);
void grman_handle_command(GraphicsManager *self, const GraphicsCommand *g, const uint8_t *payload);
