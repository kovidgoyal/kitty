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
#define WITH_OS_WINDOW(os_window_id) \
    for (size_t o = 0; o < global_state.num_os_windows; o++) { \
        OSWindow *os_window = global_state.os_windows + o; \
        if (os_window->window_id == os_window_id) { 
#define END_WITH_OS_WINDOW break; }}

#define WITH_TAB(os_window_id, tab_id) \
    for (size_t o = 0; o < global_state.num_os_windows; o++) { \
        OSWindow *osw = global_state.os_windows + o; \
        if (osw->window_id == os_window_id) { \
            for (size_t t = 0; t < osw->num_tabs; t++) { \
                if (osw->tabs[t].id == tab_id) { \
                    Tab *tab = osw->tabs + t;
#define END_WITH_TAB break; }}}}

OSWindow* 
current_os_window() {
    if (global_state.callback_os_window) return global_state.callback_os_window;
    if (global_state.focussed_os_window) return global_state.focussed_os_window;
    return global_state.os_windows;
}

OSWindow*
os_window_for_kitty_window(id_type kitty_window_id) {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        for (size_t t = 0; t < w->num_tabs; t++) {
            Tab *tab = w->tabs + t;
            for (size_t c = 0; c < tab->num_windows; c++) {
                if (tab->windows[c].id == kitty_window_id) return w;
            }
        }
    }
    return NULL;
}

static inline void
add_tab(id_type os_window_id, id_type id) {
    WITH_OS_WINDOW(os_window_id)
        ensure_can_add(os_window->tabs, os_window->num_tabs, "Too many children (add_tab)");
        os_window->tabs[os_window->num_tabs] = EMPTY_TAB;
        os_window->tabs[os_window->num_tabs].id = id;
        os_window->num_tabs++;
    END_WITH_OS_WINDOW
}

static inline void
add_window(id_type os_window_id, id_type tab_id, id_type id, PyObject *title) {
    WITH_TAB(os_window_id, tab_id);
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
update_window_title(id_type os_window_id, id_type tab_id, id_type window_id, PyObject *title) {
    WITH_TAB(os_window_id, tab_id);
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
remove_tab(id_type os_window_id, id_type id) {
    WITH_OS_WINDOW(os_window_id)
        REMOVER(os_window->tabs, id, os_window->num_tabs, EMPTY_TAB, Tab, noop);
    END_WITH_OS_WINDOW
}

static inline void
remove_window(id_type os_window_id, id_type tab_id, id_type id) {
    WITH_TAB(os_window_id, tab_id);
#define destroy_window(w) Py_CLEAR(w.render_data.screen); Py_CLEAR(w.title);
    REMOVER(tab->windows, id, tab->num_windows, EMPTY_WINDOW, Window, destroy_window);
#undef destroy_window
    END_WITH_TAB;
}


static inline void
set_active_tab(id_type os_window_id, unsigned int idx) {
    WITH_OS_WINDOW(os_window_id)
        os_window->active_tab = idx;
    END_WITH_OS_WINDOW
}

static inline void
set_active_window(id_type os_window_id, id_type tab_id, unsigned int idx) {
    WITH_TAB(os_window_id, tab_id)
        tab->active_window = idx;
    END_WITH_TAB;
}

static inline void
swap_tabs(id_type os_window_id, unsigned int a, unsigned int b) {
    WITH_OS_WINDOW(os_window_id)
        Tab t = os_window->tabs[b];
        os_window->tabs[b] = os_window->tabs[a];
        os_window->tabs[a] = t;
    END_WITH_OS_WINDOW
}

static inline void
swap_windows(id_type os_window_id, id_type tab_id, unsigned int a, unsigned int b) {
    WITH_TAB(os_window_id, tab_id);
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
#define TWO_ID(name) PYWRAP1(name) { id_type a, b; PA("KK", &a, &b); name(a, b); Py_RETURN_NONE; }
#define THREE_ID(name) PYWRAP1(name) { id_type a, b, c; PA("KKK", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define THREE_ID_OBJ(name) PYWRAP1(name) { id_type a, b, c; PyObject *o; PA("KKKO", &a, &b, &c, &o); name(a, b, c, o); Py_RETURN_NONE; }
#define KI(name) PYWRAP1(name) { id_type a; unsigned int b; PA("KI", &a, &b); name(a, b); Py_RETURN_NONE; }
#define KII(name) PYWRAP1(name) { id_type a; unsigned int b, c; PA("KII", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define KKI(name) PYWRAP1(name) { id_type a, b; unsigned int c; PA("KKI", &a, &b, &c); name(a, b, c); Py_RETURN_NONE; }
#define KKII(name) PYWRAP1(name) { id_type a, b; unsigned int c, d; PA("KKII", &a, &b, &c, &d); name(a, b, c, d); Py_RETURN_NONE; }

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
    S(focus_follows_mouse, PyObject_IsTrue);
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
    S(macos_option_as_alt, PyObject_IsTrue);
    S(macos_hide_titlebar, PyObject_IsTrue);

    PyObject *chars = PyObject_GetAttrString(args, "select_by_word_characters");
    if (chars == NULL) return NULL;
    for (size_t i = 0; i < MIN((size_t)PyUnicode_GET_LENGTH(chars), sizeof(OPT(select_by_word_characters))/sizeof(OPT(select_by_word_characters[0]))); i++) {
        OPT(select_by_word_characters)[i] = PyUnicode_READ(PyUnicode_KIND(chars), PyUnicode_DATA(chars), i);
    }
    OPT(select_by_word_characters_count) = PyUnicode_GET_LENGTH(chars);
    Py_DECREF(chars);

    GA(keymap); set_special_keys(ret);
    Py_DECREF(ret); if (PyErr_Occurred()) return NULL;

    PyObject *al = PyObject_GetAttrString(args, "adjust_line_height");
    if (PyFloat_Check(al)) { 
        OPT(adjust_line_height_frac) = (float)PyFloat_AsDouble(al);
        OPT(adjust_line_height_px) = 0;
    } else {
        OPT(adjust_line_height_frac) = 0;
        OPT(adjust_line_height_px) = (int)PyLong_AsLong(al);
    }
    Py_DECREF(al);
#undef S
    Py_RETURN_NONE;
}

PYWRAP1(set_tab_bar_render_data) {
#define A(name) &(d.name)
    ScreenRenderData d = {0};
    id_type os_window_id;
    PA("KiffffO", &os_window_id, A(vao_idx), A(xstart), A(ystart), A(dx), A(dy), A(screen));
    WITH_OS_WINDOW(os_window_id)
        Py_CLEAR(os_window->tab_bar_render_data.screen);
        Py_INCREF(os_window->tab_bar_render_data.screen);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
#undef A
}

PYWRAP1(set_window_render_data) {
#define A(name) &(d.name)
#define B(name) &(g.name)
    id_type os_window_id, tab_id;
    unsigned int window_idx;
    ScreenRenderData d = {0};
    WindowGeometry g = {0};
    PA("KIiiffffOIIII", &os_window_id, &tab_id, &window_idx, A(vao_idx), A(gvao_idx), A(xstart), A(ystart), A(dx), A(dy), A(screen), B(left), B(top), B(right), B(bottom));

    WITH_TAB(os_window_id, tab_id);
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
    id_type os_window_id;
    unsigned int window_idx, tab_id;
    int visible;
    PA("KIIp", &os_window_id, &tab_id, &window_idx, &visible);
    WITH_TAB(os_window_id, tab_id);
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
    Py_CLEAR(global_state.boss);
    Py_RETURN_NONE;
}

PYWRAP1(set_display_state) {
    int vw, vh;
    PA("iiII", &vw, &vh, &global_state.cell_width, &global_state.cell_height);
    Py_RETURN_NONE;
}

THREE_ID_OBJ(add_window)
THREE_ID_OBJ(update_window_title)
THREE_ID(remove_window)
TWO_ID(add_tab)
TWO_ID(remove_tab)
KI(set_active_tab)
KKI(set_active_window)
KII(swap_tabs)
KKII(swap_windows)

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
    MW(set_display_state, METH_VARARGS),
    MW(destroy_global_data, METH_NOARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool 
init_state(PyObject *module) {
    global_state.cell_width = 1; global_state.cell_height = 1;
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
// }}}
