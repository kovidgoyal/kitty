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
unsigned int glyph_id_for_codepoint(PyObject *, char_type);
int get_glyph_width(PyObject *, glyph_index);
bool is_glyph_empty(PyObject *, glyph_index);
hb_font_t* harfbuzz_font_for_face(PyObject*);
bool set_size_for_face(PyObject*, unsigned int, bool, FONTS_DATA_HANDLE);
void cell_metrics(PyObject*, unsigned int*, unsigned int*, unsigned int*, unsigned int*, unsigned int*, unsigned int*, unsigned int*);
bool render_glyphs_in_cells(PyObject *f, bool bold, bool italic, hb_glyph_info_t *info, hb_glyph_position_t *positions, unsigned int num_glyphs, pixel *canvas, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, unsigned int baseline, bool *was_colored, FONTS_DATA_HANDLE, bool center_glyph);
PyObject* create_fallback_face(PyObject *base_face, CPUCell* cell, bool bold, bool italic, bool emoji_presentation, FONTS_DATA_HANDLE fg);
PyObject* specialize_font_descriptor(PyObject *base_descriptor, FONTS_DATA_HANDLE);
PyObject* face_from_path(const char *path, int index, FONTS_DATA_HANDLE);
PyObject* face_from_descriptor(PyObject*, FONTS_DATA_HANDLE);
PyObject* iter_fallback_faces(FONTS_DATA_HANDLE fgh, ssize_t *idx);
bool face_equals_descriptor(PyObject *face_, PyObject *descriptor);
const char* postscript_name_for_face(const PyObject*);

void sprite_tracker_current_layout(FONTS_DATA_HANDLE data, unsigned int *x, unsigned int *y, unsigned int *z);
void render_alpha_mask(const uint8_t *alpha_mask, pixel* dest, Region *src_rect, Region *dest_rect, size_t src_stride, size_t dest_stride, pixel color_rgb);
void render_line(FONTS_DATA_HANDLE, Line *line, index_type lnum, Cursor *cursor, DisableLigature);
void sprite_tracker_set_limits(size_t max_texture_size, size_t max_array_len);
typedef void (*free_extra_data_func)(void*);
StringCanvas render_simple_text_impl(PyObject *s, const char *text, unsigned int baseline);
StringCanvas render_simple_text(FONTS_DATA_HANDLE fg_, const char *text);

bool
add_font_name_record(PyObject *table, uint16_t platform_id, uint16_t encoding_id, uint16_t language_id, uint16_t name_id, const char *string, uint16_t string_len);
PyObject*
get_best_name_from_name_table(PyObject *table, PyObject *name_id);
PyObject*
read_name_font_table(const uint8_t *table, size_t table_len);
bool
read_fvar_font_table(const uint8_t *table, size_t table_len, PyObject *name_lookup_table, PyObject *output);
bool
read_STAT_font_table(const uint8_t *table, size_t table_len, PyObject *name_lookup_table, PyObject *output);

static inline void
right_shift_canvas(pixel *canvas, size_t width, size_t height, size_t amt) {
    pixel *src;
    size_t r;
    for (r = 0, src = canvas; r < height; r++, src += width) {
        memmove(src + amt, src, sizeof(pixel) * (width - amt));
        zero_at_ptr_count(src, amt);
    }
}
