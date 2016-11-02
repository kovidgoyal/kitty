/*
 * line-buf.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

static inline void
clear_chars_to_space(LineBuf* linebuf, index_type y) {
    char_type *chars = linebuf->chars + linebuf->xnum * y;
    for (index_type i = 0; i < linebuf->xnum; i++) chars[i] = (1 << ATTRS_SHIFT) | 32;
}

static PyObject *
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    LineBuf *self;
    index_type xnum, ynum;

    if (!PyArg_ParseTuple(args, "II", &ynum, &xnum)) return NULL;

    if (xnum > 5000 || ynum > 50000) {
        PyErr_SetString(PyExc_ValueError, "Number of rows or columns is too large.");
        return NULL;
    }

    if (xnum * ynum == 0) {
        PyErr_SetString(PyExc_ValueError, "Cannot create an empty LineBuf");
        return NULL;
    }

    self = (LineBuf *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->xnum = xnum;
        self->ynum = ynum;
        self->block_size = xnum * ynum;
        self->buf = PyMem_Calloc(xnum * ynum, CELL_SIZE);
        self->line_map = PyMem_Calloc(ynum, sizeof(index_type));
        self->continued_map = PyMem_Calloc(ynum, sizeof(uint8_t));
        self->line = alloc_line();
        if (self->buf == NULL || self->line_map == NULL || self->continued_map == NULL || self->line == NULL) {
            PyErr_NoMemory();
            PyMem_Free(self->buf); PyMem_Free(self->line_map); PyMem_Free(self->continued_map); Py_XDECREF(self->line);
            Py_DECREF(self);
            self = NULL;
        } else {
            self->chars = (char_type*)self->buf;
            self->colors = (color_type*)(self->chars + self->block_size);
            self->decoration_fg = (decoration_type*)(self->colors + self->block_size);
            self->combining_chars = (combining_type*)(self->decoration_fg + self->block_size);
            self->line->xnum = xnum;
            for(index_type i = 0; i < ynum; i++) {
                self->line_map[i] = i;
                clear_chars_to_space(self, i);
            }
        }
    }

    return (PyObject*)self;
}

static void
dealloc(LineBuf* self) {
    PyMem_Free(self->buf); PyMem_Free(self->line_map); PyMem_Free(self->continued_map);
    Py_XDECREF(self->line);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
line(LineBuf *self, PyObject *y) {
    unsigned long idx = PyLong_AsUnsignedLong(y);
    if (idx >= self->ynum) {
        PyErr_SetString(PyExc_ValueError, "Line number too large");
        return NULL;
    }
    self->line->ynum = self->line_map[idx];
    size_t off = self->line->ynum * self->xnum;
    self->line->chars = self->chars + off;
    self->line->colors = self->colors + off;
    self->line->decoration_fg = self->decoration_fg + off;
    self->line->combining_chars = self->combining_chars + off;
    Py_INCREF(self->line);
    return (PyObject*)self->line;
}

// Boilerplate {{{
static PyMethodDef methods[] = {
    {"line", (PyCFunction)line, METH_O,
     "Return the specified line as a Line object. Note the Line Object is a live view into the underlying buffer. And only a single line object can be used at a time."
    },
    {NULL}  /* Sentinel */
};

static PyTypeObject LineBuf_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.LineBuf",
    .tp_basicsize = sizeof(LineBuf),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "Line buffers",
    .tp_methods = methods,
    .tp_new = new
};

INIT_TYPE(LineBuf)
// }}

