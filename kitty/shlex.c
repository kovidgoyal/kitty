/*
 * shlex.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

typedef enum { NORMAL, WORD, STRING_WITHOUT_ESCAPES, STRING_WITH_ESCAPES, ANSI_C_QUOTED } State;
typedef struct {
    PyObject_HEAD

    PyObject *src;
    Py_UCS4 *buf;
    Py_ssize_t src_sz, src_pos, word_start, buf_pos;
    int kind, support_ansi_c_quoting; void *src_data;
    State state;
} Shlex;


static PyObject *
new_shlex_object(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Shlex *self;
    self = (Shlex *)type->tp_alloc(type, 0);
    if (self) {
        PyObject *src;
        if (!PyArg_ParseTuple(args, "U|p", &src, &self->support_ansi_c_quoting)) return NULL;
        self->src_sz = PyUnicode_GET_LENGTH(src);
        self->buf = malloc(sizeof(Py_UCS4) * self->src_sz);
        if (self->buf) {
            self->src = src;
            Py_INCREF(src);
            self->kind = PyUnicode_KIND(src);
            self->src_data = PyUnicode_DATA(src);
        } else { Py_CLEAR(self); PyErr_NoMemory(); }
    }
    return (PyObject*) self;
}

static void
dealloc(Shlex* self) {
    Py_CLEAR(self->src); free(self->buf);
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
    self->buf[self->buf_pos++] = ch;
}

static PyObject*
get_word(Shlex *self) {
    Py_ssize_t pos = self->buf_pos; self->buf_pos = 0;
    return Py_BuildValue("nN", self->word_start, PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, self->buf, pos));
}

static Py_UCS4
read_ch(Shlex *self) {
    Py_UCS4 nch = PyUnicode_READ(self->kind, self->src_data, self->src_pos); self->src_pos++;
    return nch;
}

static bool
write_escape_ch(Shlex *self) {
    if (self->src_pos < self->src_sz) {
        Py_UCS4 nch = read_ch(self);
        write_ch(self, nch);
        return true;
    }
    return false;
}

static bool
write_control_ch(Shlex *self) {
    if (self->src_pos >= self->src_sz) { PyErr_SetString(PyExc_ValueError, "Trailing \\c escape at end of input data"); return false; }
    Py_UCS4 ch = read_ch(self);
    write_ch(self, ch & 0x1f);
    return true;
}

static void
read_valid_digits(Shlex *self, int max, char *output, bool(*is_valid)(Py_UCS4 ch)) {
    for (int i = 0; i < max && self->src_pos < self->src_sz; i++, output++) {
        Py_UCS4 ch = read_ch(self);
        if (!is_valid(ch)) { self->src_pos--; break; }
        *output = ch;
    }
}

static bool
is_octal_digit(Py_UCS4 ch) { return '0' <= ch && ch <= '7'; }

static bool
is_hex_digit(Py_UCS4 ch) { return ('0' <= ch && ch <= '9') || ('a' <= ch && ch <= 'f') || ('A' <= ch && ch <= 'F'); }

static void
write_octal_ch(Shlex *self, Py_UCS4 ch) {
    char chars[4] = {ch, 0, 0, 0};
    read_valid_digits(self, 2, chars + 1, is_octal_digit);
    write_ch(self, strtol(chars, NULL, 8));
}

static bool
write_unicode_ch(Shlex *self, int max) {
    char chars[16] = {0};
    read_valid_digits(self, max, chars, is_hex_digit);
    if (!chars[0]) { PyErr_SetString(PyExc_ValueError, "Trailing unicode escape at end of input data"); return false; }
    write_ch(self, strtol(chars, NULL, 16));
    return true;
}

static bool
write_ansi_escape_ch(Shlex *self) {
    if (self->src_pos >= self->src_sz) { PyErr_SetString(PyExc_ValueError, "Trailing backslash at end of input data"); return false; }
    Py_UCS4 ch = read_ch(self);
    switch(ch) {
        case 'a': write_ch(self, '\a'); return true;
        case 'b': write_ch(self, '\b'); return true;
        case 'e': case 'E': write_ch(self, 0x1b); return true;
        case 'f': write_ch(self, '\f'); return true;
        case 'n': write_ch(self, '\n'); return true;
        case 'r': write_ch(self, '\r'); return true;
        case 't': write_ch(self, '\t'); return true;
        case 'v': write_ch(self, '\v'); return true;
        case '\\': write_ch(self, '\\'); return true;
        case '\'': write_ch(self, '\''); return true;
        case '\"': write_ch(self, '\"'); return true;
        case '\?': write_ch(self, '\?'); return true;

        case 'c': return write_control_ch(self);
        case 'x': return write_unicode_ch(self, 2);
        case 'u': return write_unicode_ch(self, 4);
        case 'U': return write_unicode_ch(self, 8);
START_ALLOW_CASE_RANGE
        case '0' ... '7': write_octal_ch(self, ch); return true;
END_ALLOW_CASE_RANGE

        default:
            write_ch(self, ch); return true;
    }
}

static void
set_state(Shlex *self, State s) {
    self->state = s;
}

static PyObject*
next_word(Shlex *self, PyObject *args UNUSED) {
#define write_escaped_or_fail() if (!write_escape_ch(self)) { PyErr_SetString(PyExc_ValueError, "Trailing backslash at end of input data"); return NULL; }

    Py_UCS4 prev_word_ch = 0;
    while (self->src_pos < self->src_sz) {
        Py_UCS4 ch = read_ch(self);
        switch(self->state) {
            case NORMAL:
                switch(ch) {
                    case WHITESPACE: break;
                    case STRING_WITH_ESCAPES_DELIM: set_state(self, STRING_WITH_ESCAPES); start_word(self); break;
                    case STRING_WITHOUT_ESCAPES_DELIM: set_state(self, STRING_WITHOUT_ESCAPES); start_word(self); break;
                    case ESCAPE_CHAR: start_word(self); write_escaped_or_fail(); set_state(self, WORD); break;
                    default: set_state(self, WORD); start_word(self); write_ch(self, ch); prev_word_ch = ch; break;
                }
                break;
            case WORD:
                switch(ch) {
                    case WHITESPACE: set_state(self, NORMAL); if (self->buf_pos) return get_word(self); break;
                    case STRING_WITH_ESCAPES_DELIM: set_state(self, STRING_WITH_ESCAPES); break;
                    case STRING_WITHOUT_ESCAPES_DELIM:
                        if (self->support_ansi_c_quoting && prev_word_ch == '$') { self->buf_pos--; set_state(self, ANSI_C_QUOTED); }
                        else set_state(self, STRING_WITHOUT_ESCAPES);
                        break;
                    case ESCAPE_CHAR: write_escaped_or_fail(); break;
                    default: write_ch(self, ch); prev_word_ch = ch; break;
                } break;
            case STRING_WITHOUT_ESCAPES:
                switch(ch) {
                    case STRING_WITHOUT_ESCAPES_DELIM: set_state(self, WORD); break;
                    default: write_ch(self, ch); break;
                } break;
            case STRING_WITH_ESCAPES:
                switch(ch) {
                    case STRING_WITH_ESCAPES_DELIM: set_state(self, WORD); break;
                    case ESCAPE_CHAR: write_escaped_or_fail(); break;
                    default: write_ch(self, ch); break;
                } break;
            case ANSI_C_QUOTED:
                switch(ch) {
                    case STRING_WITHOUT_ESCAPES_DELIM: set_state(self, WORD); break;
                    case ESCAPE_CHAR: if (!write_ansi_escape_ch(self)) return NULL; break;
                    default: write_ch(self, ch); break;
                } break;
        }
    }
    switch (self->state) {
        case WORD:
            self->state = NORMAL;
            if (self->buf_pos) return get_word(self);
            break;
        case STRING_WITH_ESCAPES: case STRING_WITHOUT_ESCAPES: case ANSI_C_QUOTED:
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
