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

#define EQ(x) (a->x == b->x)
#define PEQ(x) (PyObject_RichCompareBool(a->x, b->x, Py_EQ) == 1)
int is_eq(Cursor *a, Cursor *b) {
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

// Boilerplate {{{

static PyMemberDef Cursor_members[] = {
    {"x", T_OBJECT_EX, offsetof(Cursor, x), 0, "x"},
    {"y", T_OBJECT_EX, offsetof(Cursor, y), 0, "y"},
    {"shape", T_OBJECT_EX, offsetof(Cursor, shape), 0, "shape"},
    {"blink", T_OBJECT_EX, offsetof(Cursor, blink), 0, "blink"},
    {"color", T_OBJECT_EX, offsetof(Cursor, color), 0, "color"},
    {"hidden", T_OBJECT_EX, offsetof(Cursor, hidden), 0, "hidden"},

    {"bold", T_UBYTE, offsetof(Cursor, bold), 0, "bold"},
    {"italic", T_UBYTE, offsetof(Cursor, italic), 0, "italic"},
    {"strikethrough", T_UBYTE, offsetof(Cursor, strikethrough), 0, "strikethrough"},
    {"reverse", T_UBYTE, offsetof(Cursor, reverse), 0, "reverse"},
    {"decoration", T_UBYTE, offsetof(Cursor, decoration), 0, "decoration"},
    {"fg", T_UINT, offsetof(Cursor, fg), 0, "fg"},
    {"bg", T_UINT, offsetof(Cursor, bg), 0, "bg"},
    {"decoration_fg", T_UINT, offsetof(Cursor, decoration_fg), 0, "decoration_fg"},
    {NULL}  /* Sentinel */
};

static PyMethodDef Cursor_methods[] = {
    {NULL}  /* Sentinel */
};


static PyObject *
richcmp(PyObject *obj1, PyObject *obj2, int op);

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
    (reprfunc)repr,            /* tp_repr */
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
    richcmp,                   /* tp_richcompare */
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


// }}}
 
static PyObject *
richcmp(PyObject *obj1, PyObject *obj2, int op)
{
    PyObject *result = NULL;
    int eq;

    if (op != Py_EQ || op != Py_NE) { Py_RETURN_NOTIMPLEMENTED; }
    if (!PyObject_TypeCheck(obj1, &Cursor_Type)) { Py_RETURN_FALSE; }
    if (!PyObject_TypeCheck(obj2, &Cursor_Type)) { Py_RETURN_FALSE; }
    eq = is_eq((Cursor*)obj1, (Cursor*)obj2);
    if (op == Py_NE) result = eq ? Py_False : Py_True;
    else result = eq ? Py_True : Py_False;
    Py_INCREF(result);
    return result;
}
