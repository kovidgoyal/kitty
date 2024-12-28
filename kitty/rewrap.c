/*
 * rewrap.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "rewrap.h"
#include "lineops.h"
#include "text-cache.h"


typedef void (*init_line_func_t)(void *buf, index_type y, Line *line);
typedef index_type (*first_dest_line_func_t)(void *buf, ANSIBuf *as_ansi_buf, Line *src_line, Line *dest_line);
typedef index_type (*next_dest_line_func_t)(void *buf, HistoryBuf *historybuf, ANSIBuf *as_ansi_buf, Line *src_line, index_type dest_y, Line *dest_line, bool continued);

static void
LineBuf_init_line(void *buf, index_type y, Line *line) {
    linebuf_init_line_at(buf, y, line);
}

static void
HistoryBuf_init_line(void *buf, index_type y, Line *line) {
    HistoryBuf *dest = buf;
    // historybuf_init_line uses reverse indexing
    historybuf_init_line(dest, dest->count ? dest->count - y - 1 : 0, line);
}


#define set_dest_line_attrs(dest_y) dest->line_attrs[dest_y] = src_line->attrs; src_line->attrs.prompt_kind = UNKNOWN_PROMPT_KIND;

static index_type
LineBuf_first_dest_line(void *buf, ANSIBuf *as_ansi_buf, Line *src_line, Line *dest_line) {
    (void)as_ansi_buf;
    LineBuf *dest = buf;
    linebuf_init_line_at(dest, 0, dest_line);
    set_dest_line_attrs(0);
    return 0;
}

static index_type
HistoryBuf_first_dest_line(void *buf, ANSIBuf *as_ansi_buf, Line *src_line, Line *dest_line) {
    HistoryBuf *dest = buf;
    historybuf_next_dest_line(dest, as_ansi_buf, src_line, 0, dest_line, false);
    return 0;
}

static index_type
LineBuf_next_dest_line(void *buf, HistoryBuf *historybuf, ANSIBuf *as_ansi_buf, Line *src_line, index_type dest_y, Line *dest_line, bool continued) {
    LineBuf *dest = buf;
    linebuf_set_last_char_as_continuation(dest, dest_y, continued);
    if (dest_y >= dest->ynum - 1) {
        linebuf_index(dest, 0, dest->ynum - 1);
        if (historybuf != NULL) {
            linebuf_init_line(dest, dest->ynum - 1);
            dest->line->attrs.has_dirty_text = true;
            historybuf_add_line(historybuf, dest->line, as_ansi_buf);
        }
        linebuf_clear_line(dest, dest->ynum - 1, true);
    } else dest_y++;
    linebuf_init_line_at(dest, dest_y, dest_line);
    set_dest_line_attrs(dest_y);
    return dest_y;
}

static index_type
HistoryBuf_next_dest_line(void *buf, HistoryBuf *historybuf, ANSIBuf *as_ansi_buf, Line *src_line, index_type dest_y, Line *dest_line, bool continued) {
    (void)historybuf;
    HistoryBuf *dest = buf;
    return historybuf_next_dest_line(dest, as_ansi_buf, src_line, dest_y, dest_line, continued);
}

typedef struct Rewrap {
    void *src_buf, *dest_buf;
    index_type src_xnum, dest_xnum;
    ANSIBuf *as_ansi_buf;
    TextCache *text_cache;
    HistoryBuf *historybuf;
    TrackCursor *cursors;
    index_type src_limit;

    Line src, dest;
    index_type src_y, src_x, dest_x, dest_y, num, src_x_limit;
    init_line_func_t init_line;
    first_dest_line_func_t first_dest_line;
    next_dest_line_func_t next_dest_line;
    LineBuf *scratch;
    bool current_dest_line_has_multiline_cells, current_src_line_has_multline_cells, prev_src_line_ended_with_wrap;
} Rewrap;

static void
copy_range(Line *src, index_type src_at, Line* dest, index_type dest_at, index_type num) {
    memcpy(dest->cpu_cells + dest_at, src->cpu_cells + src_at, num * sizeof(CPUCell));
    memcpy(dest->gpu_cells + dest_at, src->gpu_cells + src_at, num * sizeof(GPUCell));
}

static void
setup_line(TextCache *tc, index_type xnum, Line *l) {
    l->text_cache = tc;
    l->xnum = xnum;
}

static void
next_dest_line(Rewrap *r, bool continued) {
    r->dest_y = r->next_dest_line(r->dest_buf, r->historybuf, r->as_ansi_buf, &r->src, r->dest_y, &r->dest, continued);
    r->dest_x = 0;
    r->current_dest_line_has_multiline_cells = false;
    if (r->scratch->line_attrs[0].has_dirty_text) {
        CPUCell *cpu_cells; GPUCell *gpu_cells;
        linebuf_init_cells(r->scratch, 0, &cpu_cells, &gpu_cells);
        memcpy(r->dest.cpu_cells, cpu_cells, r->dest_xnum * sizeof(cpu_cells[0]));
        memcpy(r->dest.gpu_cells, gpu_cells, r->dest_xnum * sizeof(gpu_cells[0]));
        r->current_dest_line_has_multiline_cells = true;
    }
    linebuf_index(r->scratch, 0, r->scratch->ynum - 1);
    if (r->scratch->line_attrs[r->scratch->ynum - 1].has_dirty_text) {
        linebuf_clear_line(r->scratch, r->scratch->ynum - 1, true);
    }
}

static void
first_dest_line(Rewrap *r) {
    r->dest_y = r->first_dest_line(r->dest_buf, r->as_ansi_buf, &r->src, &r->dest);
}

static bool
init_src_line(Rewrap *r) {
    bool newline_needed = !r->prev_src_line_ended_with_wrap;
    r->init_line(r->src_buf, r->src_y, &r->src);
    r->src_x_limit = r->src_xnum;
    if (!r->src.cpu_cells[r->src_xnum-1].next_char_was_wrapped) {
        // Trim trailing blanks since there is a hard line break at the end of this line
        while(r->src_x_limit && r->src.cpu_cells[r->src_x_limit - 1].ch_and_idx == BLANK_CHAR) r->src_x_limit--;
    }
    r->prev_src_line_ended_with_wrap = r->src.cpu_cells[r->src_xnum - 1].next_char_was_wrapped;
    r->src.cpu_cells[r->src_xnum - 1].next_char_was_wrapped = false;
    r->src_x = 0;
    for (TrackCursor *t = r->cursors; !t->is_sentinel; t++) {
        if (r->src_y == t->y) {
            t->is_tracked_line = true;
            if (t->x >= r->src_x_limit) t->x = MAX(1u, r->src_x_limit) - 1;
        } else t->is_tracked_line = false;
    }
    return newline_needed;
}

static index_type
rewrap_inner(Rewrap r) {
    setup_line(r.text_cache, r.src_xnum, &r.src); setup_line(r.text_cache, r.dest_xnum, &r.dest);
    static TrackCursor tc_end = {.is_sentinel = true };
    if (!r.cursors) r.cursors = &tc_end;
    r.scratch = alloc_linebuf(SCALE_BITS << 1, r.dest_xnum, r.text_cache);
    if (!r.scratch) fatal("Out of memory");
    RAII_PyObject(scratch, (PyObject*)r.scratch);
    for (; r.src_y < r.src_limit; r.src_y++) {
        if (init_src_line(&r)) {
            if (r.src_y) next_dest_line(&r, false);
            else first_dest_line(&r);
        }
        while (r.src_x < r.src_x_limit) {
            if (r.dest_x >= r.dest_xnum) next_dest_line(&r, true);
            index_type num = MIN(r.src.xnum - r.src_x, r.dest_xnum - r.dest_x);
            copy_range(&r.src, r.src_x, &r.dest, r.dest_x, num);
            for (TrackCursor *t = r.cursors; !t->is_sentinel; t++) {
                if (t->is_tracked_line && r.src_x <= t->x && t->x < r.src_x + num) {
                    t->y = r.dest_y;
                    t->x = r.dest_x + (t->x - r.src_x + (t->x > 0));
                }
            }
            r.src_x += num; r.dest_x += num;
        }
    }
    return r.dest_y;
}

index_type
linebuf_rewrap_inner(LineBuf *src, LineBuf *dest, const index_type src_limit, HistoryBuf *historybuf, TrackCursor *track, ANSIBuf *as_ansi_buf) {
    Rewrap r = {
        .src_buf = src, .dest_buf = dest, .as_ansi_buf = as_ansi_buf, .text_cache = src->text_cache, .cursors = track,
        .src_limit = src_limit, .historybuf=historybuf, .src_xnum = src->xnum, .dest_xnum = dest->xnum,

        .init_line = LineBuf_init_line, .next_dest_line = LineBuf_next_dest_line, .first_dest_line = LineBuf_first_dest_line,
    };
    return rewrap_inner(r);
}

index_type
historybuf_rewrap_inner(HistoryBuf *src, HistoryBuf *dest, const index_type src_limit, ANSIBuf *as_ansi_buf) {
    Rewrap r = {
        .src_buf = src, .dest_buf = dest, .as_ansi_buf = as_ansi_buf, .text_cache = src->text_cache,
        .src_limit = src_limit, .src_xnum = src->xnum, .dest_xnum = dest->xnum,

        .init_line = HistoryBuf_init_line, .next_dest_line = HistoryBuf_next_dest_line, .first_dest_line = HistoryBuf_first_dest_line,
    };
    return rewrap_inner(r);
}
