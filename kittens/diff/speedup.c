/*
 * speedup.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

static PyObject*
changed_center(PyObject *self UNUSED, PyObject *args) {
    unsigned int prefix_count = 0, suffix_count = 0;
    PyObject *lp, *rp;
    if (!PyArg_ParseTuple(args, "UU", &lp, &rp)) return NULL;
    const size_t left_len = PyUnicode_GET_LENGTH(lp), right_len = PyUnicode_GET_LENGTH(rp);

#define R(which, index) PyUnicode_READ(PyUnicode_KIND(which), PyUnicode_DATA(which), index)
    while(prefix_count < MIN(left_len, right_len)) {
        if (R(lp, prefix_count) != R(rp, prefix_count)) break;
        prefix_count++;
    }
    if (left_len && right_len && prefix_count < MIN(left_len, right_len)) {
        while(suffix_count < MIN(left_len - prefix_count, right_len - prefix_count)) {
            if(R(lp, left_len - 1 - suffix_count) != R(rp, right_len - 1 - suffix_count)) break;
            suffix_count++;
        }
    }
#undef R
    return Py_BuildValue("II", prefix_count, suffix_count);
}

static PyMethodDef module_methods[] = {
    {"changed_center", (PyCFunction)changed_center, METH_VARARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static struct PyModuleDef module = {
   .m_base = PyModuleDef_HEAD_INIT,
   .m_name = "diff_speedup",   /* name of module */
   .m_doc = NULL,
   .m_size = -1,
   .m_methods = module_methods
};

EXPORTED PyMODINIT_FUNC
PyInit_diff_speedup(void) {
    PyObject *m;

    m = PyModule_Create(&module);
    if (m == NULL) return NULL;
    return m;
}
