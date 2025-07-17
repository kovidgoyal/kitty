/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "../state.h"
#include "../colors.h"
#include "../fonts.h"

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

static inline WindowTitleIn
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

static inline unsigned
undercurl_style(PyObject *x) {
    RAII_PyObject(thick, PyUnicode_FromString("thick"));
    RAII_PyObject(dense, PyUnicode_FromString("dense"));
    unsigned ans = 0;
    int ret;
    switch ((ret = PyUnicode_Find(x, dense, 0, PyUnicode_GET_LENGTH(x), 1))) {
        case -2: PyErr_Clear(); case -1: break;
        default: ans |= 1;
    }
    switch ((ret = PyUnicode_Find(x, thick, 0, PyUnicode_GET_LENGTH(x), 1))) {
        case -2: PyErr_Clear(); case -1: break;
        default: ans |= 2;
    }
    return ans;
}

static inline UnderlineHyperlinks
underline_hyperlinks(PyObject *x) {
    const char *in = PyUnicode_AsUTF8(x);
    switch(in[0]) {
        case 'a': return UNDERLINE_ALWAYS;
        case 'n': return UNDERLINE_NEVER;
        default : return UNDERLINE_ON_HOVER;
    }
}

static inline BackgroundImageLayout
bglayout(PyObject *layout_name) {
    const char *name = PyUnicode_AsUTF8(layout_name);
    switch(name[0]) {
        case 't': return TILING;
        case 'm': return MIRRORED;
        case 's': return SCALED;
        case 'c': {
            return name[1] == 'l' ? CLAMPED : (name[1] == 's' ? CENTER_SCALED : CENTER_CLAMPED);
        }
        default: break;
    }
    return TILING;
}

static inline ImageAnchorPosition
bganchor(PyObject *anchor_name) {
    const char *name = PyUnicode_AsUTF8(anchor_name);
    ImageAnchorPosition anchor = {0.5f, 0.5f, 0.5f, 0.5f};
    if (strstr(name, "top") != NULL) {
        anchor.canvas_y = 0.f; anchor.image_y = 0.f;
    } else if (strstr(name, "bottom") != NULL) {
        anchor.canvas_y = 1.f; anchor.image_y = 1.f;
    }
    if (strstr(name, "left") != NULL) {
        anchor.canvas_x = 0.f; anchor.image_x = 0.f;
    } else if (strstr(name, "right") != NULL) {
        anchor.canvas_x = 1.f; anchor.image_x = 1.f;
    }
    return anchor;
}

#define STR_SETTER(name) { \
    free(opts->name); opts->name = NULL; \
    if (src == Py_None || !PyUnicode_Check(src)) return; \
    Py_ssize_t sz; \
    const char *s = PyUnicode_AsUTF8AndSize(src, &sz); \
    opts->name = calloc(sz + 1, sizeof(s[0])); \
    if (opts->name) memcpy(opts->name, s, sz); \
}

static inline void
background_image(PyObject *src, Options *opts) { STR_SETTER(background_image); }

static inline void
bell_path(PyObject *src, Options *opts) { STR_SETTER(bell_path); }

static inline void
bell_theme(PyObject *src, Options *opts) { STR_SETTER(bell_theme); }

static inline void
window_logo_path(PyObject *src, Options *opts) { STR_SETTER(default_window_logo); }

#undef STR_SETTER

static void
add_easing_function(Animation *a, PyObject *e, double y_at_start, double y_at_end) {
#define G(name) RAII_PyObject(name, PyObject_GetAttrString(e, #name))
#define D(container, idx) PyFloat_AsDouble(PyTuple_GET_ITEM(container, idx))
#define EQ(x, val) (PyUnicode_CompareWithASCIIString((x), val) == 0)
    G(type);
    if (EQ(type, "cubic-bezier")) {
        G(cubic_bezier_points);
        add_cubic_bezier_animation(a, y_at_start, y_at_end, D(cubic_bezier_points, 0), D(cubic_bezier_points, 1), D(cubic_bezier_points, 2), D(cubic_bezier_points, 3));
    } else if (EQ(type, "linear")) {
        G(linear_x); G(linear_y);
        size_t count = PyTuple_GET_SIZE(linear_x);
        RAII_ALLOC(double, x, malloc(2 * sizeof(double) * count));
        if (x) {
            double *y = x + count;
            for (size_t i = 0; i < count; i++) {
                x[i] = D(linear_x, i); y[i] = D(linear_y, i);
            }
            add_linear_animation(a, y_at_start, y_at_end, count, x, y);
        }
    } else if (EQ(type, "steps")) {
        G(num_steps); G(jump_type);
        EasingStep jt = EASING_STEP_END;
        if (EQ(jump_type, "start")) jt = EASING_STEP_START;
        else if (EQ(jump_type, "none")) jt = EASING_STEP_NONE;
        else if (EQ(jump_type, "both")) jt = EASING_STEP_BOTH;
        add_steps_animation(a, y_at_start, y_at_end, PyLong_AsSize_t(num_steps), jt);
    }
#undef EQ
#undef D
#undef G
}

#define parse_animation(duration, name, start, end) \
    opts->duration = parse_s_double_to_monotonic_t(PyTuple_GET_ITEM(src, 0)); \
    opts->animation.name = free_animation(opts->animation.name); \
    if (PyObject_IsTrue(PyTuple_GET_ITEM(src, 1)) && (opts->animation.name = alloc_animation()) != NULL) { \
        add_easing_function(opts->animation.name, PyTuple_GET_ITEM(src, 1), start, end); \
        if (PyObject_IsTrue(PyTuple_GET_ITEM(src, 2))) { \
            add_easing_function(opts->animation.name, PyTuple_GET_ITEM(src, 2), end, start); \
        } else { \
            add_easing_function(opts->animation.name, PyTuple_GET_ITEM(src, 1), end, start); \
        } \
    } \

static inline void
cursor_blink_interval(PyObject *src, Options *opts) {
    parse_animation(cursor_blink_interval, cursor, 1, 0);
}

static inline void
visual_bell_duration(PyObject *src, Options *opts) {
    parse_animation(visual_bell_duration, visual_bell, 0, 1);
}

#undef parse_animation

static inline void
mouse_hide_wait(PyObject *val, Options *opts) {
    if (!PyTuple_Check(val) || PyTuple_GET_SIZE(val) != 4) {
        PyErr_SetString(PyExc_TypeError, "mouse_hide_wait is not a 4-item tuple");
        return;
    }
    opts->mouse_hide.hide_wait = parse_s_double_to_monotonic_t(PyTuple_GET_ITEM(val, 0));
    opts->mouse_hide.unhide_wait = parse_s_double_to_monotonic_t(PyTuple_GET_ITEM(val, 1));
    opts->mouse_hide.unhide_threshold = PyLong_AsLong(PyTuple_GET_ITEM(val, 2));
    opts->mouse_hide.scroll_unhide = PyObject_IsTrue(PyTuple_GET_ITEM(val, 3));
}

static inline void
cursor_trail_decay(PyObject *src, Options *opts) {
    opts->cursor_trail_decay_fast = PyFloat_AsFloat(PyTuple_GET_ITEM(src, 0));
    opts->cursor_trail_decay_slow = PyFloat_AsFloat(PyTuple_GET_ITEM(src, 1));
}

static inline void
cursor_trail_color(PyObject *src, Options *opts) {
    opts->cursor_trail_color = color_or_none_as_int(src);
}

static void
parse_font_mod_size(PyObject *val, float *sz, AdjustmentUnit *unit) {
    PyObject *mv = PyObject_GetAttrString(val, "mod_value");
    if (mv) {
        *sz = PyFloat_AsFloat(PyTuple_GET_ITEM(mv, 0));
        long u = PyLong_AsLong(PyTuple_GET_ITEM(mv, 1));
        switch (u) { case POINT: case PERCENT: case PIXEL: *unit = u; break; }
    }
}

static inline void
modify_font(PyObject *mf, Options *opts) {
#define S(which) { PyObject *v = PyDict_GetItemString(mf, #which); if (v) parse_font_mod_size(v, &opts->which.val, &opts->which.unit); }
    S(underline_position); S(underline_thickness); S(strikethrough_thickness); S(strikethrough_position);
    S(cell_height); S(cell_width); S(baseline);
#undef S
}

static inline void
free_font_features(Options *opts) {
    if (opts->font_features.entries) {
        for (size_t i = 0; i < opts->font_features.num; i++) {
            free((void*)opts->font_features.entries[i].psname);
            free((void*)opts->font_features.entries[i].features);
        }
        free(opts->font_features.entries);
    }
    memset(&opts->font_features, 0, sizeof(opts->font_features));
}

static inline void
font_features(PyObject *mf, Options *opts) {
    free_font_features(opts);
    opts->font_features.num = PyDict_GET_SIZE(mf);
    if (!opts->font_features.num) return;
    opts->font_features.entries = calloc(opts->font_features.num, sizeof(opts->font_features.entries[0]));
    if (!opts->font_features.entries) { PyErr_NoMemory(); return; }
    PyObject *key, *value;
    Py_ssize_t pos = 0, i = 0;
    while (PyDict_Next(mf, &pos, &key, &value)) {
        __typeof__(opts->font_features.entries) e = opts->font_features.entries + i++;
        Py_ssize_t psname_sz; const char *psname = PyUnicode_AsUTF8AndSize(key, &psname_sz);
        e->psname = strndup(psname, psname_sz);
        if (!e->psname) { PyErr_NoMemory(); return; }
        e->num = PyTuple_GET_SIZE(value);
        if (e->num) {
            e->features = calloc(e->num, sizeof(e->features[0]));
            if (!e->features) { PyErr_NoMemory(); return; }
            for (size_t n = 0; n < e->num; n++) {
                ParsedFontFeature *f = (ParsedFontFeature*)PyTuple_GET_ITEM(value, n);
                e->features[n] = f->feature;
            }
        }
    }
}

static inline MouseShape
pointer_shape(PyObject *shape_name) {
    const char *name = PyUnicode_AsUTF8(shape_name);
    if (!name) return TEXT_POINTER;
    /* start pointer shapes (auto generated by gen-key-constants.py do not edit) */
    else if (strcmp(name, "arrow") == 0) return DEFAULT_POINTER;
    else if (strcmp(name, "beam") == 0) return TEXT_POINTER;
    else if (strcmp(name, "text") == 0) return TEXT_POINTER;
    else if (strcmp(name, "pointer") == 0) return POINTER_POINTER;
    else if (strcmp(name, "hand") == 0) return POINTER_POINTER;
    else if (strcmp(name, "help") == 0) return HELP_POINTER;
    else if (strcmp(name, "wait") == 0) return WAIT_POINTER;
    else if (strcmp(name, "progress") == 0) return PROGRESS_POINTER;
    else if (strcmp(name, "crosshair") == 0) return CROSSHAIR_POINTER;
    else if (strcmp(name, "cell") == 0) return CELL_POINTER;
    else if (strcmp(name, "vertical-text") == 0) return VERTICAL_TEXT_POINTER;
    else if (strcmp(name, "move") == 0) return MOVE_POINTER;
    else if (strcmp(name, "e-resize") == 0) return E_RESIZE_POINTER;
    else if (strcmp(name, "ne-resize") == 0) return NE_RESIZE_POINTER;
    else if (strcmp(name, "nw-resize") == 0) return NW_RESIZE_POINTER;
    else if (strcmp(name, "n-resize") == 0) return N_RESIZE_POINTER;
    else if (strcmp(name, "se-resize") == 0) return SE_RESIZE_POINTER;
    else if (strcmp(name, "sw-resize") == 0) return SW_RESIZE_POINTER;
    else if (strcmp(name, "s-resize") == 0) return S_RESIZE_POINTER;
    else if (strcmp(name, "w-resize") == 0) return W_RESIZE_POINTER;
    else if (strcmp(name, "ew-resize") == 0) return EW_RESIZE_POINTER;
    else if (strcmp(name, "ns-resize") == 0) return NS_RESIZE_POINTER;
    else if (strcmp(name, "nesw-resize") == 0) return NESW_RESIZE_POINTER;
    else if (strcmp(name, "nwse-resize") == 0) return NWSE_RESIZE_POINTER;
    else if (strcmp(name, "zoom-in") == 0) return ZOOM_IN_POINTER;
    else if (strcmp(name, "zoom-out") == 0) return ZOOM_OUT_POINTER;
    else if (strcmp(name, "alias") == 0) return ALIAS_POINTER;
    else if (strcmp(name, "copy") == 0) return COPY_POINTER;
    else if (strcmp(name, "not-allowed") == 0) return NOT_ALLOWED_POINTER;
    else if (strcmp(name, "no-drop") == 0) return NO_DROP_POINTER;
    else if (strcmp(name, "grab") == 0) return GRAB_POINTER;
    else if (strcmp(name, "grabbing") == 0) return GRABBING_POINTER;
/* end pointer shapes */
    return TEXT_POINTER;
}

static inline void
dragging_pointer_shape(PyObject *parts, Options *opts) {
    opts->pointer_shape_when_dragging = pointer_shape(PyTuple_GET_ITEM(parts, 0));
    opts->pointer_shape_when_dragging_rectangle = pointer_shape(PyTuple_GET_ITEM(parts, 1));
}

static inline int
macos_colorspace(PyObject *csname) {
    if (PyUnicode_CompareWithASCIIString(csname, "srgb") == 0) return 1;
    if (PyUnicode_CompareWithASCIIString(csname, "displayp3") == 0) return 2;
    return 0;
}

static inline void
free_url_prefixes(Options *opts) {
    opts->url_prefixes.num = 0;
    opts->url_prefixes.max_prefix_len = 0;
    if (opts->url_prefixes.values) {
        free(opts->url_prefixes.values);
        opts->url_prefixes.values = NULL;
    }
}

static inline void
url_prefixes(PyObject *up, Options *opts) {
    if (!PyTuple_Check(up)) { PyErr_SetString(PyExc_TypeError, "url_prefixes must be a tuple"); return; }
    free_url_prefixes(opts);
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

static inline void
free_menu_map(Options *opts) {
    if (opts->global_menu.entries) {
        for (size_t i=0; i < opts->global_menu.count; i++) {
            struct MenuItem *e = opts->global_menu.entries + i;
            if (e->definition) { free((void*)e->definition); }
            if (e->location) {
                for (size_t l=0; l < e->location_count; l++) { free((void*)e->location[l]); }
                free(e->location);
            }
        }
        free(opts->global_menu.entries); opts->global_menu.entries = NULL;
    }
    opts->global_menu.count = 0;
}

static inline void
menu_map(PyObject *entry_dict, Options *opts) {
    if (!PyDict_Check(entry_dict)) { PyErr_SetString(PyExc_TypeError, "menu_map entries must be a dict"); return; }
    free_menu_map(opts);
    size_t maxnum = PyDict_Size(entry_dict);
    opts->global_menu.count = 0;
    opts->global_menu.entries = calloc(maxnum, sizeof(opts->global_menu.entries[0]));
    if (!opts->global_menu.entries) { PyErr_NoMemory(); return; }

    PyObject *key, *value;
    Py_ssize_t pos = 0;

    while (PyDict_Next(entry_dict, &pos, &key, &value)) {
        if (PyTuple_Check(key) && PyTuple_GET_SIZE(key) > 1 && PyUnicode_Check(value) && PyUnicode_CompareWithASCIIString(PyTuple_GET_ITEM(key, 0), "global") == 0) {
            struct MenuItem *e = opts->global_menu.entries + opts->global_menu.count++;
            e->location_count = PyTuple_GET_SIZE(key) - 1;
            e->location = calloc(e->location_count, sizeof(e->location[0]));
            if (!e->location) { PyErr_NoMemory(); return; }
            e->definition = strdup(PyUnicode_AsUTF8(value));
            if (!e->definition) { PyErr_NoMemory(); return; }
            for (size_t i = 0; i < e->location_count; i++) {
                e->location[i] = strdup(PyUnicode_AsUTF8(PyTuple_GET_ITEM(key, i+1)));
                if (!e->location[i]) { PyErr_NoMemory(); return; }
            }
        }
    }
}

static inline void
underline_exclusion(PyObject *val, Options *opts) {
    if (!PyTuple_Check(val)) { PyErr_SetString(PyExc_TypeError, "underline_exclusion must be a tuple"); return; }
    opts->underline_exclusion.thickness = PyFloat_AsFloat(PyTuple_GET_ITEM(val, 0));
    if (!PyUnicode_GET_LENGTH(PyTuple_GET_ITEM(val, 1))) opts->underline_exclusion.unit = 0;
    else if (PyUnicode_CompareWithASCIIString(PyTuple_GET_ITEM(val, 1), "px")) opts->underline_exclusion.unit = 1;
    else if (PyUnicode_CompareWithASCIIString(PyTuple_GET_ITEM(val, 1), "pt")) opts->underline_exclusion.unit = 2;
    else opts->underline_exclusion.unit = 0;
}

static inline void
box_drawing_scale(PyObject *val, Options *opts) {
    for (unsigned i = 0; i < MIN(arraysz(opts->box_drawing_scale), (size_t)PyTuple_GET_SIZE(val)); i++) {
        opts->box_drawing_scale[i] = PyFloat_AsFloat(PyTuple_GET_ITEM(val, i));
    }
}

static inline void
text_composition_strategy(PyObject *val, Options *opts) {
    if (!PyUnicode_Check(val)) { PyErr_SetString(PyExc_TypeError, "text_rendering_strategy must be a string"); return; }
    opts->text_old_gamma = false;
    opts->text_gamma_adjustment = 1.0f; opts->text_contrast = 0.f;
    if (PyUnicode_CompareWithASCIIString(val, "platform") == 0) {
#ifdef __APPLE__
        opts->text_gamma_adjustment = 1.7f; opts->text_contrast = 30.f;
#endif
    }
    else if (PyUnicode_CompareWithASCIIString(val, "legacy") == 0) {
        opts->text_old_gamma = true;
    } else {
        RAII_PyObject(parts, PyUnicode_Split(val, NULL, 2));
        int size = PyList_GET_SIZE(parts);
        if (size < 1 || 2 < size) { PyErr_SetString(PyExc_ValueError, "text_rendering_strategy must be of the form number:[number]"); return; }

        if (size > 0) {
            RAII_PyObject(ga, PyFloat_FromString(PyList_GET_ITEM(parts, 0)));
            if (PyErr_Occurred()) return;
            opts->text_gamma_adjustment = MAX(0.01f, PyFloat_AsFloat(ga));
        }

        if (size > 1) {
            RAII_PyObject(contrast, PyFloat_FromString(PyList_GET_ITEM(parts, 1)));
            if (PyErr_Occurred()) return;
            opts->text_contrast = MAX(0.0f, PyFloat_AsFloat(contrast));
            opts->text_contrast = MIN(100.0f, opts->text_contrast);
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

static inline void
url_excluded_characters(PyObject *chars, Options *opts) {
    free(opts->url_excluded_characters);
    opts->url_excluded_characters = list_of_chars(chars);
}

static inline void
select_by_word_characters(PyObject *chars, Options *opts) {
    free(opts->select_by_word_characters);
    opts->select_by_word_characters = list_of_chars(chars);
}

static inline void
select_by_word_characters_forward(PyObject *chars, Options *opts) {
    free(opts->select_by_word_characters_forward);
    opts->select_by_word_characters_forward = list_of_chars(chars);
}

static inline void
tab_bar_style(PyObject *val, Options *opts) {
    opts->tab_bar_hidden = PyUnicode_CompareWithASCIIString(val, "hidden") == 0 ? true: false;
}

static inline void
tab_bar_margin_height(PyObject *val, Options *opts) {
    if (!PyTuple_Check(val) || PyTuple_GET_SIZE(val) != 2) {
        PyErr_SetString(PyExc_TypeError, "tab_bar_margin_height is not a 2-item tuple");
        return;
    }
    opts->tab_bar_margin_height.outer = PyFloat_AsDouble(PyTuple_GET_ITEM(val, 0));
    opts->tab_bar_margin_height.inner = PyFloat_AsDouble(PyTuple_GET_ITEM(val, 1));
}

static inline void
window_logo_scale(PyObject *src, Options *opts) {
    opts->window_logo_scale.width = PyFloat_AsFloat(PyTuple_GET_ITEM(src, 0));
    opts->window_logo_scale.height = PyFloat_AsFloat(PyTuple_GET_ITEM(src, 1));
}

static inline void
resize_debounce_time(PyObject *src, Options *opts) {
    opts->resize_debounce_time.on_end = s_double_to_monotonic_t(PyFloat_AsDouble(PyTuple_GET_ITEM(src, 0)));
    opts->resize_debounce_time.on_pause = s_double_to_monotonic_t(PyFloat_AsDouble(PyTuple_GET_ITEM(src, 1)));
}

static inline void
free_allocs_in_options(Options *opts) {
    free_menu_map(opts);
    free_url_prefixes(opts);
    free_font_features(opts);
#define F(x) free(opts->x); opts->x = NULL;
    F(select_by_word_characters); F(url_excluded_characters); F(select_by_word_characters_forward);
    F(background_image); F(bell_path); F(bell_theme); F(default_window_logo);
#undef F
}
