/*
 * data-types.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
extern int init_LineBuf(PyObject *);
extern int init_Cursor(PyObject *);
extern int init_Line(PyObject *);

static PyMethodDef module_methods[] = {
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static struct PyModuleDef module = {
   PyModuleDef_HEAD_INIT,
   "fast_data_types",   /* name of module */
   NULL, 
   -1,       
   module_methods
};

PyMODINIT_FUNC
PyInit_fast_data_types(void) {
    PyObject *m;


    m = PyModule_Create(&module);
    if (m == NULL) return NULL;

    if (m != NULL) {
        if (!init_LineBuf(m)) return NULL;
        if (!init_Line(m)) return NULL;
        if (!init_Cursor(m)) return NULL;
    }

    return m;
}
