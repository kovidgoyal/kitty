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
new(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    Cursor *self;

    self = (Cursor *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->x = PyLong_FromLong(0);
        if (self->x == NULL) { Py_CLEAR(self); return NULL; }
        self->y = self->x; Py_INCREF(self->y);
        INIT_NONE(self->shape);
        INIT_NONE(self->blink);
        INIT_NONE(self->color);
        self->hidden = Py_False; Py_INCREF(Py_False);
        self->bold = 0; self->italic = 0; self->reverse = 0; self->strikethrough = 0; self->decoration = 0;
        self->fg = 0; self->bg = 0; self->decoration_fg = 0;
    }
    return (PyObject*) self;
}

static void
dealloc(Cursor* self) {
    Py_CLEAR(self->shape);
    Py_CLEAR(self->blink);
    Py_CLEAR(self->color);
    Py_CLEAR(self->hidden);
    Py_CLEAR(self->x);
    Py_CLEAR(self->y);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

#define EQ(x) (a->x == b->x)
#define PEQ(x) (PyObject_RichCompareBool(a->x, b->x, Py_EQ) == 1)
static int __eq__(Cursor *a, Cursor *b) {
    return EQ(bold) && EQ(italic) && EQ(strikethrough) && EQ(reverse) && EQ(decoration) && EQ(fg) && EQ(bg) && EQ(decoration_fg) && PEQ(x) && PEQ(y) && PEQ(shape) && PEQ(blink) && PEQ(color) && PEQ(hidden);
}

#define BOOL(x) ((x) ? Py_True : Py_False)
static PyObject *
repr(Cursor *self) {
    return PyUnicode_FromFormat(
        "Cursor(x=%R, y=%R, shape=%R, blink=%R, hidden=%R, color=%R, fg=#%08x, bg=#%08x, bold=%R, italic=%R, reverse=%R, strikethrough=%R, decoration=%d, decoration_fg=#%08x)",
        self->x, self->y, self->shape, self->blink, self->hidden, self->color, self->fg, self->bg, BOOL(self->bold), BOOL(self->italic), BOOL(self->reverse), BOOL(self->strikethrough), self->decoration, self->decoration_fg
    );
}

static PyObject*
copy(Cursor *self, PyObject *args);
#define copy_doc "Create a clone of this cursor"

// Boilerplate {{{

BOOL_GETSET(Cursor, bold)
BOOL_GETSET(Cursor, italic)
BOOL_GETSET(Cursor, reverse)
BOOL_GETSET(Cursor, strikethrough)

static PyMemberDef members[] = {
    {"x", T_OBJECT_EX, offsetof(Cursor, x), 0, "x"},
    {"y", T_OBJECT_EX, offsetof(Cursor, y), 0, "y"},
    {"shape", T_OBJECT_EX, offsetof(Cursor, shape), 0, "shape"},
    {"blink", T_OBJECT_EX, offsetof(Cursor, blink), 0, "blink"},
    {"color", T_OBJECT_EX, offsetof(Cursor, color), 0, "color"},
    {"hidden", T_OBJECT_EX, offsetof(Cursor, hidden), 0, "hidden"},

    {"decoration", T_UBYTE, offsetof(Cursor, decoration), 0, "decoration"},
    {"fg", T_UINT, offsetof(Cursor, fg), 0, "fg"},
    {"bg", T_UINT, offsetof(Cursor, bg), 0, "bg"},
    {"decoration_fg", T_UINT, offsetof(Cursor, decoration_fg), 0, "decoration_fg"},
    {NULL}  /* Sentinel */
};

static PyGetSetDef getseters[] = {
    GETSET(bold)
    GETSET(italic)
    GETSET(reverse)
    GETSET(strikethrough)
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
    METHOD(copy, METH_NOARGS)
    {NULL}  /* Sentinel */
};


static PyObject *
richcmp(PyObject *obj1, PyObject *obj2, int op);

PyTypeObject Cursor_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Cursor",
    .tp_basicsize = sizeof(Cursor),
    .tp_dealloc = (destructor)dealloc, 
    .tp_repr = (reprfunc)repr,
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "Cursors",
    .tp_richcompare = richcmp,                   
    .tp_methods = methods,
    .tp_members = members,            
    .tp_getset = getseters,
    .tp_new = new,                
};

RICHCMP(Cursor)

// }}}
 
static PyObject*
copy(Cursor *self, PyObject UNUSED *args) {
#define CPY(x) ans->x = self->x; Py_XINCREF(self->x);
#define CCY(x) ans->x = self->x;
    Cursor* ans;
    ans = alloc_cursor();
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    CPY(x); CPY(y); CPY(shape); CPY(blink); CPY(color); CPY(hidden);
    CCY(bold); CCY(italic); CCY(strikethrough); CCY(reverse); CCY(decoration); CCY(fg); CCY(bg); CCY(decoration_fg); 
    return (PyObject*)ans;
}

Cursor *alloc_cursor() {
    return (Cursor*)new(&Cursor_Type, NULL, NULL);
}

INIT_TYPE(Cursor)
