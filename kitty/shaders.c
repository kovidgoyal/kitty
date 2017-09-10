/*
 * shaders.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#ifdef __APPLE__
#include <OpenGL/gl3.h>
#include <OpenGL/gl3ext.h>
#else
#include <GL/glew.h>
#endif


// GL setup and error handling {{{
// Required minimum OpenGL version
#define REQUIRED_VERSION_MAJOR 3
#define REQUIRED_VERSION_MINOR 3
#define GLSL_VERSION (REQUIRED_VERSION_MAJOR * 100 + REQUIRED_VERSION_MINOR * 10)

static inline bool
set_error_from_gl() {
    int code = glGetError();
    switch(code) { 
        case GL_NO_ERROR: return false; 
        case GL_INVALID_ENUM: 
            PyErr_SetString(PyExc_ValueError, "An enum value is invalid (GL_INVALID_ENUM)"); break; 
        case GL_INVALID_VALUE: 
            PyErr_SetString(PyExc_ValueError, "An numeric value is invalid (GL_INVALID_VALUE)"); break; 
        case GL_INVALID_OPERATION: 
            PyErr_SetString(PyExc_ValueError, "This operation is not allowed in the current state (GL_INVALID_OPERATION)"); break; 
        case GL_INVALID_FRAMEBUFFER_OPERATION: 
            PyErr_SetString(PyExc_ValueError, "The framebuffer object is not complete (GL_INVALID_FRAMEBUFFER_OPERATION)"); break; 
        case GL_OUT_OF_MEMORY: 
            PyErr_SetString(PyExc_MemoryError, "There is not enough memory left to execute the command. (GL_OUT_OF_MEMORY)"); break; 
        case GL_STACK_UNDERFLOW: 
            PyErr_SetString(PyExc_OverflowError, "An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_UNDERFLOW)"); break; 
        case GL_STACK_OVERFLOW: 
            PyErr_SetString(PyExc_OverflowError, "An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_OVERFLOW)"); break; 
        default: 
            PyErr_Format(PyExc_RuntimeError, "An unknown OpenGL error occurred with code: %d", code); break; 
    }
    return true;
}

static bool _enable_error_checking = false;
#define CHECK_ERROR if (_enable_error_checking) { if (set_error_from_gl()) return NULL; }


static PyObject* 
glew_init(PyObject UNUSED *self) {
#ifndef __APPLE__
    GLenum err = glewInit();
    if (err != GLEW_OK) {
        PyErr_Format(PyExc_RuntimeError, "GLEW init failed: %s", glewGetErrorString(err));
        return NULL;
    }
#define ARB_TEST(name) \
    if (!GLEW_ARB_##name) { \
        PyErr_Format(PyExc_RuntimeError, "The OpenGL driver on this system is missing the required extension: ARB_%s", #name); \
        return NULL; \
    }
    ARB_TEST(texture_storage);
#undef ARB_TEST
#endif
    Py_RETURN_NONE;
}
// }}}

enum Program { CELL_PROGRAM, CURSOR_PROGRAM, BORDERS_PROGRAM, NUM_PROGRAMS };

/* static GLuint program_ids[NUM_PROGRAMS] = {0}; */


// Python API {{{
static PyObject*
enable_automatic_error_checking(PyObject UNUSED *self, PyObject *val) {
    _enable_error_checking = PyObject_IsTrue(val) ? true : false;
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    {"enable_automatic_opengl_error_checking", (PyCFunction)enable_automatic_error_checking, METH_O, NULL}, 
    {"glewInit", (PyCFunction)glew_init, METH_NOARGS, NULL}, 
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_shaders(PyObject *module) {
#define C(x) if (PyModule_AddIntConstant(module, #x, x) != 0) { PyErr_NoMemory(); return false; }
    C(CELL_PROGRAM); C(CURSOR_PROGRAM); C(BORDERS_PROGRAM);
    C(GLSL_VERSION);
#undef C
    PyModule_AddObject(module, "GL_VERSION_REQUIRED", Py_BuildValue("II", REQUIRED_VERSION_MAJOR, REQUIRED_VERSION_MINOR));
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
// }}}
