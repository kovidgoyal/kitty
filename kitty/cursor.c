/*
 * cursor.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

#include <structmember.h>

static PyObject *
new(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    Cursor *self;

    self = (Cursor *)type->tp_alloc(type, 0);
    return (PyObject*) self;
}

static void
dealloc(Cursor* self) {
    Py_TYPE(self)->tp_free((PyObject*)self);
}

#define EQ(x) (a->x == b->x)
static int __eq__(Cursor *a, Cursor *b) {
    return EQ(bold) && EQ(italic) && EQ(strikethrough) && EQ(reverse) && EQ(decoration) && EQ(fg) && EQ(bg) && EQ(decoration_fg) && EQ(x) && EQ(y) && EQ(shape) && EQ(blink) && EQ(color) && EQ(hidden);
}

#define BOOL(x) ((x) ? Py_True : Py_False)
static PyObject *
repr(Cursor *self) {
    return PyUnicode_FromFormat(
        "Cursor(x=%u, y=%u, shape=%d, blink=%R, hidden=%R, color=#%08x, fg=#%08x, bg=#%08x, bold=%R, italic=%R, reverse=%R, strikethrough=%R, decoration=%d, decoration_fg=#%08x)",
        self->x, self->y, self->shape, BOOL(self->blink), BOOL(self->hidden), self->color, self->fg, self->bg, BOOL(self->bold), BOOL(self->italic), BOOL(self->reverse), BOOL(self->strikethrough), self->decoration, self->decoration_fg
    );
}

void cursor_reset_display_attrs(Cursor *self) {
    self->bg = 0; self->fg = 0; self->decoration_fg = 0;
    self->decoration = 0; self->bold = false; self->italic = false; self->reverse = false; self->strikethrough = false;
}

static PyObject *
reset_display_attrs(Cursor *self) {
#define reset_display_attrs_doc "Reset all display attributes to unset"
    cursor_reset_display_attrs(self);
    Py_RETURN_NONE;
}

void cursor_reset(Cursor *self) {
    cursor_reset_display_attrs(self);
    self->x = 0; self->y = 0;
    self->shape = 0; self->blink = false;
    self->color = 0; self->hidden = false;
}

void cursor_copy_to(Cursor *src, Cursor *dest) {
#define CCY(x) dest->x = src->x;
    CCY(x); CCY(y); CCY(shape); CCY(blink); CCY(color); CCY(hidden);
    CCY(bold); CCY(italic); CCY(strikethrough); CCY(reverse); CCY(decoration); CCY(fg); CCY(bg); CCY(decoration_fg); 
}

static PyObject*
copy(Cursor *self);
#define copy_doc "Create a clone of this cursor"

static PyObject* color_get(Cursor *self, void UNUSED *closure) { 
    if (!(self->color & 0xFF)) { Py_RETURN_NONE; }
    return Py_BuildValue("BBB", (self->color >> 24) & 0xFF, (self->color >> 16) & 0xFF, (self->color >> 8) & 0xFF);
}

// Boilerplate {{{

BOOL_GETSET(Cursor, bold)
BOOL_GETSET(Cursor, italic)
BOOL_GETSET(Cursor, reverse)
BOOL_GETSET(Cursor, strikethrough)
BOOL_GETSET(Cursor, hidden)
BOOL_GETSET(Cursor, blink)

static PyMemberDef members[] = {
    {"x", T_UINT, offsetof(Cursor, x), 0, "x"},
    {"y", T_UINT, offsetof(Cursor, y), 0, "y"},
    {"shape", T_UBYTE, offsetof(Cursor, shape), 0, "shape"},
    {"color", T_ULONG, offsetof(Cursor, color), 0, "color"},
    {"decoration", T_UBYTE, offsetof(Cursor, decoration), 0, "decoration"},
    {"fg", T_ULONG, offsetof(Cursor, fg), 0, "fg"},
    {"bg", T_ULONG, offsetof(Cursor, bg), 0, "bg"},
    {"decoration_fg", T_ULONG, offsetof(Cursor, decoration_fg), 0, "decoration_fg"},
    {NULL}  /* Sentinel */
};

static PyGetSetDef getseters[] = {
    GETSET(bold)
    GETSET(italic)
    GETSET(reverse)
    GETSET(strikethrough)
    GETSET(hidden)
    GETSET(blink)
    {"color", (getter) color_get, NULL, "color", NULL},
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
    METHOD(copy, METH_NOARGS)
    METHOD(reset_display_attrs, METH_NOARGS)
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
 
Cursor*
cursor_copy(Cursor *self) {
    Cursor* ans;
    ans = alloc_cursor();
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    cursor_copy_to(self, ans);
    return ans;
}

static PyObject*
copy(Cursor *self) {
    return (PyObject*)cursor_copy(self);
}

Cursor *alloc_cursor() {
    return (Cursor*)new(&Cursor_Type, NULL, NULL);
}

INIT_TYPE(Cursor)
