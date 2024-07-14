/*
 * history.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "line.h"

typedef struct {
    PyObject_HEAD

    index_type xnum, ynum, num_segments;
    HistoryBufSegment *segments;
    PagerHistoryBuf *pagerhist;
    Line *line;
    TextCache *text_cache;
    index_type start_of_data, count;
} HistoryBuf;


HistoryBuf* alloc_historybuf(unsigned int, unsigned int, unsigned int, TextCache *tc);
