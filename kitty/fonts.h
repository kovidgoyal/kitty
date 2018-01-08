/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "lineops.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <hb.h>
#pragma GCC diagnostic pop


// API that font backends need to implement
unsigned int glyph_id_for_codepoint(PyObject *, char_type);
hb_font_t* harfbuzz_font_for_face(PyObject*);
bool set_size_for_face(PyObject*, unsigned int, bool);
void cell_metrics(PyObject*, unsigned int*, unsigned int*, unsigned int*, unsigned int*, unsigned int*);
bool render_glyphs_in_cells(PyObject *f, bool bold, bool italic, hb_glyph_info_t *info, hb_glyph_position_t *positions, unsigned int num_glyphs, pixel *canvas, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, unsigned int baseline, bool *was_colored);
PyObject* create_fallback_face(PyObject *base_face, Cell* cell, bool bold, bool italic);
PyObject* specialize_font_descriptor(PyObject *base_descriptor);
PyObject* face_from_path(const char *path, int index);
PyObject* face_from_descriptor(PyObject*);

void sprite_tracker_current_layout(unsigned int *x, unsigned int *y, unsigned int *z);
void render_alpha_mask(uint8_t *alpha_mask, pixel* dest, Region *src_rect, Region *dest_rect, size_t src_stride, size_t dest_stride);
void render_line(Line *line);
void sprite_tracker_set_limits(size_t max_texture_size, size_t max_array_len);
void sprite_tracker_set_layout(unsigned int cell_width, unsigned int cell_height);
typedef void (*free_extra_data_func)(void*);
PyObject* ft_face_from_data(const uint8_t* data, size_t sz, void *extra_data, free_extra_data_func fed, PyObject *path, int hinting, int hintstyle, float);
PyObject* ft_face_from_path_and_psname(PyObject* path, const char* psname, void *extra_data, free_extra_data_func fed, int hinting, int hintstyle, float);

static inline void
right_shift_canvas(pixel *canvas, size_t width, size_t height, size_t amt) {
    pixel *src;
    size_t r;
    for (r = 0, src = canvas; r < height; r++, src += width) {
        memmove(src + amt, src, sizeof(pixel) * (width - amt));
        memset(src, 0, sizeof(pixel) * amt);
    }
}
