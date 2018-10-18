/*
 * state.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include <math.h>

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
    ans->background_opacity = OPT(background_opacity);
    ans->font_sz_in_pts = global_state.font_sz_in_pts;
    END_WITH_OS_WINDOW_REFS
    return ans;
}

static inline id_type
add_tab(id_type os_window_id) {
    WITH_OS_WINDOW(os_window_id)
        make_os_window_context_current(os_window);
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
        os_window->needs_render = true;
    END_WITH_OS_WINDOW
}

static inline void
set_active_window(id_type os_window_id, id_type tab_id, unsigned int idx) {
    WITH_TAB(os_window_id, tab_id)
        tab->active_window = idx;
        osw->needs_render = true;
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


void
os_window_regions(OSWindow *os_window, Region *central, Region *tab_bar) {
    if (os_window->num_tabs > 1) {
        switch(OPT(tab_bar_edge)) {
            case TOP_EDGE:
                central->left = 0; central->top = os_window->fonts_data->cell_height; central->right = os_window->viewport_width - 1;
                central->bottom = os_window->viewport_height - 1;
                tab_bar->left = central->left; tab_bar->right = central->right; tab_bar->top = 0;
                tab_bar->bottom = central->top - 1;
                break;
            default:
                central->left = 0; central->top = 0; central->right = os_window->viewport_width - 1;
                central->bottom = os_window->viewport_height - os_window->fonts_data->cell_height - 1;
                tab_bar->left = central->left; tab_bar->right = central->right; tab_bar->top = central->bottom + 1;
                tab_bar->bottom = os_window->viewport_height - 1;
                break;
        }
    } else {
        memset(tab_bar, 0, sizeof(Region));
        central->left = 0; central->top = 0; central->right = os_window->viewport_width - 1;
        central->bottom = os_window->viewport_height - 1;
    }
}


// Python API {{{
#define PYWRAP0(name) static PyObject* py##name(PYNOARG)
#define PYWRAP1(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args)
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
#define BOOL_SET(name) PYWRAP1(set_##name) { global_state.name = PyObject_IsTrue(args); Py_RETURN_NONE; }

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

static int kitty_mod = 0;

static inline int
resolve_mods(int mods) {
    if (mods & GLFW_MOD_KITTY) {
        mods = (mods & ~GLFW_MOD_KITTY) | kitty_mod;
    }
    return mods;
}

static int
convert_mods(PyObject *obj) {
    return resolve_mods(PyLong_AsLong(obj));
}

static inline void
set_special_keys(PyObject *dict) {
    dict_iter(dict) {
        if (!PyTuple_Check(key)) { PyErr_SetString(PyExc_TypeError, "dict keys for special keys must be tuples"); return; }
        int mods = PyLong_AsLong(PyTuple_GET_ITEM(key, 0));
        bool is_native = PyTuple_GET_ITEM(key, 1) == Py_True;
        int glfw_key = PyLong_AsLong(PyTuple_GET_ITEM(key, 2));
        set_special_key_combo(glfw_key, mods, is_native);
    }}
}

PYWRAP0(next_window_id) {
    return PyLong_FromUnsignedLongLong(global_state.window_id_counter + 1);
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
    int is_wayland = 0, debug_gl = 0, debug_font_fallback = 0;
    PA("O|ppp", &opts, &is_wayland, &debug_gl, &debug_font_fallback);
    global_state.is_wayland = is_wayland ? true : false;
    global_state.debug_gl = debug_gl ? true : false;
    global_state.debug_font_fallback = debug_font_fallback ? true : false;
#define GA(name) ret = PyObject_GetAttrString(opts, #name); if (ret == NULL) return NULL;
#define S(name, convert) { GA(name); global_state.opts.name = convert(ret); Py_DECREF(ret); if (PyErr_Occurred()) return NULL; }
    GA(kitty_mod);
    kitty_mod = PyLong_AsLong(ret); Py_CLEAR(ret); if (PyErr_Occurred()) return NULL;
    S(visual_bell_duration, PyFloat_AsDouble);
    S(enable_audio_bell, PyObject_IsTrue);
    S(focus_follows_mouse, PyObject_IsTrue);
    S(cursor_blink_interval, PyFloat_AsDouble);
    S(cursor_stop_blinking_after, PyFloat_AsDouble);
    S(background_opacity, PyFloat_AsDouble);
    S(dim_opacity, PyFloat_AsDouble);
    S(dynamic_background_opacity, PyObject_IsTrue);
    S(inactive_text_alpha, PyFloat_AsDouble);
    S(window_padding_width, PyFloat_AsDouble);
    S(scrollback_pager_history_size, PyLong_AsUnsignedLong);
    S(cursor_shape, PyLong_AsLong);
    S(url_style, PyLong_AsUnsignedLong);
    S(tab_bar_edge, PyLong_AsLong);
    S(mouse_hide_wait, PyFloat_AsDouble);
    S(wheel_scroll_multiplier, PyFloat_AsDouble);
    S(open_url_modifiers, convert_mods);
    S(rectangle_select_modifiers, convert_mods);
    S(click_interval, PyFloat_AsDouble);
    S(url_color, color_as_int);
    S(background, color_as_int);
    S(active_border_color, color_as_int);
    S(inactive_border_color, color_as_int);
    S(bell_border_color, color_as_int);
    S(repaint_delay, repaint_delay);
    S(input_delay, repaint_delay);
    S(sync_to_monitor, PyObject_IsTrue);
    S(close_on_child_death, PyObject_IsTrue);
    S(window_alert_on_bell, PyObject_IsTrue);
    S(macos_option_as_alt, PyObject_IsTrue);
    S(macos_traditional_fullscreen, PyObject_IsTrue);
    S(macos_hide_titlebar, PyObject_IsTrue);
    S(macos_hide_menu_bar_title, PyObject_IsTrue);
    S(macos_quit_when_last_window_closed, PyObject_IsTrue);
    S(macos_window_resizable, PyObject_IsTrue);
    S(x11_hide_window_decorations, PyObject_IsTrue);
    S(macos_hide_from_tasks, PyObject_IsTrue);
    S(macos_thicken_font, PyFloat_AsDouble);

    PyObject *chars = PyObject_GetAttrString(opts, "select_by_word_characters");
    if (chars == NULL) return NULL;
    for (size_t i = 0; i < MIN((size_t)PyUnicode_GET_LENGTH(chars), sizeof(OPT(select_by_word_characters))/sizeof(OPT(select_by_word_characters[0]))); i++) {
        OPT(select_by_word_characters)[i] = PyUnicode_READ(PyUnicode_KIND(chars), PyUnicode_DATA(chars), i);
    }
    OPT(select_by_word_characters_count) = PyUnicode_GET_LENGTH(chars);
    Py_DECREF(chars);

    GA(keymap); set_special_keys(ret);
    Py_DECREF(ret); if (PyErr_Occurred()) return NULL;
    GA(sequence_map); set_special_keys(ret);
    Py_DECREF(ret); if (PyErr_Occurred()) return NULL;

#define read_adjust(name) { \
    PyObject *al = PyObject_GetAttrString(opts, #name); \
    if (PyFloat_Check(al)) { \
        OPT(name##_frac) = (float)PyFloat_AsDouble(al); \
        OPT(name##_px) = 0; \
    } else { \
        OPT(name##_frac) = 0; \
        OPT(name##_px) = (int)PyLong_AsLong(al); \
    } \
    Py_DECREF(al); \
}
    read_adjust(adjust_line_height);
    read_adjust(adjust_column_width);
#undef read_adjust
#undef S
    Py_RETURN_NONE;
}

BOOL_SET(in_sequence_mode)

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

static PyTypeObject RegionType;
static PyStructSequence_Field region_fields[] = {
    {"left", ""}, {"top", ""}, {"right", ""}, {"bottom", ""}, {"width", ""}, {"height", ""}, {NULL, NULL}
};
static PyStructSequence_Desc region_desc = {"Region", NULL, region_fields, 6};

static inline PyObject*
wrap_region(Region *r) {
    PyObject *ans = PyStructSequence_New(&RegionType);
    if (ans) {
        PyStructSequence_SET_ITEM(ans, 0, PyLong_FromUnsignedLong(r->left));
        PyStructSequence_SET_ITEM(ans, 1, PyLong_FromUnsignedLong(r->top));
        PyStructSequence_SET_ITEM(ans, 2, PyLong_FromUnsignedLong(r->right));
        PyStructSequence_SET_ITEM(ans, 3, PyLong_FromUnsignedLong(r->bottom));
        PyStructSequence_SET_ITEM(ans, 4, PyLong_FromUnsignedLong(r->right - r->left + 1));
        PyStructSequence_SET_ITEM(ans, 5, PyLong_FromUnsignedLong(r->bottom - r->top + 1));
    }
    return ans;
}

PYWRAP1(viewport_for_window) {
    id_type os_window_id;
    int vw = 100, vh = 100;
    unsigned int cell_width = 1, cell_height = 1;
    PA("K", &os_window_id);
    Region central = {0}, tab_bar = {0};
    WITH_OS_WINDOW(os_window_id)
        os_window_regions(os_window, &central, &tab_bar);
        vw = os_window->viewport_width; vh = os_window->viewport_height;
        cell_width = os_window->fonts_data->cell_width; cell_height = os_window->fonts_data->cell_height;
        goto end;
    END_WITH_OS_WINDOW
end:
    return Py_BuildValue("NNiiII", wrap_region(&central), wrap_region(&tab_bar), vw, vh, cell_width, cell_height);
}

PYWRAP1(cell_size_for_window) {
    id_type os_window_id;
    unsigned int cell_width = 0, cell_height = 0;
    PA("K", &os_window_id);
    WITH_OS_WINDOW(os_window_id)
        cell_width = os_window->fonts_data->cell_width; cell_height = os_window->fonts_data->cell_height;
        goto end;
    END_WITH_OS_WINDOW
end:
    return Py_BuildValue("II", cell_width, cell_height);
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

PYWRAP1(focus_os_window) {
    id_type os_window_id;
    int also_raise = 1;
    PA("K|p", &os_window_id, &also_raise);
    WITH_OS_WINDOW(os_window_id)
        if (!os_window->is_focused) focus_os_window(os_window, also_raise);
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(set_titlebar_color) {
    id_type os_window_id;
    unsigned int color;
    PA("KI", &os_window_id, &color);
    WITH_OS_WINDOW(os_window_id)
        set_titlebar_color(os_window, color);
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(mark_tab_bar_dirty) {
    id_type os_window_id = PyLong_AsUnsignedLongLong(args);
    WITH_OS_WINDOW(os_window_id)
        os_window->tab_bar_data_updated = false;
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

PYWRAP1(change_background_opacity) {
    id_type os_window_id;
    float opacity;
    PA("Kf", &os_window_id, &opacity);
    WITH_OS_WINDOW(os_window_id)
        os_window->background_opacity = opacity;
        os_window->is_damaged = true;
        Py_RETURN_TRUE;
    END_WITH_OS_WINDOW
    Py_RETURN_FALSE;
}

PYWRAP1(background_opacity_of) {
    id_type os_window_id = PyLong_AsUnsignedLongLong(args);
    WITH_OS_WINDOW(os_window_id)
        return PyFloat_FromDouble((double)os_window->background_opacity);
    END_WITH_OS_WINDOW
    Py_RETURN_NONE;
}

static inline bool
fix_window_idx(Tab *tab, id_type window_id, unsigned int *window_idx) {
    for (id_type fix = 0; fix < tab->num_windows; fix++) {
        if (tab->windows[fix].id == window_id) { *window_idx = fix; return true; }
    }
    return false;
}

PYWRAP1(set_window_render_data) {
#define A(name) &(d.name)
#define B(name) &(g.name)
    id_type os_window_id, tab_id, window_id;
    unsigned int window_idx;
    ScreenRenderData d = {0};
    WindowGeometry g = {0};
    PA("KKKIffffOIIII", &os_window_id, &tab_id, &window_id, &window_idx, A(xstart), A(ystart), A(dx), A(dy), A(screen), B(left), B(top), B(right), B(bottom));

    WITH_TAB(os_window_id, tab_id);
        if (tab->windows[window_idx].id != window_id) {
            if (!fix_window_idx(tab, window_id, &window_idx)) Py_RETURN_NONE;
        }
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
    id_type os_window_id, tab_id, window_id;
    unsigned int window_idx;
    int visible;
    PA("KKKIp", &os_window_id, &tab_id, &window_id, &window_idx, &visible);
    WITH_TAB(os_window_id, tab_id);
        if (tab->windows[window_idx].id != window_id) {
            if (!fix_window_idx(tab, window_id, &window_idx)) Py_RETURN_NONE;
        }
        tab->windows[window_idx].visible = visible & 1;
    END_WITH_TAB;
    Py_RETURN_NONE;
}

static inline double
dpi_for_os_window_id(id_type os_window_id) {
    double dpi = 0;
    if (os_window_id) {
        WITH_OS_WINDOW(os_window_id)
            dpi = (os_window->logical_dpi_x + os_window->logical_dpi_y) / 2.;
        END_WITH_OS_WINDOW
    }
    if (dpi == 0) {
        dpi = (global_state.default_dpi.x + global_state.default_dpi.y) / 2.;
    }
    return dpi;
}

PYWRAP1(pt_to_px) {
    double pt, dpi = 0;
    id_type os_window_id = 0;
    PA("d|K", &pt, &os_window_id);
    dpi = dpi_for_os_window_id(os_window_id);
    return PyLong_FromLong((long)round((pt * (dpi / 72.0))));
}

PYWRAP1(global_font_size) {
    double set_val = -1;
    PA("|d", &set_val);
    if (set_val > 0) global_state.font_sz_in_pts = set_val;
    return Py_BuildValue("d", global_state.font_sz_in_pts);
}

static inline void
resize_screen(OSWindow *os_window, Screen *screen, bool has_graphics) {
    if (screen) {
        screen->cell_size.width = os_window->fonts_data->cell_width;
        screen->cell_size.height = os_window->fonts_data->cell_height;
        screen_dirty_sprite_positions(screen);
        if (has_graphics) screen_rescale_images(screen);
    }
}

PYWRAP1(os_window_font_size) {
    id_type os_window_id;
    int force = 0;
    double new_sz = -1;
    PA("K|dp", &os_window_id, &new_sz, &force);
    WITH_OS_WINDOW(os_window_id)
        if (new_sz > 0 && (force || new_sz != os_window->font_sz_in_pts)) {
            os_window->font_sz_in_pts = new_sz;
            os_window->fonts_data = NULL;
            os_window->fonts_data = load_fonts_data(os_window->font_sz_in_pts, os_window->logical_dpi_x, os_window->logical_dpi_y);
            send_prerendered_sprites_for_window(os_window);
            resize_screen(os_window, os_window->tab_bar_render_data.screen, false);
            for (size_t ti = 0; ti < os_window->num_tabs; ti++) {
                Tab *tab = os_window->tabs + ti;
                for (size_t wi = 0; wi < tab->num_windows; wi++) {
                    Window *w = tab->windows + wi;
                    resize_screen(os_window, w->render_data.screen, true);
                }
            }
        }
        return Py_BuildValue("d", os_window->font_sz_in_pts);
    END_WITH_OS_WINDOW
    return Py_BuildValue("d", 0.0);
}

PYWRAP1(set_boss) {
    Py_CLEAR(global_state.boss);
    global_state.boss = args;
    Py_INCREF(global_state.boss);
    Py_RETURN_NONE;
}

PYWRAP1(patch_global_colors) {
    PyObject *spec;
    int configured;
    if (!PyArg_ParseTuple(args, "Op", &spec, &configured)) return NULL;
#define P(name) { \
    PyObject *val = PyDict_GetItemString(spec, #name); \
    if (val) { \
		global_state.opts.name = PyLong_AsLong(val); \
	} \
}
    P(active_border_color); P(inactive_border_color); P(bell_border_color);
    if (configured) {
        P(background); P(url_color);
    }
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

PYWRAP0(destroy_global_data) {
    Py_CLEAR(global_state.boss);
    free(global_state.os_windows); global_state.os_windows = NULL;
    Py_RETURN_NONE;
}

THREE_ID_OBJ(update_window_title)
THREE_ID(remove_window)
PYWRAP1(resolve_key_mods) { int mods; PA("ii", &kitty_mod, &mods); return PyLong_FromLong(resolve_mods(mods)); }
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
    MW(next_window_id, METH_NOARGS),
    MW(set_options, METH_VARARGS),
    MW(set_in_sequence_mode, METH_O),
    MW(resolve_key_mods, METH_VARARGS),
    MW(handle_for_window_id, METH_VARARGS),
    MW(pt_to_px, METH_VARARGS),
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
    MW(cell_size_for_window, METH_VARARGS),
    MW(mark_os_window_for_close, METH_VARARGS),
    MW(set_titlebar_color, METH_VARARGS),
    MW(focus_os_window, METH_VARARGS),
    MW(mark_tab_bar_dirty, METH_O),
    MW(change_background_opacity, METH_VARARGS),
    MW(background_opacity_of, METH_O),
    MW(update_window_visibility, METH_VARARGS),
    MW(global_font_size, METH_VARARGS),
    MW(os_window_font_size, METH_VARARGS),
    MW(set_boss, METH_O),
    MW(patch_global_colors, METH_VARARGS),
    MW(destroy_global_data, METH_NOARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_state(PyObject *module) {
    global_state.font_sz_in_pts = 11.0;
#ifdef __APPLE__
#define DPI 72.0
#else
#define DPI 96.0
#endif
    global_state.default_dpi.x = DPI; global_state.default_dpi.y = DPI;
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (PyStructSequence_InitType2(&RegionType, &region_desc) != 0) return false;
    Py_INCREF((PyObject *) &RegionType);
    PyModule_AddObject(module, "Region", (PyObject *) &RegionType);
    return true;
}
// }}}
