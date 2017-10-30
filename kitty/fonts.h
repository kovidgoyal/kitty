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
