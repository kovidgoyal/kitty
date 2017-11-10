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



bool face_has_codepoint(PyObject *, char_type);
hb_font_t* harfbuzz_font_for_face(PyObject*);
bool set_size_for_face(PyObject*, float, float, float);
void cell_metrics(PyObject*, unsigned int*, unsigned int*, unsigned int*, unsigned int*, unsigned int*); 
void sprite_tracker_current_layout(unsigned int *x, unsigned int *y, unsigned int *z);
bool render_glyphs_in_cells(PyObject *f, bool bold, bool italic, hb_glyph_info_t *info, hb_glyph_position_t *positions, unsigned int num_glyphs, uint8_t *canvas, unsigned int cell_width, unsigned int cell_height, unsigned int num_cells, unsigned int baseline);
void render_line(Line *line);
void sprite_tracker_set_limits(size_t max_texture_size, size_t max_array_len);
void sprite_tracker_set_layout(unsigned int cell_width, unsigned int cell_height);
typedef void (*free_extra_data_func)(void*);
PyObject* ft_face_from_data(const uint8_t* data, size_t sz, void *extra_data, free_extra_data_func fed, PyObject *path, int hinting, int hintstyle, float size_in_pts, float xdpi, float ydpi, float);
PyObject* ft_face_from_path_and_psname(PyObject* path, const char* psname, void *extra_data, free_extra_data_func fed, int hinting, int hintstyle, float size_in_pts, float xdpi, float ydpi, float);
