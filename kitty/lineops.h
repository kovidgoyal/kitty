/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "history.h"
#include "line-buf.h"

#define set_attribute_on_line(cells, which, val, xnum) { \
    for (index_type i__ = 0; i__ < xnum; i__++) cells[i__].attrs.which = val; }

static inline bool
set_named_attribute_on_line(GPUCell *cells, const char* which, uint16_t val, index_type xnum) {
    // Set a single attribute on all cells in the line
#define s(q) if (strcmp(#q, which) == 0) { set_attribute_on_line(cells, q, val, xnum); return true; }
    s(reverse); s(strike); s(dim); s(mark); s(bold); s(italic); s(decoration);
    return false;
#undef s
}


static inline void
copy_line(const Line *src, Line *dest) {
    memcpy(dest->cpu_cells, src->cpu_cells, sizeof(CPUCell) * MIN(src->xnum, dest->xnum));
    memcpy(dest->gpu_cells, src->gpu_cells, sizeof(GPUCell) * MIN(src->xnum, dest->xnum));
}

static inline void
clear_chars_in_line(CPUCell *cpu_cells, GPUCell *gpu_cells, index_type xnum, char_type ch) {
    // Clear only the char part of each cell, the rest must have been cleared by a memset or similar
    if (ch) {
        static const CellAttrs empty = {0};
        const CPUCell c = {.ch_or_idx=ch};
        for (index_type i = 0; i < xnum; i++) { cpu_cells[i] = c; gpu_cells[i].attrs = empty; }
    }
}

static inline index_type
xlimit_for_line(const Line *line) {
    index_type xlimit = line->xnum;
    while (xlimit > 0 && !line->cpu_cells[xlimit - 1].ch_and_idx) xlimit--;
    return xlimit;
}

static inline void
line_save_cells(Line *line, index_type start, index_type num, GPUCell *gpu_cells, CPUCell *cpu_cells) {
    memcpy(gpu_cells + start, line->gpu_cells + start, sizeof(GPUCell) * num);
    memcpy(cpu_cells + start, line->cpu_cells + start, sizeof(CPUCell) * num);
}

static inline void
line_reset_cells(Line *line, index_type start, index_type num, GPUCell *gpu_cells, CPUCell *cpu_cells) {
    memcpy(line->gpu_cells + start, gpu_cells + start, sizeof(GPUCell) * num);
    memcpy(line->cpu_cells + start, cpu_cells + start, sizeof(CPUCell) * num);
}

static inline bool
line_is_empty(const Line *line) {
#if BLANK_CHAR != 0
#error This implementation is incorrect for BLANK_CHAR != 0
#endif
    for (index_type i = 0; i < line->xnum; i++) if (line->cpu_cells[i].ch_and_idx) return false;
    return true;
}

typedef Line*(get_line_func)(void *, int);
void line_clear_text(Line *self, unsigned int at, unsigned int num, char_type ch);
void line_apply_cursor(Line *self, const Cursor *cursor, unsigned int at, unsigned int num, bool clear_char);
char_type line_get_char(Line *self, index_type at);
index_type line_url_start_at(Line *self, index_type x, ListOfChars *lc);
index_type line_url_end_at(Line *self, index_type x, bool, char_type, bool, bool, index_type, ListOfChars*);
bool line_startswith_url_chars(Line*, bool, ListOfChars*);
char_type get_url_sentinel(Line *line, index_type url_start);
index_type find_char(Line *self, index_type start, char_type ch);
index_type next_char_pos(const Line *self, index_type x, index_type num);
index_type prev_char_pos(const Line *self, index_type x, index_type num);
bool line_as_ansi(Line *self, ANSILineState *s, index_type start_at, index_type stop_before, char_type prefix_char, bool skip_multiline_non_zero_lines) __attribute__((nonnull));
unsigned int line_length(Line *self);
size_t cell_as_unicode_for_fallback(const ListOfChars *lc, Py_UCS4 *buf, size_t sz);
size_t cell_as_utf8_for_fallback(const ListOfChars *lc, char *buf, size_t sz);
bool unicode_in_range(const Line *self, const index_type start, const index_type limit, const bool include_cc, const bool add_trailing_newline, const bool skip_zero_cells, bool skip_multiline_non_zero_lines, ANSIBuf*);
PyObject* line_as_unicode(Line *, bool, ANSIBuf*);

void linebuf_init_line(LineBuf *, index_type);
void linebuf_init_line_at(LineBuf *, index_type, Line*);
void linebuf_init_cells(LineBuf *lb, index_type ynum, CPUCell **c, GPUCell **g);
CPUCell* linebuf_cpu_cells_for_line(LineBuf *lb, index_type idx);
void linebuf_clear(LineBuf *, char_type ch);
void linebuf_clear_lines(LineBuf *self, const Cursor *cursor, index_type start, index_type end);
void linebuf_index(LineBuf* self, index_type top, index_type bottom);
void linebuf_reverse_index(LineBuf *self, index_type top, index_type bottom);
void linebuf_clear_line(LineBuf *self, index_type y, bool clear_attrs);
void linebuf_insert_lines(LineBuf *self, unsigned int num, unsigned int y, unsigned int bottom);
void linebuf_delete_lines(LineBuf *self, index_type num, index_type y, index_type bottom);
void linebuf_copy_line_to(LineBuf *, Line *, index_type);
void linebuf_mark_line_dirty(LineBuf *self, index_type y);
void linebuf_clear_attrs_and_dirty(LineBuf *self, index_type y);
void linebuf_mark_line_clean(LineBuf *self, index_type y);
void linebuf_set_line_has_image_placeholders(LineBuf *self, index_type y, bool val);
void linebuf_set_last_char_as_continuation(LineBuf *self, index_type y, bool continued);
CPUCell* linebuf_cpu_cell_at(LineBuf *self, index_type x, index_type y);
bool linebuf_line_ends_with_continuation(LineBuf *self, index_type y);
void linebuf_refresh_sprite_positions(LineBuf *self);
void historybuf_add_line(HistoryBuf *self, const Line *line, ANSIBuf*);
bool historybuf_pop_line(HistoryBuf *, Line *);
void historybuf_init_line(HistoryBuf *self, index_type num, Line *l);
bool history_buf_endswith_wrap(HistoryBuf *self);
CPUCell* historybuf_cpu_cells(HistoryBuf *self, index_type num);
void historybuf_mark_line_clean(HistoryBuf *self, index_type y);
void historybuf_mark_line_dirty(HistoryBuf *self, index_type y);
void historybuf_set_line_has_image_placeholders(HistoryBuf *self, index_type y, bool val);
void historybuf_refresh_sprite_positions(HistoryBuf *self);
void historybuf_clear(HistoryBuf *self);
void mark_text_in_line(PyObject *marker, Line *line, ANSIBuf *buf);
bool line_has_mark(Line *, uint16_t mark);
PyObject* as_text_generic(PyObject *args, void *container, get_line_func get_line, index_type lines, ANSIBuf *ansibuf, bool add_trailing_newline);
bool colors_for_cell(Line *self, const ColorProfile *cp, index_type *x, color_type *fg, color_type *bg, bool *reversed);
