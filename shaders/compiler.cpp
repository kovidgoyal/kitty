/*
 * compiler.cpp
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include <Python.h>


static char doc[] = "Compile shaders";
static PyMethodDef methods[] = {
    {NULL}  /* Sentinel */
};

static int
exec_module(PyObject *mod) { (void)mod; return 0; }

static PyModuleDef_Slot slots[] = { {Py_mod_exec, (void*)exec_module}, {0, NULL} };

static struct PyModuleDef module_def = {PyModuleDef_HEAD_INIT};

PyObject*
PyInit_slangc(void) {
	module_def.m_name = "slangc";
	module_def.m_slots = slots;
	module_def.m_doc = doc;
	module_def.m_methods = methods;
	return PyModuleDef_Init(&module_def);
}
