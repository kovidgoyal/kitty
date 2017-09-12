/*
 * state.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define IS_STATE
#include "data-types.h"

GlobalState global_state = {{0}};
static const Tab EMPTY_TAB = {0};

#define ensure_can_add(array, count, msg) if (count >= sizeof(array)/sizeof(array[0]) - 1) fatal(msg);

#define REMOVER(array, qid, count, empty, structure) { \
    size_t capacity = sizeof(array)/sizeof(array[0]); \
    for (size_t i = 0; i < count; i++) { \
        if (array[i].id == qid) { \
            array[i] = empty; \
            size_t num_to_right = capacity - count - 1; \
            if (num_to_right) memmove(array + i, array + i + 1, num_to_right * sizeof(structure)); \
            (count)--; \
        } \
    }} 

static inline void
add_tab(unsigned int id) {
    ensure_can_add(global_state.tabs, global_state.num_tabs, "Too many children (add_tab)");
    global_state.tabs[global_state.num_tabs] = EMPTY_TAB;
    global_state.tabs[global_state.num_tabs].id = id;
    global_state.num_tabs++;
}

static inline void
remove_tab(unsigned int id) {
    REMOVER(global_state.tabs, id, global_state.num_tabs, EMPTY_TAB, Tab);
}

static inline void
set_active_tab(unsigned int idx) {
    global_state.active_tab = idx;
}

static inline void
swap_tabs(unsigned int a, unsigned int b) {
    Tab t = global_state.tabs[b];
    global_state.tabs[b] = global_state.tabs[a];
    global_state.tabs[a] = t;
}

// Python API {{{
#define PYWRAP0(name) static PyObject* py##name(PyObject UNUSED *self)
#define PYWRAP1(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args)
#define PYWRAP2(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args, PyObject *kw)
#define PA(fmt, ...) if(!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;
#define ONE_UINT(name) PYWRAP1(name) { name((unsigned int)PyLong_AsUnsignedLong(args)); Py_RETURN_NONE; }
#define TWO_UINT(name) PYWRAP1(name) { unsigned int a, b; PA("II", &a, &b); name(a, b); Py_RETURN_NONE; }

PYWRAP1(set_options) {
#define S(name, convert) { PyObject *ret = PyObject_GetAttrString(args, #name); if (ret == NULL) return NULL; global_state.opts.name = convert(ret); Py_DECREF(ret); }
    S(visual_bell_duration, PyFloat_AsDouble);
    S(enable_audio_bell, PyObject_IsTrue);
#undef S
    Py_RETURN_NONE;
}

PYWRAP1(set_tab_bar_render_data) {
#define A(name) &(global_state.tab_bar_render_data.name)
    Py_CLEAR(global_state.tab_bar_render_data.screen);
    PA("iffffO", A(vao_idx), A(xstart), A(ystart), A(dx), A(dy), A(screen));
    Py_INCREF(global_state.tab_bar_render_data.screen);
    Py_RETURN_NONE;
#undef A
}

PYWRAP0(destroy_global_data) {
    Py_CLEAR(global_state.tab_bar_render_data.screen);
    Py_RETURN_NONE;
}

ONE_UINT(add_tab)
ONE_UINT(remove_tab)
ONE_UINT(set_active_tab)
TWO_UINT(swap_tabs)

#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, NULL}
#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}

static PyMethodDef module_methods[] = {
    MW(set_options, METH_O),
    MW(add_tab, METH_O),
    MW(remove_tab, METH_O),
    MW(set_active_tab, METH_O),
    MW(swap_tabs, METH_VARARGS),
    MW(set_tab_bar_render_data, METH_VARARGS),
    MW(destroy_global_data, METH_NOARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool 
init_state(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
// }}}
