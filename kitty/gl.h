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
            PyErr_SetString(PyExc_OverflowError, "An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_OVERFLOW)"); break; \
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
ClearColor(PyObject UNUSED *self, PyObject *args) {
    float x, y, w, h;
    if (!PyArg_ParseTuple(args, "ffff", &x, &y, &w, &h)) return NULL;
    glClearColor(x, y, w, h);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

// Uniforms {{{
static PyObject* 
Uniform2ui(PyObject UNUSED *self, PyObject *args) {
    int location;
    unsigned int x, y;
    if (!PyArg_ParseTuple(args, "iII", &location, &x, &y)) return NULL;
    glUniform2ui(location, x, y);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
Uniform1i(PyObject UNUSED *self, PyObject *args) {
    int location;
    int x;
    if (!PyArg_ParseTuple(args, "ii", &location, &x)) return NULL;
    glUniform1i(location, x);
    CHECK_ERROR;
    Py_RETURN_NONE;
}


static PyObject* 
Uniform2f(PyObject UNUSED *self, PyObject *args) {
    int location;
    float x, y;
    if (!PyArg_ParseTuple(args, "iff", &location, &x, &y)) return NULL;
    glUniform2f(location, x, y);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
Uniform4f(PyObject UNUSED *self, PyObject *args) {
    int location;
    float x, y, a, b;
    if (!PyArg_ParseTuple(args, "iffff", &location, &x, &y, &a, &b)) return NULL;
    glUniform4f(location, x, y, a, b);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
// }}}


static PyObject* 
CheckError(PyObject UNUSED *self) {
    CHECK_ERROR; Py_RETURN_NONE;
}

static PyObject* 
_glewInit(PyObject UNUSED *self) {
    GLenum err = glewInit();
    if (err != GLEW_OK) {
        PyErr_Format(PyExc_RuntimeError, "GLEW init failed: %s", glewGetErrorString(err));
        return NULL;
    }
    if(!GLEW_ARB_copy_image) {
        PyErr_SetString(PyExc_RuntimeError, "OpenGL is missing the required ARB_copy_image extension");
        return NULL;
    }
    if(!GLEW_ARB_texture_storage) {
        PyErr_SetString(PyExc_RuntimeError, "OpenGL is missing the required ARB_texture_storage extension");
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject* 
GetString(PyObject UNUSED *self, PyObject *val) {
    const unsigned char *ans = glGetString(PyLong_AsUnsignedLong(val));
    if (ans == NULL) { SET_GL_ERR; return NULL; }
    return PyBytes_FromString((const char*)ans);
}

static PyObject* 
Clear(PyObject UNUSED *self, PyObject *val) {
    unsigned long m = PyLong_AsUnsignedLong(val);
    glClear((GLbitfield)m);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
DrawArraysInstanced(PyObject UNUSED *self, PyObject *args) {
    int mode, first;
    unsigned int count, primcount;
    if (!PyArg_ParseTuple(args, "iiII", &mode, &first, &count, &primcount)) return NULL;
    glDrawArraysInstanced(mode, first, count, primcount);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
 
int add_module_gl_constants(PyObject *module) {
#define GLC(x) if (PyModule_AddIntConstant(module, #x, x) != 0) { PyErr_NoMemory(); return 0; }
    GLC(GL_VERSION);
    GLC(GL_VENDOR);
    GLC(GL_SHADING_LANGUAGE_VERSION);
    GLC(GL_RENDERER);
    GLC(GL_TRIANGLE_FAN);
    GLC(GL_COLOR_BUFFER_BIT);
    return 1;
}

#define GL_METHODS \
    {"enable_automatic_opengl_error_checking", (PyCFunction)enable_automatic_error_checking, METH_O, NULL}, \
    {"glewInit", (PyCFunction)_glewInit, METH_NOARGS, NULL}, \
    METH(Viewport, METH_VARARGS) \
    METH(CheckError, METH_NOARGS) \
    METH(ClearColor, METH_VARARGS) \
    METH(Uniform2ui, METH_VARARGS) \
    METH(Uniform1i, METH_VARARGS) \
    METH(Uniform2f, METH_VARARGS) \
    METH(Uniform4f, METH_VARARGS) \
    METH(GetString, METH_O) \
    METH(Clear, METH_O) \
    METH(DrawArraysInstanced, METH_VARARGS) \


