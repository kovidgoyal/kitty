/*
 * line.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"


static PyObject *
new(PyTypeObject UNUSED *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    PyErr_SetString(PyExc_TypeError, "Line objects cannot be instantiated directly, create them using LineBuf.line()");
    return NULL;
}

static void
dealloc(LineBuf* self) {
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject *
text_at(Line* self, PyObject *x) {
    unsigned long xval = PyLong_AsUnsignedLong(x);
    char_type ch;
    combining_type cc;
    PyObject *ans;

    if (xval >= self->xnum) { PyErr_SetString(PyExc_ValueError, "Column number out of bounds"); return NULL; }

    ch = self->chars[xval] & CHAR_MASK;
    cc = self->combining_chars[xval];
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
static PyMethodDef methods[] = {
    {"text_at", (PyCFunction)text_at, METH_O,
     "Return the text in the specified cell"
    },
    {NULL}  /* Sentinel */
};

PyTypeObject Line_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "fast_data_types.Line",
    sizeof(Line),
    0,                         /* tp_itemsize */
    (destructor)dealloc,       /* tp_dealloc */
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
    "Lines",                   /* tp_doc */
    0,                         /* tp_traverse */
    0,                         /* tp_clear */
    0,                         /* tp_richcompare */
    0,                         /* tp_weaklistoffset */
    0,                         /* tp_iter */
    0,                         /* tp_iternext */
    methods,                   /* tp_methods */
    0,                         /* tp_members */
    0,                         /* tp_getset */
    0,                         /* tp_base */
    0,                         /* tp_dict */
    0,                         /* tp_descr_get */
    0,                         /* tp_descr_set */
    0,                         /* tp_dictoffset */
    0,                         /* tp_init */
    0,                         /* tp_alloc */
    new,                       /* tp_new */
};
// }}

