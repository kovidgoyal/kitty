/*
 * freetype.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <ft2build.h>
#include FT_FREETYPE_H
#undef FTERRORS_H_
#define FT_ERRORDEF( e, v, s )  { e, s },
#define FT_ERROR_START_LIST     {
#define FT_ERROR_END_LIST       { 0, NULL } };
#include <structmember.h>

const struct {
    int          err_code;
    const char*  err_msg;
} ft_errors[] =

#include FT_ERRORS_H

typedef struct {
    PyObject_HEAD

    FT_Face face;
    unsigned int units_per_EM;
    int ascender, descender, height, max_advance_width, max_advance_height, underline_position, underline_thickness;
} Face;


void 
set_freetype_error(const char* prefix, int err_code) {
    int i = 0;
    while(ft_errors[i].err_msg != NULL) {
        if (ft_errors[i].err_code == err_code) {
            PyErr_Format(PyExc_Exception, "%s %s", prefix, ft_errors[i].err_msg);
            return;
        }
    }
    PyErr_Format(PyExc_Exception, "%s (error code: %d)", prefix, err_code);
}

static FT_Library  library;


static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Face *self;
    char *path;
    int error;
    /* unsigned int columns=80, lines=24, scrollback=0; */
    if (!PyArg_ParseTuple(args, "s", &path)) return NULL;

    self = (Face *)type->tp_alloc(type, 0);
    if (self != NULL) {
        Py_BEGIN_ALLOW_THREADS;
        error = FT_New_Face(library, path, 0, &(self->face));
#define CPY(n) self->n = self->face->n;
        CPY(units_per_EM); CPY(ascender); CPY(descender); CPY(height); CPY(max_advance_width); CPY(max_advance_height); CPY(underline_position); CPY(underline_thickness);
#undef CPY
        Py_END_ALLOW_THREADS;
        if(error) { set_freetype_error("Failed to load face, with error: ", error); Py_CLEAR(self); return NULL; }
    }
    return (PyObject*)self;
}
 
static void
dealloc(Face* self) {
    FT_Done_Face(self->face);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
set_char_size(Face *self, PyObject *args) {
#define set_char_size_doc "set_char_size(width, height, xdpi, ydpi) -> set the character size. width, height is in 1/64th of a pt. dpi is in pixels per inch"
    long char_width, char_height;
    unsigned int xdpi, ydpi;
    if (!PyArg_ParseTuple(args, "llII", &char_width, &char_height, &xdpi, &ydpi)) return NULL;
    int error = FT_Set_Char_Size(self->face, char_width, char_height, xdpi, ydpi);
    if (error) { set_freetype_error("Failed to set char size, with error: ", error); Py_CLEAR(self); return NULL; }
    Py_RETURN_NONE;
}

static PyObject*
load_char(Face *self, PyObject *args) {
#define load_char_doc "load_char(char, hinting, hintstyle)"
    int char_code, hinting, hintstyle, error;
    if (!PyArg_ParseTuple(args, "Cpp", &char_code, &hinting, &hintstyle)) return NULL;

    int glyph_index = FT_Get_Char_Index(self->face, char_code);
    int flags = FT_LOAD_RENDER;
    if (hinting) {
        if (hintstyle >= 3) flags |= FT_LOAD_TARGET_NORMAL;
        else if (0 < hintstyle  && hintstyle < 3) flags |= FT_LOAD_TARGET_LIGHT;
    } else flags |= FT_LOAD_NO_HINTING;
    Py_BEGIN_ALLOW_THREADS;
    error = FT_Load_Glyph(self->face, glyph_index, flags);
    Py_END_ALLOW_THREADS;
    if (error) { set_freetype_error("Failed to load glyph, with error: ", error); Py_CLEAR(self); return NULL; }
    Py_RETURN_NONE;
}

static PyObject*
get_char_index(Face *self, PyObject *args) {
#define get_char_index_doc ""
    int code;
    if (!PyArg_ParseTuple(args, "C", &code)) return NULL;

    return Py_BuildValue("I", FT_Get_Char_Index(self->face, code));
}
 
static PyStructSequence_Field gm_fields[] = {
    {"width", NULL},
    {"height", NULL},
    {"horiBearingX", NULL},
    {"horiBearingY", NULL},
    {"horiAdvance", NULL},
    {"vertBearingX", NULL},
    {"vertBearingY", NULL},
    {"vertAdvance", NULL},
    {NULL}
};

static PyStructSequence_Desc gm_desc = {"GlpyhMetrics", NULL, gm_fields, 8};
static PyTypeObject GlpyhMetricsType = {0};

static PyObject*
glyph_metrics(Face *self) {
#define glyph_metrics_doc ""
    PyObject *ans = PyStructSequence_New(&GlpyhMetricsType);
    if (ans != NULL) {
#define SI(num, attr) PyStructSequence_SET_ITEM(ans, num, PyLong_FromLong(self->face->glyph->metrics.attr)); if (PyStructSequence_GET_ITEM(ans, num) == NULL) { Py_CLEAR(ans); return PyErr_NoMemory(); }
        SI(0, width); SI(1, height);
        SI(2, horiBearingX); SI(3, horiBearingY); SI(4, horiAdvance);
        SI(5, vertBearingX); SI(6, vertBearingY); SI(7, vertAdvance);
#undef SI
    } else return PyErr_NoMemory();
    return ans;
}

static PyStructSequence_Field bm_fields[] = {
    {"rows", NULL},
    {"width", NULL},
    {"pitch", NULL},
    {"buffer", NULL},
    {"num_grays", NULL},
    {"pixel_mode", NULL},
    {"palette_mode", NULL},
    {NULL}
};
static PyStructSequence_Desc bm_desc = {"Bitmap", NULL, bm_fields, 7};
static PyTypeObject BitmapType = {0};

static PyObject*
bitmap(Face *self) {
#define bitmap_doc ""
    PyObject *ans = PyStructSequence_New(&BitmapType);
    if (ans != NULL) {
#define SI(num, attr, func, conv) PyStructSequence_SET_ITEM(ans, num, func((conv)self->face->glyph->bitmap.attr)); if (PyStructSequence_GET_ITEM(ans, num) == NULL) { Py_CLEAR(ans); return PyErr_NoMemory(); }
        SI(0, rows, PyLong_FromUnsignedLong, unsigned long); SI(1, width, PyLong_FromUnsignedLong, unsigned long);
        SI(2, pitch, PyLong_FromLong, long); 
        PyObject *t = PyByteArray_FromStringAndSize((const char*)self->face->glyph->bitmap.buffer, self->face->glyph->bitmap.rows * self->face->glyph->bitmap.pitch);
        if (t == NULL) { Py_CLEAR(ans); return PyErr_NoMemory(); }
        PyStructSequence_SET_ITEM(ans, 3, t);
        SI(4, num_grays, PyLong_FromUnsignedLong, unsigned long);
        SI(5, pixel_mode, PyLong_FromUnsignedLong, unsigned long); SI(6, palette_mode, PyLong_FromUnsignedLong, unsigned long);
#undef SI
    } else return PyErr_NoMemory();
    return ans;
}
 
// Boilerplate {{{

static PyMemberDef members[] = {
#define MEM(name, type) {#name, type, offsetof(Face, name), READONLY, #name}
    MEM(units_per_EM, T_UINT),
    MEM(ascender, T_INT),
    MEM(descender, T_INT),
    MEM(height, T_INT),
    MEM(max_advance_width, T_INT),
    MEM(max_advance_height, T_INT),
    MEM(underline_position, T_INT),
    MEM(underline_thickness, T_INT),
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
    METHOD(set_char_size, METH_VARARGS)
    METHOD(load_char, METH_VARARGS)
    METHOD(get_char_index, METH_VARARGS)
    METHOD(glyph_metrics, METH_NOARGS)
    METHOD(bitmap, METH_NOARGS)
    {NULL}  /* Sentinel */
};


PyTypeObject Face_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Face",
    .tp_basicsize = sizeof(Face),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "FreeType Font face",
    .tp_methods = methods,
    .tp_members = members,
    .tp_new = new,                
};

INIT_TYPE(Face)


bool 
init_freetype_library(PyObject *m) {
    int error = FT_Init_FreeType(&library);
    if (error) {
        set_freetype_error("Failed to initialize FreeType library, with error: ", error);
        return false;
    }
    if (PyStructSequence_InitType2(&GlpyhMetricsType, &gm_desc) != 0) return false;
    if (PyStructSequence_InitType2(&BitmapType, &bm_desc) != 0) return false;
    PyModule_AddObject(m, "GlyphMetrics", (PyObject*)&GlpyhMetricsType);
    PyModule_AddIntMacro(m, FT_LOAD_RENDER);
    PyModule_AddIntMacro(m, FT_LOAD_TARGET_NORMAL);
    PyModule_AddIntMacro(m, FT_LOAD_TARGET_LIGHT);
    PyModule_AddIntMacro(m, FT_LOAD_NO_HINTING);
    PyModule_AddIntMacro(m, FT_PIXEL_MODE_GRAY);
    return true;
}

// }}}
