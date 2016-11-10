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
        memcpy(self->color_table_256, FG_BG_256, sizeof(FG_BG_256));
    }
    return (PyObject*) self;
}

static void
dealloc(Cursor* self) {
    Py_TYPE(self)->tp_free((PyObject*)self);
}


static PyObject*
update_ansi_color_table(ColorProfile *self, PyObject *val) {
#define update_ansi_color_table_doc "Update the 16 basic colors"
    index_type i;
    PyObject *t;

    if (!PyList_Check(val)) { PyErr_SetString(PyExc_TypeError, "color table must be a list"); return NULL; }

#define TO_COLOR \
    t = PyList_GET_ITEM(val, i); \
    self->ansi_color_table[i] = PyLong_AsUnsignedLong(t);

    for(i = 30; i < 38; i++) {
        TO_COLOR;
    }
    i = 39; TO_COLOR;
    for(i = 90; i < 98; i++) {
        TO_COLOR;
    }
    i = 99; TO_COLOR;
    for(i = 40; i < 48; i++) {
        TO_COLOR;
    }
    i = 49; TO_COLOR;
    for(i = 100; i < 108; i++) {
        TO_COLOR;
    }
    Py_RETURN_NONE;
}

static PyObject*
ansi_color(ColorProfile *self, PyObject *val) {
#define ansi_color_doc "Return the color at the specified index"
    if (!PyLong_Check(val)) { PyErr_SetString(PyExc_TypeError, "index must be an int"); return NULL; }
    unsigned long idx = PyLong_AsUnsignedLong(val);
    if (idx >= sizeof(self->ansi_color_table) / sizeof(self->ansi_color_table[0])) {
        PyErr_SetString(PyExc_IndexError, "Out of bounds"); return NULL;
    }
    return PyLong_FromUnsignedLong(self->ansi_color_table[idx]);
}

static PyObject*
color_256(ColorProfile *self, PyObject *val) {
#define color_256_doc "Return the color at the specified 256-color index"
    if (!PyLong_Check(val)) { PyErr_SetString(PyExc_TypeError, "index must be an int"); return NULL; }
    unsigned long idx = PyLong_AsUnsignedLong(val);
    if (idx >= 256) {
        PyErr_SetString(PyExc_IndexError, "Out of bounds"); return NULL;
    }
    return PyLong_FromUnsignedLong(self->color_table_256[idx]);
}

static PyObject*
as_color(ColorProfile *self, PyObject *val) {
#define as_color_doc "Convert the specified terminal color into an (r, g, b) tuple based on the current profile values"
    if (!PyLong_Check(val)) { PyErr_SetString(PyExc_TypeError, "val must be an int"); return NULL; }
    unsigned long entry = PyLong_AsUnsignedLong(val);
    unsigned int t = entry & 0xFF;
    uint8_t r, g, b;
    uint32_t col = 0;
    PyObject *ans = NULL;
    switch(t) {
        case 1:
            r = (entry >> 8) & 0xff;
            col = self->ansi_color_table[r];
            break;
        case 2:
            r = (entry >> 8) & 0xff;
            col = self->color_table_256[r];
            break;
        case 3:
            r = (entry >> 8) & 0xff;
            g = (entry >> 16) & 0xff;
            b = (entry >> 24) & 0xff;
            ans = Py_BuildValue("BBB", r, g, b);
            break;
        default:
            ans = Py_None; Py_INCREF(Py_None);
    }
    if (ans == NULL) ans = Py_BuildValue("BBB", (unsigned char)(col >> 16), (unsigned char)((col >> 8) & 0xFF), (unsigned char)(col & 0xFF)); 
    return ans;
}

uint32_t to_color(ColorProfile *self, uint32_t entry, uint32_t defval) {
    unsigned int t = entry & 0xFF, r;
    switch(t) {
        case 1:
            r = (entry >> 8) & 0xff;
            return self->ansi_color_table[r];
        case 2:
            r = (entry >> 8) & 0xff;
            return self->color_table_256[r];
        case 3:
            return entry >> 8;
        default:
            return defval;
    }
}

// Boilerplate {{{


static PyMethodDef methods[] = {
    METHOD(update_ansi_color_table, METH_O)
    METHOD(ansi_color, METH_O)
    METHOD(color_256, METH_O)
    METHOD(as_color, METH_O)
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
