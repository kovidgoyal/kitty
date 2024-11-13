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
    return (PyObject*) self;
}

static void
dealloc(Cursor* self) {
    Py_TYPE(self)->tp_free((PyObject*)self);
}

#define EQ(x) (a->x == b->x)
static int __eq__(Cursor *a, Cursor *b) {
    return EQ(bold) && EQ(italic) && EQ(strikethrough) && EQ(dim) && EQ(reverse) && EQ(decoration) && EQ(fg) && EQ(bg) && EQ(decoration_fg) && EQ(x) && EQ(y) && EQ(shape) && EQ(non_blinking);
}

static const char* cursor_names[NUM_OF_CURSOR_SHAPES] = { "NO_SHAPE", "BLOCK", "BEAM", "UNDERLINE", "HOLLOW" };

#define BOOL(x) ((x) ? Py_True : Py_False)
static PyObject *
repr(Cursor *self) {
    return PyUnicode_FromFormat(
        "Cursor(x=%u, y=%u, shape=%s, blink=%R, fg=#%08x, bg=#%08x, bold=%R, italic=%R, reverse=%R, strikethrough=%R, dim=%R, decoration=%d, decoration_fg=#%08x)",
        self->x, self->y, (self->shape < NUM_OF_CURSOR_SHAPES ? cursor_names[self->shape] : "INVALID"),
        BOOL(!self->non_blinking), self->fg, self->bg, BOOL(self->bold), BOOL(self->italic), BOOL(self->reverse), BOOL(self->strikethrough), BOOL(self->dim), self->decoration, self->decoration_fg
    );
}

void
cursor_reset_display_attrs(Cursor *self) {
    self->bg = 0; self->fg = 0; self->decoration_fg = 0;
    self->decoration = 0; self->bold = false; self->italic = false; self->reverse = false; self->strikethrough = false; self->dim = false;
}


static void
parse_color(int *params, unsigned int *i, unsigned int count, uint32_t *result) {
    unsigned int attr;
    uint8_t r, g, b;
    if (*i < count) {
        attr = params[(*i)++];
        switch(attr) {
            case 5:
                if (*i < count) *result = (params[(*i)++] & 0xFF) << 8 | 1;
                break;
            case 2: \
                if (*i + 2 < count) {
                    /* Ignore the first parameter in a four parameter RGB */
                    /* sequence (unused color space id), see https://github.com/kovidgoyal/kitty/issues/227 */
                    if (*i +3 < count) (*i)++;
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
#define SET_COLOR(which) { parse_color(params, &i, count, &self->which); } break;
START_ALLOW_CASE_RANGE
    unsigned int i = 0, attr;
    if (!count) { params[0] = 0; count = 1; }
    while (i < count) {
        attr = params[i++];
        switch(attr) {
            case 0:
                cursor_reset_display_attrs(self);  break;
            case 1:
                self->bold = true;  break;
            case 2:
                self->dim = true; break;
            case 3:
                self->italic = true;  break;
            case 4:
                if (is_group && i < count) { self->decoration = MIN(5, params[i]); i++; }
                else self->decoration = 1;
                break;
            case 7:
                self->reverse = true;  break;
            case 9:
                self->strikethrough = true;  break;
            case 21:
                self->decoration = 2; break;
            case 221:
                self->bold = false; break;
            case 222:
                self->dim = false; break;
            case 22:
                self->bold = false;  self->dim = false; break;
            case 23:
                self->italic = false;  break;
            case 24:
                self->decoration = 0;  break;
            case 27:
                self->reverse = false;  break;
            case 29:
                self->strikethrough = false;  break;
            case 30 ... 37:
                self->fg = ((attr - 30) << 8) | 1;  break;
            case 38:
                SET_COLOR(fg);
            case 39:
                self->fg = 0;  break;
            case 40 ... 47:
                self->bg = ((attr - 40) << 8) | 1;  break;
            case 48:
                SET_COLOR(bg);
            case 49:
                self->bg = 0;  break;
            case 90 ... 97:
                self->fg = ((attr - 90 + 8) << 8) | 1;  break;
            case 100 ... 107:
                self->bg = ((attr - 100 + 8) << 8) | 1;  break;
            case DECORATION_FG_CODE:
                SET_COLOR(decoration_fg);
            case DECORATION_FG_CODE + 1:
                self->decoration_fg = 0; break;
        }
        if (is_group) break;
    }
#undef SET_COLOR
END_ALLOW_CASE_RANGE
}

void
apply_sgr_to_cells(GPUCell *first_cell, unsigned int cell_count, int *params, unsigned int count, bool is_group) {
#define RANGE for(unsigned c = 0; c < cell_count; c++, cell++)
#define SET_COLOR(which) { color_type color = 0; parse_color(params, &i, count, &color); if (color) { RANGE { cell->which = color; }} } break;
#define SIMPLE(which, val) RANGE { cell->which = (val); } break;
#define S(which, val) RANGE { cell->attrs.which = (val); } break;

    unsigned int i = 0, attr;
    if (!count) { params[0] = 0; count = 1; }
    while (i < count) {
        GPUCell *cell = first_cell;
        attr = params[i++];
        switch(attr) {
            case 0: {
                const CellAttrs remove_sgr_mask = {.val=~SGR_MASK};
                RANGE { cell->attrs.val &= remove_sgr_mask.val; cell->fg = 0; cell->bg = 0; cell->decoration_fg = 0; }
            }
                break;
            case 1:
                S(bold, true);
            case 2:
                S(dim, true);
            case 3:
                S(italic, true);
            case 4: {
                uint8_t val = 1;
                if (is_group && i < count) { val = MIN(5, params[i]); i++; }
                S(decoration, val);
            }
            case 7:
                S(reverse, true);
            case 9:
                S(strike, true);
            case 21:
                S(decoration, 2);
            case 221:
                S(bold, false);
            case 222:
                S(dim, false);
            case 22:
                RANGE { cell->attrs.bold = false; cell->attrs.dim = false; } break;
            case 23:
                S(italic, false);
            case 24:
                S(decoration, 0);
            case 27:
                S(reverse, false);
            case 29:
                S(strike, false);
START_ALLOW_CASE_RANGE
            case 30 ... 37:
                SIMPLE(fg, ((attr - 30) << 8) | 1);
            case 38:
                SET_COLOR(fg);
            case 39:
                SIMPLE(fg, 0);
            case 40 ... 47:
                SIMPLE(bg, ((attr - 40) << 8) | 1);
            case 48:
                SET_COLOR(bg);
            case 49:
                SIMPLE(bg, 0);
            case 90 ... 97:
                SIMPLE(fg, ((attr - 90 + 8) << 8) | 1);
            case 100 ... 107:
                SIMPLE(bg, ((attr - 100 + 8) << 8) | 1);
END_ALLOW_CASE_RANGE
            case DECORATION_FG_CODE:
                SET_COLOR(decoration_fg);
            case DECORATION_FG_CODE + 1:
                SIMPLE(decoration_fg, 0);
        }
        if (is_group) break;
    }
#undef SET_COLOR
#undef RANGE
#undef SIMPLE
#undef S
}

const char*
cursor_as_sgr(const Cursor *self) {
    GPUCell blank_cell = { 0 }, cursor_cell = {
        .attrs = cursor_to_attrs(self),
        .fg = self->fg & COL_MASK,
        .bg = self->bg & COL_MASK,
        .decoration_fg = self->decoration_fg & COL_MASK,
    };
    return cell_as_sgr(&cursor_cell, &blank_cell);
}

static PyObject *
reset_display_attrs(Cursor *self, PyObject *a UNUSED) {
#define reset_display_attrs_doc "Reset all display attributes to unset"
    cursor_reset_display_attrs(self);
    Py_RETURN_NONE;
}

void cursor_reset(Cursor *self) {
    cursor_reset_display_attrs(self);
    self->x = 0; self->y = 0;
    self->shape = NO_CURSOR_SHAPE; self->non_blinking = false;
}

void cursor_copy_to(Cursor *src, Cursor *dest) {
#define CCY(x) dest->x = src->x;
    CCY(x); CCY(y); CCY(shape); CCY(non_blinking);
    CCY(bold); CCY(italic); CCY(strikethrough); CCY(dim); CCY(reverse); CCY(decoration); CCY(fg); CCY(bg); CCY(decoration_fg);
}

static PyObject*
copy(Cursor *self, PyObject*);
#define copy_doc "Create a clone of this cursor"

// Boilerplate {{{

BOOL_GETSET(Cursor, bold)
BOOL_GETSET(Cursor, italic)
BOOL_GETSET(Cursor, reverse)
BOOL_GETSET(Cursor, strikethrough)
BOOL_GETSET(Cursor, dim)

static PyObject* blink_get(Cursor *self, void UNUSED *closure) { PyObject *ans = !self->non_blinking ? Py_True : Py_False; Py_INCREF(ans); return ans; }

static int blink_set(Cursor *self, PyObject *value, void UNUSED *closure) { if (value == NULL) { PyErr_SetString(PyExc_TypeError, "Cannot delete attribute"); return -1; } self->non_blinking = PyObject_IsTrue(value) ? false : true; return 0; }


static PyMemberDef members[] = {
    {"x", T_UINT, offsetof(Cursor, x), 0, "x"},
    {"y", T_UINT, offsetof(Cursor, y), 0, "y"},
    {"shape", T_INT, offsetof(Cursor, shape), 0, "shape"},
    {"decoration", T_UBYTE, offsetof(Cursor, decoration), 0, "decoration"},
    {"fg", T_UINT, offsetof(Cursor, fg), 0, "fg"},
    {"bg", T_UINT, offsetof(Cursor, bg), 0, "bg"},
    {"decoration_fg", T_UINT, offsetof(Cursor, decoration_fg), 0, "decoration_fg"},
    {NULL}  /* Sentinel */
};

static PyGetSetDef getseters[] = {
    GETSET(bold)
    GETSET(italic)
    GETSET(reverse)
    GETSET(strikethrough)
    GETSET(dim)
    GETSET(blink)
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
    METHOD(copy, METH_NOARGS)
    METHOD(reset_display_attrs, METH_NOARGS)
    {NULL}  /* Sentinel */
};


static PyObject *
richcmp(PyObject *obj1, PyObject *obj2, int op);

PyTypeObject Cursor_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Cursor",
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

Cursor*
cursor_copy(Cursor *self) {
    Cursor* ans;
    ans = alloc_cursor();
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    cursor_copy_to(self, ans);
    return ans;
}

static PyObject*
copy(Cursor *self, PyObject *a UNUSED) {
    return (PyObject*)cursor_copy(self);
}

Cursor *alloc_cursor(void) {
    return (Cursor*)new_cursor_object(&Cursor_Type, NULL, NULL);
}

INIT_TYPE(Cursor)
