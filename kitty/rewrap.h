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
#define init_src_line(src_y) INIT_LINE(src, src->line, src->line_map[src_y]);
#endif

#ifndef init_dest_line
#define init_dest_line(dest_y) INIT_LINE(dest, dest->line, dest->line_map[dest_y]);
#endif

#ifndef first_dest_line
#define first_dest_line init_dest_line(0)
#endif

#ifndef next_dest_line
#define next_dest_line(continued) \
    if (dest_y >= dest->ynum - 1) { \
        linebuf_index(dest, 0, dest->ynum - 1); \
        linebuf_init_line(dest, dest->ynum - 1); \
        historybuf_add_line(historybuf, dest->line); \
    } else dest_y++; \
    init_dest_line(dest_y); \
    dest->continued_map[dest_y] = continued;
#endif

#ifndef is_src_line_continued
#define is_src_line_continued(src_y) (src_y < src->ynum - 1 ? src->continued_map[src_y + 1] : false)
#endif

static inline void copy_range(Line *src, index_type src_at, Line* dest, index_type dest_at, index_type num) {
    memcpy(dest->chars + dest_at, src->chars + src_at, num * sizeof(char_type));
    memcpy(dest->colors + dest_at, src->colors + src_at, num * sizeof(color_type));
    memcpy(dest->decoration_fg + dest_at, src->decoration_fg + src_at, num * sizeof(decoration_type));
    memcpy(dest->combining_chars + dest_at, src->combining_chars + src_at, num * sizeof(combining_type));
}


static void rewrap_inner(BufType *src, BufType *dest, const index_type src_limit, HistoryBuf UNUSED *historybuf) {
    bool src_line_is_continued = false;
    index_type src_y = 0, src_x = 0, dest_x = 0, dest_y = 0, num = 0, src_x_limit = 0;
    Py_BEGIN_ALLOW_THREADS;

    first_dest_line;
    do {
        init_src_line(src_y);
        src_line_is_continued = is_src_line_continued(src_y);
        src_x_limit = src->xnum;
        if (!src_line_is_continued) {
            // Trim trailing white-space since there is a hard line break at the end of this line
            while(src_x_limit && (src->line->chars[src_x_limit - 1] & CHAR_MASK) == 32) src_x_limit--;
            
        }
        while (src_x < src_x_limit) {
            if (dest_x >= dest->xnum) { next_dest_line(true); dest_x = 0; }
            num = MIN(src->line->xnum - src_x, dest->xnum - dest_x);
            copy_range(src->line, src_x, dest->line, dest_x, num);
            src_x += num; dest_x += num;
        }
        src_y++; src_x = 0;
        if (!src_line_is_continued && src_y < src_limit) { next_dest_line(false); dest_x = 0; }
    } while (src_y < src_limit);
    dest->line->ynum = dest_y;
    Py_END_ALLOW_THREADS;
}
