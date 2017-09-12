/*
 * state.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

#define PYWRAP0(name) static PyObject* py##name(PyObject UNUSED *self)
#define PYWRAP1(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args)
#define PYWRAP2(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args, PyObject *kw)
#define PA(fmt, ...) if(!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;

typedef struct {
    double visual_bell_duration;
} Options;

typedef struct {
    Options opts;
} GlobalState;

static GlobalState global_state = {{0}};


// Python API {{{
PYWRAP1(set_options) {
#define S(name, convert) { PyObject *ret = PyObject_GetAttrString(args, #name); if (ret == NULL) return NULL; global_state.opts.name = convert(ret); Py_DECREF(ret); }
    S(visual_bell_duration, PyFloat_AsDouble);
#undef S
    Py_RETURN_NONE;
}

#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, NULL}
#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}
static PyMethodDef module_methods[] = {
    MW(set_options, METH_O),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool 
init_state(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
// }}}
