/*
 * screen.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

static const ScreenModes empty_modes = {0};

static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Screen *self;
    PyObject *callbacks = Py_None;
    if (!PyArg_ParseTuple(args, "|O", &callbacks)) return NULL;

    self = (Screen *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->current_charset = 2;
        self->columns = 80; self->lines=24;
        self->modes = empty_modes;
        self->utf8_state = 0;
        self->margin_top = 0; self->margin_bottom = self->lines - 1;
        self->callbacks = callbacks; Py_INCREF(callbacks);
        self->cursor = alloc_cursor();
        self->main_linebuf = alloc_linebuf(); self->alt_linebuf = alloc_linebuf();
        self->linebuf = self->main_linebuf;
        self->main_savepoints = PyList_New(0); self->alt_savepoints = PyList_New(0);
        self->savepoints = self->main_savepoints;
        self->change_tracker = alloc_change_tracker();
        if (self->cursor == NULL || self->main_linebuf == NULL || self->alt_linebuf == NULL || self->main_savepoints == NULL || self->alt_savepoints == NULL || self->change_tracker == NULL) {
            Py_CLEAR(self); return NULL;
        }
    }
    return (PyObject*) self;
}

static void
dealloc(Screen* self) {
    Py_CLEAR(self->callbacks);
    Py_CLEAR(self->cursor); Py_CLEAR(self->main_linebuf); Py_CLEAR(self->alt_linebuf);
    Py_CLEAR(self->main_savepoints); Py_CLEAR(self->alt_savepoints); Py_CLEAR(self->change_tracker);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

bool screen_bell(Screen UNUSED *scr, uint8_t ch) {
    FILE *f = fopen("/dev/tty", "w");
    if (f != NULL) {
        fwrite(&ch, 1, 1, f);
        fclose(f);
    }
    return true;
}

bool screen_draw(Screen UNUSED *scr, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}

bool screen_backspace(Screen UNUSED *scr, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}

bool screen_tab(Screen UNUSED *scr, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}


bool screen_linefeed(Screen UNUSED *scr, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}

bool screen_carriage_return(Screen UNUSED *scr, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}

bool screen_shift_out(Screen UNUSED *scr, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}

bool screen_shift_in(Screen UNUSED *scr, uint8_t UNUSED ch) {
    // TODO: Implement this
    return true;
}

// Boilerplate {{{

static PyMethodDef methods[] = {
    {NULL}  /* Sentinel */
};


PyTypeObject Screen_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Screen",
    .tp_basicsize = sizeof(Screen),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "Screen",
    .tp_methods = methods,
    .tp_new = new,                
};

INIT_TYPE(Screen)
// }}}


