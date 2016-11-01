/*
 * line.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
extern PyTypeObject Cursor_Type;

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
#define text_at_doc "text_at(x) -> Return the text in the specified cell"
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
        Py_UCS4 cc1 = cc & CC_MASK, cc2 = cc >> 16;
        Py_UCS4 maxc = (ch > cc1) ? MAX(ch, cc2) : MAX(cc1, cc2);
        ans = PyUnicode_New(cc2 ? 3 : 2, maxc);
        if (ans == NULL) return PyErr_NoMemory();
        PyUnicode_WriteChar(ans, 0, ch);
        PyUnicode_WriteChar(ans, 1, cc1);
        if (cc2) PyUnicode_WriteChar(ans, 2, cc2);
    }

    return ans;
}

static PyObject *
as_unicode(Line* self) {
    Py_ssize_t n = 0;
    Py_UCS4 *buf = PyMem_Malloc(3 * self->xnum * sizeof(Py_UCS4));
    if (buf == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    for(index_type i = 0; i < self->xnum; i++) {
        char_type ch = self->chars[i] & CHAR_MASK;
        char_type cc = self->combining_chars[i];
        buf[n++] = ch & CHAR_MASK;
        Py_UCS4 cc1 = cc & CC_MASK, cc2;
        if (cc1) {
            buf[n++] = cc1;
            cc2 = cc >> 16;
            if (cc2) buf[n++] = cc2;
        }
    }
    PyObject *ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buf, n);
    PyMem_Free(buf);
    return ans;
}

static PyObject*
add_combining_char(Line* self, PyObject *args) {
#define add_combining_char_doc "add_combining_char(x, ch) -> Add the specified character as a combining char to the specified cell."
    int new_char;
    unsigned int x;
    if (!PyArg_ParseTuple(args, "IC", &x, &new_char)) return NULL;
    if (x >= self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Column index out of bounds");
        return NULL;
    }
    combining_type c = self->combining_chars[x];
    if (c & CC_MASK) self->combining_chars[x] = (c & CC_MASK) | ( (new_char & CC_MASK) << CC_SHIFT );
    else self->combining_chars[x] = new_char & CC_MASK;
    Py_RETURN_NONE;
}


static PyObject*
set_text(Line* self, PyObject *args) {
#define set_text_doc "set_text(src, offset, sz, cursor) -> Set the characters and attributes from the specified text and cursor"
    PyObject *src;
    Py_ssize_t offset, sz, limit;
    char_type attrs;
    Cursor *cursor;
    int kind;
    void *buf;
    unsigned long x;

    if (!PyArg_ParseTuple(args, "UnnO!", &src, &offset, &sz, &Cursor_Type, &cursor)) return NULL;
    if (PyUnicode_READY(src) != 0) {
        PyErr_NoMemory();
        return NULL;
    }
    kind = PyUnicode_KIND(src);
    buf = PyUnicode_DATA(src);
    limit = offset + sz;
    if (PyUnicode_GET_LENGTH(src) < limit) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds offset/sz");
        return NULL;
    }
    x = PyLong_AsUnsignedLong(cursor->x);
    attrs = CURSOR_TO_ATTRS(cursor, 1);
    color_type col = (cursor->fg & COL_MASK) | ((color_type)(cursor->bg & COL_MASK) << COL_SHIFT);
    decoration_type dfg = cursor->decoration_fg & COL_MASK;

    for (index_type i = x; offset < limit && i < self->xnum; i++, offset++) {
        self->chars[i] = (PyUnicode_READ(kind, buf, offset) & CHAR_MASK) | attrs;
        self->colors[i] = col;
        self->decoration_fg[i] = dfg;
        self->combining_chars[i] = 0;
    }

    Py_RETURN_NONE;
}

static PyObject*
cursor_from(Line* self, PyObject *args) {
#define cursor_from_doc "cursor_from(x, y=0) -> Create a cursor object based on the formatting attributes at the specified x position. The y value of the cursor is set as specified."
    unsigned long x, y = 0;
    PyObject *xo, *yo;
    Cursor* ans;
    if (!PyArg_ParseTuple(args, "k|k", &x, &y)) return NULL;
    if (x >= self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds x");
        return NULL;
    }
    ans = PyObject_New(Cursor, &Cursor_Type);
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    xo = PyLong_FromUnsignedLong(x); yo = PyLong_FromUnsignedLong(y);
    if (xo == NULL || yo == NULL) {
        Py_DECREF(ans); Py_XDECREF(xo); Py_XDECREF(yo);
        PyErr_NoMemory(); return NULL;
    }
    Py_XDECREF(ans->x); Py_XDECREF(ans->y);
    ans->x = xo; ans->y = yo;
    char_type attrs = self->chars[x] >> ATTRS_SHIFT;
    ATTRS_TO_CURSOR(attrs, ans);
    COLORS_TO_CURSOR(self->colors[x], ans);
    ans->decoration_fg = self->decoration_fg[x] & COL_MASK;

    return (PyObject*)ans;
}

// Boilerplate {{{
static PyMethodDef methods[] = {
    METHOD(text_at, METH_O)
    METHOD(add_combining_char, METH_VARARGS)
    METHOD(set_text, METH_VARARGS)
    METHOD(cursor_from, METH_VARARGS)
        
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
    (reprfunc)as_unicode,      /* tp_repr */
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

