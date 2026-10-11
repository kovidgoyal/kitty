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

    bool input_read, write_space_created, has_pending_input;
} ParseData;

// How the I/O thread should wake the main loop for this parser's pending bytes.
// small_pending: under 1 KB of fresh bytes, or a chunk accepted with vt_parser_accept_input(). Parsed
// immediately, but the I/O thread still coalesces wakes.
// large_ready: a large chunk the parser will accept on the next wake.
// large_held_until: a large chunk the parser will refuse until this time. Zero if none.
// chunk: identifies the pending bytes, it changes once they are parsed. Zero if nothing is pending.
typedef struct ParserInputWake {
    bool small_pending, large_ready;
    monotonic_t large_held_until;
    uint64_t chunk;
} ParserInputWake;

// The must only be called on the main thread
Parser *alloc_vt_parser(id_type window_id);
void free_vt_parser(Parser *);
void reset_vt_parser(Parser *);


// The following are thread safe, using an internal lock
uint8_t *vt_parser_create_write_buffer(Parser *, size_t *);
void vt_parser_commit_write(Parser *, size_t);
bool vt_parser_has_space_for_input(const Parser *);
ParserInputWake vt_parser_input_wake(const Parser *, monotonic_t now);
// Make the parser accept chunk on its next run even if it has grown past the small input threshold
void vt_parser_accept_input(Parser *, uint64_t chunk);
void parse_worker(void *p, ParseData *data, bool flush);
void parse_worker_dump(void *p, ParseData *data, bool flush);
