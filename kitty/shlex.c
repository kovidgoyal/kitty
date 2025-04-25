/*
 * shlex.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "unicodeobject.h"
#include "launcher/shlex.h"

typedef struct {
    PyObject_HEAD
    ShlexState state;
    PyObject *src;
    bool yielded;
    void *data; int kind;
    size_t unicode_pos, src_pos_at_last_unicode_pos;
} Shlex;


static PyObject *
new_shlex_object(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Shlex *self;
    self = (Shlex *)type->tp_alloc(type, 0);
    if (self) {
        const char *src; Py_ssize_t sz;
        int support_ansi_c_quoting;
        if (!PyArg_ParseTuple(args, "s#|p", &src, &sz, &support_ansi_c_quoting)) return NULL;
        if (!alloc_shlex_state(&self->state, src, sz, support_ansi_c_quoting != 0)) return PyErr_NoMemory();
        self->src = PyTuple_GetItem(args, 0);
        self->data = PyUnicode_DATA(self->src);
        self->kind = PyUnicode_KIND(self->src);
        Py_INCREF(self->src);
    }
    return (PyObject*) self;
}

static void
dealloc(Shlex* self) {
    Py_CLEAR(self->src); dealloc_shlex_state(&self->state);
}

static size_t
advance_unicode_pos(Shlex *self) {
    ssize_t num_bytes = self->state.word_start - self->src_pos_at_last_unicode_pos;
    self->src_pos_at_last_unicode_pos = self->state.word_start;
    char buf[8];
    while (num_bytes > 0) {
        Py_UCS4 ch = PyUnicode_READ(self->kind, self->data, self->unicode_pos);
        num_bytes -= encode_utf8(ch, buf);
        self->unicode_pos++;
    }
    return self->unicode_pos;
}

static PyObject*
next_word_with_position(Shlex *self, PyObject *args UNUSED) {
    ssize_t len = next_word(&self->state);
    unsigned long pos = advance_unicode_pos(self);
    switch(len) {
        case -1: PyErr_SetString(PyExc_ValueError, self->state.err); return NULL;
        case -2:
            if (self->yielded) return Py_BuildValue("is#", -1, self->state.buf, 0);
            len = 0;
            /* fallthrough */
        default:
            self->yielded = true;
            return Py_BuildValue("ks#", pos, self->state.buf, (Py_ssize_t)len);
    }
}

static PyObject*
next(PyObject *self_) {
    Shlex *self = (Shlex*)self_;
    ssize_t len = next_word(&self->state);
    switch(len) {
        case -1: PyErr_SetString(PyExc_ValueError, self->state.err); return NULL;
        case -2:
            if (self->yielded) { PyErr_SetNone(PyExc_StopIteration); return NULL; }
            len = 0;
            /* fallthrough */
        default:
            self->yielded = true;
            return PyUnicode_FromStringAndSize(self->state.buf, (Py_ssize_t)len);
    }
}

static PyObject*
iter(PyObject *s) { return Py_NewRef(s); }

static PyMethodDef methods[] = {
    {"next_word", (PyCFunction)next_word_with_position, METH_NOARGS, ""},
    {NULL}  /* Sentinel */
};

PyTypeObject Shlex_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Shlex",
    .tp_basicsize = sizeof(Shlex),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Lexing like a shell",
    .tp_iternext = next,
    .tp_new = new_shlex_object,
    .tp_iter = iter,
    .tp_methods = methods,
};

INIT_TYPE(Shlex)
