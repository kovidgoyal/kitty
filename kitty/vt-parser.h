/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef struct { int x; } PARSER_STATE_HANDLE;

typedef struct Parser {
    PyObject_HEAD

    PARSER_STATE_HANDLE *state;
} Parser;


Parser* alloc_vt_parser(id_type window_id);
void free_vt_parser(Parser*);
void reset_vt_parser(Parser*);
