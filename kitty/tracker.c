/*
 * tracker.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "tracker.h"


bool tracker_resize(ChangeTracker *self, unsigned int ynum, unsigned int xnum) {
#define ALLOC_VAR(name, sz) \
    bool *name = PyMem_Calloc(sz, sizeof(bool)); \
    if (name == NULL) { PyErr_NoMemory(); return false; } \
    PyMem_Free(self->name); self->name = name;

    self->ynum = ynum; self->xnum = xnum;
    ALLOC_VAR(changed_lines, self->ynum);
    ALLOC_VAR(changed_cells, self->xnum * self->ynum);
    ALLOC_VAR(lines_with_changed_cells, self->ynum);
    RESET_STATE_VARS(self);
    return true;
}

static PyObject*
resize(ChangeTracker *self, PyObject *args) {
#define resize_doc "Resize this change tracker must be called when the screen it is tracking for is resized"
    unsigned int ynum=1, xnum=1;
    if (!PyArg_ParseTuple(args, "|II", &ynum, &xnum)) return NULL;
    if (!tracker_resize(self, ynum, xnum)) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    ChangeTracker *self;
    self = (ChangeTracker *)type->tp_alloc(type, 0);
    if (self != NULL) {
        PyObject *ret = resize(self, args);
        if (ret == NULL) { Py_CLEAR(self); return NULL; }
        Py_CLEAR(ret);
    }
    return (PyObject*) self;
}

static void
dealloc(ChangeTracker* self) {
    PyMem_Free(self->changed_lines); PyMem_Free(self->changed_cells); PyMem_Free(self->lines_with_changed_cells);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
reset(ChangeTracker *self) {
#define reset_doc "Reset all changes"
    tracker_reset(self);

    Py_RETURN_NONE;
}

static PyObject*
cursor_changed(ChangeTracker *self) {
#define cursor_changed_doc ""
    tracker_cursor_changed(self);
    Py_RETURN_NONE;
}

static PyObject*
line_added_to_history(ChangeTracker *self) {
#define line_added_to_history_doc ""
    tracker_line_added_to_history(self);
    Py_RETURN_NONE;
}

static PyObject*
update_screen(ChangeTracker *self) {
#define update_screen_doc ""
    tracker_update_screen(self);
    Py_RETURN_NONE;
}

static PyObject*
update_line_range(ChangeTracker *self, PyObject *args) {
#define update_line_range_doc ""
    unsigned int f, l;
    if (!PyArg_ParseTuple(args, "II", &f, &l)) return NULL;
    tracker_update_line_range(self, f, l);
    Py_RETURN_NONE;
}

static PyObject*
update_cell_range(ChangeTracker *self, PyObject *args) {
#define update_cell_range_doc ""
    unsigned int line, f, l;
    if (!PyArg_ParseTuple(args, "III", &line, &f, &l)) return NULL;
    tracker_update_cell_range(self, line, f, l);
    Py_RETURN_NONE;
}

bool tracker_update_cell_data(ScreenModes *modes, ChangeTracker *self, LineBuf *lb, SpriteMap *spm, unsigned int *data, bool force_screen_refresh) {
    unsigned int y;
    Py_ssize_t start;

#define UPDATE_RANGE(xstart, xmax) \
    linebuf_init_line(lb, y); \
    if (!update_cell_range_data(modes, spm, lb->line, (xstart), (xmax), data)) return false;

    if (self->screen_changed || force_screen_refresh) {
        for (y = 0; y < self->ynum; y++) {
            UPDATE_RANGE(0, self->xnum - 1);
        }
    } else {
        for (y = 0; y < self->ynum; y++) {
            if (self->changed_lines[y]) {
                UPDATE_RANGE(0, self->xnum - 1);
            } else if (self->lines_with_changed_cells[y]) {
                start = -1;
                bool *line = self->changed_cells + y * self->xnum;
                for (unsigned int i = 0; i < self->xnum; i++) {
                    if (line[i]) {
                        if (start == -1) {
                            start = i;
                        }
                    } else {
                        if (start != -1) {
                            UPDATE_RANGE(start, i - 1);
                            start = -1;
                        }
                    }
                }
                if (start != -1) {
                    UPDATE_RANGE(start, self->xnum - 1);
                }
            }
        }
    }
    tracker_reset(self);
    return true;
}

static inline PyObject*
get_ranges(bool *line, unsigned int xnum) {
    PyObject *ans = PyList_New(0), *t;
    Py_ssize_t start = -1;
    if (ans == NULL) return PyErr_NoMemory();

#define APPEND_RANGE(x) \
    t = Py_BuildValue("nI", start, x); \
    if (t == NULL) { Py_CLEAR(ans); return NULL; } \
    if (PyList_Append(ans, t) != 0) { Py_CLEAR(ans); Py_CLEAR(t); return NULL; } \
    Py_CLEAR(t);

    for (unsigned int i = 0; i < xnum; i++) {
        if (line[i]) {
            if (start == -1) {
                start = i;
            }
        } else {
            if (start != -1) {
                APPEND_RANGE(i - 1);
                start = -1;
            }
        }
    }
    if (start != -1) {
        APPEND_RANGE(xnum - 1);
    }

    return ans;
}

PyObject*
tracker_consolidate_changes(ChangeTracker *self) {
    PyObject *ans = PyDict_New();
    if (ans == NULL) return PyErr_NoMemory();
    if (PyDict_SetItemString(ans, "screen", self->screen_changed ? Py_True : Py_False) != 0) { Py_CLEAR(ans); return NULL; }
    if (PyDict_SetItemString(ans, "cursor", self->cursor_changed ? Py_True : Py_False) != 0) { Py_CLEAR(ans); return NULL; }
    PyObject *t = PyLong_FromUnsignedLong((unsigned long)self->history_line_added_count);
    if (t == NULL) { Py_CLEAR(ans); return NULL; }
    if (PyDict_SetItemString(ans, "history_line_added_count", t) != 0) { Py_CLEAR(t); Py_CLEAR(ans); return NULL; }
    Py_CLEAR(t);

    // Changed lines
    Py_ssize_t num = 0;
    if (!self->screen_changed) {
        for (unsigned int i = 0; i < self->ynum; i++) { num += self->changed_lines[i]; }
    }
    t = PyTuple_New(num);
    if (t == NULL) { Py_CLEAR(ans); return NULL; }
    if (num > 0) {
        for (unsigned int i = 0, j=0; i < self->ynum; i++) { 
            if (self->changed_lines[i]) {
                PyObject *n = PyLong_FromUnsignedLong(i);
                if (n == NULL) { Py_CLEAR(t); Py_CLEAR(ans); return NULL; }
                PyTuple_SET_ITEM(t, j++, n);
            }
        }
    }
    if (PyDict_SetItemString(ans, "lines", t) != 0) { Py_CLEAR(t); Py_CLEAR(ans); return NULL; }
    Py_CLEAR(t);

    // Changed cells
    t = PyDict_New();
    if (t == NULL) { Py_CLEAR(ans); return PyErr_NoMemory(); }
    if (!self->screen_changed) {
        for (unsigned int i = 0; i < self->ynum; i++) { 
            if (self->lines_with_changed_cells[i] && !self->changed_lines[i]) {
                PyObject *ranges = get_ranges(self->changed_cells + i * self->xnum, self->xnum);
                if (ranges == NULL) { Py_CLEAR(t); Py_CLEAR(ans); return NULL; }
                PyObject *key = PyLong_FromUnsignedLong(i);
                if (key == NULL) { Py_CLEAR(t); Py_CLEAR(ans); Py_CLEAR(ranges); return NULL; }
                if (PyDict_SetItem(t, key, ranges) != 0) { Py_CLEAR(key); Py_CLEAR(t); Py_CLEAR(ans); Py_CLEAR(ranges); return NULL; }
                Py_CLEAR(key); Py_CLEAR(ranges);
            }
        }
    }

    if (PyDict_SetItemString(ans, "cells", t) != 0) { Py_CLEAR(t); Py_CLEAR(ans); return NULL; }
    Py_CLEAR(t);

    tracker_reset(self);
    return ans;
}

// Boilerplate {{{

BOOL_GETSET(ChangeTracker, dirty)
static PyGetSetDef getseters[] = {
    GETSET(dirty)
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
    METHOD(resize, METH_VARARGS)
    METHOD(reset, METH_NOARGS)
    METHOD(cursor_changed, METH_NOARGS)
    {"consolidate_changes", (PyCFunction)tracker_consolidate_changes, METH_NOARGS, ""},
    METHOD(line_added_to_history, METH_NOARGS)
    METHOD(update_screen, METH_NOARGS)
    METHOD(update_line_range, METH_VARARGS)
    METHOD(update_cell_range, METH_VARARGS)
    {NULL}  /* Sentinel */
};


PyTypeObject ChangeTracker_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.ChangeTracker",
    .tp_basicsize = sizeof(ChangeTracker),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "ChangeTracker",
    .tp_methods = methods,
    .tp_getset = getseters,
    .tp_new = new,                
};

INIT_TYPE(ChangeTracker)
// }}}

ChangeTracker* alloc_change_tracker(unsigned int ynum, unsigned int xnum) {
    ChangeTracker *self = (ChangeTracker *)(&ChangeTracker_Type)->tp_alloc((&ChangeTracker_Type), 0);
    if (!tracker_resize(self, ynum, xnum)) { Py_CLEAR(self); return NULL; }
    return self;
}
