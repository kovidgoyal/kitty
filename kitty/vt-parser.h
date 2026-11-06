/*
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef struct {
    int x;
} PARSER_STATE_HANDLE;

typedef struct Parser {
    PyObject_HEAD

        PARSER_STATE_HANDLE *state;
} Parser;

typedef struct ParseData {
    PyObject *dump_callback;
    monotonic_t now;
    // Called, from the thread doing the parsing, when the parser frees space in its
    // buffer after it had become full, so that whoever fills the buffer can resume.
    void (*write_space_created)(void *);
    void *write_space_created_data;

    // input_read: some input was parsed. has_pending_input: input remains unparsed
    // because a single pass parses at most a bounded amount of input.
    bool input_read, has_pending_input;
} ParseData;


// The must only be called on the main thread
Parser *alloc_vt_parser(id_type window_id);
void free_vt_parser(Parser *);
void reset_vt_parser(Parser *);


// The following are thread safe, using an internal lock
uint8_t *vt_parser_create_write_buffer(Parser *, size_t *);
// Same as vt_parser_create_write_buffer() except that it returns NULL instead of aborting if a write buffer already exists
uint8_t *vt_parser_create_write_buffer_if_none(Parser *, size_t *);
void vt_parser_commit_write(Parser *, size_t);
bool vt_parser_has_space_for_input(const Parser *);
void parse_worker(void *p, ParseData *data, bool flush);
void parse_worker_dump(void *p, ParseData *data, bool flush);
