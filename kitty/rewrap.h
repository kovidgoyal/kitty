/*
 * rewrap.h
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#ifndef BufType
#define BufType LineBuf
#endif

#ifndef init_src_line
#define init_src_line(src_y) init_line(src, src->line, src->line_map[src_y]);
#endif

#ifndef init_dest_line
#define init_dest_line(dest_y) init_line(dest, dest->line, dest->line_map[dest_y]); dest->line->continued = dest->line_attrs[dest_y];
#endif

#ifndef first_dest_line
#define first_dest_line init_dest_line(0)
#endif

#ifndef next_dest_line
#define next_dest_line(continued) \
    if (dest_y >= dest->ynum - 1) { \
        linebuf_index(dest, 0, dest->ynum - 1); \
        if (historybuf != NULL) { \
            init_dest_line(dest->ynum - 1); \
            dest->line->has_dirty_text = true; \
            historybuf_add_line(historybuf, dest->line, as_ansi_buf); \
        }\
        linebuf_clear_line(dest, dest->ynum - 1); \
    } else dest_y++; \
    init_dest_line(dest_y); \
    dest->line_attrs[dest_y] = continued ? CONTINUED_MASK : 0;
#endif

#ifndef is_src_line_continued
#define is_src_line_continued(src_y) (src_y < src->ynum - 1 ? (src->line_attrs[src_y + 1] & CONTINUED_MASK) : false)
#endif

static inline void
copy_range(Line *src, index_type src_at, Line* dest, index_type dest_at, index_type num) {
    memcpy(dest->cpu_cells + dest_at, src->cpu_cells + src_at, num * sizeof(CPUCell));
    memcpy(dest->gpu_cells + dest_at, src->gpu_cells + src_at, num * sizeof(GPUCell));
}


static void
rewrap_inner(BufType *src, BufType *dest, const index_type src_limit, HistoryBuf UNUSED *historybuf, index_type *track_x, index_type *track_y, ANSIBuf *as_ansi_buf) {
    bool src_line_is_continued = false;
    index_type src_y = 0, src_x = 0, dest_x = 0, dest_y = 0, num = 0, src_x_limit = 0;

    first_dest_line;
    do {
        bool is_tracked_line = src_y == *track_y;
        init_src_line(src_y);
        src_line_is_continued = is_src_line_continued(src_y);
        src_x_limit = src->xnum;
        if (!src_line_is_continued) {
            // Trim trailing blanks since there is a hard line break at the end of this line
            while(src_x_limit && (src->line->cpu_cells[src_x_limit - 1].ch) == BLANK_CHAR) src_x_limit--;

        }
        if (is_tracked_line && *track_x >= src_x_limit) *track_x = MAX(1u, src_x_limit) - 1;
        while (src_x < src_x_limit) {
            if (dest_x >= dest->xnum) { next_dest_line(true); dest_x = 0; }
            num = MIN(src->line->xnum - src_x, dest->xnum - dest_x);
            copy_range(src->line, src_x, dest->line, dest_x, num);
            if (is_tracked_line && src_x <= *track_x && *track_x < src_x + num) {
                *track_y = dest_y;
                *track_x = dest_x + (*track_x - src_x + 1);
            }
            src_x += num; dest_x += num;
        }
        src_y++; src_x = 0;
        if (!src_line_is_continued && src_y < src_limit) { next_dest_line(false); dest_x = 0; }
    } while (src_y < src_limit);
    dest->line->ynum = dest_y;
}
