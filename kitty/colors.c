/*
 * colors.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

static uint32_t FG_BG_256[256] = {
    0x000000,  // 0
    0xcd0000,  // 1
    0x00cd00,  // 2
    0xcdcd00,  // 3
    0x0000ee,  // 4
    0xcd00cd,  // 5
    0x00cdcd,  // 6
    0xe5e5e5,  // 7
    0x7f7f7f,  // 8
    0xff0000,  // 9
    0x00ff00,  // 10
    0xffff00,  // 11
    0x5c5cff,  // 12
    0xff00ff,  // 13
    0x00ffff,  // 14
    0xffffff,  // 15
};

PyObject* create_256_color_table() {
    // colors 16..232: the 6x6x6 color cube
    const uint8_t valuerange[6] = {0x00, 0x5f, 0x87, 0xaf, 0xd7, 0xff};
    uint8_t i, j=16;
    for(i = 0; i < 217; i++, j++) {
        uint8_t r = valuerange[(i / 36) % 6], g = valuerange[(i / 6) % 6], b = valuerange[i % 6];
        FG_BG_256[j] = (r << 16) | (g << 8) | b;
    }
    // colors 233..255: grayscale
    for(i = 1; i < 24; i++, j++) {
        uint8_t v = 8 + i * 10;
        FG_BG_256[j] = (v << 16) | (v << 8) | v;
    }
    
    PyObject *ans = PyTuple_New(255);
    if (ans == NULL) return PyErr_NoMemory();
    for (i=0; i < 255; i++) {
        PyObject *temp = PyLong_FromUnsignedLong(FG_BG_256[i]);
        if (temp == NULL) { Py_CLEAR(ans); return NULL; }
        PyTuple_SET_ITEM(ans, i, temp);
    }
    return ans;
}

static PyObject *
new(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    ColorProfile *self;

    self = (ColorProfile *)type->tp_alloc(type, 0);
    if (self != NULL) {
        if (FG_BG_256[255] == 0) create_256_color_table();
        memcpy(self->color_table, FG_BG_256, sizeof(FG_BG_256));
        memcpy(self->orig_color_table, FG_BG_256, sizeof(FG_BG_256));
    }
    return (PyObject*) self;
}

static void
dealloc(ColorProfile* self) {
    Py_TYPE(self)->tp_free((PyObject*)self);
}


static PyObject*
update_ansi_color_table(ColorProfile *self, PyObject *val) {
#define update_ansi_color_table_doc "Update the 16 basic colors"
    index_type i;

    if (!PyList_Check(val)) { PyErr_SetString(PyExc_TypeError, "color table must be a list"); return NULL; }
    if (PyList_GET_SIZE(val) != 16) { PyErr_SetString(PyExc_TypeError, "color table must have 16 items"); return NULL; }
    for (i = 0; i < 16; i++) {
        self->color_table[i] = PyLong_AsUnsignedLong(PyList_GET_ITEM(val, i));
        self->orig_color_table[i] = self->color_table[i];
    }
    Py_RETURN_NONE;
}

static PyObject*
as_color(ColorProfile *self, PyObject *val) {
#define as_color_doc "Convert the specified terminal color into an (r, g, b) tuple based on the current profile values"
    if (!PyLong_Check(val)) { PyErr_SetString(PyExc_TypeError, "val must be an int"); return NULL; }
    unsigned long entry = PyLong_AsUnsignedLong(val);
    unsigned int t = entry & 0xFF;
    uint8_t r;
    uint32_t col = 0;
    PyObject *ans = NULL;
    switch(t) {
        case 1:
            r = (entry >> 8) & 0xff;
            col = self->color_table[r];
            break;
        case 2:
            col = entry >> 8;
        default:
            ans = Py_None; Py_INCREF(Py_None);
    }
    if (ans == NULL) ans = Py_BuildValue("BBB", (unsigned char)(col >> 16), (unsigned char)((col >> 8) & 0xFF), (unsigned char)(col & 0xFF)); 
    return ans;
}

static PyObject*
reset_color_table(ColorProfile *self) {
#define reset_color_table_doc "Reset all customized colors back to defaults"
    memcpy(self->color_table, self->orig_color_table, sizeof(FG_BG_256));
    Py_RETURN_NONE;
}

static PyObject*
reset_color(ColorProfile *self, PyObject *val) {
#define reset_color_doc "Reset the specified color"
    uint8_t i = PyLong_AsUnsignedLong(val) & 0xff;
    self->color_table[i] = self->orig_color_table[i];
    Py_RETURN_NONE;
}

static PyObject*
set_color(ColorProfile *self, PyObject *args) {
#define set_color_doc "Set the specified color"
    unsigned char i;
    unsigned long val;
    if (!PyArg_ParseTuple(args, "Bk", &i, &val)) return NULL;
    self->color_table[i] = val;
    Py_RETURN_NONE;
}


uint32_t 
to_color(ColorProfile *self, uint32_t entry, uint32_t defval) {
    unsigned int t = entry & 0xFF, r;
    switch(t) {
        case 1:
            r = (entry >> 8) & 0xff;
            return self->color_table[r];
        case 2:
            return entry >> 8;
        default:
            return defval;
    }
}

// Boilerplate {{{


static PyMethodDef methods[] = {
    METHOD(update_ansi_color_table, METH_O)
    METHOD(reset_color_table, METH_NOARGS)
    METHOD(as_color, METH_O)
    METHOD(reset_color, METH_O)
    METHOD(set_color, METH_VARARGS)
    {NULL}  /* Sentinel */
};


PyTypeObject ColorProfile_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.ColorProfile",
    .tp_basicsize = sizeof(ColorProfile),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "ColorProfile",
    .tp_methods = methods,
    .tp_new = new,                
};

INIT_TYPE(ColorProfile)
// }}}
