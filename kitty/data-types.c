/*
 * data-types.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

extern PyTypeObject LineBuf_Type;

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


    if (PyType_Ready(&LineBuf_Type) < 0) return NULL;
    m = PyModule_Create(&module);
    if (m == NULL) return NULL;

    if (m != NULL) {
        Py_INCREF(&LineBuf_Type);
        PyModule_AddObject(m, "LineBuf", (PyObject *)&LineBuf_Type);
    }

    return m;
}
