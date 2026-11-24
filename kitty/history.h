/*
 * history.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "line.h"

typedef struct {
    CPUCell *cpu_cells;
    LineAttrs *line_attrs;
    void *mem;
    size_t mmap_size;
} HistoryBufSegment;

typedef struct {
    void *ringbuf;
    size_t maximum_size;
    bool rewrap_needed;
    // The bidi record of the paragraph its text ends in, which the history lines continuing it continue, see
    // ansi_bidi_row_start()
    uint8_t bidi_open;
} PagerHistoryBuf;


typedef struct {
    PyObject_HEAD

        index_type xnum,
        ynum, num_segments;
    HistoryBufSegment *segments;
    PagerHistoryBuf *pagerhist;
    Line *line;
    TextCache *text_cache;
    index_type start_of_data, count;
    // The number of lines pushed minus the number popped, so that the newest
    // line has the absolute line number num_pushed - 1, which does not change
    // while it is in the buffer.
    uint64_t num_pushed;
    // Some line added holds bidi bits, until the buffer is cleared. Set by the code adding such a line with
    // historybuf_note_bidi(), not by historybuf_add_line(), which the scroll path calls for every line
    bool bidi_stamped;
    // num_pushed at the last bidi walk of a view of history lines only, 0
    // once lines were removed, see bidi_map_paragraph()
    uint64_t bidi_walked;
    // Cache of bidi_history_line0_recorded(), keyed on the pushed and count fields and the screen height
    bool line0_recorded, line0_cache_valid;
    uint64_t line0_cache_pushed;
    index_type line0_cache_count, line0_cache_lines;
    // Render data for history lines being displayed, see historybuf_init_line_for_render()
    struct {
        RenderCell *cells;
        uint64_t *keys; // absolute line number + 1 of the line whose data is in each row, 0 if none
        index_type num_rows;
    } render_cache;
} HistoryBuf;


HistoryBuf *alloc_historybuf(unsigned int, unsigned int, unsigned int, TextCache *tc);

#ifdef __SSE2__
#include <emmintrin.h>
#endif
static inline void
historybuf_finish_writes(void) {
    // Lines are added to the history buffer with non-temporal stores, which
    // are weakly ordered. Order them before any later stores, so that they
    // are visible to other threads once later stores, such as the unlocking
    // of a mutex, are. Called once per parse pass, as fencing after every
    // line is costly. The thread that added the lines always sees them.
#ifdef __SSE2__
    _mm_sfence();
#endif
}
// Called by the code adding a line, see bidi_stamped
static inline void
historybuf_note_bidi(HistoryBuf *hb, LineAttrs a) {
    if (line_has_bidi_bits(a)) hb->bidi_stamped = true;
}

// The bidi record that the paragraph of the oldest line continues from the scrollback pager history, 0 for none
static inline uint8_t
historybuf_pagerhist_bidi_open(const HistoryBuf *hb) {
    return hb->pagerhist ? hb->pagerhist->bidi_open : 0;
}

HistoryBuf *historybuf_alloc_for_rewrap(unsigned int columns, HistoryBuf *self);
void historybuf_finish_rewrap(HistoryBuf *dest, HistoryBuf *src);
void historybuf_fast_rewrap(HistoryBuf *dest, HistoryBuf *src, index_type count, bool steal);
index_type historybuf_next_dest_line(HistoryBuf *self, ANSIBuf *as_ansi_buf, Line *src_line, index_type dest_y, Line *dest_line, bool continued);
bool historybuf_is_line_continued(HistoryBuf *self, index_type lnum);
void historybuf_delete_newest_lines(HistoryBuf *self, index_type count);
void historybuf_delete_lines(HistoryBuf *self, index_type num_newer, index_type count);
