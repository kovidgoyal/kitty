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
        for (index_type i = 0; i < xnum; i++) { cpu_cells[i].ch = ch; gpu_cells[i].attrs = 1; }
    }
}

static inline index_type
xlimit_for_line(Line *line) {
    index_type xlimit = line->xnum;
    if (BLANK_CHAR == 0) {
        while (xlimit > 0 && (line->cpu_cells[xlimit - 1].ch) == BLANK_CHAR) xlimit--;
    }
    return xlimit;
}


void line_clear_text(Line *self, unsigned int at, unsigned int num, char_type ch);
void line_apply_cursor(Line *self, Cursor *cursor, unsigned int at, unsigned int num, bool clear_char);
void line_set_char(Line *, unsigned int , uint32_t , unsigned int , Cursor *, bool);
void line_right_shift(Line *, unsigned int , unsigned int );
void line_add_combining_char(Line *, uint32_t , unsigned int );
index_type line_url_start_at(Line *self, index_type x);
index_type line_url_end_at(Line *self, index_type x, bool);
index_type line_as_ansi(Line *self, Py_UCS4 *buf, index_type buflen);
unsigned int line_length(Line *self);
size_t cell_as_unicode(CPUCell *cell, bool include_cc, Py_UCS4 *buf, char_type);
size_t cell_as_utf8(CPUCell *cell, bool include_cc, char *buf, char_type);
PyObject* unicode_in_range(Line *self, index_type start, index_type limit, bool include_cc, char leading_char);
PyObject* line_as_unicode(Line *);

void linebuf_init_line(LineBuf *, index_type);
void linebuf_clear(LineBuf *, char_type ch);
void linebuf_index(LineBuf* self, index_type top, index_type bottom);
void linebuf_reverse_index(LineBuf *self, index_type top, index_type bottom);
void linebuf_clear_line(LineBuf *self, index_type y);
void linebuf_insert_lines(LineBuf *self, unsigned int num, unsigned int y, unsigned int bottom);
void linebuf_delete_lines(LineBuf *self, index_type num, index_type y, index_type bottom);
void linebuf_set_attribute(LineBuf *, unsigned int , unsigned int );
void linebuf_rewrap(LineBuf *self, LineBuf *other, index_type *, index_type *, HistoryBuf *, index_type *, index_type *);
void linebuf_mark_line_dirty(LineBuf *self, index_type y);
void linebuf_mark_line_clean(LineBuf *self, index_type y);
unsigned int linebuf_char_width_at(LineBuf *self, index_type x, index_type y);
void linebuf_refresh_sprite_positions(LineBuf *self);
void historybuf_add_line(HistoryBuf *self, const Line *line);
void historybuf_rewrap(HistoryBuf *self, HistoryBuf *other);
void historybuf_init_line(HistoryBuf *self, index_type num, Line *l);
void historybuf_mark_line_clean(HistoryBuf *self, index_type y);
void historybuf_mark_line_dirty(HistoryBuf *self, index_type y);
void historybuf_refresh_sprite_positions(HistoryBuf *self);
void historybuf_clear(HistoryBuf *self);


#define as_text_generic(args, container, get_line, lines, columns) { \
    PyObject *callback; \
    int as_ansi = 0, insert_wrap_markers = 0; \
    if (!PyArg_ParseTuple(args, "O|pp", &callback, &as_ansi, &insert_wrap_markers)) return NULL; \
    PyObject *ret = NULL, *t = NULL; \
    Py_UCS4 *buf = NULL; \
    PyObject *nl = PyUnicode_FromString("\n"); \
    PyObject *cr = PyUnicode_FromString("\r"); \
    if (nl == NULL || cr == NULL) goto end; \
    if (as_ansi) { \
        buf = malloc(sizeof(Py_UCS4) * columns * 100); \
        if (buf == NULL) { PyErr_NoMemory(); goto end; } \
    } \
    for (index_type y = 0; y < lines; y++) { \
        Line *line = get_line(container, y); \
        if (!line->continued && y > 0) { \
            ret = PyObject_CallFunctionObjArgs(callback, nl, NULL); \
            if (ret == NULL) goto end; \
            Py_CLEAR(ret); \
        } \
        if (as_ansi) { \
            index_type num = line_as_ansi(line, buf, columns * 100 - 2); \
            t = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buf, num); \
        } else { \
            t = line_as_unicode(line); \
        } \
        if (t == NULL) goto end; \
        ret = PyObject_CallFunctionObjArgs(callback, t, NULL); \
        Py_DECREF(t); if (ret == NULL) goto end; Py_DECREF(ret); \
        if (insert_wrap_markers) { \
            ret = PyObject_CallFunctionObjArgs(callback, cr, NULL); \
            if (ret == NULL) goto end; \
            Py_CLEAR(ret); \
        }\
    } \
end: \
    Py_CLEAR(nl); Py_CLEAR(cr); free(buf); \
    if (PyErr_Occurred()) return NULL; \
    Py_RETURN_NONE; \
}
