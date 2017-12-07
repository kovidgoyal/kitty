/*
 * state.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"

GlobalState global_state = {{0}};

#define REMOVER(array, qid, count, structure, destroy, capacity) { \
    for (size_t i = 0; i < count; i++) { \
        if (array[i].id == qid) { \
            destroy(array + i); \
            memset(array + i, 0, sizeof(structure)); \
            size_t num_to_right = count - 1 - i; \
            if (num_to_right) memmove(array + i, array + i + 1, num_to_right * sizeof(structure)); \
            (count)--; \
            break; \
        } \
    }} 

#define WITH_OS_WINDOW(os_window_id) \
    for (size_t o = 0; o < global_state.num_os_windows; o++) { \
        OSWindow *os_window = global_state.os_windows + o; \
        if (os_window->id == os_window_id) { 
#define END_WITH_OS_WINDOW break; }}

#define WITH_TAB(os_window_id, tab_id) \
    for (size_t o = 0; o < global_state.num_os_windows; o++) { \
        OSWindow *osw = global_state.os_windows + o; \
        if (osw->id == os_window_id) { \
            for (size_t t = 0; t < osw->num_tabs; t++) { \
                if (osw->tabs[t].id == tab_id) { \
                    Tab *tab = osw->tabs + t;
#define END_WITH_TAB break; }}}}

#define WITH_OS_WINDOW_REFS \
    id_type cb_window_id = 0, focused_window_id = 0; \
    if (global_state.callback_os_window) cb_window_id = global_state.callback_os_window->id; \

#define END_WITH_OS_WINDOW_REFS \
    if (cb_window_id || focused_window_id) { \
        global_state.callback_os_window = NULL; \
        for (size_t wn = 0; wn < global_state.num_os_windows; wn++) { \
            OSWindow *wp = global_state.os_windows + wn; \
            if (wp->id == cb_window_id && cb_window_id) global_state.callback_os_window = wp; \
    }}


OSWindow* 
current_os_window() {
    if (global_state.callback_os_window) return global_state.callback_os_window;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        if (global_state.os_windows[i].is_focused) return global_state.os_windows + i;
    }
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

OSWindow*
add_os_window() {
    WITH_OS_WINDOW_REFS
    ensure_space_for(&global_state, os_windows, OSWindow, global_state.num_os_windows + 1, capacity, 1, true);
    OSWindow *ans = global_state.os_windows + global_state.num_os_windows++;
    memset(ans, 0, sizeof(OSWindow));
    ans->id = ++global_state.os_window_id_counter;
    ans->tab_bar_render_data.vao_idx = create_cell_vao();
    END_WITH_OS_WINDOW_REFS
    return ans;
}

static inline id_type
add_tab(id_type os_window_id) {
    WITH_OS_WINDOW(os_window_id)
        ensure_space_for(os_window, tabs, Tab, os_window->num_tabs + 1, capacity, 1, true);
        memset(os_window->tabs + os_window->num_tabs, 0, sizeof(Tab));
        os_window->tabs[os_window->num_tabs].id = ++global_state.tab_id_counter;
        os_window->tabs[os_window->num_tabs].border_rects.vao_idx = create_border_vao();
        return os_window->tabs[os_window->num_tabs++].id;
    END_WITH_OS_WINDOW
    return 0;
}

static inline id_type
add_window(id_type os_window_id, id_type tab_id, PyObject *title) {
    WITH_TAB(os_window_id, tab_id);
        ensure_space_for(tab, windows, Window, tab->num_windows + 1, capacity, 1, true);
        make_os_window_context_current(osw);
        memset(tab->windows + tab->num_windows, 0, sizeof(Window));
        tab->windows[tab->num_windows].id = ++global_state.window_id_counter;
        tab->windows[tab->num_windows].visible = true;
        tab->windows[tab->num_windows].title = title;
        tab->windows[tab->num_windows].render_data.vao_idx = create_cell_vao();
        tab->windows[tab->num_windows].render_data.gvao_idx = create_graphics_vao();
        Py_INCREF(tab->windows[tab->num_windows].title);
        return tab->windows[tab->num_windows++].id;
    END_WITH_TAB;
    return 0;
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
destroy_window(Window *w) {
    Py_CLEAR(w->render_data.screen); Py_CLEAR(w->title);
    remove_vao(w->render_data.vao_idx); remove_vao(w->render_data.gvao_idx);
}

static inline void
remove_window_inner(Tab *tab, id_type id) {
    REMOVER(tab->windows, id, tab->num_windows, Window, destroy_window, tab->capacity);
}

static inline void
remove_window(id_type os_window_id, id_type tab_id, id_type id) {
    WITH_TAB(os_window_id, tab_id);
        make_os_window_context_current(osw);
        remove_window_inner(tab, id);
    END_WITH_TAB;
}

static inline void
destroy_tab(Tab *tab) {
    for (size_t i = tab->num_windows; i > 0; i--) remove_window_inner(tab, tab->windows[i - 1].id);
    remove_vao(tab->border_rects.vao_idx);
    free(tab->border_rects.rect_buf); tab->border_rects.rect_buf = NULL;
    free(tab->windows); tab->windows = NULL;
}

static inline void
remove_tab_inner(OSWindow *os_window, id_type id) {
    make_os_window_context_current(os_window);
    REMOVER(os_window->tabs, id, os_window->num_tabs, Tab, destroy_tab, os_window->capacity);
}

static inline void
remove_tab(id_type os_window_id, id_type id) {
    WITH_OS_WINDOW(os_window_id)
        remove_tab_inner(os_window, id);
    END_WITH_OS_WINDOW
}

static inline void
destroy_os_window_item(OSWindow *w) {
    for (size_t t = w->num_tabs; t > 0; t--) {
        Tab *tab = w->tabs + t - 1;
        remove_tab_inner(w, tab->id);
    }
    Py_CLEAR(w->window_title); Py_CLEAR(w->tab_bar_render_data.screen);
    if (w->offscreen_texture_id) free_texture(&w->offscreen_texture_id);
    remove_vao(w->tab_bar_render_data.vao_idx);
    free(w->tabs); w->tabs = NULL;
}

bool
remove_os_window(id_type os_window_id) {
    bool found = false;
    WITH_OS_WINDOW(os_window_id)
        found = true;
        make_os_window_context_current(os_window);
    END_WITH_OS_WINDOW
    if (found) { 
        WITH_OS_WINDOW_REFS
            REMOVER(global_state.os_windows, os_window_id, global_state.num_os_windows, OSWindow, destroy_os_window_item, global_state.capacity);
        END_WITH_OS_WINDOW_REFS
        update_os_window_references();
    }
    return found;
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

static void
add_borders_rect(id_type os_window_id, id_type tab_id, uint32_t left, uint32_t top, uint32_t right, uint32_t bottom, uint32_t color) {
    WITH_TAB(os_window_id, tab_id)
        BorderRects *br = &tab->border_rects;
        br->is_dirty = true;
        if (!left && !top && !right && !bottom) { br->num_border_rects = 0; return; }
        ensure_space_for(br, rect_buf, BorderRect, br->num_border_rects + 1, capacity, 32, false);
        BorderRect *r = br->rect_buf + br->num_border_rects++;
        r->left = left; r->right = right; r->top = top; r->bottom = bottom; r->color = color;
    END_WITH_TAB
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
#define KK5I(name) PYWRAP1(name) { id_type a, b; unsigned int c, d, e, f, g; PA("KKIIIII", &a, &b, &c, &d, &e, &f, &g); name(a, b, c, d, e, f, g); Py_RETURN_NONE; }

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

PYWRAP1(handle_for_window_id) {
    id_type os_window_id;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        return PyLong_FromVoidPtr(os_window->handle);
    END_WITH_OS_WINDOW
    PyErr_SetString(PyExc_ValueError, "No such window");
    return NULL;
}

PYWRAP1(set_options) {
    PyObject *ret, *opts;
    int is_wayland, debug_gl = 0;
    PA("Op|p", &opts, &is_wayland, &debug_gl);
    global_state.is_wayland = is_wayland ? true : false;
    global_state.debug_gl = debug_gl ? true : false;
#define GA(name) ret = PyObject_GetAttrString(opts, #name); if (ret == NULL) return NULL;
#define S(name, convert) { GA(name); global_state.opts.name = convert(ret); Py_DECREF(ret); if (PyErr_Occurred()) return NULL; }
    S(visual_bell_duration, PyFloat_AsDouble);
    S(enable_audio_bell, PyObject_IsTrue);
    S(prefer_color_emoji, PyObject_IsTrue);
    S(focus_follows_mouse, PyObject_IsTrue);
    S(cursor_blink_interval, PyFloat_AsDouble);
    S(cursor_stop_blinking_after, PyFloat_AsDouble);
    S(background_opacity, PyFloat_AsDouble);
    S(cursor_shape, PyLong_AsLong);
    S(url_style, PyLong_AsUnsignedLong);
    S(x11_bell_volume, PyLong_AsLong);
    S(mouse_hide_wait, PyFloat_AsDouble);
    S(wheel_scroll_multiplier, PyFloat_AsDouble);
    S(open_url_modifiers, PyLong_AsUnsignedLong);
    S(click_interval, PyFloat_AsDouble);
    S(url_color, color_as_int);
    S(background, color_as_int);
    S(repaint_delay, repaint_delay);
    S(input_delay, repaint_delay);
    S(macos_option_as_alt, PyObject_IsTrue);
    S(macos_hide_titlebar, PyObject_IsTrue);

    PyObject *chars = PyObject_GetAttrString(opts, "select_by_word_characters");
    if (chars == NULL) return NULL;
    for (size_t i = 0; i < MIN((size_t)PyUnicode_GET_LENGTH(chars), sizeof(OPT(select_by_word_characters))/sizeof(OPT(select_by_word_characters[0]))); i++) {
        OPT(select_by_word_characters)[i] = PyUnicode_READ(PyUnicode_KIND(chars), PyUnicode_DATA(chars), i);
    }
    OPT(select_by_word_characters_count) = PyUnicode_GET_LENGTH(chars);
    Py_DECREF(chars);

    GA(keymap); set_special_keys(ret);
    Py_DECREF(ret); if (PyErr_Occurred()) return NULL;

    PyObject *al = PyObject_GetAttrString(opts, "adjust_line_height");
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
    ScreenRenderData d = {0};
    id_type os_window_id;
    PA("KffffO", &os_window_id, &d.xstart, &d.ystart, &d.dx, &d.dy, &d.screen);
    WITH_OS_WINDOW(os_window_id)
        Py_CLEAR(os_window->tab_bar_render_data.screen);
        d.vao_idx = os_window->tab_bar_render_data.vao_idx;
        os_window->tab_bar_render_data = d;
        Py_INCREF(os_window->tab_bar_render_data.screen);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(viewport_for_window) {
    id_type os_window_id = 0;
    PA("|K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        int available_height = os_window->viewport_height;
        if (os_window->num_tabs > 1) available_height -= global_state.cell_height;
        return Py_BuildValue("iiiII", os_window->viewport_width, os_window->viewport_height, available_height, global_state.cell_width, global_state.cell_height);
    END_WITH_OS_WINDOW
    return Py_BuildValue("iiII", 400, 400, global_state.cell_width, global_state.cell_height);
}

PYWRAP1(mark_os_window_for_close) {
    id_type os_window_id;
    int yes = 1;
    PA("K|p", &os_window_id, &yes);
    WITH_OS_WINDOW(os_window_id)
        mark_os_window_for_close(os_window, yes ? true : false);
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(set_window_render_data) {
#define A(name) &(d.name)
#define B(name) &(g.name)
    id_type os_window_id, tab_id;
    unsigned int window_idx;
    ScreenRenderData d = {0};
    WindowGeometry g = {0};
    PA("KKIffffOIIII", &os_window_id, &tab_id, &window_idx, A(xstart), A(ystart), A(dx), A(dy), A(screen), B(left), B(top), B(right), B(bottom));

    WITH_TAB(os_window_id, tab_id);
        Py_CLEAR(tab->windows[window_idx].render_data.screen);
        d.vao_idx = tab->windows[window_idx].render_data.vao_idx;
        d.gvao_idx = tab->windows[window_idx].render_data.gvao_idx;
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
    free(global_state.os_windows); global_state.os_windows = NULL;
    Py_RETURN_NONE;
}

PYWRAP1(set_display_state) {
    int vw, vh;
    PA("iiII", &vw, &vh, &global_state.cell_width, &global_state.cell_height);
    Py_RETURN_NONE;
}

THREE_ID_OBJ(update_window_title)
THREE_ID(remove_window)
PYWRAP1(add_tab) { return PyLong_FromUnsignedLongLong(add_tab(PyLong_AsUnsignedLongLong(args))); }
PYWRAP1(add_window) { PyObject *title; id_type a, b; PA("KKO", &a, &b, &title); return PyLong_FromUnsignedLongLong(add_window(a, b, title)); }
PYWRAP0(current_os_window) { OSWindow *w = current_os_window(); if (!w) Py_RETURN_NONE; return PyLong_FromUnsignedLongLong(w->id); }
TWO_ID(remove_tab)
KI(set_active_tab)
KKI(set_active_window)
KII(swap_tabs)
KKII(swap_windows)
KK5I(add_borders_rect)

#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, NULL}
#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}

static PyMethodDef module_methods[] = {
    MW(current_os_window, METH_NOARGS),
    MW(set_options, METH_VARARGS),
    MW(handle_for_window_id, METH_VARARGS),
    MW(set_logical_dpi, METH_VARARGS),
    MW(add_tab, METH_O),
    MW(add_window, METH_VARARGS),
    MW(update_window_title, METH_VARARGS),
    MW(remove_tab, METH_VARARGS),
    MW(remove_window, METH_VARARGS),
    MW(set_active_tab, METH_VARARGS),
    MW(set_active_window, METH_VARARGS),
    MW(swap_tabs, METH_VARARGS),
    MW(swap_windows, METH_VARARGS),
    MW(add_borders_rect, METH_VARARGS),
    MW(set_tab_bar_render_data, METH_VARARGS),
    MW(set_window_render_data, METH_VARARGS),
    MW(viewport_for_window, METH_VARARGS),
    MW(mark_os_window_for_close, METH_VARARGS),
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
