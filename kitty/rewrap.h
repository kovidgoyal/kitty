/*
 * rewrap.h
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "line-buf.h"
#include "history.h"

typedef struct TrackCursor {
    const index_type x, y;
    index_type dest_x, dest_y;
    bool is_sentinel;
} TrackCursor;


index_type linebuf_rewrap_inner(LineBuf *src, LineBuf *dest, const index_type src_limit, HistoryBuf *historybuf, TrackCursor *track, ANSIBuf *as_ansi_buf);

index_type historybuf_rewrap_inner(HistoryBuf *src, HistoryBuf *dest, const index_type src_limit, ANSIBuf *as_ansi_buf);

