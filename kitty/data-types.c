/*
 * data-types.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

extern PyTypeObject LineBuf_Type;
extern PyTypeObject Cursor_Type;
extern PyTypeObject Line_Type;

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
    if (PyType_Ready(&Cursor_Type) < 0) return NULL;
    if (PyType_Ready(&Line_Type) < 0) return NULL;
    m = PyModule_Create(&module);
    if (m == NULL) return NULL;

    if (m != NULL) {
        Py_INCREF(&LineBuf_Type);
        PyModule_AddObject(m, "LineBuf", (PyObject *)&LineBuf_Type);
        Py_INCREF(&Cursor_Type);
        PyModule_AddObject(m, "Cursor", (PyObject *)&Cursor_Type);
        Py_INCREF(&Line_Type);
        PyModule_AddObject(m, "Line", (PyObject *)&Line_Type);
    }

    return m;
}
