/*
 * parser.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
extern PyTypeObject Screen_Type;

PyObject*
#ifdef DUMP_COMMANDS
parse_bytes_dump(PyObject UNUSED *self, PyObject *args) {
    PyObject *dump_callback = NULL;
#else
parse_bytes(PyObject UNUSED *self, PyObject *args) {
#endif
    Py_buffer pybuf;
    Screen *screen;
#ifdef DUMP_COMMANDS
    if (!PyArg_ParseTuple(args, "OO!y*", &dump_callback, &Screen_Type, &screen, &pybuf)) return NULL;
#else
    if (!PyArg_ParseTuple(args, "O!y*", &Screen_Type, &screen, &pybuf)) return NULL;
#endif
    Py_RETURN_NONE;
}
