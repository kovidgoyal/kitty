/*
 * savepoints.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

static PyObject *
new(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    Savepoint *self;
    self = (Savepoint *)type->tp_alloc(type, 0);
    return (PyObject*) self;
}

static void
dealloc(Savepoint* self) {
    Py_TYPE(self)->tp_free((PyObject*)self);
}


// Boilerplate {{{

static PyMethodDef methods[] = {
    {NULL}  /* Sentinel */
};


PyTypeObject Savepoint_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Savepoint",
    .tp_basicsize = sizeof(Savepoint),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "Savepoint",
    .tp_methods = methods,
    .tp_new = new,                
};

INIT_TYPE(Savepoint)

Savepoint *alloc_savepoint() {
    return (Savepoint*)new(&Savepoint_Type, NULL, NULL);
}

// }}}
