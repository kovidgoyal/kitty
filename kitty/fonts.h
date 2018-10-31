/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "lineops.h"
#include "state.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <hb.h>
#pragma GCC diagnostic pop

typedef struct {
    uint8_t *canvas;
    size_t width, height;
} StringCanvas;

// API that font backends need to implement
typedef uint16_t glyph_index;
unsigned int glyph_id_for_codepoint(PyObject *, char_type);
int get_glyph_width(PyObject *, glyph_index);
bool is_glyph_empty(PyObject *, glyph_index);
hb_font_t* harfbuzz_font_for_face(PyObject*);
bool set_size_for_face(PyObject*, unsigned int, bool, FONTS_DATA_HANDLE);
void cell_metrics(PyObject*, unsigned int*, unsigned int*, unsigned int*, unsigned int*, unsigned int*);
bool render_glyphs_in_cells(PyObject *f, bool bold, bool italic, hb_glyph_info_t *info, hb_glyph_position_t *positions, unsigned int num_glyphs, pixel *canvas, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, unsigned int baseline, bool *was_colored, FONTS_DATA_HANDLE, bool center_glyph);
PyObject* create_fallback_face(PyObject *base_face, CPUCell* cell, bool bold, bool italic, bool emoji_presentation, FONTS_DATA_HANDLE fg);
PyObject* specialize_font_descriptor(PyObject *base_descriptor, FONTS_DATA_HANDLE);
PyObject* face_from_path(const char *path, int index, FONTS_DATA_HANDLE);
PyObject* face_from_descriptor(PyObject*, FONTS_DATA_HANDLE);

void sprite_tracker_current_layout(FONTS_DATA_HANDLE data, unsigned int *x, unsigned int *y, unsigned int *z);
void render_alpha_mask(uint8_t *alpha_mask, pixel* dest, Region *src_rect, Region *dest_rect, size_t src_stride, size_t dest_stride);
void render_line(FONTS_DATA_HANDLE, Line *line, index_type lnum, Cursor *cursor);
void sprite_tracker_set_limits(size_t max_texture_size, size_t max_array_len);
typedef void (*free_extra_data_func)(void*);
StringCanvas render_simple_text_impl(PyObject *s, const char *text, unsigned int baseline);
StringCanvas render_simple_text(FONTS_DATA_HANDLE fg_, const char *text);

static inline void
right_shift_canvas(pixel *canvas, size_t width, size_t height, size_t amt) {
    pixel *src;
    size_t r;
    for (r = 0, src = canvas; r < height; r++, src += width) {
        memmove(src + amt, src, sizeof(pixel) * (width - amt));
        memset(src, 0, sizeof(pixel) * amt);
    }
}
