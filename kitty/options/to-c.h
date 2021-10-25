/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "../state.h"
#include "../colors.h"

static inline float
PyFloat_AsFloat(PyObject *o) {
    return (float)PyFloat_AsDouble(o);
}

static inline color_type
color_as_int(PyObject *color) {
    if (!PyObject_TypeCheck(color, &Color_Type)) { PyErr_SetString(PyExc_TypeError, "Not a Color object"); return 0; }
    Color *c = (Color*)color;
    return c->color.val & 0xffffff;
}

static inline color_type
color_or_none_as_int(PyObject *color) {
    if (color == Py_None) return 0;
    return color_as_int(color);
}

static inline color_type
active_border_color(PyObject *color) {
    if (color == Py_None) return 0x00ff00;
    return color_as_int(color);
}


static inline monotonic_t
parse_s_double_to_monotonic_t(PyObject *val) {
    return s_double_to_monotonic_t(PyFloat_AsDouble(val));
}

static inline monotonic_t
parse_ms_long_to_monotonic_t(PyObject *val) {
    return ms_to_monotonic_t(PyLong_AsUnsignedLong(val));
}

static inline int
resolve_mods(int kitty_mod, int mods) {
    if (mods & GLFW_MOD_KITTY) {
        mods = (mods & ~GLFW_MOD_KITTY) | kitty_mod;
    }
    return mods;
}

static WindowTitleIn
window_title_in(PyObject *title_in) {
    const char *in = PyUnicode_AsUTF8(title_in);
    switch(in[0]) {
        case 'a': return ALL;
        case 'w': return WINDOW;
        case 'm': return MENUBAR;
        case 'n': return NONE;
        default: break;
    }
    return ALL;
}

static BackgroundImageLayout
bglayout(PyObject *layout_name) {
    const char *name = PyUnicode_AsUTF8(layout_name);
    switch(name[0]) {
        case 't': return TILING;
        case 'm': return MIRRORED;
        case 's': return SCALED;
        case 'c': return CLAMPED;
        default: break;
    }
    return TILING;
}

static BackgroundImageAnchor
bganchor(PyObject *anchor_name) {
    const char *name = PyUnicode_AsUTF8(anchor_name);
    if (strcmp(name, "north") == 0) {
        return NORTH;
    }
    else if (strcmp(name, "northeast") == 0) {
        return NORTHEAST;
    }
    else if (strcmp(name, "east") == 0) {
        return EAST;
    }
    else if (strcmp(name, "southeast") == 0) {
        return SOUTHEAST;
    }
    else if (strcmp(name, "south") == 0) {
        return SOUTH;
    }
    else if (strcmp(name, "southwest") == 0) {
        return SOUTHWEST;
    }
    else if (strcmp(name, "west") == 0) {
        return WEST;
    }
    else if (strcmp(name, "center") == 0) {
        return CENTER;
    }
    return NORTHWEST;
}

#define STR_SETTER(name) { \
    free(opts->name); opts->name = NULL; \
    if (src == Py_None || !PyUnicode_Check(src)) return; \
    Py_ssize_t sz; \
    const char *s = PyUnicode_AsUTF8AndSize(src, &sz); \
    opts->name = calloc(sz + 1, 1); \
    if (opts->name) memcpy(opts->name, s, sz); \
}

static void
background_image(PyObject *src, Options *opts) { STR_SETTER(background_image); }

static void
bell_path(PyObject *src, Options *opts) { STR_SETTER(bell_path); }

#undef STR_SETTER

static MouseShape
pointer_shape(PyObject *shape_name) {
    const char *name = PyUnicode_AsUTF8(shape_name);
    switch(name[0]) {
        case 'a': return ARROW;
        case 'h': return HAND;
        case 'b': return BEAM;
        default: break;
    }
    return BEAM;
}

static inline void
free_url_prefixes(void) {
    OPT(url_prefixes).num = 0;
    OPT(url_prefixes).max_prefix_len = 0;
    if (OPT(url_prefixes).values) {
        free(OPT(url_prefixes.values));
        OPT(url_prefixes).values = NULL;
    }
}

static void
url_prefixes(PyObject *up, Options *opts) {
    if (!PyTuple_Check(up)) { PyErr_SetString(PyExc_TypeError, "url_prefixes must be a tuple"); return; }
    free_url_prefixes();
    opts->url_prefixes.values = calloc(PyTuple_GET_SIZE(up), sizeof(UrlPrefix));
    if (!opts->url_prefixes.values) { PyErr_NoMemory(); return; }
    opts->url_prefixes.num = PyTuple_GET_SIZE(up);
    for (size_t i = 0; i < opts->url_prefixes.num; i++) {
        PyObject *t = PyTuple_GET_ITEM(up, i);
        if (!PyUnicode_Check(t)) { PyErr_SetString(PyExc_TypeError, "url_prefixes must be strings"); return; }
        opts->url_prefixes.values[i].len = MIN(arraysz(opts->url_prefixes.values[i].string) - 1, (size_t)PyUnicode_GET_LENGTH(t));
        int kind = PyUnicode_KIND(t);
        opts->url_prefixes.max_prefix_len = MAX(opts->url_prefixes.max_prefix_len, opts->url_prefixes.values[i].len);
        for (size_t x = 0; x < opts->url_prefixes.values[i].len; x++) {
            opts->url_prefixes.values[i].string[x] = PyUnicode_READ(kind, PyUnicode_DATA(t), x);
        }
    }
}

static char_type*
list_of_chars(PyObject *chars) {
    if (!PyUnicode_Check(chars)) { PyErr_SetString(PyExc_TypeError, "list_of_chars must be a string"); return NULL; }
    char_type *ans = calloc(PyUnicode_GET_LENGTH(chars) + 1, sizeof(char_type));
    if (ans) {
        for (ssize_t i = 0; i < PyUnicode_GET_LENGTH(chars); i++) {
            ans[i] = PyUnicode_READ(PyUnicode_KIND(chars), PyUnicode_DATA(chars), i);
        }
    }
    return ans;
}

static void
url_excluded_characters(PyObject *chars, Options *opts) {
    free(opts->url_excluded_characters);
    opts->url_excluded_characters = list_of_chars(chars);
}

static void
select_by_word_characters(PyObject *chars, Options *opts) {
    free(opts->select_by_word_characters);
    opts->select_by_word_characters = list_of_chars(chars);
}

static void
tab_bar_style(PyObject *val, Options *opts) {
    opts->tab_bar_hidden = PyUnicode_CompareWithASCIIString(val, "hidden") == 0 ? true: false;
}

static void
tab_bar_margin_height(PyObject *val, Options *opts) {
    if (!PyTuple_Check(val) || PyTuple_GET_SIZE(val) != 2) {
        PyErr_SetString(PyExc_TypeError, "tab_bar_margin_height is not a 2-item tuple");
        return;
    }
    opts->tab_bar_margin_height.outer = PyFloat_AsDouble(PyTuple_GET_ITEM(val, 0));
    opts->tab_bar_margin_height.inner = PyFloat_AsDouble(PyTuple_GET_ITEM(val, 1));
}

#define read_adjust(name) { \
    if (PyFloat_Check(al)) { \
        opts->name##_frac = (float)PyFloat_AsDouble(al); \
        opts->name##_px = 0; \
    } else { \
        opts->name##_frac = 0; \
        opts->name##_px = (int)PyLong_AsLong(al); \
    } \
}

static void
adjust_line_height(PyObject *al, Options *opts) { read_adjust(adjust_line_height); }
static void
adjust_column_width(PyObject *al, Options *opts) { read_adjust(adjust_column_width); }
static void
adjust_baseline(PyObject *al, Options *opts) { read_adjust(adjust_baseline); }
#undef read_adjust
