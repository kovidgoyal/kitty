/*
 * colors.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define EXTRA_INIT if (PyModule_AddFunctions(module, module_methods) != 0) return false;
#include "data-types.h"
#include <structmember.h>

PyTypeObject ColorProfile_Type;

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

static inline void
init_FG_BG_table(void) {
    if (UNLIKELY(FG_BG_256[255] == 0)) {
        // colors 16..232: the 6x6x6 color cube
        const uint8_t valuerange[6] = {0x00, 0x5f, 0x87, 0xaf, 0xd7, 0xff};
        uint8_t i, j=16;
        for(i = 0; i < 217; i++, j++) {
            uint8_t r = valuerange[(i / 36) % 6], g = valuerange[(i / 6) % 6], b = valuerange[i % 6];
            FG_BG_256[j] = (r << 16) | (g << 8) | b;
        }
        // colors 233..255: grayscale
        for(i = 1; i < 24; i++, j++) {
            uint8_t v = 8 + i * 10;
            FG_BG_256[j] = (v << 16) | (v << 8) | v;
        }
    }
}

PyObject* create_256_color_table() {
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

static PyObject *
new(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    ColorProfile *self;

    self = (ColorProfile *)type->tp_alloc(type, 0);
    if (self != NULL) {
        init_FG_BG_table();
        memcpy(self->color_table, FG_BG_256, sizeof(FG_BG_256));
        memcpy(self->orig_color_table, FG_BG_256, sizeof(FG_BG_256));
        self->dirty = true;
    }
    return (PyObject*) self;
}

static void
dealloc(ColorProfile* self) {
    Py_TYPE(self)->tp_free((PyObject*)self);
}

ColorProfile*
alloc_color_profile() {
    return (ColorProfile*)new(&ColorProfile_Type, NULL, NULL);
}


static PyObject*
update_ansi_color_table(ColorProfile *self, PyObject *val) {
#define update_ansi_color_table_doc "Update the 256 basic colors"
    if (!PyList_Check(val)) { PyErr_SetString(PyExc_TypeError, "color table must be a list"); return NULL; }
    if (PyList_GET_SIZE(val) != arraysz(FG_BG_256)) { PyErr_SetString(PyExc_TypeError, "color table must have 256 items"); return NULL; }
    for (size_t i = 0; i < arraysz(FG_BG_256); i++) {
        self->color_table[i] = PyLong_AsUnsignedLong(PyList_GET_ITEM(val, i));
        self->orig_color_table[i] = self->color_table[i];
    }
    self->dirty = true;
    Py_RETURN_NONE;
}

static PyObject*
patch_color_profiles(PyObject *module UNUSED, PyObject *args) {
    PyObject *spec, *profiles, *v; ColorProfile *self; int change_configured; PyObject *cursor_text_color;
    if (!PyArg_ParseTuple(args, "O!OO!p", &PyDict_Type, &spec, &cursor_text_color, &PyTuple_Type, &profiles, &change_configured)) return NULL;
    char key[32] = {0};
    for (size_t i = 0; i < arraysz(FG_BG_256); i++) {
        snprintf(key, sizeof(key) - 1, "color%zu", i);
        v = PyDict_GetItemString(spec, key);
        if (v) {
            color_type color = PyLong_AsUnsignedLong(v);
            for (Py_ssize_t j = 0; j < PyTuple_GET_SIZE(profiles); j++) {
                self = (ColorProfile*)PyTuple_GET_ITEM(profiles, j);
                self->color_table[i] = color;
                if (change_configured) self->orig_color_table[i] = color;
                self->dirty = true;
            }
        }
    }
#define S(config_name, profile_name) { \
    v = PyDict_GetItemString(spec, #config_name); \
    if (v) { \
        color_type color = PyLong_AsUnsignedLong(v); \
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(profiles); i++) { \
            self = (ColorProfile*)PyTuple_GET_ITEM(profiles, i); \
            self->overridden.profile_name = (color << 8) | 2; \
            if (change_configured) self->configured.profile_name = color; \
            self->dirty = true; \
        } \
    } \
}
        S(foreground, default_fg); S(background, default_bg); S(cursor, cursor_color);
        S(selection_foreground, highlight_fg); S(selection_background, highlight_bg);
#undef S
    if (cursor_text_color != Py_False) {
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(profiles); i++) {
            self = (ColorProfile*)PyTuple_GET_ITEM(profiles, i);
            self->overridden.cursor_text_color = 0x111111;
            self->overridden.cursor_text_uses_bg = 3;
            if (cursor_text_color != Py_None) {
                self->overridden.cursor_text_color = (PyLong_AsUnsignedLong(cursor_text_color) << 8) | 2;
                self->overridden.cursor_text_uses_bg = 1;
            }
            if (change_configured) {
                self->configured.cursor_text_color = self->overridden.cursor_text_color;
                self->configured.cursor_text_uses_bg = self->overridden.cursor_text_uses_bg;
            }
            self->dirty = true;
        }
    }

    Py_RETURN_NONE;
}

color_type
colorprofile_to_color(ColorProfile *self, color_type entry, color_type defval) {
    color_type t = entry & 0xFF, r;
    switch(t) {
        case 1:
            r = (entry >> 8) & 0xff;
            return self->color_table[r];
        case 2:
            return entry >> 8;
        default:
            return defval;
    }
}

float
cursor_text_as_bg(ColorProfile *self) {
    if (self->overridden.cursor_text_uses_bg & 1) {
        return self->overridden.cursor_text_uses_bg & 2 ? 1.f : 0.f;
    }
    return self->configured.cursor_text_uses_bg & 2 ? 1.f : 0.f;
}


static PyObject*
as_dict(ColorProfile *self, PyObject *args UNUSED) {
#define as_dict_doc "Return all colors as a dictionary of color_name to integer (names are the same as used in kitty.conf)"
    PyObject *ans = PyDict_New();
    if (ans == NULL) return PyErr_NoMemory();
    for (unsigned i = 0; i < arraysz(self->color_table); i++) {
        static char buf[32] = {0};
        snprintf(buf, sizeof(buf) - 1, "color%u", i);
        PyObject *val = PyLong_FromUnsignedLong(self->color_table[i]);
        if (!val) { Py_CLEAR(ans); return PyErr_NoMemory(); }
        int ret = PyDict_SetItemString(ans, buf, val);
        Py_CLEAR(val);
        if (ret != 0) { Py_CLEAR(ans); return NULL; }
    }
#define D(attr, name) { \
    color_type c = colorprofile_to_color(self, self->overridden.attr, 0xffffffff); \
    if (c != 0xffffffff) { \
        PyObject *val = PyLong_FromUnsignedLong(c); \
        if (!val) { Py_CLEAR(ans); return PyErr_NoMemory(); } \
        int ret = PyDict_SetItemString(ans, #name, val); \
        Py_CLEAR(val); \
        if (ret != 0) { Py_CLEAR(ans); return NULL; } \
    }}
    D(default_fg, foreground); D(default_bg, background);
    D(cursor_color, cursor); D(cursor_text_color, cursor_text); D(highlight_fg, selection_foreground);
    D(highlight_bg, selection_background);

#undef D
    return ans;
}

static PyObject*
as_color(ColorProfile *self, PyObject *val) {
#define as_color_doc "Convert the specified terminal color into an (r, g, b) tuple based on the current profile values"
    if (!PyLong_Check(val)) { PyErr_SetString(PyExc_TypeError, "val must be an int"); return NULL; }
    unsigned long entry = PyLong_AsUnsignedLong(val);
    unsigned int t = entry & 0xFF;
    uint8_t r;
    uint32_t col = 0;
    PyObject *ans = NULL;
    switch(t) {
        case 1:
            r = (entry >> 8) & 0xff;
            col = self->color_table[r];
            break;
        case 2:
            col = entry >> 8;
            break;
        default:
            ans = Py_None; Py_INCREF(Py_None);
    }
    if (ans == NULL) ans = Py_BuildValue("BBB", (unsigned char)(col >> 16), (unsigned char)((col >> 8) & 0xFF), (unsigned char)(col & 0xFF));
    return ans;
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

static PyObject*
set_configured_colors(ColorProfile *self, PyObject *args) {
#define set_configured_colors_doc "Set the configured colors"
    if (!PyArg_ParseTuple(
                args, "II|IIIII",
                &(self->configured.default_fg), &(self->configured.default_bg),
                &(self->configured.cursor_color), &(self->configured.cursor_text_color), &(self->configured.cursor_text_uses_bg),
                &(self->configured.highlight_fg), &(self->configured.highlight_bg))) return NULL;
    self->dirty = true;
    Py_RETURN_NONE;
}

void
copy_color_table_to_buffer(ColorProfile *self, color_type *buf, int offset, size_t stride) {
    size_t i;
    stride = MAX(1u, stride);
    for (i = 0, buf = buf + offset; i < sizeof(self->color_table)/sizeof(self->color_table[0]); i++, buf += stride) {
        *buf = self->color_table[i];
    }
    self->dirty = false;
}

void
colorprofile_push_dynamic_colors(ColorProfile *self) {
    if (self->dynamic_color_stack_idx >= arraysz(self->dynamic_color_stack)) {
        memmove(self->dynamic_color_stack, self->dynamic_color_stack + 1, sizeof(self->dynamic_color_stack) - sizeof(self->dynamic_color_stack[0]));
        self->dynamic_color_stack_idx = arraysz(self->dynamic_color_stack) - 1;
    }
    self->dynamic_color_stack[self->dynamic_color_stack_idx++] = self->overridden;
}

void
colorprofile_pop_dynamic_colors(ColorProfile *self) {
    if (!self->dynamic_color_stack_idx) return;
    self->overridden = self->dynamic_color_stack[--(self->dynamic_color_stack_idx)];
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

#define CGETSET(name) \
    static PyObject* name##_get(ColorProfile *self, void UNUSED *closure) { return PyLong_FromUnsignedLong(colorprofile_to_color(self, self->overridden.name, self->configured.name));  } \
    static int name##_set(ColorProfile *self, PyObject *val, void UNUSED *closure) { if (val == NULL) { PyErr_SetString(PyExc_TypeError, "Cannot delete attribute"); return -1; } self->overridden.name = (color_type) PyLong_AsUnsignedLong(val); self->dirty = true; return 0; }

CGETSET(default_fg)
CGETSET(default_bg)
CGETSET(cursor_color)
CGETSET(cursor_text_color)
CGETSET(highlight_fg)
CGETSET(highlight_bg)

static PyGetSetDef getsetters[] = {
    GETSET(default_fg)
    GETSET(default_bg)
    GETSET(cursor_color)
    GETSET(cursor_text_color)
    GETSET(highlight_fg)
    GETSET(highlight_bg)
    {NULL}  /* Sentinel */
};


static PyMemberDef members[] = {
    {NULL}
};

static PyMethodDef methods[] = {
    METHOD(update_ansi_color_table, METH_O)
    METHOD(reset_color_table, METH_NOARGS)
    METHOD(as_dict, METH_NOARGS)
    METHOD(color_table_address, METH_NOARGS)
    METHOD(as_color, METH_O)
    METHOD(reset_color, METH_O)
    METHOD(set_color, METH_VARARGS)
    METHOD(set_configured_colors, METH_VARARGS)
    {NULL}  /* Sentinel */
};


PyTypeObject ColorProfile_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.ColorProfile",
    .tp_basicsize = sizeof(ColorProfile),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "ColorProfile",
    .tp_members = members,
    .tp_methods = methods,
    .tp_getset = getsetters,
    .tp_new = new,
};

static PyMethodDef module_methods[] = {
    METHODB(default_color_table, METH_NOARGS),
    METHODB(patch_color_profiles, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


INIT_TYPE(ColorProfile)
// }}}
