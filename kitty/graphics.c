/*
 * graphics.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "graphics.h"
#include "state.h"

#define REPORT_ERROR(fmt, ...) { fprintf(stderr, fmt, __VA_ARGS__); fprintf(stderr, "\n"); }

GraphicsManager*
grman_realloc(GraphicsManager *old, index_type lines, index_type columns) {
    GraphicsManager *self = (GraphicsManager *)GraphicsManager_Type.tp_alloc(&GraphicsManager_Type, 0);
    self->lines = lines; self->columns = columns;
    if (old == NULL) {
        self->images_capacity = 64;
        self->images = calloc(self->images_capacity, sizeof(Image));
        if (self->images == NULL) {
            Py_CLEAR(self); return NULL;
        }
    } else {
        self->images_capacity = old->images_capacity; self->images = old->images; self->image_count = old->image_count;
        old->images = NULL;
        grman_free(old);
    }
    return self;
}

GraphicsManager*
grman_free(GraphicsManager* self) {
    free(self->images);
    Py_TYPE(self)->tp_free((PyObject*)self);
    return NULL;
}

/* static size_t internal_id_counter = 1; */

static void
handle_add_command(GraphicsManager UNUSED *self, const GraphicsCommand UNUSED *g, const uint8_t UNUSED *payload) {
}

void
grman_handle_command(GraphicsManager *self, const GraphicsCommand *g, const uint8_t *payload) {
    switch(g->action) {
        case 't':
            handle_add_command(self, g, payload);
            break;
        default:
            REPORT_ERROR("Unknown graphics command action: %c", g->action);
            break;
    }
}

void
grman_clear(GraphicsManager UNUSED *self) {
    // TODO: Implement this
}


// Boilerplate {{{
static PyObject *
new(PyTypeObject UNUSED *type, PyObject *args, PyObject UNUSED *kwds) {
    unsigned int lines, columns;
    if (!PyArg_ParseTuple(args, "II", &lines, &columns)) return NULL;
    PyObject *ans = (PyObject*)grman_realloc(NULL, lines, columns);
    if (ans == NULL) PyErr_NoMemory();
    return ans;
}

static void
dealloc(GraphicsManager* self) {
    grman_free(self);
}


PyTypeObject GraphicsManager_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.GraphicsManager",
    .tp_basicsize = sizeof(GraphicsManager),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "GraphicsManager",
    .tp_new = new,                
};

bool
init_graphics(PyObject *module) {
    if (PyType_Ready(&GraphicsManager_Type) < 0) return false;
    if (PyModule_AddObject(module, "GraphicsManager", (PyObject *)&GraphicsManager_Type) != 0) return false; 
    Py_INCREF(&GraphicsManager_Type);
    return true;
}
// }}}
