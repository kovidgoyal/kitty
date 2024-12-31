/*
 * resize.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "line-buf.h"
#include "history.h"

typedef struct TrackCursor {
    index_type x, y;
    index_type dest_x, dest_y;
    bool is_sentinel;
} TrackCursor;

typedef struct ResizeResult {
    LineBuf *lb; HistoryBuf *hb;
    bool ok;
    index_type num_content_lines_before, num_content_lines_after;
} ResizeResult;

ResizeResult
resize_screen_buffers(LineBuf *lb, HistoryBuf *hb, index_type lines, index_type columns, ANSIBuf *as_ansi_buf, TrackCursor *cursors);
