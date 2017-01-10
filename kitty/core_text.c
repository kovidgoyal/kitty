/*
 * core_text.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <structmember.h>
#include <CoreText/CTFont.h>


typedef struct {
    PyObject_HEAD

    unsigned int units_per_EM;
    int ascender, descender, height, max_advance_width, max_advance_height, underline_position, underline_thickness;
} Face;


static PyObject*
new(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    Face *self;
    self = (Face *)type->tp_alloc(type, 0);
    return (PyObject*)self;
}


static void
dealloc(Face* self) {
    Py_TYPE(self)->tp_free((PyObject*)self);
}


// Boilerplate {{{

static PyMemberDef members[] = {
#define MEM(name, type) {#name, type, offsetof(Face, name), READONLY, #name}
    MEM(units_per_EM, T_UINT),
    MEM(ascender, T_INT),
    MEM(descender, T_INT),
    MEM(height, T_INT),
    MEM(max_advance_width, T_INT),
    MEM(max_advance_height, T_INT),
    MEM(underline_position, T_INT),
    MEM(underline_thickness, T_INT),
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
    {NULL}  /* Sentinel */
};


PyTypeObject Face_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.CTFace",
    .tp_basicsize = sizeof(Face),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "CoreText Font face",
    .tp_methods = methods,
    .tp_members = members,
    .tp_new = new,                
};


int 
init_CoreText(PyObject *module) {
    if (PyType_Ready(&Face_Type) < 0) return 0;
    if (PyModule_AddObject(module, "CTFace", (PyObject *)&Face_Type) != 0) return 0;
    return 1;
}


// }}}
