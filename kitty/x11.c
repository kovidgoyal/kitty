/*
 * x11.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include <Python.h>
#include <stdbool.h>
#include <GLFW/glfw3.h>
#if GLFW_VERSION_MAJOR > 3 || (GLFW_VERSION_MAJOR == 3 && GLFW_VERSION_MINOR > 2)
#define HAS_X11_SELECTION
#endif

#ifdef HAS_X11_SELECTION
#define GLFW_EXPOSE_NATIVE_X11
#include <GLFW/glfw3native.h>

static PyObject*
get_selection_x11(PyObject *self) {
    (void)(self);
    return Py_BuildValue("y", glfwGetX11SelectionString());
}

static PyObject*
set_selection_x11(PyObject *self, PyObject *args) {
    (void)(self);
    const char *data;
    if (!PyArg_ParseTuple(args, "y", &data)) return NULL;
    glfwSetX11SelectionString(data);
    Py_RETURN_NONE;
}

static PyMethodDef sel_methods[] = {
    {"get_selection_x11", (PyCFunction)get_selection_x11, METH_NOARGS, ""},
    {"set_selection_x11", (PyCFunction)set_selection_x11, METH_VARARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


#endif

bool 
init_x11_funcs(PyObject *module) { 
#ifdef HAS_X11_SELECTION
    if (PyModule_AddFunctions(module, sel_methods) != 0) return false;
#endif
    return true; 
}
