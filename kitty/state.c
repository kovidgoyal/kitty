/*
 * state.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"

GlobalState global_state = {{0}};
static const Tab EMPTY_TAB = {0};
static const Window EMPTY_WINDOW = {0};

#define ensure_can_add(array, count, msg) if (count >= sizeof(array)/sizeof(array[0]) - 1) fatal(msg);

#define noop(...)
#define REMOVER(array, qid, count, empty, structure, destroy) { \
    size_t capacity = sizeof(array)/sizeof(array[0]); \
    for (size_t i = 0; i < count; i++) { \
        if (array[i].id == qid) { \
            destroy(array[i]); \
            array[i] = empty; \
            size_t num_to_right = capacity - count - 1; \
            if (num_to_right) memmove(array + i, array + i + 1, num_to_right * sizeof(structure)); \
            (count)--; \
        } \
    }} 
#define WITH_TAB(tab_id) \
    for (size_t t = 0; t < global_state.num_tabs; t++) { \
        if (global_state.tabs[t].id == tab_id) { \
            Tab *tab = global_state.tabs + t;
#define END_WITH_TAB break; }}

static inline void
add_tab(unsigned int id) {
    ensure_can_add(global_state.tabs, global_state.num_tabs, "Too many children (add_tab)");
    global_state.tabs[global_state.num_tabs] = EMPTY_TAB;
    global_state.tabs[global_state.num_tabs].id = id;
    global_state.num_tabs++;
}

static inline void
add_window(unsigned int tab_id, unsigned int id) {
    WITH_TAB(tab_id);
    ensure_can_add(tab->windows, tab->num_windows, "Too many children (add_window)");
    tab->windows[tab->num_windows] = EMPTY_WINDOW;
    tab->windows[tab->num_windows].id = id;
    tab->windows[tab->num_windows].visible = true;
    tab->num_windows++;
    END_WITH_TAB;
}

static inline void
remove_tab(unsigned int id) {
    REMOVER(global_state.tabs, id, global_state.num_tabs, EMPTY_TAB, Tab, noop);
}

static inline void
remove_window(unsigned int tab_id, unsigned int id) {
    WITH_TAB(tab_id);
#define destroy_window(w) Py_CLEAR(w.render_data.screen)
    REMOVER(tab->windows, id, tab->num_windows, EMPTY_WINDOW, Window, destroy_window);
#undef destroy_window
    END_WITH_TAB;
}


static inline void
set_active_tab(unsigned int idx) {
    global_state.active_tab = idx;
}

static inline void
set_active_window(unsigned int tab_id, unsigned int idx) {
    WITH_TAB(tab_id);
    tab->active_window = idx;
    END_WITH_TAB;
}

static inline void
swap_tabs(unsigned int a, unsigned int b) {
    Tab t = global_state.tabs[b];
    global_state.tabs[b] = global_state.tabs[a];
    global_state.tabs[a] = t;
}

static inline void
swap_windows(unsigned int tab_id, unsigned int a, unsigned int b) {
    WITH_TAB(tab_id);
    Window w = tab->windows[b];
    tab->windows[b] = tab->windows[a];
    tab->windows[a] = w;
    END_WITH_TAB;
}

// Python API {{{
#define PYWRAP0(name) static PyObject* py##name(PyObject UNUSED *self)
#define PYWRAP1(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args)
#define PYWRAP2(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args, PyObject *kw)
#define PA(fmt, ...) if(!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;
#define ONE_UINT(name) PYWRAP1(name) { name((unsigned int)PyLong_AsUnsignedLong(args)); Py_RETURN_NONE; }
#define TWO_UINT(name) PYWRAP1(name) { unsigned int a, b; PA("II", &a, &b); name(a, b); Py_RETURN_NONE; }
#define THREE_UINT(name) PYWRAP1(name) { unsigned int a, b, c; PA("III", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }

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

PYWRAP1(set_window_render_data) {
#define A(name) &(d.name)
    unsigned int window_idx, tab_id;
    ScreenRenderData d = {0};
    PA("IIiffffO", &tab_id, &window_idx, A(vao_idx), A(xstart), A(ystart), A(dx), A(dy), A(screen));

    WITH_TAB(tab_id);
    Py_CLEAR(tab->windows[window_idx].render_data.screen);
    tab->windows[window_idx].render_data = d;
    Py_INCREF(tab->windows[window_idx].render_data.screen);
    END_WITH_TAB;
    Py_RETURN_NONE;
#undef A
}

PYWRAP1(update_window_visibility) {
    unsigned int window_idx, tab_id;
    int visible;
    PA("IIp", &tab_id, &window_idx, &visible);
    WITH_TAB(tab_id);
    tab->windows[window_idx].visible = visible & 1;
    END_WITH_TAB;
    Py_RETURN_NONE;
}

PYWRAP0(destroy_global_data) {
    Py_CLEAR(global_state.tab_bar_render_data.screen);
    Py_RETURN_NONE;
}

ONE_UINT(add_tab)
TWO_UINT(add_window)
ONE_UINT(remove_tab)
TWO_UINT(remove_window)
ONE_UINT(set_active_tab)
TWO_UINT(set_active_window)
TWO_UINT(swap_tabs)
THREE_UINT(swap_windows)

#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, NULL}
#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}

static PyMethodDef module_methods[] = {
    MW(set_options, METH_O),
    MW(add_tab, METH_O),
    MW(add_window, METH_VARARGS),
    MW(remove_tab, METH_O),
    MW(remove_window, METH_VARARGS),
    MW(set_active_tab, METH_O),
    MW(set_active_window, METH_VARARGS),
    MW(swap_tabs, METH_VARARGS),
    MW(swap_windows, METH_VARARGS),
    MW(set_tab_bar_render_data, METH_VARARGS),
    MW(set_window_render_data, METH_VARARGS),
    MW(update_window_visibility, METH_VARARGS),
    MW(destroy_global_data, METH_NOARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool 
init_state(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
// }}}
