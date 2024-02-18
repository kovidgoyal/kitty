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

typedef struct ParseData {
    PyObject *dump_callback;
    monotonic_t now;

    bool input_read, write_space_created, has_pending_input;
    monotonic_t time_since_new_input;
} ParseData;

// The must only be called on the main thread
Parser* alloc_vt_parser(id_type window_id);
void free_vt_parser(Parser*);
void reset_vt_parser(Parser*);


// The following are thread safe, using an internal lock
uint8_t* vt_parser_create_write_buffer(Parser*, size_t*);
void vt_parser_commit_write(Parser*, size_t);
bool vt_parser_has_space_for_input(const Parser*);
void parse_worker(void *p, ParseData *data, bool flush);
void parse_worker_dump(void *p, ParseData *data, bool flush);
