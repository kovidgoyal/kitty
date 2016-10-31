/*
 * cursor.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

#include <structmember.h>

#define INIT_NONE(x) Py_INCREF(Py_None); x = Py_None;

static PyObject *
Cursor_new(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    Cursor *self;

    self = (Cursor *)type->tp_alloc(type, 0);
    if (self != NULL) {
        INIT_NONE(self->shape);
        INIT_NONE(self->blink);
        INIT_NONE(self->color);
        self->hidden = Py_False; Py_INCREF(Py_False);
        self->bold = 0; self->italic = 0; self->reverse = 0; self->strikethrough = 0; self->decoration = 0;
        self->fg = 0; self->bg = 0; self->decoration_fg = 0;
        self->x = PyLong_FromLong(0); self->y = PyLong_FromLong(0);
        if (self->x == NULL || self->y == NULL) { Py_DECREF(self); self = NULL; }
    }
    return (PyObject*) self;
}

static void
Cursor_dealloc(Cursor* self) {
    Py_XDECREF(self->shape);
    Py_XDECREF(self->blink);
    Py_XDECREF(self->color);
    Py_XDECREF(self->hidden);
    Py_XDECREF(self->x);
    Py_XDECREF(self->y);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

// Boilerplate {{{

static PyMemberDef Cursor_members[] = {
    {"x", T_OBJECT_EX, offsetof(Cursor, x), 0, "x"},
    {"y", T_OBJECT_EX, offsetof(Cursor, y), 0, "y"},
    {"shape", T_OBJECT_EX, offsetof(Cursor, shape), 0, "shape"},
    {"blink", T_OBJECT_EX, offsetof(Cursor, blink), 0, "blink"},
    {"color", T_OBJECT_EX, offsetof(Cursor, color), 0, "color"},
    {"hidden", T_OBJECT_EX, offsetof(Cursor, hidden), 0, "hidden"},
    {NULL}  /* Sentinel */
};

static PyMethodDef Cursor_methods[] = {
    {NULL}  /* Sentinel */
};

PyTypeObject Cursor_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    "fast_data_types.Cursor",
    sizeof(Cursor),
    0,                         /* tp_itemsize */
    (destructor)Cursor_dealloc, /* tp_dealloc */
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
    "Cursors",                 /* tp_doc */
    0,                         /* tp_traverse */
    0,                         /* tp_clear */
    0,                         /* tp_richcompare */
    0,                         /* tp_weaklistoffset */
    0,                         /* tp_iter */
    0,                         /* tp_iternext */
    Cursor_methods,            /* tp_methods */
    Cursor_members,            /* tp_members */
    0,                         /* tp_getset */
    0,                         /* tp_base */
    0,                         /* tp_dict */
    0,                         /* tp_descr_get */
    0,                         /* tp_descr_set */
    0,                         /* tp_dictoffset */
    0,                         /* tp_init */
    0,                         /* tp_alloc */
    Cursor_new,                /* tp_new */
};
// }}

