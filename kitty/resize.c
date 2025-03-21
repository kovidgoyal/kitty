/*
 * resize.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "resize.h"
#include "lineops.h"

typedef struct Rewrap {
    struct {
        LineBuf *lb;
        HistoryBuf *hb;
        index_type x, y, hb_count;
        Line line, scratch_line;
    } src, dest;
    ANSIBuf *as_ansi_buf;
    TrackCursor *cursors;
    LineBuf *sb;

    index_type num_content_lines_before, src_x_limit;
    bool prev_src_line_ended_with_wrap, current_src_line_has_multline_cells, current_dest_line_has_multiline_cells;
    bool dest_line_from_linebuf, src_is_in_linebuf;

} Rewrap;

static void
setup_line(TextCache *tc, index_type xnum, Line *l) {
    l->text_cache = tc;
    l->xnum = xnum;
}

#define src_xnum (r->src.lb->xnum)
#define dest_xnum (r->dest.lb->xnum)

static void
exclude_empty_lines_at_bottom(Rewrap *r) {
    index_type first, i;
    bool is_empty = true;
    // Find the first line that contains some content
#define self (r->src.lb)
    first = self->ynum;
    do {
        first--;
        CPUCell *cells = linebuf_cpu_cells_for_line(self, first);
        for(i = 0; i < self->xnum; i++) {
            if (cells[i].ch_or_idx || cells[i].ch_is_idx) { is_empty = false; break; }
        }
    } while(is_empty && first > 0);
    if (!is_empty) r->num_content_lines_before = first + 1;
#undef self
}

static void
init_src_line_basic(Rewrap *r, index_type y, Line *dest, bool update_state) {
    if (r->src_is_in_linebuf) {
        linebuf_init_line_at(r->src.lb, y - r->src.hb_count, dest);
    } else if (y >= r->src.hb_count) {
        if (update_state) r->src_is_in_linebuf = true;
        linebuf_init_line_at(r->src.lb, y - r->src.hb_count, dest);
    } else {
        // historybuf_init_line uses reverse indexing
        historybuf_init_line(r->src.hb, r->src.hb->count - y - 1, dest);
    }
}

static bool
init_src_line(Rewrap *r) {
    bool newline_needed = !r->prev_src_line_ended_with_wrap;
    init_src_line_basic(r, r->src.y, &r->src.line, true);
    r->src_x_limit = src_xnum;
    r->prev_src_line_ended_with_wrap = r->src.line.cpu_cells[src_xnum - 1].next_char_was_wrapped;
    r->src.line.cpu_cells[src_xnum - 1].next_char_was_wrapped = false;
    // Trim trailing blanks
    while (r->src_x_limit && r->src.line.cpu_cells[r->src_x_limit - 1].ch_and_idx == BLANK_CHAR) r->src_x_limit--;
    r->src.x = 0;
    r->current_src_line_has_multline_cells = false;
    for (index_type i = 0; i < r->src_x_limit; i++) if (r->src.line.cpu_cells[i].is_multicell && r->src.line.cpu_cells[i].scale > 1) {
        r->current_src_line_has_multline_cells = true;
        break;
    }
    return newline_needed;
}

#define set_dest_line_attrs(dest_y) r->dest.lb->line_attrs[dest_y] = r->src.line.attrs; r->src.line.attrs.prompt_kind = UNKNOWN_PROMPT_KIND;

static void
first_dest_line(Rewrap *r) {
    if (r->src.hb_count) {
        historybuf_next_dest_line(r->dest.hb, r->as_ansi_buf, &r->src.line, 0, &r->dest.line, false);
        r->src.line.attrs.prompt_kind = UNKNOWN_PROMPT_KIND;
    } else {
        r->dest_line_from_linebuf = true;
        linebuf_init_line_at(r->dest.lb, 0, &r->dest.line);
        set_dest_line_attrs(0);
    }
}

static index_type
linebuf_next_dest_line(Rewrap *r, bool continued) {
#define dest_y r->dest.y
    LineBuf *dest = r->dest.lb;
    linebuf_set_last_char_as_continuation(dest, dest_y, continued);
    if (dest_y >= dest->ynum - 1) {
        linebuf_index(dest, 0, dest->ynum - 1);
        if (r->dest.hb != NULL) {
            linebuf_init_line(dest, dest->ynum - 1);
            dest->line->attrs.has_dirty_text = true;
            historybuf_add_line(r->dest.hb, dest->line, r->as_ansi_buf);
        }
        linebuf_clear_line(dest, dest->ynum - 1, true);
    } else dest_y++;
    linebuf_init_line_at(dest, dest_y, &r->dest.line);
    set_dest_line_attrs(dest_y);
    return dest_y;
#undef dest_y
}


static void
next_dest_line(Rewrap *r, bool continued) {
    r->dest.x = 0;
    r->current_dest_line_has_multiline_cells = false;
    if (r->dest_line_from_linebuf) {
        r->dest.y = linebuf_next_dest_line(r, continued);
    } else if (r->src_is_in_linebuf) {
        r->dest_line_from_linebuf = true;
        r->dest.y = 0;
        linebuf_init_line_at(r->dest.lb, 0, &r->dest.line);
        set_dest_line_attrs(0);
        if (continued && r->dest.hb && r->dest.hb->count) {
            historybuf_init_line(r->dest.hb, 0, r->dest.hb->line);
            r->dest.hb->line->cpu_cells[dest_xnum-1].next_char_was_wrapped = true;
        }
    } else {
        r->dest.y = historybuf_next_dest_line(r->dest.hb, r->as_ansi_buf, &r->src.line, r->dest.y, &r->dest.line, continued);
        r->src.line.attrs.prompt_kind = UNKNOWN_PROMPT_KIND;
    }
    if (r->sb->line_attrs[0].has_dirty_text) {
        CPUCell *cpu_cells; GPUCell *gpu_cells;
        linebuf_init_cells(r->sb, 0, &cpu_cells, &gpu_cells);
        memcpy(r->dest.line.cpu_cells, cpu_cells, dest_xnum * sizeof(cpu_cells[0]));
        memcpy(r->dest.line.gpu_cells, gpu_cells, dest_xnum * sizeof(gpu_cells[0]));
        r->current_dest_line_has_multiline_cells = true;
    }
    linebuf_index(r->sb, 0, r->sb->ynum - 1);
    if (r->sb->line_attrs[r->sb->ynum - 1].has_dirty_text) {
        linebuf_clear_line(r->sb, r->sb->ynum - 1, true);
    }
}

static void
update_tracked_cursors(Rewrap *r, index_type num_cells, index_type src_y, index_type dest_y, index_type x_limit) {
    if (!r->src_is_in_linebuf) return;
    src_y -= r->src.hb_count;
    for (TrackCursor *t = r->cursors; !t->is_sentinel; t++) {
        if (t->y == src_y && r->src.x <= t->x && (t->x < r->src.x + num_cells || t->x >= x_limit)) {
            t->dest_y = dest_y;
            t->dest_x = r->dest.x + (t->x - r->src.x);
            if (t->dest_x > dest_xnum) t->dest_x = dest_xnum;
        }
    }
}

static bool
find_space_in_dest_line(Rewrap *r, index_type num_cells) {
    while (r->dest.x + num_cells <= dest_xnum) {
        index_type before = r->dest.x;
        for (index_type x = r->dest.x; x < r->dest.x + num_cells; x++) {
            if (r->dest.line.cpu_cells[x].is_multicell) {
                r->dest.x = x + mcd_x_limit(r->dest.line.cpu_cells + x);
                break;
            }
        }
        if (before == r->dest.x) return true;
    }
    return false;
}

static void
find_space_in_dest(Rewrap *r, index_type num_cells) {
    while (!find_space_in_dest_line(r, num_cells)) next_dest_line(r, true);
}

static void
copy_range(Line *src, index_type src_at, Line* dest, index_type dest_at, index_type num) {
    memcpy(dest->cpu_cells + dest_at, src->cpu_cells + src_at, num * sizeof(CPUCell));
    memcpy(dest->gpu_cells + dest_at, src->gpu_cells + src_at, num * sizeof(GPUCell));
}

static void
copy_multiline_extra_lines(Rewrap *r, CPUCell *src_cell, index_type mc_width) {
    for (index_type i = 1; i < src_cell->scale; i++) {
        init_src_line_basic(r, r->src.y + i, &r->src.scratch_line, false);
        linebuf_init_line_at(r->sb, i - 1, &r->dest.scratch_line);
        linebuf_mark_line_dirty(r->sb, i - 1);
        copy_range(&r->src.scratch_line, r->src.x, &r->dest.scratch_line, r->dest.x, mc_width);
        update_tracked_cursors(r, mc_width, r->src.y + i, r->dest.y + i, src_xnum + 10000 /* ensure cursor is moved only if in region being copied */);
    }
}


static void
multiline_copy_src_to_dest(Rewrap *r) {
    CPUCell *c; index_type mc_width;
    while (r->src.x < r->src_x_limit) {
        c = &r->src.line.cpu_cells[r->src.x];
        if (c->is_multicell) {
            mc_width = mcd_x_limit(c);
            if (mc_width > dest_xnum) {
                update_tracked_cursors(r, mc_width, r->src.y, r->dest.y, r->src_x_limit);
                r->src.x += mc_width;
                continue;
            } else if (c->y) {
                r->src.x += mc_width;
                continue;
            }
        } else mc_width = 1;
        find_space_in_dest(r, mc_width);
        copy_range(&r->src.line, r->src.x, &r->dest.line, r->dest.x, mc_width);
        update_tracked_cursors(r, mc_width, r->src.y, r->dest.y, r->src_x_limit);
        if (c->scale > 1) copy_multiline_extra_lines(r, c, mc_width);
        r->src.x += mc_width; r->dest.x += mc_width;
    }
}


static void
fast_copy_src_to_dest(Rewrap *r) {
    CPUCell *c;
    while (r->src.x < r->src_x_limit) {
        if (r->dest.x >= dest_xnum) {
            next_dest_line(r, true);
            if (r->current_dest_line_has_multiline_cells) {
                multiline_copy_src_to_dest(r);
                return;
            }
        }
        index_type num = MIN(r->src_x_limit - r->src.x, dest_xnum - r->dest.x);
        if (num && (c = &r->src.line.cpu_cells[r->src.x + num - 1])->is_multicell && c->x != mcd_x_limit(c) - 1) {
            // we have a split multicell at the right edge of the copy region
            multiline_copy_src_to_dest(r);
            return;
        }
        copy_range(&r->src.line, r->src.x, &r->dest.line, r->dest.x, num);
        update_tracked_cursors(r, num, r->src.y, r->dest.y, r->src_x_limit);
        r->src.x += num; r->dest.x += num;
    }
}


static void
rewrap(Rewrap *r) {
    r->src.hb_count = r->src.hb ? r->src.hb->count : 0;
    // Fast path
    if (r->dest.lb->xnum == r->src.lb->xnum && r->dest.lb->ynum == r->src.lb->ynum) {
        memcpy(r->dest.lb->line_map, r->src.lb->line_map, sizeof(index_type) * r->src.lb->ynum);
        memcpy(r->dest.lb->line_attrs, r->src.lb->line_attrs, sizeof(LineAttrs) * r->src.lb->ynum);
        memcpy(r->dest.lb->cpu_cell_buf, r->src.lb->cpu_cell_buf, (size_t)r->src.lb->xnum * r->src.lb->ynum * sizeof(CPUCell));
        memcpy(r->dest.lb->gpu_cell_buf, r->src.lb->gpu_cell_buf, (size_t)r->src.lb->xnum * r->src.lb->ynum * sizeof(GPUCell));
        r->num_content_lines_before = r->src.lb->ynum;
        if (r->dest.hb && r->src.hb) historybuf_fast_rewrap(r->dest.hb, r->src.hb);
        r->dest.y = r->src.lb->ynum - 1;
        return;
    }

    setup_line(r->src.lb->text_cache, src_xnum, &r->src.line);
    setup_line(r->src.lb->text_cache, dest_xnum, &r->dest.line);
    setup_line(r->src.lb->text_cache, src_xnum, &r->src.scratch_line);
    setup_line(r->src.lb->text_cache, dest_xnum, &r->dest.scratch_line);

    exclude_empty_lines_at_bottom(r);

    for (; r->src.y < r->num_content_lines_before + r->src.hb_count; r->src.y++) {
        if (init_src_line(r)) {
            if (r->src.y) next_dest_line(r, false);
            else first_dest_line(r);
        }
        if (r->current_src_line_has_multline_cells || r->current_dest_line_has_multiline_cells) multiline_copy_src_to_dest(r);
        else fast_copy_src_to_dest(r);
    }
}

ResizeResult
resize_screen_buffers(LineBuf *lb, HistoryBuf *hb, index_type lines, index_type columns, ANSIBuf *as_ansi_buf, TrackCursor *cursors) {
    ResizeResult ans = {0};
    ans.lb = alloc_linebuf(lines, columns, lb->text_cache);
    if (!ans.lb) return ans;
    RAII_PyObject(raii_nlb, (PyObject*)ans.lb); (void) raii_nlb;
    if (hb) {
        ans.hb = historybuf_alloc_for_rewrap(columns, hb);
        if (!ans.hb) return ans;
    }
    RAII_PyObject(raii_nhb, (PyObject*)ans.hb); (void) raii_nhb;
    Rewrap r = {
        .src = {.lb=lb, .hb=hb}, .dest = {.lb=ans.lb, .hb=ans.hb},
        .as_ansi_buf = as_ansi_buf, .cursors = cursors,
    };
    r.sb = alloc_linebuf(SCALE_BITS << 1, columns, lb->text_cache);
    if (!r.sb) return ans;
    RAII_PyObject(scratch, (PyObject*)r.sb); (void)scratch;
    for (TrackCursor *t = cursors; !t->is_sentinel; t++) { t->dest_x = t->x; t->dest_y = t->y; }
    rewrap(&r);
    ans.num_content_lines_before = r.num_content_lines_before;
    ans.num_content_lines_after = MIN(r.dest.y + 1, ans.lb->ynum);
    if (hb) historybuf_finish_rewrap(ans.hb, hb);
    for (unsigned i = 0; i < ans.num_content_lines_after; i++) linebuf_mark_line_dirty(ans.lb, i);
    for (TrackCursor *t = cursors; !t->is_sentinel; t++) { t->dest_x = MIN(t->dest_x, columns); t->dest_y = MIN(t->dest_y, lines); }
    Py_INCREF(raii_nlb); Py_XINCREF(raii_nhb);
    ans.ok = true;
    return ans;
}
