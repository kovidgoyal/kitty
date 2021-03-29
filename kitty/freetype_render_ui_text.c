/*
 * freetype_render_ui_text.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "fonts.h"

static PyObject*
path_for_font(PyObject *self UNUSED, PyObject *args) {
    const char *family = NULL; int bold = 0, italic = 0;
    if (!PyArg_ParseTuple(args, "|zpp", &family, &bold, &italic)) return NULL;
    const char *ans = file_path_for_font(family, bold, italic);
    if (!ans) return NULL;
    return PyUnicode_FromString(ans);
}

static PyMethodDef module_methods[] = {
    METHODB(path_for_font, METH_VARARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_freetype_render_ui_text(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
