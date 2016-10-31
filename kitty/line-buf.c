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
    for (index_type i = 0; i < linebuf->xnum; i++) chars[i] = 32;
}

static PyObject *
LineBuf_new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
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
        if (self->buf == NULL || self->line_map == NULL || self->continued_map == NULL) {
            PyErr_NoMemory();
            PyMem_Free(self->buf); PyMem_Free(self->line_map); PyMem_Free(self->continued_map);
            Py_DECREF(self);
            self = NULL;
        } else {
            self->chars = (char_type*)self->buf;
            self->colors = (color_type*)(self->chars + self->block_size);
            self->decoration_fg = (decoration_type*)(self->colors + self->block_size);
            self->combining_chars = (combining_type*)(self->decoration_fg + self->block_size);
            for(index_type i = 0; i < ynum; i++) {
                self->line_map[i] = i;
                clear_chars_to_space(self, i);
            }
        }
    }

    return (PyObject*)self;
}

static void
LineBuf_dealloc(LineBuf* self) {
    PyMem_Free(self->buf); PyMem_Free(self->line_map); PyMem_Free(self->continued_map);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject *
text_at(LineBuf* self, PyObject *args) {
    index_type ynum, xnum, idx;
    char_type ch;
    combining_type cc;
    PyObject * ans;

    if (!PyArg_ParseTuple(args, "II", &ynum, &xnum)) return NULL;
    if (ynum >= self->ynum) { PyErr_SetString(PyExc_ValueError, "Line number out of bounds"); return NULL; }
    if (xnum >= self->xnum) { PyErr_SetString(PyExc_ValueError, "Column number out of bounds"); return NULL; }

    idx = xnum + ynum * self->xnum;
    ch = self->chars[idx] & CHAR_MASK;
    cc = self->combining_chars[idx];
    if (cc == 0) {
        ans = PyUnicode_New(1, ch);
        if (ans == NULL) return PyErr_NoMemory();
        PyUnicode_WriteChar(ans, 0, ch);
    } else {
        Py_UCS4 cc1 = cc & 0xFFFF, cc2 = cc >> 16;
        Py_UCS4 maxc = (ch > cc1) ? MAX(ch, cc2) : MAX(cc1, cc2);
        ans = PyUnicode_New(cc2 ? 3 : 2, maxc);
        if (ans == NULL) return PyErr_NoMemory();
        PyUnicode_WriteChar(ans, 0, ch);
        PyUnicode_WriteChar(ans, 1, cc1);
        if (cc2) PyUnicode_WriteChar(ans, 2, cc2);
    }

    return ans;
}

// Boilerplate {{{
static PyMethodDef LineBuf_methods[] = {
    {"text_at", (PyCFunction)text_at, METH_VARARGS,
     "Return the text in the specified cell"
    },
    {NULL}  /* Sentinel */
};

PyTypeObject LineBuf_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "fast_data_types.LineBuf",
    sizeof(LineBuf),
    0,                         /* tp_itemsize */
    (destructor)LineBuf_dealloc, /* tp_dealloc */
    0,                         /* tp_print */
    0,                         /* tp_getattr */
    0,                         /* tp_setattr */
    0,                         /* tp_reserved */
    0,                         /* tp_repr */
    0,                         /* tp_as_number */
    0,                         /* tp_as_sequence */
    0,                         /* tp_as_mapping */
    0,                         /* tp_hash  */
    0,                         /* tp_call */
    0,                         /* tp_str */
    0,                         /* tp_getattro */
    0,                         /* tp_setattro */
    0,                         /* tp_as_buffer */
    Py_TPFLAGS_DEFAULT,        /* tp_flags */
    "Line buffers",            /* tp_doc */
    0,                         /* tp_traverse */
    0,                         /* tp_clear */
    0,                         /* tp_richcompare */
    0,                         /* tp_weaklistoffset */
    0,                         /* tp_iter */
    0,                         /* tp_iternext */
    LineBuf_methods,           /* tp_methods */
    0,                         /* tp_members */
    0,                         /* tp_getset */
    0,                         /* tp_base */
    0,                         /* tp_dict */
    0,                         /* tp_descr_get */
    0,                         /* tp_descr_set */
    0,                         /* tp_dictoffset */
    0,                         /* tp_init */
    0,                         /* tp_alloc */
    LineBuf_new,               /* tp_new */
};
// }}

