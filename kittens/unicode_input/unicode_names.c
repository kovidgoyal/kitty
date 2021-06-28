/*
 * unicode_names.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "names.h"

static PyObject*
all_words(PYNOARG) {
    PyObject *ans = PyTuple_New(arraysz(all_words_map));
    if (!ans) return NULL;
    for (size_t i = 0; i < arraysz(all_words_map); i++) {
        PyObject *w = PyUnicode_FromString(all_words_map[i]);
        if (w == NULL) { Py_DECREF(ans); return NULL; }
        PyTuple_SET_ITEM(ans, i, w);
    }
    return ans;
}

static void
add_matches(const word_trie *wt, PyObject *ans) {
    size_t num = mark_groups[wt->match_offset];
    for (size_t i = wt->match_offset + 1; i < wt->match_offset + 1 + num; i++) {
        PyObject *t = PyLong_FromUnsignedLong(mark_to_cp[mark_groups[i]]);
        if (!t) return;
        int ret = PySet_Add(ans, t);
        Py_DECREF(t);
        if (ret != 0) return;
    }
}

static void
process_trie_node(const word_trie *wt, PyObject *ans) {
    if (wt->match_offset) { add_matches(wt, ans); if (PyErr_Occurred()) return; }
    size_t num_children = children_array[wt->children_offset];
    if (!num_children) return;
    for (size_t c = wt->children_offset + 1; c < wt->children_offset + 1 + num_children; c++) {
        uint32_t x = children_array[c];
        process_trie_node(&all_trie_nodes[x >> 8], ans);
        if (PyErr_Occurred()) return;
    }
}

static PyObject*
codepoints_for_word(const char *word, size_t len) {
    const word_trie *wt = all_trie_nodes;
    for (size_t i = 0; i < len; i++) {
        unsigned char ch = word[i];
        size_t num_children = children_array[wt->children_offset];
        if (!num_children) return PyFrozenSet_New(NULL);
        bool found = false;
        for (size_t c = wt->children_offset + 1; c < wt->children_offset + 1 + num_children; c++) {
            uint32_t x = children_array[c];
            if ((x & 0xff) == ch) {
                found = true;
                wt = &all_trie_nodes[x >> 8];
                break;
            }
        }
        if (!found) return PyFrozenSet_New(NULL);
    }
    PyObject *ans = PyFrozenSet_New(NULL);
    if (!ans) return NULL;
    process_trie_node(wt, ans);
    if (PyErr_Occurred()) return NULL;
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
    {"all_words", (PyCFunction)all_words, METH_NOARGS, ""},
    {"codepoints_for_word", (PyCFunction)cfw, METH_VARARGS, ""},
    {"name_for_codepoint", (PyCFunction)nfc, METH_VARARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

#if PY_VERSION_HEX >= 0x03000000
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
#else
EXPORTED
initunicode_names(void) {
    PyObject *m;
    m = Py_InitModule3("unicode_names", module_methods,
    ""
    );
    if (m == NULL) return;
}
#endif
