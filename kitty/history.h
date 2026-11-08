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
HistoryBuf *historybuf_alloc_for_rewrap(unsigned int columns, HistoryBuf *self);
void historybuf_finish_rewrap(HistoryBuf *dest, HistoryBuf *src);
void historybuf_fast_rewrap(HistoryBuf *dest, HistoryBuf *src, index_type count, bool steal);
index_type historybuf_next_dest_line(HistoryBuf *self, ANSIBuf *as_ansi_buf, Line *src_line, index_type dest_y, Line *dest_line, bool continued);
bool historybuf_is_line_continued(HistoryBuf *self, index_type lnum);
void historybuf_delete_newest_lines(HistoryBuf *self, index_type count);
void historybuf_delete_lines(HistoryBuf *self, index_type num_newer, index_type count);
