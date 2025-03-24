/*
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef enum {NORMAL, IN_ESC, IN_CSI, FLAG_PAIR_STARTED, IN_ST_TERMINATED} WCSParserState;

typedef struct {
    char_type prev_ch;
    int prev_width;
    WCSParserState parser_state;
} WCSState;


void initialize_wcs_state(WCSState *state);
int wcswidth_step(WCSState *state, const char_type ch);
PyObject * wcswidth_std(PyObject UNUSED *self, PyObject *str);
size_t wcswidth_string(const char_type *s);
