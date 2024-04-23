/*
 * font-names.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"

static PyObject*
decode_name_record(PyObject *namerec) {
#define d(x) PyLong_AsUnsignedLong(PyTuple_GET_ITEM(namerec, x))
    unsigned long platform_id = d(0), encoding_id = d(1), language_id = d(2);
#undef d
    const char *encoding = "unicode_escape";
    if ((platform_id == 3 && encoding_id == 1) || platform_id == 0) encoding = "utf-16-be";
    else if (platform_id == 1 && encoding_id == 0 && language_id == 0) encoding = "mac-roman";
    PyObject *b = PyTuple_GET_ITEM(namerec, 3);
    return PyUnicode_Decode(PyBytes_AS_STRING(b), PyBytes_GET_SIZE(b), encoding, "replace");
}


static bool
namerec_matches(PyObject *namerec, unsigned platform_id, unsigned encoding_id, unsigned language_id) {
#define d(x) PyLong_AsUnsignedLong(PyTuple_GET_ITEM(namerec, x))
    return d(0) == platform_id && d(1) == encoding_id && d(2) == language_id;
#undef d
}

static PyObject*
find_matching_namerec(PyObject *namerecs, unsigned platform_id, unsigned encoding_id, unsigned language_id) {
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(namerecs); i++) {
        PyObject *namerec = PyList_GET_ITEM(namerecs, i);
        if (namerec_matches(namerec, platform_id, encoding_id, language_id)) return decode_name_record(namerec);
    }
    return NULL;
}


bool
add_font_name_record(PyObject *table, uint16_t platform_id, uint16_t encoding_id, uint16_t language_id, uint16_t name_id, const char *string, uint16_t string_len) {
    RAII_PyObject(key, PyLong_FromUnsignedLong((unsigned long)name_id));
    if (!key) return false;
    RAII_PyObject(list, PyDict_GetItem(table, key));
    if (list == NULL) {
        list = PyList_New(0);
        if (!list) return false;
        if (PyDict_SetItem(table, key, list) != 0) return false;
    } else Py_INCREF(list);
    RAII_PyObject(value, Py_BuildValue("(H H H y#)", platform_id, encoding_id, language_id, string, (Py_ssize_t)string_len));
    if (!value) return false;
    if (PyList_Append(list, value) != 0) return false;
    return true;
}

PyObject*
get_best_name_from_name_table(PyObject *table, PyObject *name_id) {
    PyObject *namerecs = PyDict_GetItem(table, name_id);
    if (namerecs == NULL) return PyUnicode_FromString("");
    if (PyList_GET_SIZE(namerecs) == 1) return decode_name_record(PyList_GET_ITEM(namerecs, 0));
#define d(...) { PyObject *ans = find_matching_namerec(namerecs, __VA_ARGS__); if (ans != NULL || PyErr_Occurred()) return ans; }
    d(3, 1, 1033);  // Microsoft/Windows/US English
    d(1, 0, 0);     // Mac/Roman/English
    d(0, 6, 0);     // Unicode/SMP/*
    d(0, 4, 0);     // Unicode/SMP/*
    d(0, 3, 0);     // Unicode/BMP/*
    d(0, 2, 0);     // Unicode/10646-BMP/*
    d(0, 1, 0);     // Unicode/1.1/*
#undef d
    return PyUnicode_FromString("");

}
