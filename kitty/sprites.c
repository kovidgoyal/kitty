/*
 * sprites.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "lineops.h"
#include <structmember.h>

typedef struct SpritePosition SpritePosition;
struct SpritePosition {
    SpritePosition *next;
    sprite_index x, y, z;
    char_type ch;
    combining_type cc;
    bool bold, italic;
    bool is_second;
    bool filled;
    bool rendered;
};

typedef struct {
    size_t max_array_len, max_texture_size, max_y;
    unsigned int x, y, z, xnum, ynum;
    SpritePosition cache[1024];
    bool dirty;
} SpriteMap;

static SpriteMap sprite_map = {
    .max_array_len = 1000,
    .max_texture_size = 1000,
    .max_y = 100,
    .dirty = true
};

static inline void 
sprite_map_set_error(int error) {
    switch(error) {
        case 1:
            PyErr_NoMemory(); break;
        case 2:
            PyErr_SetString(PyExc_RuntimeError, "Out of texture space for sprites"); break;
        default:
            PyErr_SetString(PyExc_RuntimeError, "Unknown error occurred while allocating sprites"); break;
    }
}

void
sprite_map_set_limits(size_t max_texture_size, size_t max_array_len) {
    sprite_map.max_texture_size = max_texture_size;
    sprite_map.max_array_len = max_array_len;
}

static PyObject*
sprite_map_set_limits_py(PyObject UNUSED *self, PyObject *args) {
    unsigned int w, h;
    if(!PyArg_ParseTuple(args, "II", &w, &h)) return NULL;
    sprite_map_set_limits(w, h);
    Py_RETURN_NONE;
}

void
sprite_map_free() {
    SpritePosition *s, *t;
    for (size_t i = 0; i < sizeof(sprite_map.cache)/sizeof(sprite_map.cache[0]); i++) {
        s = &(sprite_map.cache[i]);
        s = s->next;
        while (s) {
            t = s;
            s = s->next;
            PyMem_Free(t);
        }
    }
}

static inline void
do_increment(int *error) {
    sprite_map.x++;
    if (sprite_map.x >= sprite_map.xnum) {
        sprite_map.x = 0; sprite_map.y++;
        sprite_map.ynum = MIN(MAX(sprite_map.ynum, sprite_map.y + 1), sprite_map.max_y);
        if (sprite_map.y >= sprite_map.max_y) {
            sprite_map.y = 0; sprite_map.z++;
            if (sprite_map.z >= MIN(UINT16_MAX, sprite_map.max_array_len)) *error = 2;
        }
    }
}

SpritePosition*
sprite_map_position_for(char_type ch, attrs_type attrs, combining_type cc, bool is_second, int *error) {
    uint8_t bold_italic = (attrs >> BOLD_SHIFT) & 3;
    unsigned int idx = (ch & 0xFF) | (bold_italic << 8); // Only bold italic bits and lowest byte of char
    SpritePosition *s = &(sprite_map.cache[idx]);
    // Optimize for the common case of an ASCII char already in the cache
    if (LIKELY(s->ch == ch && s->filled && s->cc == cc && s->is_second == is_second)) return s;  // Cache hit
    while(true) {
        if (s->filled) {
            if (s->ch == ch && s->cc == cc && s->is_second == is_second) return s;  // Cache hit
        } else {
            break;
        }
        if (!s->next) {
            s->next = PyMem_Calloc(1, sizeof(SpritePosition));
            if (s->next == NULL) { *error = 1; return NULL; }
        }
        s = s->next;
    }
    s->ch = ch;
    s->cc = cc;
    s->is_second = is_second;
    s->filled = true;
    s->rendered = false;
    s->bold = bold_italic & 1;
    s->italic = bold_italic >> 1;
    s->x = sprite_map.x; s->y = sprite_map.y; s->z = sprite_map.z;
    do_increment(error);
    sprite_map.dirty = true;
    return s;
}


void
set_sprite_position(Cell *cell, Cell *previous_cell) {
    SpritePosition *sp;
    static int error;
    if (UNLIKELY(previous_cell != NULL && ((previous_cell->attrs) & WIDTH_MASK) == 2)) {
        sp = sprite_map_position_for(previous_cell->ch, previous_cell->attrs, 0, true, &error);
    } else {
        sp = sprite_map_position_for(cell->ch, cell->attrs, cell->cc, false, &error);
    }
    cell->sprite_x = sp->x;
    cell->sprite_y = sp->y;
    cell->sprite_z = sp->z;
}

int 
sprite_map_increment(sprite_index *x, sprite_index *y, sprite_index *z) {
    int error = 0;
    *x = sprite_map.x; *y = sprite_map.y; *z = sprite_map.z;
    do_increment(&error);
    return error;
}

void
sprite_map_set_layout(unsigned int cell_width, unsigned int cell_height) {
    // Invalidate cache since cell size has changed.
    SpritePosition *s;
    sprite_map.xnum = MIN(MAX(1, sprite_map.max_texture_size / cell_width), UINT16_MAX);
    sprite_map.max_y = MIN(MAX(1, sprite_map.max_texture_size / cell_height), UINT16_MAX);
    sprite_map.ynum = 1;
    sprite_map.x = 0; sprite_map.y = 0; sprite_map.z = 0;

    for (size_t i = 0; i < sizeof(sprite_map.cache)/sizeof(sprite_map.cache[0]); i++) {
        s = &(sprite_map.cache[i]);
        do {
            s->filled = false;
            s->is_second = false;
            s->rendered = false;
            s->ch = 0; s->cc = 0;
            s->x = 0; s->y = 0; s->z = 0;
            s = s->next;
        } while (s != NULL);
    }
    sprite_map.dirty = true;
}

static PyObject*
sprite_map_set_layout_py(PyObject UNUSED *self, PyObject *args) {
    unsigned int w, h;
    if(!PyArg_ParseTuple(args, "II", &w, &h)) return NULL;
    sprite_map_set_layout(w, h);
    Py_RETURN_NONE;
}

void
sprite_map_current_layout(unsigned int *x, unsigned int *y, unsigned int *z) {
    *x = sprite_map.xnum; *y = sprite_map.ynum; *z = sprite_map.z;
}

PyObject*
sprite_position_for(PyObject UNUSED *self, PyObject *args) {
#define sprite_position_for_doc "sprite_position_for(ch, cc, is_second, attrs) -> x, y, z the sprite position for the specified text"
    unsigned long ch = 0;
    unsigned long long cc = 0;
    unsigned int attrs = 1;
    int is_second = 0, error = 0;
    if (!PyArg_ParseTuple(args, "|kKpI", &ch, &cc, &is_second, &attrs)) return NULL;
    SpritePosition *pos = sprite_map_position_for(ch, attrs, cc, is_second, &error);
    if (pos == NULL) { sprite_map_set_error(error); return NULL; }
    return Py_BuildValue("III", pos->x, pos->y, pos->z);
}

void
render_dirty_sprites(void (*render)(PyObject*, bool, bool, bool, sprite_index, sprite_index, sprite_index)) {
#define render_dirty_cells_doc "Render all cells that are marked as dirty"
    if (!sprite_map.dirty) return;

    for (size_t i = 0; i < sizeof(sprite_map.cache)/sizeof(sprite_map.cache[0]); i++) {
        SpritePosition *sp = &(sprite_map.cache[i]);
        do {
            if (sp->filled && !sp->rendered) {
                PyObject *text = line_text_at(sp->ch, sp->cc);
                render(text, sp->bold, sp->italic, sp->is_second, sp->x, sp->y, sp->z);
                Py_CLEAR(text);
                sp->rendered = true; 
            }
            sp = sp->next;
        } while(sp);
    }
    sprite_map.dirty = false;
}


static PyMethodDef module_methods[] = {
    {"sprite_position_for", (PyCFunction)sprite_position_for, METH_VARARGS, ""},
    {"sprite_map_set_layout", (PyCFunction)sprite_map_set_layout_py, METH_VARARGS, ""},
    {"sprite_map_set_limits", (PyCFunction)sprite_map_set_limits_py, METH_VARARGS, ""},

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool 
init_sprites(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
