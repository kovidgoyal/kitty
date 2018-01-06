/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"

typedef struct {
    unsigned char action, transmission_type, compressed, delete_action;
    uint32_t format, more, id, data_sz, data_offset;
    uint32_t width, height, x_offset, y_offset, data_height, data_width, num_cells, num_lines, cell_x_offset, cell_y_offset;
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
    bool is_opaque;
} LoadData;

typedef struct {
    float left, top, right, bottom;
} ImageRect;

typedef struct {
    uint32_t src_width, src_height, src_x, src_y;
    uint32_t cell_x_offset, cell_y_offset, num_cols, num_rows, effective_num_rows, effective_num_cols;
    int32_t z_index;
    int32_t start_row, start_column;
    ImageRect src_rect;
} ImageRef;


typedef struct {
    uint32_t texture_id, client_id, width, height;
    size_t internal_id;

    bool data_loaded;
    LoadData load_data;

    ImageRef *refs;
    size_t refcnt, refcap;
    double atime;
    size_t used_storage;
} Image;

typedef struct {
    float vertices[16];
    uint32_t texture_id, group_count;
    int z_index;
    size_t image_id;
} ImageRenderData;

typedef struct {
    PyObject_HEAD

    size_t image_count, images_capacity, loading_image;
    GraphicsCommand last_init_graphics_command;
    Image *images;
    size_t count, capacity;
    ImageRenderData *render_data;
    bool layers_dirty;
    size_t num_of_negative_refs, num_of_positive_refs;
    unsigned int last_scrolled_by;
    size_t used_storage;
} GraphicsManager;


typedef struct {
    int32_t amt, limit;
    index_type margin_top, margin_bottom;
    bool has_margins;
} ScrollData;

GraphicsManager* grman_alloc();
void grman_clear(GraphicsManager*, bool);
const char* grman_handle_command(GraphicsManager *self, const GraphicsCommand *g, const uint8_t *payload, Cursor *c, bool *is_dirty);
bool grman_update_layers(GraphicsManager *self, unsigned int scrolled_by, float screen_left, float screen_top, float dx, float dy, unsigned int num_cols, unsigned int num_rows);
void grman_scroll_images(GraphicsManager *self, const ScrollData*);
void grman_resize(GraphicsManager*, index_type, index_type, index_type, index_type);
void grman_rescale(GraphicsManager *self, unsigned int old_cell_width, unsigned int old_cell_height);
