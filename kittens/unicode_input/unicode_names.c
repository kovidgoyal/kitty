/*
 * unicode_names.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "names.h"

static PyObject*
all_words(PYNOARG) {
    PyObject *ans = PyTuple_New(arraysz(idx_to_word));
    if (!ans) return NULL;
    for (size_t i = 0; i < arraysz(idx_to_word); i++) {
        PyObject *w = PyUnicode_FromString(idx_to_word[i]);
        if (w == NULL) { Py_DECREF(ans); return NULL; }
        PyTuple_SET_ITEM(ans, i, w);
    }
    return ans;
}

static inline PyObject*
codepoints_for_word(const char *word, size_t len) {
    PyObject *ans = PyFrozenSet_New(NULL); if (ans == NULL) return NULL;
    const unsigned short *words = words_for_first_letter[(unsigned)*word];
    if (words == NULL) return ans;
    for (unsigned short i = 1; i <= words[0]; i++) {
        unsigned short word_idx = words[i];
        const char *w = idx_to_word[word_idx];
        if (strncmp(word, w, len) == 0 && strlen(w) == len) {
            const char_type* codepoints = codepoints_for_word_idx[word_idx];
            for (char_type i = 1; i <= codepoints[0]; i++) {
                PyObject *t = PyLong_FromUnsignedLong(codepoints[i]); if (t == NULL) { Py_DECREF(ans); return NULL; }
                int ret = PySet_Add(ans, t); Py_DECREF(t); if (ret != 0) { Py_DECREF(ans); return NULL; }
            }
            break;
        }
    }
    return ans;
}

static PyObject*
cfw(PyObject *self UNUSED, PyObject *args) {
    const char *word;
    if (!PyArg_ParseTuple(args, "s", &word)) return NULL;
    return codepoints_for_word(word, strlen(word));
}

static PyObject*
nfc(PyObject *self UNUSED, PyObject *args) {
    unsigned int cp;
    if (!PyArg_ParseTuple(args, "I", &cp)) return NULL;
    const char *n = name_for_codepoint(cp);
    if (n == NULL) Py_RETURN_NONE;
    return PyUnicode_FromString(n);
}

static PyMethodDef module_methods[] = {
    METHODB(all_words, METH_NOARGS),
    {"codepoints_for_word", (PyCFunction)cfw, METH_VARARGS, ""},
    {"name_for_codepoint", (PyCFunction)nfc, METH_VARARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static struct PyModuleDef module = {
   .m_base = PyModuleDef_HEAD_INIT,
   .m_name = "unicode_names",   /* name of module */
   .m_doc = NULL,
   .m_size = -1,
   .m_methods = module_methods
};


EXPORTED PyMODINIT_FUNC
PyInit_unicode_names(void) {
    PyObject *m;

    m = PyModule_Create(&module);
    if (m == NULL) return NULL;
    return m;
}
