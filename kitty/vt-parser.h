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


Parser* alloc_parser(id_type window_id);
void parse_vte(Parser*);
void parse_vte_dump(Parser*);
