/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

static inline void
update_sprites_in_line(Cell *cells, index_type xnum) {
    if (LIKELY(xnum > 0)) {
        if (CHAR_IS_BLANK(cells->ch)) { clear_sprite_position(cells[0]); }
        else set_sprite_position(cells, NULL);
        for (index_type i = 1; i < xnum; i++) {
            if (CHAR_IS_BLANK(cells[i].ch)) { clear_sprite_position(cells[i]); }
            else set_sprite_position(cells + i, cells + i - 1);
        }
    }
}

static inline void
set_attribute_on_line(Cell *cells, uint32_t shift, uint32_t val, index_type xnum) {
    uint32_t mask = shift == DECORATION_SHIFT ? 3 : 1;
    uint32_t aval = (val & mask) << (ATTRS_SHIFT + shift); 
    mask = ~(mask << (ATTRS_SHIFT + shift));
    for (index_type i = 0; i < xnum; i++) cells[i].ch = (cells[i].ch & mask) | aval;
    if (shift == BOLD_SHIFT || shift == ITALIC_SHIFT) update_sprites_in_line(cells, xnum);
}

static inline void
copy_cells(const Cell *src, Cell *dest, index_type xnum) {
    memcpy(dest, src, sizeof(Cell) * xnum);
}

static inline void
copy_line(const Line *src, Line *dest) {
    copy_cells(src->cells, dest->cells, MIN(src->xnum, dest->xnum));
}

static inline void
clear_chars_in_line(Cell *cells, index_type xnum, char_type ch) {
    // Clear only the char part of each cell, the rest must have been cleared by a memset or similar
    char_type c = (1 << ATTRS_SHIFT) | ch;
    for (index_type i = 0; i < xnum; i++) cells[i].ch = c;
}

static inline index_type
xlimit_for_line(Line *line) {
    index_type xlimit = line->xnum;
    if (BLANK_CHAR == 0) {
        while (xlimit > 0 && (line->cells[xlimit - 1].ch & CHAR_MASK) == BLANK_CHAR) xlimit--;
    }
    return xlimit;
}

PyObject* line_text_at(char_type, combining_type);
void line_clear_text(Line *self, unsigned int at, unsigned int num, int ch);
void line_apply_cursor(Line *self, Cursor *cursor, unsigned int at, unsigned int num, bool clear_char);
void line_set_char(Line *, unsigned int , uint32_t , unsigned int , Cursor *);
void line_right_shift(Line *, unsigned int , unsigned int );
void line_add_combining_char(Line *, uint32_t , unsigned int );
index_type line_url_start_at(Line *self, index_type x);
index_type line_as_ansi(Line *self, Py_UCS4 *buf, index_type buflen);
unsigned int line_length(Line *self);
PyObject* unicode_in_range(Line *self, index_type start, index_type limit, bool include_cc, char leading_char);

void linebuf_init_line(LineBuf *, index_type);
void linebuf_clear(LineBuf *, char_type ch);
void linebuf_init_line(LineBuf *, index_type);
void linebuf_index(LineBuf* self, index_type top, index_type bottom);
void linebuf_reverse_index(LineBuf *self, index_type top, index_type bottom);
void linebuf_clear_line(LineBuf *self, index_type y);
void linebuf_insert_lines(LineBuf *self, unsigned int num, unsigned int y, unsigned int bottom);
void linebuf_delete_lines(LineBuf *self, index_type num, index_type y, index_type bottom);
void linebuf_set_attribute(LineBuf *, unsigned int , unsigned int );
void linebuf_rewrap(LineBuf *self, LineBuf *other, int *cursor_y_out, HistoryBuf *);
unsigned int linebuf_char_width_at(LineBuf *self, index_type x, index_type y);
void linebuf_refresh_sprite_positions(LineBuf *self);
bool historybuf_resize(HistoryBuf *self, index_type lines);
void historybuf_add_line(HistoryBuf *self, const Line *line);
void historybuf_rewrap(HistoryBuf *self, HistoryBuf *other);
void historybuf_init_line(HistoryBuf *self, index_type num, Line *l);
void historybuf_refresh_sprite_positions(HistoryBuf *self);
