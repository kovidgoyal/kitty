/*
 * colors.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include <structmember.h>
#include "colors.h"


static uint32_t FG_BG_256[256] = {
    0x000000,  // 0
    0xcd0000,  // 1
    0x00cd00,  // 2
    0xcdcd00,  // 3
    0x0000ee,  // 4
    0xcd00cd,  // 5
    0x00cdcd,  // 6
    0xe5e5e5,  // 7
    0x7f7f7f,  // 8
    0xff0000,  // 9
    0x00ff00,  // 10
    0xffff00,  // 11
    0x5c5cff,  // 12
    0xff00ff,  // 13
    0x00ffff,  // 14
    0xffffff,  // 15
};

static void
init_FG_BG_table(void) {
    if (UNLIKELY(FG_BG_256[255] == 0)) {
        // colors 16..232: the 6x6x6 color cube
        const uint8_t valuerange[6] = {0x00, 0x5f, 0x87, 0xaf, 0xd7, 0xff};
        uint8_t i, j=16;
        for(i = 0; i < 216; i++, j++) {
            uint8_t r = valuerange[(i / 36) % 6], g = valuerange[(i / 6) % 6], b = valuerange[i % 6];
            FG_BG_256[j] = (r << 16) | (g << 8) | b;
        }
        // colors 232..255: grayscale
        for(i = 0; i < 24; i++, j++) {
            uint8_t v = 8 + i * 10;
            FG_BG_256[j] = (v << 16) | (v << 8) | v;
        }
    }
}

static PyObject*
create_256_color_table(void) {
    init_FG_BG_table();
    PyObject *ans = PyTuple_New(arraysz(FG_BG_256));
    if (ans == NULL) return PyErr_NoMemory();
    for (size_t i=0; i < arraysz(FG_BG_256); i++) {
        PyObject *temp = PyLong_FromUnsignedLong(FG_BG_256[i]);
        if (temp == NULL) { Py_CLEAR(ans); return NULL; }
        PyTuple_SET_ITEM(ans, i, temp);
    }
    return ans;
}

static void
set_transparent_background_colors(TransparentDynamicColor *dest, PyObject *src) {
    memset(dest, 0, sizeof(((ColorProfile*)0)->configured_transparent_colors));
    for (Py_ssize_t i = 0; i < MIN(PyTuple_GET_SIZE(src), (Py_ssize_t)arraysz(((ColorProfile*)0)->configured_transparent_colors)); i++) {
        PyObject *e = PyTuple_GET_ITEM(src, i);
        dest[i].color = ((Color*)(PyTuple_GET_ITEM(e, 0)))->color.val & 0xffffff;
        dest[i].opacity = (float)PyFloat_AsDouble(PyTuple_GET_ITEM(e, 1));
        dest[i].is_set = true;
    }
}

static bool
set_configured_colors(ColorProfile *self, PyObject *opts) {
#define n(which, attr) { \
    RAII_PyObject(t, PyObject_GetAttrString(opts, #attr)); \
    if (t == NULL) return false; \
    if (t == Py_None) { self->configured.which.rgb = 0; self->configured.which.type = COLOR_IS_SPECIAL; } \
    else if (PyLong_Check(t)) { \
        unsigned int x = PyLong_AsUnsignedLong(t); \
        self->configured.which.rgb = x & 0xffffff; \
        self->configured.which.type = COLOR_IS_RGB; \
    } else if (PyObject_TypeCheck(t, &Color_Type)) { \
        Color *c = (Color*)t; \
        self->configured.which.rgb = c->color.rgb; \
        self->configured.which.type = COLOR_IS_RGB; \
    } else { PyErr_SetString(PyExc_TypeError, "colors must be integers or Color objects"); return false; } \
}

    n(default_fg, foreground); n(default_bg, background);
    n(cursor_color, cursor); n(cursor_text_color, cursor_text_color);
    n(highlight_fg, selection_foreground); n(highlight_bg, selection_background);
    n(visual_bell_color, visual_bell_color);
#undef n
    RAII_PyObject(src, PyObject_GetAttrString(opts, "transparent_background_colors"));
    if (!src) { PyErr_SetString(PyExc_TypeError, "No transparent_background_colors on opts object"); return false; }
    set_transparent_background_colors(self->configured_transparent_colors, src);
    return PyErr_Occurred() ? false : true;
}

static bool
set_mark_colors(ColorProfile *self, PyObject *opts) {
    char fgattr[] = "mark?_foreground", bgattr[] = "mark?_background";
#define n(i, attr, which) { \
    attr[4] = '1' + i; \
    RAII_PyObject(t, PyObject_GetAttrString(opts, attr)); \
    if (t == NULL) return false; \
    if (!PyObject_TypeCheck(t, &Color_Type)) { PyErr_SetString(PyExc_TypeError, "mark color is not Color object"); return false; } \
    Color *c = (Color*)t; self->which[i] = c->color.rgb; \
}
#define m(i) n(i, fgattr, mark_foregrounds); n(i, bgattr, mark_backgrounds);
    m(0); m(1); m(2);
#undef m
#undef n
    return true;
}

static bool
set_colortable(ColorProfile *self, PyObject *opts) {
    RAII_PyObject(ct, PyObject_GetAttrString(opts, "color_table"));
    if (!ct) return false;
    RAII_PyObject(ret, PyObject_CallMethod(ct, "buffer_info", NULL));
    if (!ret) return false;
    unsigned long *color_table = PyLong_AsVoidPtr(PyTuple_GET_ITEM(ret, 0));
    size_t count = PyLong_AsSize_t(PyTuple_GET_ITEM(ret, 1));
    if (!color_table || count != arraysz(FG_BG_256)) { PyErr_SetString(PyExc_TypeError, "color_table has incorrect length"); return false; }
    RAII_PyObject(r2, PyObject_GetAttrString(ct, "itemsize")); if (!r2) return false;
    size_t itemsize = PyLong_AsSize_t(r2);
    if (itemsize != sizeof(unsigned long)) { PyErr_Format(PyExc_TypeError, "color_table has incorrect itemsize: %zu", itemsize); return false; }
    for (size_t i = 0; i < arraysz(FG_BG_256); i++) self->color_table[i] = color_table[i];
    memcpy(self->orig_color_table, self->color_table, arraysz(self->color_table) * sizeof(self->color_table[0]));
    return true;
}


static PyObject*
new_cp(PyTypeObject *type, PyObject *args, PyObject *kwds) {
    PyObject *opts = global_state.options_object;
    ColorProfile *self;
    static const char* kw[] = {"opts", NULL};
    if (args && !PyArg_ParseTupleAndKeywords(args, kwds, "|O", (char**)kw, &opts)) return NULL;
    self = (ColorProfile *)type->tp_alloc(type, 0);
    RAII_PyObject(ans, (PyObject*)self);
    if (self != NULL) {
        init_FG_BG_table();
        if (opts) {
            if (!set_configured_colors(self, opts)) return NULL;
            if (!set_mark_colors(self, opts)) return NULL;
            if (!set_colortable(self, opts)) return NULL;
        } else {
            memcpy(self->color_table, FG_BG_256, sizeof(FG_BG_256));
            memcpy(self->orig_color_table, FG_BG_256, sizeof(FG_BG_256));
        }
        self->dirty = true;
        Py_INCREF(ans);
    }
    return ans;
}

static void
dealloc_cp(ColorProfile* self) {
    if (self->color_stack) free(self->color_stack);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

ColorProfile*
alloc_color_profile(void) {
    return (ColorProfile*)new_cp(&ColorProfile_Type, NULL, NULL);
}


void
copy_color_profile(ColorProfile *dest, ColorProfile *src) {
    memcpy(dest->color_table, src->color_table, sizeof(dest->color_table));
    memcpy(dest->orig_color_table, src->orig_color_table, sizeof(dest->color_table));
    memcpy(&dest->configured, &src->configured, sizeof(dest->configured));
    memcpy(&dest->overridden, &src->overridden, sizeof(dest->overridden));
    memcpy(dest->overriden_transparent_colors, src->overriden_transparent_colors, sizeof(dest->overriden_transparent_colors));
    memcpy(dest->configured_transparent_colors, src->configured_transparent_colors, sizeof(dest->configured_transparent_colors));
    dest->dirty = true;
}

static void
patch_color_table(const char *key, PyObject *profiles, PyObject *spec, size_t which, int change_configured) {
    PyObject *v = PyDict_GetItemString(spec, key);
    if (v && PyLong_Check(v)) {
        color_type color = PyLong_AsUnsignedLong(v);
        for (Py_ssize_t j = 0; j < PyTuple_GET_SIZE(profiles); j++) {
            ColorProfile *self = (ColorProfile*)PyTuple_GET_ITEM(profiles, j);
            self->color_table[which] = color;
            if (change_configured) self->orig_color_table[which] = color;
            self->dirty = true;
        }
    }

}

#define patch_mark_color(key, profiles, spec, array, i) { \
    PyObject *v = PyDict_GetItemString(spec, key); \
    if (v && PyLong_Check(v)) { \
        color_type color = PyLong_AsUnsignedLong(v); \
        for (Py_ssize_t j = 0; j < PyTuple_GET_SIZE(profiles); j++) { \
            ColorProfile *self = (ColorProfile*)PyTuple_GET_ITEM(profiles, j); \
            self->array[i] = color; \
            self->dirty = true; \
} } }


static PyObject*
patch_color_profiles(PyObject *module UNUSED, PyObject *args) {
    PyObject *spec, *transparent_background_colors, *profiles, *v; ColorProfile *self; int change_configured;
    if (!PyArg_ParseTuple(args, "O!O!O!p", &PyDict_Type, &spec, &PyTuple_Type, &transparent_background_colors, &PyTuple_Type, &profiles, &change_configured)) return NULL;
    char key[32] = {0};
    for (size_t i = 0; i < arraysz(FG_BG_256); i++) {
        snprintf(key, sizeof(key) - 1, "color%zu", i);
        patch_color_table(key, profiles, spec, i, change_configured);
    }
    for (size_t i = 1; i <= MARK_MASK; i++) {
#define S(which, i) snprintf(key, sizeof(key) - 1, "mark%zu_" #which, i); patch_mark_color(key, profiles, spec, mark_##which##s, i)
    S(background, i); S(foreground, i);
#undef S
    }
#define SI(profile_name) \
    DynamicColor color; \
    if (PyLong_Check(v)) { \
        color.rgb = PyLong_AsUnsignedLong(v);  color.type = COLOR_IS_RGB; \
    } else { color.rgb = 0; color.type = COLOR_IS_SPECIAL; }\
    self->overridden.profile_name = color; \
    if (change_configured) self->configured.profile_name = color; \
    self->dirty = true;

#define S(config_name, profile_name) { \
    v = PyDict_GetItemString(spec, #config_name); \
    if (v) { \
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(profiles); i++) { \
            self = (ColorProfile*)PyTuple_GET_ITEM(profiles, i); \
            SI(profile_name); \
        } \
    } \
}
        S(foreground, default_fg); S(background, default_bg); S(cursor, cursor_color);
        S(selection_foreground, highlight_fg); S(selection_background, highlight_bg);
        S(cursor_text_color, cursor_text_color); S(visual_bell_color, visual_bell_color);
#undef SI
#undef S
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(profiles); i++) {
        self = (ColorProfile*)PyTuple_GET_ITEM(profiles, i);
        set_transparent_background_colors(self->overriden_transparent_colors, transparent_background_colors);
        if (change_configured) set_transparent_background_colors(self->configured_transparent_colors, transparent_background_colors);
    }
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

bool
colorprofile_to_transparent_color(const ColorProfile *self, unsigned index, color_type *color, float *opacity) {
    *color = UINT32_MAX; *opacity = 1.0;
    if (index < arraysz(self->configured_transparent_colors)) {
        if (self->overriden_transparent_colors[index].is_set) {
            *color = self->overriden_transparent_colors[index].color; *opacity = self->overriden_transparent_colors[index].opacity;
            if (*opacity < 0) *opacity = OPT(background_opacity);
            return true;
        }
        if (self->configured_transparent_colors[index].is_set) {
            *color = self->configured_transparent_colors[index].color; *opacity = self->configured_transparent_colors[index].opacity;
            if (*opacity < 0) *opacity = OPT(background_opacity);
            return true;
        }
    }
    return false;
}

DynamicColor
colorprofile_to_color(const ColorProfile *self, DynamicColor entry, DynamicColor defval) {
    switch(entry.type) {
        case COLOR_NOT_SET:
            return defval;
        case COLOR_IS_INDEX: {
            DynamicColor ans;
            ans.rgb = self->color_table[entry.rgb & 0xff] & 0xffffff;
            ans.type = COLOR_IS_RGB;
            return ans;
        }
        case COLOR_IS_RGB:
        case COLOR_IS_SPECIAL:
            return entry;
    }
    return entry;
}

color_type
colorprofile_to_color_with_fallback(ColorProfile *self, DynamicColor entry, DynamicColor defval, DynamicColor fallback, DynamicColor fallback_defval) {
    switch(entry.type) {
        case COLOR_NOT_SET:
        case COLOR_IS_SPECIAL:
            if (defval.type == COLOR_IS_SPECIAL) return colorprofile_to_color(self, fallback, fallback_defval).rgb;
            return defval.rgb;
        case COLOR_IS_RGB:
            return entry.rgb;
        case COLOR_IS_INDEX:
            return self->color_table[entry.rgb & 0xff] & 0xffffff;
    }
    return entry.rgb;
}
static Color* alloc_color(unsigned char r, unsigned char g, unsigned char b, unsigned a);

static bool
colortable_colors_into_dict(ColorProfile *self, unsigned start, unsigned limit, PyObject *ans) {
    static char buf[32] = {'c', 'o', 'l', 'o', 'r', 0};
    for (unsigned i = start; i < limit; i++) {
        snprintf(buf + 5, sizeof(buf) - 6, "%u", i);
        PyObject *val = PyLong_FromUnsignedLong(self->color_table[i]);
        if (!val) return false;
        int ret = PyDict_SetItemString(ans, buf, val);
        Py_DECREF(val);
        if (ret != 0) return false;
    }
    return true;
}

static PyObject*
basic_colors(ColorProfile *self, PyObject *args UNUSED) {
#define basic_colors_doc "Return the basic colors as a dictionary of color_name to integer or None (names are the same as used in kitty.conf)"
    RAII_PyObject(ans, PyDict_New()); if (ans == NULL) return NULL;
    if (!colortable_colors_into_dict(self, 0, 16, ans)) return NULL;

#define D(attr, name) { \
    unsigned long c = colorprofile_to_color(self, self->overridden.attr, self->configured.attr).rgb; \
    PyObject *val = PyLong_FromUnsignedLong(c); if (!val) return NULL; \
    int ret = PyDict_SetItemString(ans, #name, val); Py_DECREF(val); \
    if (ret != 0) return NULL; \
}

    D(default_fg, foreground); D(default_bg, background);
#undef D
    return Py_NewRef(ans);
}

static PyObject*
as_dict(ColorProfile *self, PyObject *args UNUSED) {
#define as_dict_doc "Return all colors as a dictionary of color_name to integer or None (names are the same as used in kitty.conf)"
    RAII_PyObject(ans, PyDict_New()); if (ans == NULL) return NULL;
    if (!colortable_colors_into_dict(self, 0, arraysz(self->color_table), ans)) return NULL;
#define D(attr, name) { \
    if (self->overridden.attr.type != COLOR_NOT_SET) { \
        int ret; PyObject *val; \
        if (self->overridden.attr.type == COLOR_IS_SPECIAL) { \
            val = Py_NewRef(Py_None); \
        } else { \
            unsigned long c = colorprofile_to_color(self, self->overridden.attr, self->configured.attr).rgb; \
            val = PyLong_FromUnsignedLong(c); \
        } \
        if (!val) { return NULL; } \
        ret = PyDict_SetItemString(ans, #name, val); \
        Py_DECREF(val); \
        if (ret != 0) { return NULL; } \
    }}
    D(default_fg, foreground); D(default_bg, background);
    D(cursor_color, cursor); D(cursor_text_color, cursor_text); D(highlight_fg, selection_foreground);
    D(highlight_bg, selection_background); D(visual_bell_color, visual_bell_color);
    RAII_PyObject(transparent_background_colors, PyList_New(0));
    if (!transparent_background_colors) return NULL;
    for (size_t i = 0; i < arraysz(self->overriden_transparent_colors); i++) {
        TransparentDynamicColor *c = NULL;
        if (self->overriden_transparent_colors[i].is_set) c = self->overriden_transparent_colors + i;
        else if (self->configured_transparent_colors[i].is_set) c = self->configured_transparent_colors + i;
        if (c) {
            RAII_PyObject(t, Py_BuildValue("Nf", alloc_color((c->color >> 16) & 0xff, (c->color >> 8) & 0xff, c->color & 0xff, 0), c->opacity));
            if (!t) return NULL;
            if (PyList_Append(transparent_background_colors, t) != 0) return NULL;
        }
    }
    if (PyList_GET_SIZE(transparent_background_colors)) {
        RAII_PyObject(t, PyList_AsTuple(transparent_background_colors));
        if (!t) return NULL;
        if (PyDict_SetItemString(ans, "transparent_background_colors", t) != 0) return NULL;
    }
#undef D
    return Py_NewRef(ans);
}

static PyObject*
as_color(ColorProfile *self, PyObject *val) {
#define as_color_doc "Convert the specified terminal color into an (r, g, b) tuple based on the current profile values"
    if (!PyLong_Check(val)) { PyErr_SetString(PyExc_TypeError, "val must be an int"); return NULL; }
    unsigned long entry = PyLong_AsUnsignedLong(val);
    unsigned int t = entry & 0xFF;
    uint8_t r;
    uint32_t col = 0;
    switch(t) {
        case 1:
            r = (entry >> 8) & 0xff;
            col = self->color_table[r];
            break;
        case 2:
            col = entry >> 8;
            break;
        default:
            Py_RETURN_NONE;
    }
    Color *ans = PyObject_New(Color, &Color_Type);
    if (ans) {
        ans->color.val = 0;
        ans->color.rgb = col;
    }
    return (PyObject*)ans;
}

static PyObject*
reset_color_table(ColorProfile *self, PyObject *a UNUSED) {
#define reset_color_table_doc "Reset all customized colors back to defaults"
    memcpy(self->color_table, self->orig_color_table, sizeof(FG_BG_256));
    self->dirty = true;
    Py_RETURN_NONE;
}

static PyObject*
reset_color(ColorProfile *self, PyObject *val) {
#define reset_color_doc "Reset the specified color"
    uint8_t i = PyLong_AsUnsignedLong(val) & 0xff;
    self->color_table[i] = self->orig_color_table[i];
    self->dirty = true;
    Py_RETURN_NONE;
}

static PyObject*
set_color(ColorProfile *self, PyObject *args) {
#define set_color_doc "Set the specified color"
    unsigned char i;
    unsigned long val;
    if (!PyArg_ParseTuple(args, "Bk", &i, &val)) return NULL;
    self->color_table[i] = val;
    self->dirty = true;
    Py_RETURN_NONE;
}

void
copy_color_table_to_buffer(ColorProfile *self, color_type *buf, int offset, size_t stride) {
    size_t i;
    stride = MAX(1u, stride);
    for (i = 0, buf = buf + offset; i < arraysz(self->color_table); i++, buf += stride) *buf = self->color_table[i];
    // Copy the mark colors
    for (i = 0; i < arraysz(self->mark_backgrounds); i++) {
        *buf = self->mark_backgrounds[i]; buf += stride;
    }
    for (i = 0; i < arraysz(self->mark_foregrounds); i++) {
        *buf = self->mark_foregrounds[i]; buf += stride;
    }
    self->dirty = false;
}

static void
push_onto_color_stack_at(ColorProfile *self, unsigned int i) {
    self->color_stack[i].dynamic_colors = self->overridden;
    memcpy(self->color_stack[i].transparent_colors, self->overriden_transparent_colors, sizeof(self->overriden_transparent_colors));
    self->color_stack[i].dynamic_colors = self->overridden;
    memcpy(self->color_stack[i].color_table, self->color_table, sizeof(self->color_stack->color_table));
}

static void
copy_from_color_stack_at(ColorProfile *self, unsigned int i) {
    self->overridden = self->color_stack[i].dynamic_colors;
    memcpy(self->color_table, self->color_stack[i].color_table, sizeof(self->color_table));
    memcpy(self->overriden_transparent_colors, self->color_stack[i].transparent_colors, sizeof(self->overriden_transparent_colors));
}

bool
colorprofile_push_colors(ColorProfile *self, unsigned int idx) {
    if (idx > 10) return false;
    size_t sz = idx ? idx : self->color_stack_idx + 1;
    sz = MIN(10u, sz);
    if (self->color_stack_sz < sz) {
        self->color_stack = realloc(self->color_stack, sz * sizeof(self->color_stack[0]));
        if (self->color_stack == NULL) fatal("Out of memory while ensuring space for %zu elements in color stack", sz);
        memset(self->color_stack + self->color_stack_sz, 0, (sz - self->color_stack_sz) * sizeof(self->color_stack[0]));
        self->color_stack_sz = sz;
    }
    if (idx == 0) {
        if (self->color_stack_idx >= self->color_stack_sz) {
            memmove(self->color_stack, self->color_stack + 1, (self->color_stack_sz - 1) * sizeof(self->color_stack[0]));
            idx = self->color_stack_sz - 1;
        } else idx = self->color_stack_idx++;
        push_onto_color_stack_at(self, idx);
        return true;
    }
    idx -= 1;
    if (idx < self->color_stack_sz) {
        push_onto_color_stack_at(self, idx);
        return true;
    }
    return false;
}

bool
colorprofile_pop_colors(ColorProfile *self, unsigned int idx) {
    if (idx == 0) {
        if (!self->color_stack_idx) return false;
        copy_from_color_stack_at(self, --self->color_stack_idx);
        memset(self->color_stack + self->color_stack_idx, 0, sizeof(self->color_stack[0]));
        return true;
    }
    idx -= 1;
    if (idx < self->color_stack_sz) {
        copy_from_color_stack_at(self, idx);
        return true;
    }
    return false;
}

void
colorprofile_report_stack(ColorProfile *self, unsigned int *idx, unsigned int *count) {
    *count = self->color_stack_idx;
    *idx = self->color_stack_idx ? self->color_stack_idx - 1 : 0;
}

static PyObject*
color_table_address(ColorProfile *self, PyObject *a UNUSED) {
#define color_table_address_doc "Pointer address to start of color table"
    return PyLong_FromVoidPtr((void*)self->color_table);
}

static PyObject*
default_color_table(PyObject *self UNUSED, PyObject *args UNUSED) {
    return create_256_color_table();
}

// Boilerplate {{{

#define CGETSET(name, nullable) \
    static PyObject* name##_get(ColorProfile *self, void UNUSED *closure) {  \
        DynamicColor ans = colorprofile_to_color(self, self->overridden.name, self->configured.name);  \
        if (ans.type == COLOR_IS_SPECIAL) { \
            if (nullable) Py_RETURN_NONE; \
            return (PyObject*)alloc_color(0, 0, 0, 0); \
        } \
        return (PyObject*)alloc_color((ans.rgb >> 16) & 0xff, (ans.rgb >> 8) & 0xff, ans.rgb & 0xff, 0); \
    } \
    static int name##_set(ColorProfile *self, PyObject *v, void UNUSED *closure) { \
        if (v == NULL) { self->overridden.name.val = 0; return 0; } \
        if (PyLong_Check(v)) { \
            unsigned long val = PyLong_AsUnsignedLong(v); \
            self->overridden.name.rgb = val & 0xffffff; \
            self->overridden.name.type = COLOR_IS_RGB; \
        } else if (PyObject_TypeCheck(v, &Color_Type)) { \
            Color *c = (Color*)v; self->overridden.name.rgb = c->color.rgb; self->overridden.name.type = COLOR_IS_RGB; \
        } else if (v == Py_None) { \
            if (!nullable) { PyErr_SetString(PyExc_TypeError, #name " cannot be set to None"); return -1; } \
            self->overridden.name.type = COLOR_IS_SPECIAL; self->overridden.name.rgb = 0; \
        } \
        self->dirty = true; return 0; \
    }

CGETSET(default_fg, false)
CGETSET(default_bg, false)
CGETSET(cursor_color, true)
CGETSET(cursor_text_color, true)
CGETSET(highlight_fg, true)
CGETSET(highlight_bg, true)
CGETSET(visual_bell_color, true)
#undef CGETSET

static PyGetSetDef cp_getsetters[] = {
    GETSET(default_fg)
    GETSET(default_bg)
    GETSET(cursor_color)
    GETSET(cursor_text_color)
    GETSET(highlight_fg)
    GETSET(highlight_bg)
    GETSET(visual_bell_color)
    {NULL}  /* Sentinel */
};


static PyMemberDef cp_members[] = {
    {NULL}
};

static PyObject*
reload_from_opts(ColorProfile *self, PyObject *args UNUSED) {
    PyObject *opts = global_state.options_object;
    if (!PyArg_ParseTuple(args, "|O", &opts)) return NULL;
    self->dirty = true;
    if (!set_configured_colors(self, opts)) return NULL;
    if (!set_mark_colors(self, opts)) return NULL;
    if (!set_colortable(self, opts)) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
get_transparent_background_color(ColorProfile *self, PyObject *index) {
    if (!PyLong_Check(index)) { PyErr_SetString(PyExc_TypeError, "index must be an int"); return NULL; }
    unsigned long idx = PyLong_AsUnsignedLong(index);
    if (PyErr_Occurred()) return NULL;
    if (idx >= arraysz(self->configured_transparent_colors)) Py_RETURN_NONE;
    TransparentDynamicColor *c = self->overriden_transparent_colors[idx].is_set ? self->overriden_transparent_colors + idx : self->configured_transparent_colors + idx;
    if (!c->is_set) Py_RETURN_NONE;
    float opacity = c->opacity >= 0 ? c->opacity : OPT(background_opacity);
    return (PyObject*)alloc_color((c->color >> 16) & 0xff, (c->color >> 8) & 0xff, c->color & 0xff, (unsigned)(255.f * opacity));
}

static PyObject*
set_transparent_background_color(ColorProfile *self, PyObject *const *args, Py_ssize_t nargs) {
    if (nargs < 1) { PyErr_SetString(PyExc_TypeError, "must specify index"); return NULL; }
    if (!PyLong_Check(args[0])) { PyErr_SetString(PyExc_TypeError, "index must be an int"); return NULL; }
    unsigned long idx = PyLong_AsUnsignedLong(args[0]);
    if (PyErr_Occurred()) return NULL;
    if (idx >= arraysz(self->configured_transparent_colors)) Py_RETURN_NONE;
    if (nargs < 2) { self->overriden_transparent_colors[idx].is_set = false; Py_RETURN_NONE; }
    if (!PyObject_TypeCheck(args[1], &Color_Type)) { PyErr_SetString(PyExc_TypeError, "color must be Color object"); return NULL; }
    Color *c = (Color*)args[1];
    float opacity = (float)(c->color.alpha) / 255.f;
    if (nargs > 2 && PyFloat_Check(args[2])) opacity = (float)PyFloat_AsDouble(args[2]);
    self->overriden_transparent_colors[idx].is_set = true;
    self->overriden_transparent_colors[idx].color = c->color.rgb;
    self->overriden_transparent_colors[idx].opacity = MAX(-1.f, MIN(opacity, 1.f));
    Py_RETURN_NONE;
}

static PyMethodDef cp_methods[] = {
    METHOD(reset_color_table, METH_NOARGS)
    METHOD(as_dict, METH_NOARGS)
    METHOD(basic_colors, METH_NOARGS)
    METHOD(color_table_address, METH_NOARGS)
    METHOD(as_color, METH_O)
    METHOD(reset_color, METH_O)
    METHOD(set_color, METH_VARARGS)
    METHODB(get_transparent_background_color, METH_O),
    METHODB(reload_from_opts, METH_VARARGS),
    {"set_transparent_background_color", (PyCFunction)(void(*)(void))set_transparent_background_color, METH_FASTCALL, ""},
    {NULL}  /* Sentinel */
};


PyTypeObject ColorProfile_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.ColorProfile",
    .tp_basicsize = sizeof(ColorProfile),
    .tp_dealloc = (destructor)dealloc_cp,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "ColorProfile",
    .tp_members = cp_members,
    .tp_methods = cp_methods,
    .tp_getset = cp_getsetters,
    .tp_new = new_cp,
};
// }}}

static Color*
alloc_color(unsigned char r, unsigned char g, unsigned char b, unsigned a) {
    Color *self = (Color *)(&Color_Type)->tp_alloc(&Color_Type, 0);
    if (self != NULL) {
        self->color.r = r; self->color.g = g; self->color.b = b; self->color.a = a;
    }
    return self;
}

static PyObject *
new_color(PyTypeObject *type UNUSED, PyObject *args, PyObject *kwds) {
    static const char* kwlist[] = {"red", "green", "blue", "alpha", NULL};
    unsigned char r = 0, g = 0, b = 0, a = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|BBBB", (char**)kwlist, &r, &g, &b, &a)) return NULL;
    return (PyObject*) alloc_color(r, g, b, a);
}

static PyObject*
Color_as_int(Color *self) {
    return PyLong_FromUnsignedLong(self->color.val);
}

static PyObject*
color_truediv(Color *self, PyObject *divisor) {
    RAII_PyObject(o, PyNumber_Float(divisor));
    if (o == NULL) return NULL;
    double r = self->color.r, g = self->color.g, b = self->color.b, a = self->color.a;
    double d = PyFloat_AS_DOUBLE(o) * 255.;
    return Py_BuildValue("dddd", r/d, g/d, b/d, a/d);
}

static PyNumberMethods color_number_methods = {
    .nb_int = (unaryfunc)Color_as_int,
    .nb_true_divide = (binaryfunc)color_truediv,
};

#define CGETSET(name) \
    static PyObject* name##_get(Color *self, void UNUSED *closure) { return PyLong_FromUnsignedLong(self->color.name);  }
CGETSET(red)
CGETSET(green)
CGETSET(blue)
CGETSET(alpha)
#undef CGETSET

static PyObject*
rgb_get(Color *self, void *closure UNUSED) {
    return PyLong_FromUnsignedLong(self->color.rgb);
}

static PyObject*
luminance_get(Color *self, void *closure UNUSED) {
    return PyFloat_FromDouble(rgb_luminance(self->color) / 255.0);
}

static PyObject*
is_dark_get(Color *self, void *closure UNUSED) {
    if (rgb_luminance(self->color) / 255.0 < 0.5) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject*
sgr_get(Color* self, void *closure UNUSED) {
    char buf[32];
    int sz = snprintf(buf, sizeof(buf), ":2:%u:%u:%u", self->color.r, self->color.g, self->color.b);
    return PyUnicode_FromStringAndSize(buf, sz);
}

static PyObject*
sharp_get(Color* self, void *closure UNUSED) {
    char buf[32];
    int sz;
    if (self->color.alpha) sz = snprintf(buf, sizeof(buf), "#%02x%02x%02x%02x", self->color.a, self->color.r, self->color.g, self->color.b);
    else sz = snprintf(buf, sizeof(buf), "#%02x%02x%02x", self->color.r, self->color.g, self->color.b);
    return PyUnicode_FromStringAndSize(buf, sz);
}

static PyObject*
color_cmp(PyObject *self, PyObject *other, int op) {
    if (op != Py_EQ && op != Py_NE) return Py_NotImplemented;
    if (!PyObject_TypeCheck(other, &Color_Type)) {
        if (op == Py_EQ) Py_RETURN_FALSE;
        Py_RETURN_TRUE;
    }
    Color *a = (Color*)self, *b = (Color*)other;
    switch (op) {
        case Py_EQ: { if (a->color.val == b->color.val) { Py_RETURN_TRUE; } Py_RETURN_FALSE; }
        case Py_NE: { if (a->color.val != b->color.val) { Py_RETURN_TRUE; } Py_RETURN_FALSE; }
        default:
            return Py_NotImplemented;
    }
}

static PyGetSetDef color_getsetters[] = {
    {"rgb", (getter) rgb_get, NULL, "rgb", NULL},
    {"red", (getter) red_get, NULL, "red", NULL},
    {"green", (getter) green_get, NULL, "green", NULL},
    {"blue", (getter) blue_get, NULL, "blue", NULL},
    {"alpha", (getter) alpha_get, NULL, "alpha", NULL},
    {"r", (getter) red_get, NULL, "red", NULL},
    {"g", (getter) green_get, NULL, "green", NULL},
    {"b", (getter) blue_get, NULL, "blue", NULL},
    {"a", (getter) alpha_get, NULL, "alpha", NULL},
    {"luminance", (getter) luminance_get, NULL, "luminance", NULL},
    {"as_sgr", (getter) sgr_get, NULL, "as_sgr", NULL},
    {"as_sharp", (getter) sharp_get, NULL, "as_sharp", NULL},
    {"is_dark", (getter) is_dark_get, NULL, "is_dark", NULL},
    {NULL}  /* Sentinel */
};

static PyObject*
contrast(Color* self, PyObject *o) {
    if (!PyObject_TypeCheck(o, &Color_Type)) { PyErr_SetString(PyExc_TypeError, "Not a Color"); return NULL; }
    Color *other = (Color*) o;
    return PyFloat_FromDouble(rgb_contrast(self->color, other->color));
}

static PyMethodDef color_methods[] = {
    METHODB(contrast, METH_O),
    {NULL}  /* Sentinel */
};


static PyObject *
repr(Color *self) {
    if (self->color.alpha) return PyUnicode_FromFormat("Color(red=%u, green=%u, blue=%u, alpha=%u)", self->color.r, self->color.g, self->color.b, self->color.a);
    return PyUnicode_FromFormat("Color(%u, %u, %u)", self->color.r, self->color.g, self->color.b);
}

static Py_hash_t
color_hash(PyObject *x) {
    return ((Color*)x)->color.val;
}

PyTypeObject Color_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "kitty.fast_data_types.Color",
    .tp_basicsize = sizeof(Color),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Color",
    .tp_new = new_color,
    .tp_getset = color_getsetters,
    .tp_as_number = &color_number_methods,
    .tp_methods = color_methods,
    .tp_repr = (reprfunc)repr,
    .tp_hash = color_hash,
    .tp_richcompare = color_cmp,
};


static PyMethodDef module_methods[] = {
    METHODB(default_color_table, METH_NOARGS),
    METHODB(patch_color_profiles, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

int init_ColorProfile(PyObject *module) {\
    if (PyType_Ready(&ColorProfile_Type) < 0) return 0;
    if (PyModule_AddObject(module, "ColorProfile", (PyObject *)&ColorProfile_Type) != 0) return 0;
    Py_INCREF(&ColorProfile_Type);

    if (PyType_Ready(&Color_Type) < 0) return 0;
    if (PyModule_AddObject(module, "Color", (PyObject *)&Color_Type) != 0) return 0;
    Py_INCREF(&Color_Type);

    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return 1;
}


// }}}
