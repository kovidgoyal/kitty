/*
 * cursor.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "line.h"

#include <structmember.h>

static PyObject *
new_cursor_object(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    Cursor *self;

    self = (Cursor *)type->tp_alloc(type, 0);
    return (PyObject *)self;
}

static void
dealloc(Cursor *self) {
    Py_TYPE(self)->tp_free((PyObject *)self);
}

#define EQ(x) (a->x == b->x)
static int
__eq__(Cursor *a, Cursor *b) {
    return memcmp(&a->style, &b->style, sizeof(a->style)) == 0 && EQ(x) && EQ(y) && EQ(shape) && EQ(non_blinking);
}
#undef EQ

static const char *cursor_names[NUM_OF_CURSOR_SHAPES] = {"NO_SHAPE", "BLOCK", "BEAM", "UNDERLINE", "HOLLOW"};

#define BOOL(x) ((x) ? Py_True : Py_False)
static PyObject *
repr(Cursor *self) {
    return PyUnicode_FromFormat(
        "Cursor(x=%u, y=%u, shape=%s, blink=%R, fg=#%08x, bg=#%08x, bold=%R, italic=%R, reverse=%R, strikethrough=%R, dim=%R, decoration=%d, "
        "decoration_fg=#%08x, text_blink=%R)",
        self->x,
        self->y,
        (self->shape < NUM_OF_CURSOR_SHAPES ? cursor_names[self->shape] : "INVALID"),
        BOOL(!self->non_blinking),
        self->style.fg,
        self->style.bg,
        BOOL(self->style.attrs.bold),
        BOOL(self->style.attrs.italic),
        BOOL(self->style.attrs.reverse),
        BOOL(self->style.attrs.strike),
        BOOL(self->style.attrs.dim),
        (int)self->style.attrs.decoration,
        self->style.decoration_fg,
        BOOL(self->style.attrs.blink));
}

void
cursor_reset_display_attrs(Cursor *self) {
    zero_at_ptr(&self->style);
}


static void
parse_color(int *params, unsigned int *i, unsigned int count, uint32_t *result) {
    unsigned int attr;
    uint8_t r, g, b;
    if (*i < count) {
        attr = params[(*i)++];
        switch (attr) {
            case 5:
                if (*i < count) *result = (params[(*i)++] & 0xFF) << 8 | 1;
                break;
            case 2:
                if (*i + 2 < count) {
                    /* Ignore the first parameter in a four parameter RGB */
                    /* sequence (unused color space id), see https://github.com/kovidgoyal/kitty/issues/227 */
                    if (*i + 3 < count) (*i)++;
                    r = params[(*i)++] & 0xFF;
                    g = params[(*i)++] & 0xFF;
                    b = params[(*i)++] & 0xFF;
                    *result = r << 24 | g << 16 | b << 8 | 2;
                }
                break;
        }
    }
}


void
cursor_from_sgr(Cursor *self, int *params, unsigned int count, bool is_group) {
#define SET_COLOR(which)                              \
    { parse_color(params, &i, count, &self->which); } \
    break;
    START_ALLOW_CASE_RANGE
    unsigned int i = 0, attr;
    if (!count) {
        params[0] = 0;
        count = 1;
    }
    while (i < count) {
        attr = params[i++];
        switch (attr) {
            case 0: cursor_reset_display_attrs(self); break;
            case 1: self->style.attrs.bold = true; break;
            case 2: self->style.attrs.dim = true; break;
            case 3: self->style.attrs.italic = true; break;
            case 4:
                if (is_group && i < count) {
                    self->style.attrs.decoration = MIN(5, params[i]);
                    i++;
                } else self->style.attrs.decoration = 1;
                break;
            case 5: self->style.attrs.blink = true; break;
            case 7: self->style.attrs.reverse = true; break;
            case 9: self->style.attrs.strike = true; break;
            case 21: self->style.attrs.decoration = 2; break;
            case 221: self->style.attrs.bold = false; break;
            case 222: self->style.attrs.dim = false; break;
            case 22:
                self->style.attrs.bold = false;
                self->style.attrs.dim = false;
                break;
            case 23: self->style.attrs.italic = false; break;
            case 24: self->style.attrs.decoration = 0; break;
            case 25: self->style.attrs.blink = false; break;
            case 27: self->style.attrs.reverse = false; break;
            case 29: self->style.attrs.strike = false; break;
            case 30 ... 37: self->style.fg = ((attr - 30) << 8) | 1; break;
            case 38: SET_COLOR(style.fg);
            case 39: self->style.fg = 0; break;
            case 40 ... 47: self->style.bg = ((attr - 40) << 8) | 1; break;
            case 48: SET_COLOR(style.bg);
            case 49: self->style.bg = 0; break;
            case 90 ... 97: self->style.fg = ((attr - 90 + 8) << 8) | 1; break;
            case 100 ... 107: self->style.bg = ((attr - 100 + 8) << 8) | 1; break;
            case DECORATION_FG_CODE: SET_COLOR(style.decoration_fg);
            case DECORATION_FG_CODE + 1: self->style.decoration_fg = 0; break;
        }
        if (is_group) break;
    }
#undef SET_COLOR
    END_ALLOW_CASE_RANGE
}

static void
apply_sgr_to_style(CellStyle *st, int *params, unsigned int count, bool is_group) {
    // Apply SGR params to a style as DECCARA does
#define SET_COLOR(which)                        \
    {                                           \
        color_type color = 0;                   \
        parse_color(params, &i, count, &color); \
        if (color) st->which = color;           \
    }                                           \
    break;
#define SIMPLE(which, val) \
    st->which = (val);     \
    break;
#define S(which, val)        \
    st->attrs.which = (val); \
    break;

    unsigned int i = 0, attr;
    while (i < count) {
        attr = params[i++];
        switch (attr) {
            case 0: zero_at_ptr(st); break;
            case 1: S(bold, true);
            case 2: S(dim, true);
            case 3: S(italic, true);
            case 4: {
                uint8_t val = 1;
                if (is_group && i < count) {
                    val = MIN(5, params[i]);
                    i++;
                }
                S(decoration, val);
            }
            case 5: S(blink, true);
            case 7: S(reverse, true);
            case 9: S(strike, true);
            case 21: S(decoration, 2);
            case 221: S(bold, false);
            case 222: S(dim, false);
            case 22:
                st->attrs.bold = false;
                st->attrs.dim = false;
                break;
            case 23: S(italic, false);
            case 24: S(decoration, 0);
            case 25: S(blink, false);
            case 27: S(reverse, false);
            case 29: S(strike, false); START_ALLOW_CASE_RANGE
            case 30 ... 37: SIMPLE(fg, ((attr - 30) << 8) | 1);
            case 38: SET_COLOR(fg);
            case 39: SIMPLE(fg, 0);
            case 40 ... 47: SIMPLE(bg, ((attr - 40) << 8) | 1);
            case 48: SET_COLOR(bg);
            case 49: SIMPLE(bg, 0);
            case 90 ... 97: SIMPLE(fg, ((attr - 90 + 8) << 8) | 1);
            case 100 ... 107: SIMPLE(bg, ((attr - 100 + 8) << 8) | 1); END_ALLOW_CASE_RANGE
            case DECORATION_FG_CODE: SET_COLOR(decoration_fg);
            case DECORATION_FG_CODE + 1: SIMPLE(decoration_fg, 0);
        }
        if (is_group) break;
    }
#undef SET_COLOR
#undef SIMPLE
#undef S
}

void
apply_sgr_to_cells(CellStyleTable *t, CPUCell *cells, unsigned int cell_count, int *params, unsigned int count, bool is_group) {
    if (!count) {
        params[0] = 0;
        count = 1;
    }
    // Cells in a region usually have only a few distinct styles, remember the last mapping
    uint32_t last_old = UINT32_MAX, last_new = 0;
    for (unsigned c = 0; c < cell_count; c++) {
        const uint32_t old = cells[c].style_idx;
        if (old != last_old) {
            CellStyle st = *style_table_get(t, old);
            apply_sgr_to_style(&st, params, count, is_group);
            last_old = old;
            last_new = style_table_intern(t, &st);
        }
        cells[c].style_idx = last_new;
    }
}

const char *
cursor_as_sgr(const Cursor *self) {
    static const CellStyle blank = {0};
    return style_as_sgr(&self->style, &blank);
}

static PyObject *
reset_display_attrs(Cursor *self, PyObject *a UNUSED) {
#define reset_display_attrs_doc "Reset all display attributes to unset"
    cursor_reset_display_attrs(self);
    Py_RETURN_NONE;
}

void
cursor_reset(Cursor *self) {
    cursor_reset_display_attrs(self);
    self->x = 0;
    self->y = 0;
    self->shape = NO_CURSOR_SHAPE;
    self->non_blinking = false;
}

void
cursor_copy_to(Cursor *src, Cursor *dest) {
#define CCY(x) dest->x = src->x;
    CCY(x);
    CCY(y);
    CCY(shape);
    CCY(non_blinking);
#undef CCY
    dest->style = src->style;
    dest->style_idx = src->style_idx;
}

static PyObject *copy(Cursor *self, PyObject *);
#define copy_doc "Create a clone of this cursor"

// Boilerplate {{{

#define SGR_BOOL_GETSET(x, field)                                                                                                    \
    static PyObject *x##_get(Cursor *self, void UNUSED *closure) { return Py_NewRef(self->style.attrs.field ? Py_True : Py_False); } \
    static int x##_set(Cursor *self, PyObject *value, void UNUSED *closure) {                                                        \
        if (value == NULL) {                                                                                                         \
            PyErr_SetString(PyExc_TypeError, "Cannot delete attribute");                                                             \
            return -1;                                                                                                               \
        }                                                                                                                            \
        int q = PyObject_IsTrue(value);                                                                                              \
        if (q < 0) return -1;                                                                                                        \
        self->style.attrs.field = q ? 1 : 0;                                                                                         \
        return 0;                                                                                                                    \
    }

SGR_BOOL_GETSET(bold, bold)
SGR_BOOL_GETSET(italic, italic)
SGR_BOOL_GETSET(reverse, reverse)
SGR_BOOL_GETSET(strikethrough, strike)
SGR_BOOL_GETSET(dim, dim)
#undef SGR_BOOL_GETSET

static PyObject *
blink_get(Cursor *self, void UNUSED *closure) {
    PyObject *ans = !self->non_blinking ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

static int
blink_set(Cursor *self, PyObject *value, void UNUSED *closure) {
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete attribute");
        return -1;
    }
    self->non_blinking = PyObject_IsTrue(value) ? false : true;
    return 0;
}

static PyObject *
text_blink_get(Cursor *self, void UNUSED *closure) {
    return Py_NewRef(self->style.attrs.blink ? Py_True : Py_False);
}

static int
text_blink_set(Cursor *self, PyObject *value, void UNUSED *closure) {
    if (value == NULL) {
        PyErr_SetString(PyExc_TypeError, "Cannot delete attribute");
        return -1;
    }
    int blink = PyObject_IsTrue(value);
    if (blink < 0) return -1;
    self->style.attrs.blink = blink;
    return 0;
}


#define SGR_UINT_GETSET(x, field)                                                                                                      \
    static PyObject *x##_get(Cursor *self, void UNUSED *closure) { return PyLong_FromUnsignedLong((unsigned long)self->style.field); } \
    static int x##_set(Cursor *self, PyObject *value, void UNUSED *closure) {                                                          \
        if (value == NULL) {                                                                                                           \
            PyErr_SetString(PyExc_TypeError, "Cannot delete attribute");                                                               \
            return -1;                                                                                                                 \
        }                                                                                                                              \
        if (!PyLong_Check(value)) {                                                                                                    \
            PyErr_SetString(PyExc_TypeError, "value must be an int");                                                                  \
            return -1;                                                                                                                 \
        }                                                                                                                              \
        unsigned long v = PyLong_AsUnsignedLong(value);                                                                                \
        if (v == (unsigned long)-1 && PyErr_Occurred()) return -1;                                                                     \
        self->style.field = v;                                                                                                         \
        return 0;                                                                                                                      \
    }

SGR_UINT_GETSET(decoration, attrs.decoration)
SGR_UINT_GETSET(fg, fg)
SGR_UINT_GETSET(bg, bg)
SGR_UINT_GETSET(decoration_fg, decoration_fg)

static PyMemberDef members[] = {
    {"x", T_UINT, offsetof(Cursor, x), 0, "x"},
    {"y", T_UINT, offsetof(Cursor, y), 0, "y"},
    {"shape", T_INT, offsetof(Cursor, shape), 0, "shape"},
    {NULL} /* Sentinel */
};

static PyGetSetDef getseters[] = {
    GETSET(bold) GETSET(italic) GETSET(reverse) GETSET(strikethrough) GETSET(dim) GETSET(blink) GETSET(text_blink) GETSET(decoration) GETSET(fg) GETSET(bg)
        GETSET(decoration_fg){NULL} /* Sentinel */
};

static PyMethodDef methods[] = {
    METHOD(copy, METH_NOARGS) METHOD(reset_display_attrs, METH_NOARGS){NULL} /* Sentinel */
};


static PyObject *richcmp(PyObject *obj1, PyObject *obj2, int op);

PyTypeObject Cursor_Type = {
    PyVarObject_HEAD_INIT(NULL, 0).tp_name = "fast_data_types.Cursor",
    .tp_basicsize = sizeof(Cursor),
    .tp_dealloc = (destructor)dealloc,
    .tp_repr = (reprfunc)repr,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Cursors",
    .tp_richcompare = richcmp,
    .tp_methods = methods,
    .tp_members = members,
    .tp_getset = getseters,
    .tp_new = new_cursor_object,
};

RICHCMP(Cursor)

// }}}

Cursor *
cursor_copy(Cursor *self) {
    Cursor *ans;
    ans = alloc_cursor();
    if (ans == NULL) {
        PyErr_NoMemory();
        return NULL;
    }
    cursor_copy_to(self, ans);
    return ans;
}

static PyObject *
copy(Cursor *self, PyObject *a UNUSED) {
    return (PyObject *)cursor_copy(self);
}

Cursor *
alloc_cursor(void) {
    return (Cursor *)new_cursor_object(&Cursor_Type, NULL, NULL);
}

INIT_TYPE(Cursor)
