/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#define UNUSED __attribute__ ((unused))

int init_CoreText(PyObject *);
PyObject* coretext_all_fonts(PyObject UNUSED *self);

#define CORE_TEXT_FUNC_WRAPPERS \
    {"coretext_all_fonts", (PyCFunction)coretext_all_fonts, METH_NOARGS, ""},
