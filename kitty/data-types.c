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
#include "gl.h"

static PyMethodDef module_methods[] = {
    GL_METHODS
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


static struct PyModuleDef module = {
   .m_base = PyModuleDef_HEAD_INIT,
   .m_name = "fast_data_types",   /* name of module */
   .m_doc = NULL, 
   .m_size = -1,       
   .m_methods = module_methods
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
        if (!add_module_gl_constants(m)) return NULL;
        PyModule_AddIntConstant(m, "BOLD", BOLD_SHIFT);
        PyModule_AddIntConstant(m, "ITALIC", ITALIC_SHIFT);
        PyModule_AddIntConstant(m, "REVERSE", REVERSE_SHIFT);
        PyModule_AddIntConstant(m, "STRIKETHROUGH", STRIKE_SHIFT);
        PyModule_AddIntConstant(m, "DECORATION", DECORATION_SHIFT);
    }

    return m;
}
