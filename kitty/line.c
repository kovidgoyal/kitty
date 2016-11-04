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

static PyObject*
text_at(Line* self, Py_ssize_t xval) {
#define text_at_doc "[x] -> Return the text in the specified cell"
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

static PyObject*
apply_cursor(Line* self, PyObject *args) {
#define apply_cursor_doc "apply_cursor(cursor, at=0, num=1, clear_char=False) -> Apply the formatting attributes from cursor to the specified characters in this line."
    Cursor* cursor;
    unsigned int at=0, num=1;
    int clear_char = 0;
    if (!PyArg_ParseTuple(args, "O!|IIp", &Cursor_Type, &cursor, &at, &num, &clear_char)) return NULL;
    char_type attrs = CURSOR_TO_ATTRS(cursor, 1);
    color_type col = (cursor->fg & COL_MASK) | ((color_type)(cursor->bg & COL_MASK) << COL_SHIFT);
    decoration_type dfg = cursor->decoration_fg & COL_MASK;
    
    for (index_type i = at; i < self->xnum && i < at + num; i++) {
        if (clear_char) {
            self->chars[i] = 32 | attrs;
            self->combining_chars[i] = 0;
        } else self->chars[i] = (self->chars[i] & CHAR_MASK) | attrs;
        self->colors[i] = col;
        self->decoration_fg[i] = dfg;
    }

    Py_RETURN_NONE;
}

#define COPY_SELF_CELL(s, d) COPY_CELL(self, s, self, d)

static PyObject*
right_shift(Line *self, PyObject *args) {
#define right_shift_doc "right_shift(at, num) -> ..."
    unsigned int at, num;
    if (!PyArg_ParseTuple(args, "II", &at, &num)) return NULL;
    if (at >= self->xnum || at + num > self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds");
        return NULL;
    }
    if (num > 0) {
        for(index_type i = self->xnum - 1; i >= at + num; i--) {
            COPY_SELF_CELL(i - num, i)
        }
        // Check if a wide character was split at the right edge
        char_type w = (self->chars[self->xnum - 1] >> ATTRS_SHIFT) & 3;
        if (w != 1) self->chars[self->xnum - 1] = (1 << ATTRS_SHIFT) | 32;
    }
    Py_RETURN_NONE;
}

static PyObject*
left_shift(Line *self, PyObject *args) {
#define left_shift_doc "left_shift(at, num) -> ..."
    unsigned int at, num;
    if (!PyArg_ParseTuple(args, "II", &at, &num)) return NULL;
    if (at >= self->xnum || at + num > self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds");
        return NULL;
    }
    if (num > 0) {
        for(index_type i = at; i < self->xnum - num; i++) {
            COPY_SELF_CELL(i + num, i)
        }
        // Check if a wide character was split at the left edge
        char_type w = (self->chars[at] >> ATTRS_SHIFT) & 3;
        if (w != 1) self->chars[at] = (1 << ATTRS_SHIFT) | 32;
    }
    Py_RETURN_NONE;
}
 
static PyObject*
set_char(Line *self, PyObject *args) {
#define set_char_doc "set_char(at, ch, width=1, cursor=None) -> Set the character at the specified cell. If cursor is not None, also set attributes from that cursor."
    unsigned int at, width=1;
    int ch;
    Cursor *cursor = NULL;
    char_type attrs;

    if (!PyArg_ParseTuple(args, "IC|IO!", &at, &ch, &width, &Cursor_Type, &cursor)) return NULL;
    if (at >= self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds");
        return NULL;
    }

    if (cursor == NULL) {
        attrs = (((self->chars[at] >> ATTRS_SHIFT) & ~3) | (width & 3)) << ATTRS_SHIFT;
    } else {
        attrs = CURSOR_TO_ATTRS(cursor, width & 3);
        self->colors[at] = (cursor->fg & COL_MASK) | ((color_type)(cursor->bg & COL_MASK) << COL_SHIFT);
        self->decoration_fg[at] = cursor->decoration_fg & COL_MASK;
    }
    self->chars[at] = (ch & CHAR_MASK) | attrs;
    self->combining_chars[at] = 0;
    Py_RETURN_NONE;
}

static PyObject*
set_attribute(Line *self, PyObject *args) {
#define set_attribute_doc "set_attribute(which, val) -> Set the attribute on all cells in the line."
    unsigned int shift, val;
    char_type mask;
    if (!PyArg_ParseTuple(args, "II", &shift, &val)) return NULL;
    if (shift < DECORATION_SHIFT || shift > STRIKE_SHIFT) { PyErr_SetString(PyExc_ValueError, "Unknown attribute"); return NULL; }
    SET_ATTRIBUTE(self->chars, shift, val);
    Py_RETURN_NONE;
}

static Py_ssize_t
__len__(PyObject *self) {
    return (Py_ssize_t)(((Line*)self)->ynum);
}

static int __eq__(Line *a, Line *b) {
    return a->xnum == b->xnum && \
                    memcmp(a->chars, b->chars, sizeof(char_type) * a->xnum) == 0 && \
                    memcmp(a->colors, b->colors, sizeof(color_type) * a->xnum) == 0 && \
                    memcmp(a->decoration_fg, b->decoration_fg, sizeof(decoration_type) * a->xnum) == 0 && \
                    memcmp(a->combining_chars, b->combining_chars, sizeof(combining_type) * a->xnum) == 0;
}

// Boilerplate {{{
static PyObject*
copy_char(Line* self, PyObject *args);
#define copy_char_doc "copy_char(src, to, dest) -> Copy the character at src to to the character dest in the line `to`"

static PyObject *
richcmp(PyObject *obj1, PyObject *obj2, int op);


static PySequenceMethods sequence_methods = {
    .sq_length = __len__,                  
    .sq_item = (ssizeargfunc)text_at
};

static PyMethodDef methods[] = {
    METHOD(add_combining_char, METH_VARARGS)
    METHOD(set_text, METH_VARARGS)
    METHOD(cursor_from, METH_VARARGS)
    METHOD(apply_cursor, METH_VARARGS)
    METHOD(copy_char, METH_VARARGS)
    METHOD(right_shift, METH_VARARGS)
    METHOD(left_shift, METH_VARARGS)
    METHOD(set_char, METH_VARARGS)
    METHOD(set_attribute, METH_VARARGS)
        
    {NULL}  /* Sentinel */
};

static PyTypeObject Line_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Line",
    .tp_basicsize = sizeof(Line),
    .tp_dealloc = (destructor)dealloc,
    .tp_repr = (reprfunc)as_unicode,
    .tp_as_sequence = &sequence_methods,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_richcompare = richcmp,                   
    .tp_doc = "Lines",
    .tp_methods = methods,
    .tp_new = new
};

Line *alloc_line() {
    return (Line*)PyType_GenericAlloc(&Line_Type, 0);
}

RICHCMP(Line)
// }}
 
static PyObject*
copy_char(Line* self, PyObject *args) {
    unsigned int src, dest;
    Line *to;
    if (!PyArg_ParseTuple(args, "IO!I", &src, &Line_Type, &to, &dest)) return NULL;
    if (src >= self->xnum || dest >= to->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds");
        return NULL;
    }
    to->chars[dest] = self->chars[src];
    to->colors[dest] = self->colors[src];
    to->decoration_fg[dest] = self->decoration_fg[src];
    to->combining_chars[dest] = self->combining_chars[src];
    Py_RETURN_NONE;
}

INIT_TYPE(Line)
