/*
 * history.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <structmember.h>

#define CELL_SIZE_H (CELL_SIZE + 1)

static PyObject *
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    HistoryBuf *self;
    unsigned int xnum = 1, ynum = 1;

    if (!PyArg_ParseTuple(args, "II", &ynum, &xnum)) return NULL;

    if (xnum * ynum == 0) {
        PyErr_SetString(PyExc_ValueError, "Cannot create an empty history buffer");
        return NULL;
    }

    self = (HistoryBuf *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->xnum = xnum;
        self->ynum = ynum;
        self->buf = PyMem_Calloc(xnum * ynum, CELL_SIZE_H);
        self->line = alloc_line();
        if (self->buf == NULL || self->line == NULL) {
            PyErr_NoMemory();
            PyMem_Free(self->buf); Py_CLEAR(self->line);
            Py_CLEAR(self);
        } else {
            self->line->xnum = xnum;
        }
    }

    return (PyObject*)self;
}

static void
dealloc(LineBuf* self) {
    PyMem_Free(self->buf);
    Py_CLEAR(self->line);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static inline index_type index_of(HistoryBuf *self, index_type lnum) {
    // The index (buffer position) of the line with line number lnum
    // This is reverse indexing, i.e. lnum = 0 corresponds to the *last* line in the buffer.
    if (self->count == 0) return 0;
    index_type idx = self->count - 1 - MIN(self->count - 1, lnum);
    return (self->start_of_data + idx) % self->ynum;
}

static inline void* start_of(HistoryBuf *self, index_type num) {
    // Pointer to the start of the line with index (buffer position) num
    return self->buf + CELL_SIZE_H * num * self->xnum;
}

static inline void init_line(HistoryBuf *self, index_type num, Line *l) {
    // Initialize the line l, setting its pointer to the offsets for the line at index (buffer position) num
    uint8_t *start_ptr = start_of(self, num);
    l->continued = *start_ptr;
    l->chars = (char_type*)(start_ptr + 1);
    l->colors = (color_type*)(l->chars + self->xnum);
    l->decoration_fg = (decoration_type*)(l->colors + self->xnum);
    l->combining_chars = (combining_type*)(l->decoration_fg + self->xnum);
}

static inline void historybuf_push(HistoryBuf *self) {
    init_line(self, (self->start_of_data + self->count) % self->ynum, self->line);
    if (self->count == self->ynum) self->start_of_data = (self->start_of_data + 1) % self->ynum;
    else self->count++;
}

static PyObject*
change_num_of_lines(HistoryBuf *self, PyObject *val) {
#define change_num_of_lines_doc "Change the number of lines in thsi buffer"
    HistoryBuf t = {0};
    t.xnum=self->xnum;
    t.ynum=(index_type) PyLong_AsUnsignedLong(val);
    if (t.ynum > 0 && t.ynum != self->ynum) {
        t.buf = PyMem_Calloc(t.xnum * t.ynum, CELL_SIZE_H);
        if (t.buf == NULL) return PyErr_NoMemory();
        t.count = MIN(self->count, t.ynum);
        if (t.count > 0) {
            for (index_type s=0; s < t.count; s++) {
                void *src = start_of(self, index_of(self, s)), *dest = start_of(&t, index_of(&t, s));
                memcpy(dest, src, CELL_SIZE_H * t.xnum);
            }
        }
        self->count = t.count;
        self->start_of_data = t.start_of_data;
        self->ynum = t.ynum;
        PyMem_Free(self->buf);
        self->buf = t.buf;
    }
    Py_RETURN_NONE;
}

static PyObject*
line(HistoryBuf *self, PyObject *lnum) {
#define line_doc "Return the line with line number lnum. This buffer grows upwards, i.e. 0 is the most recently added line"
    init_line(self, index_of(self, PyLong_AsUnsignedLong(lnum)), self->line);
    Py_INCREF(self->line);
    return (PyObject*)self->line;
}

// Boilerplate {{{
static PyMethodDef methods[] = {
    METHOD(change_num_of_lines, METH_O)
    METHOD(line, METH_O)
    {NULL, NULL, 0, NULL}  /* Sentinel */
};

static PyMemberDef members[] = {
    {"xnum", T_UINT, offsetof(HistoryBuf, xnum), READONLY, "xnum"},
    {"ynum", T_UINT, offsetof(HistoryBuf, ynum), READONLY, "ynum"},
    {"count", T_UINT, offsetof(HistoryBuf, count), READONLY, "count"},
    {NULL}  /* Sentinel */
};

PyTypeObject HistoryBuf_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.HistoryBuf",
    .tp_basicsize = sizeof(HistoryBuf),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "History buffers",
    .tp_methods = methods,
    .tp_members = members,            
    .tp_new = new
};

INIT_TYPE(HistoryBuf)
// }}}

HistoryBuf *alloc_historybuf(unsigned int lines, unsigned int columns) {
    return (HistoryBuf*)new(&HistoryBuf_Type, Py_BuildValue("II", lines, columns), NULL);
}
