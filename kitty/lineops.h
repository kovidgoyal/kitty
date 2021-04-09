/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

static inline void
set_attribute_on_line(GPUCell *cells, uint32_t shift, uint32_t val, index_type xnum) {
    // Set a single attribute on all cells in the line
    attrs_type mask = shift == DECORATION_SHIFT ? 3 : 1;
    attrs_type aval = (val & mask) << shift;
    mask = ~(mask << shift);
    for (index_type i = 0; i < xnum; i++) cells[i].attrs = (cells[i].attrs & mask) | aval;
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
        for (index_type i = 0; i < xnum; i++) { cpu_cells[i].ch = ch; cpu_cells[i].hyperlink_id = 0; gpu_cells[i].attrs = 1; }
    }
}

static inline index_type
xlimit_for_line(const Line *line) {
    index_type xlimit = line->xnum;
    if (BLANK_CHAR == 0) {
        while (xlimit > 0 && (line->cpu_cells[xlimit - 1].ch) == BLANK_CHAR) xlimit--;
        if (xlimit < line->xnum && (line->gpu_cells[xlimit > 0 ? xlimit - 1 : xlimit].attrs & WIDTH_MASK) == 2) xlimit++;
    }
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

static inline void
left_shift_line(Line *line, index_type at, index_type num) {
    for (index_type i = at; i < line->xnum - num; i++) {
        COPY_CELL(line, i + num, line, i);
    }
    if (at < line->xnum && ((line->gpu_cells[at].attrs) & WIDTH_MASK) != 1) {
        line->cpu_cells[at].ch = BLANK_CHAR;
        line->cpu_cells[at].hyperlink_id = 0;
        line->gpu_cells[at].attrs = BLANK_CHAR ? 1 : 0;
        clear_sprite_position(line->gpu_cells[at]);
    }
}

typedef Line*(get_line_func)(void *, int);
void line_clear_text(Line *self, unsigned int at, unsigned int num, char_type ch);
void line_apply_cursor(Line *self, Cursor *cursor, unsigned int at, unsigned int num, bool clear_char);
char_type line_get_char(Line *self, index_type at);
void line_set_char(Line *, unsigned int , uint32_t , unsigned int , Cursor *, hyperlink_id_type);
void line_right_shift(Line *, unsigned int , unsigned int );
void line_add_combining_char(Line *, uint32_t , unsigned int );
index_type line_url_start_at(Line *self, index_type x);
index_type line_url_end_at(Line *self, index_type x, bool, char_type, bool);
bool line_startswith_url_chars(Line*);
void line_as_ansi(Line *self, ANSIBuf *output, const GPUCell**) __attribute__((nonnull));
unsigned int line_length(Line *self);
size_t cell_as_unicode(CPUCell *cell, bool include_cc, Py_UCS4 *buf, char_type);
size_t cell_as_unicode_for_fallback(CPUCell *cell, Py_UCS4 *buf);
size_t cell_as_utf8(CPUCell *cell, bool include_cc, char *buf, char_type);
size_t cell_as_utf8_for_fallback(CPUCell *cell, char *buf);
PyObject* unicode_in_range(const Line *self, const index_type start, const index_type limit, const bool include_cc, const char leading_char, const bool skip_zero_cells);
PyObject* line_as_unicode(Line *, bool);

void linebuf_init_line(LineBuf *, index_type);
void linebuf_clear(LineBuf *, char_type ch);
void linebuf_index(LineBuf* self, index_type top, index_type bottom);
void linebuf_reverse_index(LineBuf *self, index_type top, index_type bottom);
void linebuf_clear_line(LineBuf *self, index_type y);
void linebuf_insert_lines(LineBuf *self, unsigned int num, unsigned int y, unsigned int bottom);
void linebuf_delete_lines(LineBuf *self, index_type num, index_type y, index_type bottom);
void linebuf_copy_line_to(LineBuf *, Line *, index_type);
void linebuf_set_attribute(LineBuf *, unsigned int , unsigned int );
void linebuf_rewrap(LineBuf *self, LineBuf *other, index_type *, index_type *, HistoryBuf *, index_type *, index_type *, ANSIBuf*);
void linebuf_mark_line_dirty(LineBuf *self, index_type y);
void linebuf_mark_line_clean(LineBuf *self, index_type y);
void linebuf_mark_line_as_not_continued(LineBuf *self, index_type y);
unsigned int linebuf_char_width_at(LineBuf *self, index_type x, index_type y);
void linebuf_refresh_sprite_positions(LineBuf *self);
void historybuf_add_line(HistoryBuf *self, const Line *line, ANSIBuf*);
bool historybuf_pop_line(HistoryBuf *, Line *);
void historybuf_rewrap(HistoryBuf *self, HistoryBuf *other, ANSIBuf*);
void historybuf_init_line(HistoryBuf *self, index_type num, Line *l);
CPUCell* historybuf_cpu_cells(HistoryBuf *self, index_type num);
void historybuf_mark_line_clean(HistoryBuf *self, index_type y);
void historybuf_mark_line_dirty(HistoryBuf *self, index_type y);
void historybuf_refresh_sprite_positions(HistoryBuf *self);
void historybuf_clear(HistoryBuf *self);
void mark_text_in_line(PyObject *marker, Line *line);
bool line_has_mark(Line *, attrs_type mark);
PyObject* as_text_generic(PyObject *args, void *container, get_line_func get_line, index_type lines, ANSIBuf *ansibuf);
