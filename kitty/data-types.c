/*
 * data-types.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "glfw.h"
#include "gl.h"
#include "modes.h"

static PyMethodDef module_methods[] = {
    GL_METHODS
    {"parse_bytes", (PyCFunction)parse_bytes, METH_VARARGS, ""},
    {"parse_bytes_dump", (PyCFunction)parse_bytes_dump, METH_VARARGS, ""},
    {"read_bytes", (PyCFunction)read_bytes, METH_VARARGS, ""},
    {"read_bytes_dump", (PyCFunction)read_bytes_dump, METH_VARARGS, ""},
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
        if (!init_HistoryBuf(m)) return NULL;
        if (!init_Line(m)) return NULL;
        if (!init_Cursor(m)) return NULL;
        if (!init_ColorProfile(m)) return NULL;
        if (!init_SpriteMap(m)) return NULL;
        if (!init_ChangeTracker(m)) return NULL;
        if (!init_Screen(m)) return NULL;
        if (!init_freetype_library(m)) return NULL;
        if (!init_Face(m)) return NULL;
        if (!add_module_gl_constants(m)) return NULL;
        if (!init_glfw(m)) return NULL;
        PyModule_AddIntConstant(m, "BOLD", BOLD_SHIFT);
        PyModule_AddIntConstant(m, "ITALIC", ITALIC_SHIFT);
        PyModule_AddIntConstant(m, "REVERSE", REVERSE_SHIFT);
        PyModule_AddIntConstant(m, "STRIKETHROUGH", STRIKE_SHIFT);
        PyModule_AddIntConstant(m, "DECORATION", DECORATION_SHIFT);
        PyModule_AddStringMacro(m, BRACKETED_PASTE_START);
        PyModule_AddStringMacro(m, BRACKETED_PASTE_END);
        PyModule_AddStringMacro(m, ERROR_PREFIX);
        PyModule_AddIntMacro(m, CURSOR_BLOCK);
        PyModule_AddIntMacro(m, CURSOR_BEAM);
        PyModule_AddIntMacro(m, CURSOR_UNDERLINE);
        PyModule_AddIntMacro(m, DECAWM);
        PyModule_AddIntMacro(m, IRM);
        PyModule_AddIntMacro(m, DATA_CELL_SIZE);

    }

    return m;
}
