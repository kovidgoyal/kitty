/*
 * sprites.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <structmember.h>
extern PyTypeObject Line_Type;
extern PyTypeObject ColorProfile_Type;
extern uint32_t to_color(ColorProfile *, uint32_t, uint32_t);
extern PyObject* line_text_at(char_type, combining_type);

static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    SpriteMap *self;
    unsigned long mlen, msz;
    if (!PyArg_ParseTuple(args, "kk", &msz, &mlen)) return NULL;

    self = (SpriteMap *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->max_array_len = mlen;
        self->max_texture_size = msz;
        self->dirty = true;
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
    self->ynum = 1;

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
    s->rendered = false;
    s->x = self->x; s->y = self->y; s->z = self->z;
    increment(self, error);
    self->dirty = true;
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


bool
update_cell_range_data(SpriteMap *self, Line *line, unsigned int xstart, unsigned int xmax, ColorProfile *color_profile, const uint32_t default_bg, const uint32_t default_fg, unsigned int *data) {
#define update_cell_data_doc "update_cell_data(line, xstart, xmax, color_profile, default_bg, default_fg, data_pointer) -> Update the range [xstart, xmax] in data_pointer with the data from line"
    SpritePosition *sp;
    char_type previous_ch=0, ch;
    color_type color;
    uint32_t bg, fg;
    uint8_t previous_width = 0;
    int err = 0;

    size_t base = line->ynum * line->xnum * 9;
    for (size_t i = xstart, offset = base + xstart * 9; i <= xmax; i++, offset += 9) {
        ch = line->chars[i];
        if (previous_width == 2) sp = sprite_position_for(self, previous_ch, 0, true, &err);
        else sp = sprite_position_for(self, ch, line->combining_chars[i], false, &err);
        if (sp == NULL) { set_sprite_error(err); return false; }
        data[offset] = sp->x;
        data[offset+1] = sp->y;
        data[offset+2] = sp->z;
        color = line->colors[i];
        fg = to_color(color_profile, color & COL_MASK, default_fg);
        bg = to_color(color_profile, color >> COL_SHIFT, default_bg);
        previous_ch = ch; previous_width = (ch >> ATTRS_SHIFT) & WIDTH_MASK;
#define PACK_COL(b, col) data[b] = col >> 16; data[b + 1] = (col >> 8) & 0xff; data[b + 2] = col & 0xff;
        PACK_COL(offset + 3, fg);
        PACK_COL(offset + 6, bg);
    }
    return true;
}

static PyObject*
render_dirty_cells(SpriteMap *self, PyObject *args) {
#define render_dirty_cells_doc "Render all cells that are marked as dirty"
    PyObject *render_cell, *send_to_gpu;

    if (!PyArg_ParseTuple(args, "OO", &render_cell, &send_to_gpu)) return NULL;

    if (!self->dirty) { Py_RETURN_NONE; }

    for (size_t i = 0; i < sizeof(self->cache)/sizeof(self->cache[0]); i++) {
        SpritePosition *sp = &(self->cache[i]);
        while (sp) {
            if (sp->filled && !sp->rendered) {
                PyObject *text = line_text_at(sp->ch & CHAR_MASK, sp->cc);
                if (text == NULL) return NULL;
                char_type attrs = sp->ch >> ATTRS_SHIFT;
                bool bold = (attrs >> BOLD_SHIFT) & 1, italic = (attrs >> ITALIC_SHIFT) & 1;
                PyObject *rcell = PyObject_CallFunctionObjArgs(render_cell, text, bold ? Py_True : Py_False, italic ? Py_True : Py_False, sp->is_second ? Py_True : Py_False, NULL);
                Py_CLEAR(text);
                if (rcell == NULL) return NULL;
                PyObject *ret = PyObject_CallFunction(send_to_gpu, "IIIO", sp->x, sp->y, sp->z, rcell);
                Py_CLEAR(rcell);
                if (ret == NULL) return NULL;
                Py_CLEAR(ret); 
                sp->rendered = true; 
            }
            sp = sp->next;
        }
    }
    self->dirty = false;
    Py_RETURN_NONE;
}

// Boilerplate {{{

static PyMemberDef members[] = {
    {"xnum", T_UINT, offsetof(SpriteMap, xnum), 0, "xnum"},
    {"ynum", T_UINT, offsetof(SpriteMap, ynum), 0, "ynum"},
    {"x", T_UINT, offsetof(SpriteMap, x), 0, "x"},
    {"y", T_UINT, offsetof(SpriteMap, y), 0, "y"},
    {"z", T_UINT, offsetof(SpriteMap, z), 0, "z"},
    {NULL}  /* Sentinel */
};


static PyMethodDef methods[] = {
    METHOD(layout, METH_VARARGS)
    METHOD(position_for, METH_VARARGS)
    METHOD(render_dirty_cells, METH_VARARGS)
    {NULL}  /* Sentinel */
};


PyTypeObject SpriteMap_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.SpriteMap",
    .tp_basicsize = sizeof(SpriteMap),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "SpriteMap",
    .tp_methods = methods,
    .tp_members = members,
    .tp_new = new,                
};

INIT_TYPE(SpriteMap)
// }}}


