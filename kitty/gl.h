/*
 * gl.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <GL/glew.h>

#define STRINGIFY(x) #x
#define METH(name, argtype) {STRINGIFY(gl##name), (PyCFunction)name, argtype, NULL},

static int _enable_error_checking = 1;

#define SET_GL_ERR \
    switch(glGetError()) { \
        case GL_NO_ERROR: break; \
        case GL_INVALID_ENUM: \
            PyErr_SetString(PyExc_ValueError, "An enum value is invalid (GL_INVALID_ENUM)"); break; \
        case GL_INVALID_VALUE: \
            PyErr_SetString(PyExc_ValueError, "An numeric value is invalid (GL_INVALID_VALUE)"); break; \
        case GL_INVALID_OPERATION: \
            PyErr_SetString(PyExc_ValueError, "This operation is not allowed in the current state (GL_INVALID_OPERATION)"); break; \
        case GL_INVALID_FRAMEBUFFER_OPERATION: \
            PyErr_SetString(PyExc_ValueError, "The framebuffer object is not complete (GL_INVALID_FRAMEBUFFER_OPERATION)"); break; \
        case GL_OUT_OF_MEMORY: \
            PyErr_SetString(PyExc_MemoryError, "There is not enough memory left to execute the command. (GL_OUT_OF_MEMORY)"); break; \
        case GL_STACK_UNDERFLOW: \
            PyErr_SetString(PyExc_OverflowError, "An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_UNDERFLOW)"); break; \
        case GL_STACK_OVERFLOW: \
            PyErr_SetString(PyExc_OverflowError, "An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_UNDERFLOW)"); break; \
        default: \
            PyErr_SetString(PyExc_RuntimeError, "An unknown OpenGL error occurred."); break; \
    }

#define CHECK_ERROR if (_enable_error_checking) { SET_GL_ERR; if (PyErr_Occurred()) return NULL; }

static PyObject*
enable_automatic_error_checking(PyObject UNUSED *self, PyObject *val) {
    _enable_error_checking = PyObject_IsTrue(val) ? 1 : 0;
    Py_RETURN_NONE;
}

static PyObject* 
Viewport(PyObject UNUSED *self, PyObject *args) {
    unsigned int x, y, w, h;
    if (!PyArg_ParseTuple(args, "IIII", &x, &y, &w, &h)) return NULL;
    glViewport(x, y, w, h);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
CheckError(PyObject UNUSED *self) {
    CHECK_ERROR; Py_RETURN_NONE;
}

#define GL_METHODS \
    {"enable_automatic_opengl_error_checking", (PyCFunction)enable_automatic_error_checking, METH_O, NULL}, \
    METH(Viewport, METH_VARARGS) \
    METH(CheckError, METH_NOARGS) \

