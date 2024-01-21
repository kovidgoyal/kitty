/*
 * shlex.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

typedef enum { NORMAL, WORD, STRING_WITHOUT_ESCAPES, STRING_WITH_ESCAPES, } State;
typedef struct {
    PyObject_HEAD

    PyObject *src, *buf;
    Py_ssize_t src_sz, src_pos, word_start, buf_pos;
    int kind; void *src_data, *buf_data;
    State state;
} Shlex;


static PyObject *
new_shlex_object(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Shlex *self;
    self = (Shlex *)type->tp_alloc(type, 0);
    if (self) {
        PyObject *src;
        if (!PyArg_ParseTuple(args, "U", &src)) return NULL;
        self->src_sz = PyUnicode_GET_LENGTH(src);
        self->buf = PyUnicode_New(self->src_sz, PyUnicode_MAX_CHAR_VALUE(src));
        if (self->buf) {
            self->src = src;
            Py_INCREF(src);
            self->kind = PyUnicode_KIND(src);
            self->src_data = PyUnicode_DATA(src);
            self->buf_data = PyUnicode_DATA(self->buf);
        } else Py_CLEAR(self);
    }
    return (PyObject*) self;
}

static void
dealloc(Shlex* self) {
    Py_CLEAR(self->src); Py_CLEAR(self->buf);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

#define WHITESPACE ' ': case '\n': case '\t': case '\r'
#define STRING_WITH_ESCAPES_DELIM '"'
#define STRING_WITHOUT_ESCAPES_DELIM '\''
#define ESCAPE_CHAR '\\'

static void
start_word(Shlex *self) {
    self->word_start = self->src_pos - 1;
    self->buf_pos = 0;
}

static void
write_ch(Shlex *self, Py_UCS4 ch) {
    PyUnicode_WRITE(self->kind, self->buf_data, self->buf_pos, ch); self->buf_pos++;
}

static PyObject*
get_word(Shlex *self) {
    Py_ssize_t pos = self->buf_pos; self->buf_pos = 0;
    return Py_BuildValue("nN", self->word_start, PyUnicode_Substring(self->buf, 0, pos));
}

static bool
write_escape_ch(Shlex *self) {
    if (self->src_pos < self->src_sz) {
        Py_UCS4 nch = PyUnicode_READ(self->kind, self->src_data, self->src_pos); self->src_pos++;
        write_ch(self, nch);
        return true;
    }
    return false;
}

static void
set_state(Shlex *self, State s) {
    self->state = s;
}

static PyObject*
next_word(Shlex *self, PyObject *args UNUSED) {
#define write_escaped_or_fail() if (!write_escape_ch(self)) { PyErr_SetString(PyExc_ValueError, "Trailing backslash at end of input data"); return NULL; }

    while (self->src_pos < self->src_sz) {
        Py_UCS4 ch = PyUnicode_READ(self->kind, self->src_data, self->src_pos); self->src_pos++;
        switch(self->state) {
            case NORMAL:
                switch(ch) {
                    case WHITESPACE: break;
                    case STRING_WITH_ESCAPES_DELIM: set_state(self, STRING_WITH_ESCAPES); start_word(self); break;
                    case STRING_WITHOUT_ESCAPES_DELIM: set_state(self, STRING_WITHOUT_ESCAPES); start_word(self); break;
                    case ESCAPE_CHAR: start_word(self); write_escaped_or_fail(); set_state(self, WORD); break;
                    default: set_state(self, WORD); start_word(self); write_ch(self, ch); break;
                }
                break;
            case WORD:
                switch(ch) {
                    case WHITESPACE: set_state(self, NORMAL); if (self->buf_pos) return get_word(self); break;
                    case STRING_WITH_ESCAPES_DELIM: set_state(self, STRING_WITH_ESCAPES); break;
                    case STRING_WITHOUT_ESCAPES_DELIM: set_state(self, STRING_WITHOUT_ESCAPES); break;
                    case ESCAPE_CHAR: write_escaped_or_fail(); break;
                    default: write_ch(self, ch); break;
                } break;
            case STRING_WITHOUT_ESCAPES:
                switch(ch) {
                    case STRING_WITHOUT_ESCAPES_DELIM:
                        set_state(self, WORD);
                        break;
                    default: write_ch(self, ch); break;
                } break;
            case STRING_WITH_ESCAPES:
                switch(ch) {
                    case STRING_WITH_ESCAPES_DELIM:
                        set_state(self, WORD);
                        break;
                    case ESCAPE_CHAR:
                        write_escape_ch(self);
                        break;
                    default: write_ch(self, ch); break;
                } break;
        }
    }
    switch (self->state) {
        case WORD:
            self->state = NORMAL;
            if (self->buf_pos) return get_word(self);
            break;
        case STRING_WITH_ESCAPES: case STRING_WITHOUT_ESCAPES:
            PyErr_SetString(PyExc_ValueError, "Unterminated string at the end of input");
            self->state = NORMAL;
            return NULL;
        case NORMAL:
            break;
    }
    return Py_BuildValue("is", -1, "");
#undef write_escaped_or_fail
}


static PyMethodDef methods[] = {
    METHODB(next_word, METH_NOARGS),
    {NULL}  /* Sentinel */
};

PyTypeObject Shlex_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Shlex",
    .tp_basicsize = sizeof(Shlex),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Lexing like a shell",
    .tp_methods = methods,
    .tp_new = new_shlex_object,
};

INIT_TYPE(Shlex)
