/*
 * rsync.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <librsync.h>

static PyMethodDef module_methods[] = {
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static int
exec_module(PyObject *m UNUSED) {
    return 0;
}

IGNORE_PEDANTIC_WARNINGS
static PyModuleDef_Slot slots[] = { {Py_mod_exec, (void*)exec_module}, {0, NULL} };
END_IGNORE_PEDANTIC_WARNINGS

static struct PyModuleDef module = {
   .m_base = PyModuleDef_HEAD_INIT,
   .m_name = "rsync",   /* name of module */
   .m_doc = NULL,
   .m_slots = slots,
   .m_methods = module_methods
};

EXPORTED PyMODINIT_FUNC
PyInit_rsync(void) {
	return PyModuleDef_Init(&module);
}
