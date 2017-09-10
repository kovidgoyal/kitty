/*
 * shaders.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

#define GL_VERSION_MAJOR 3
#define GL_VERSION_MINOR 3
#define GLSL_VERSION (GL_VERSION_MAJOR * 100 + GL_VERSION_MINOR * 10)

enum Program { CELL_PROGRAM, CURSOR_PROGRAM, BORDERS_PROGRAM};

bool
init_shaders(PyObject *module) {
#define C(x) if (PyModule_AddIntConstant(module, #x, x) != 0) { PyErr_NoMemory(); return false; }
    C(CELL_PROGRAM); C(CURSOR_PROGRAM); C(BORDERS_PROGRAM);
    C(GLSL_VERSION);
#undef C
    PyModule_AddObject(module, "GL_VERSION_REQUIRED", Py_BuildValue("II", GL_VERSION_MAJOR, GL_VERSION_MINOR));
    return true;
}
