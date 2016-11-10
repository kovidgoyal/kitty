/*
 * sprites.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    SpriteMap *self;
    unsigned long mlen, msz;
    if (!PyArg_ParseTuple(args, "kk", &msz, &mlen)) return NULL;

    self = (SpriteMap *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->max_array_len = mlen;
        self->max_texture_size = msz;
    }
    return (PyObject*) self;
}

static void
dealloc(SpriteMap* self) {
    SpritePosition *s, *t;
    for (size_t i = 0; i < sizeof(self->cache)/sizeof(self->cache[0]); i++) {
        s = &(self->cache[i]);
        s = s->next;
        while (s) {
            t = s;
            s = s->next;
            PyMem_Free(t);
        }
    }
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
layout(SpriteMap *self, PyObject *args) {
#define layout_doc "layout(cell_width, cell_height) -> Invalidate the cache and prepare it for new cell size"
    unsigned long cell_width, cell_height;
    if (!PyArg_ParseTuple(args, "kk", &cell_width, &cell_height)) return NULL;
    self->xnum = MAX(1, self->max_texture_size / cell_width);
    self->max_y = MAX(1, self->max_texture_size / cell_height);

    for (size_t i = 0; i < sizeof(self->cache)/sizeof(self->cache[0]); i++) {
        SpritePosition *s = &(self->cache[i]);
        do {
            s->filled = false;
            s->is_second = false;
            s->rendered = false;
            s->ch = 0; s->cc = 0;
            s->x = 0; s->y = 0; s->z = 0;
            s = s->next;
        } while (s != NULL);
    }
    Py_RETURN_NONE;
}

static void
increment(SpriteMap *self, int *error) {
    self->x++;
    if (self->x >= self->xnum) {
        self->x = 0; self->y++;
        self->ynum = MIN(MAX(self->ynum, self->y + 1), self->max_y);
        if (self->y >= self->max_y) {
            self->y = 0; self->z++;
            if (self->z >= self->max_array_len) *error = 2;
        }
    }
}

static SpritePosition*
sprite_position_for(SpriteMap *self, char_type ch, combining_type cc, bool is_second, int *error) {
    char_type attrs = ch >> ATTRS_SHIFT, pos_char;
    uint8_t bold = (attrs >> BOLD_SHIFT) & 1, italic = (attrs >> ITALIC_SHIFT) & 1;
    size_t idx = (ch & 0xff) | (bold << 8) | (italic << 9);
    attrs = bold << BOLD_SHIFT | italic << ITALIC_SHIFT;
    pos_char = (ch & CHAR_MASK) | (attrs << ATTRS_SHIFT);
    SpritePosition *s = &(self->cache[idx]);
    while(true) {
        if (s->filled) {
            if (s->ch == pos_char && s->cc == cc && s->is_second == is_second) return s;  // Cache hit
        } else {
            break;
        }
        if (!s->next) {
            s->next = PyMem_Calloc(1, sizeof(SpritePosition));
            if (s->next == NULL) { *error = 1; return NULL; }
        }
        s = s->next;
    }
    s->ch = pos_char;
    s->cc = cc;
    s->is_second = is_second;
    s->filled = true;
    s->x = self->x; s->y = self->y; s->z = self->z;
    increment(self, error);
    return s;
}

static void set_sprite_error(int error) {
    switch(error) {
        case 1:
            PyErr_NoMemory(); break;
        case 2:
            PyErr_SetString(PyExc_RuntimeError, "Out of texture space for sprites"); break;
        default:
            PyErr_SetString(PyExc_RuntimeError, "Unknown error occurred while allocating sprites"); break;
    }
}

static PyObject*
position_for(SpriteMap *self, PyObject *args) {
#define position_for_doc "position_for(ch, cc, is_second) -> x, y, z the sprite position for the specified text"
    unsigned long ch = 0;
    unsigned long long cc = 0;
    int is_second = 0, error = 0;
    if (!PyArg_ParseTuple(args, "|kKp", &ch, &cc, &is_second)) return NULL;
    SpritePosition *pos = sprite_position_for(self, ch, cc, is_second, &error);
    if (pos == NULL) {set_sprite_error(error); return NULL; }
    return Py_BuildValue("III", pos->x, pos->y, pos->z);
}
// Boilerplate {{{


static PyMethodDef methods[] = {
    METHOD(layout, METH_VARARGS)
    METHOD(position_for, METH_VARARGS)
    {NULL}  /* Sentinel */
};


static PyTypeObject SpriteMap_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.SpriteMap",
    .tp_basicsize = sizeof(SpriteMap),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "SpriteMap",
    .tp_methods = methods,
    .tp_new = new,                
};

INIT_TYPE(SpriteMap)
// }}}


