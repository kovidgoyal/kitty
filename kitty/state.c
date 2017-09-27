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
add_window(unsigned int tab_id, unsigned int id, PyObject *title) {
    WITH_TAB(tab_id);
    ensure_can_add(tab->windows, tab->num_windows, "Too many children (add_window)");
    tab->windows[tab->num_windows] = EMPTY_WINDOW;
    tab->windows[tab->num_windows].id = id;
    tab->windows[tab->num_windows].visible = true;
    tab->windows[tab->num_windows].title = title;
    Py_INCREF(tab->windows[tab->num_windows].title);
    tab->num_windows++;
    END_WITH_TAB;
}

static inline void
update_window_title(unsigned int tab_id, unsigned int window_id, PyObject *title) {
    WITH_TAB(tab_id);
    for (size_t i = 0; i < tab->num_windows; i++) {
        if (tab->windows[i].id == window_id) {
            Py_CLEAR(tab->windows[i].title);
            tab->windows[i].title = title;
            Py_INCREF(tab->windows[i].title);
            break;
        }
    }
    END_WITH_TAB;
}

static inline void
remove_tab(unsigned int id) {
    REMOVER(global_state.tabs, id, global_state.num_tabs, EMPTY_TAB, Tab, noop);
}

static inline void
remove_window(unsigned int tab_id, unsigned int id) {
    WITH_TAB(tab_id);
#define destroy_window(w) Py_CLEAR(w.render_data.screen); Py_CLEAR(w.title);
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

static inline color_type
color_as_int(PyObject *color) {
    if (!PyTuple_Check(color)) { PyErr_SetString(PyExc_TypeError, "Not a color tuple"); return 0; }
#define I(n, s) ((PyLong_AsUnsignedLong(PyTuple_GET_ITEM(color, n)) & 0xff) << s)
    return (I(0, 16) | I(1, 8) | I(2, 0)) & 0xffffff;
#undef I
}

static inline double
repaint_delay(PyObject *val) {
    return (double)(PyLong_AsUnsignedLong(val)) / 1000.0;
}

#define dict_iter(d) { \
    PyObject *key, *value; Py_ssize_t pos = 0; \
    while (PyDict_Next(d, &pos, &key, &value))

static inline void
set_special_keys(PyObject *dict) {
    dict_iter(dict) {
        if (!PyTuple_Check(key)) { PyErr_SetString(PyExc_TypeError, "dict keys for special keys must be tuples"); return; }
        int mods = PyLong_AsLong(PyTuple_GET_ITEM(key, 0));
        int glfw_key = PyLong_AsLong(PyTuple_GET_ITEM(key, 1));
        set_special_key_combo(glfw_key, mods);
    }}
}

PYWRAP1(set_options) {
    PyObject *ret;
#define GA(name) ret = PyObject_GetAttrString(args, #name); if (ret == NULL) return NULL;
#define S(name, convert) { GA(name); global_state.opts.name = convert(ret); Py_DECREF(ret); if (PyErr_Occurred()) return NULL; }
    S(visual_bell_duration, PyFloat_AsDouble);
    S(enable_audio_bell, PyObject_IsTrue);
    S(cursor_blink_interval, PyFloat_AsDouble);
    S(cursor_stop_blinking_after, PyFloat_AsDouble);
    S(cursor_shape, PyLong_AsLong);
    S(mouse_hide_wait, PyFloat_AsDouble);
    S(wheel_scroll_multiplier, PyFloat_AsDouble);
    S(open_url_modifiers, PyLong_AsUnsignedLong);
    S(click_interval, PyFloat_AsDouble);
    S(url_color, color_as_int);
    S(repaint_delay, repaint_delay);
    S(input_delay, repaint_delay);

    PyObject *chars = PyObject_GetAttrString(args, "select_by_word_characters");
    if (chars == NULL) return NULL;
    for (size_t i = 0; i < MIN((size_t)PyUnicode_GET_LENGTH(chars), sizeof(OPT(select_by_word_characters))/sizeof(OPT(select_by_word_characters[0]))); i++) {
        OPT(select_by_word_characters)[i] = PyUnicode_READ(PyUnicode_KIND(chars), PyUnicode_DATA(chars), i);
    }
    OPT(select_by_word_characters_count) = PyUnicode_GET_LENGTH(chars);

    GA(keymap); set_special_keys(ret);
    Py_DECREF(ret); if (PyErr_Occurred()) return NULL;
    GA(send_text_map);
    dict_iter(ret) {
        set_special_keys(value);
    }}
    Py_DECREF(ret); if (PyErr_Occurred()) return NULL;

    Py_DECREF(chars);
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
#define B(name) &(g.name)
    unsigned int window_idx, tab_id;
    static ScreenRenderData d = {0};
    static WindowGeometry g = {0};
    PA("IIiffffOIIII", &tab_id, &window_idx, A(vao_idx), A(xstart), A(ystart), A(dx), A(dy), A(screen), B(left), B(top), B(right), B(bottom));

    WITH_TAB(tab_id);
    Py_CLEAR(tab->windows[window_idx].render_data.screen);
    tab->windows[window_idx].render_data = d;
    tab->windows[window_idx].geometry = g;
    Py_INCREF(tab->windows[window_idx].render_data.screen);
    END_WITH_TAB;
    Py_RETURN_NONE;
#undef A
#undef B
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

PYWRAP1(set_logical_dpi) {
    PA("dd", &global_state.logical_dpi_x, &global_state.logical_dpi_y);
    Py_RETURN_NONE;
}

PYWRAP1(set_boss) {
    Py_CLEAR(global_state.boss);
    global_state.boss = args;
    Py_INCREF(global_state.boss);
    Py_RETURN_NONE;
}

PYWRAP0(destroy_global_data) {
    Py_CLEAR(global_state.tab_bar_render_data.screen);
    Py_CLEAR(global_state.boss);
    Py_RETURN_NONE;
}

#define WF(name) PYWRAP1(name) { \
    unsigned int tab_id, window_id; \
    PyObject *title; \
    PA("IIO", &tab_id, &window_id, &title); \
    name(tab_id, window_id, title); \
    Py_RETURN_NONE; \
}
WF(add_window)
WF(update_window_title)

ONE_UINT(add_tab)
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
    MW(set_logical_dpi, METH_VARARGS),
    MW(add_tab, METH_O),
    MW(add_window, METH_VARARGS),
    MW(update_window_title, METH_VARARGS),
    MW(remove_tab, METH_O),
    MW(remove_window, METH_VARARGS),
    MW(set_active_tab, METH_O),
    MW(set_active_window, METH_VARARGS),
    MW(swap_tabs, METH_VARARGS),
    MW(swap_windows, METH_VARARGS),
    MW(set_tab_bar_render_data, METH_VARARGS),
    MW(set_window_render_data, METH_VARARGS),
    MW(update_window_visibility, METH_VARARGS),
    MW(set_boss, METH_O),
    MW(destroy_global_data, METH_NOARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool 
init_state(PyObject *module) {
    double now = monotonic();
    global_state.application_focused = true;
    global_state.cursor_blink_zero_time = now;
    global_state.last_mouse_activity_at = now;
    global_state.cell_width = 1; global_state.cell_height = 1;
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
// }}}
