/*
 * freetype.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"
#include <math.h>
#include <structmember.h>
#include <ft2build.h>
#include <hb-ft.h>

#if HB_VERSION_MAJOR > 1 || (HB_VERSION_MAJOR == 1 && (HB_VERSION_MINOR > 0 || (HB_VERSION_MINOR == 0 && HB_VERSION_MICRO >= 5)))
#define HARBUZZ_HAS_LOAD_FLAGS
#endif
#if HB_VERSION_MAJOR > 1 || (HB_VERSION_MAJOR == 1 && (HB_VERSION_MINOR > 6 || (HB_VERSION_MINOR == 6 && HB_VERSION_MICRO >= 3)))
#define HARFBUZZ_HAS_CHANGE_FONT
#endif

#include FT_FREETYPE_H
typedef struct {
    PyObject_HEAD

    FT_Face face;
    unsigned int units_per_EM;
    int ascender, descender, height, max_advance_width, max_advance_height, underline_position, underline_thickness;
    int hinting, hintstyle;
    bool is_scalable;
    float size_in_pts;
    FT_F26Dot6 char_width, char_height;
    FT_UInt xdpi, ydpi;
    PyObject *path;
    hb_font_t *harfbuzz_font;
} Face;

static PyObject* FreeType_Exception = NULL;

void 
set_freetype_error(const char* prefix, int err_code) {
    int i = 0;
#undef FTERRORS_H_
#undef __FTERRORS_H__
#define FT_ERRORDEF( e, v, s )  { e, s },
#define FT_ERROR_START_LIST     {
#define FT_ERROR_END_LIST       { 0, NULL } };

    static const struct {
        int          err_code;
        const char*  err_msg;
    } ft_errors[] =

#ifdef FT_ERRORS_H
#include FT_ERRORS_H
#else 
    FT_ERROR_START_LIST FT_ERROR_END_LIST
#endif

    while(ft_errors[i].err_msg != NULL) {
        if (ft_errors[i].err_code == err_code) {
            PyErr_Format(FreeType_Exception, "%s %s", prefix, ft_errors[i].err_msg);
            return;
        }
        i++;
    }
    PyErr_Format(FreeType_Exception, "%s (error code: %d)", prefix, err_code);
}

static FT_Library  library;

static inline bool
set_font_size(Face *self, FT_F26Dot6 char_width, FT_F26Dot6 char_height, FT_UInt xdpi, FT_UInt ydpi) {
    int error = FT_Set_Char_Size(self->face, char_width, char_height, xdpi, ydpi);
    if (!error) {
        self->char_width = char_width; self->char_height = char_height; self->xdpi = xdpi; self->ydpi = ydpi;
        if (self->harfbuzz_font != NULL) {
#ifdef HARFBUZZ_HAS_CHANGE_FONT
            hb_ft_font_changed(self->harfbuzz_font);
#else
            hb_font_set_scale(
                self->harfbuzz_font,
                (int) (((uint64_t) self->face->size->metrics.x_scale * (uint64_t) self->face->units_per_EM + (1u<<15)) >> 16),
                (int) (((uint64_t) self->face->size->metrics.y_scale * (uint64_t) self->face->units_per_EM + (1u<<15)) >> 16)
            );
#endif
        }
    } else {
        set_freetype_error("Failed to set char size, with error:", error); return false; 
    }
    return !error;
}

bool
set_size_for_face(PyObject *self, float pt_sz, float xdpi, float ydpi) {
    FT_UInt w = (FT_UInt)(ceilf(pt_sz * 64));
    ((Face*)self)->size_in_pts = pt_sz;
    return set_font_size((Face*)self, w, w, (FT_UInt)xdpi, (FT_UInt) ydpi);
}

static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    Face *self;
    char *path;
    int error, hinting, hintstyle;
    long index;
    unsigned int size_in_pts, xdpi, ydpi;
    if (!PyArg_ParseTuple(args, "sliifff", &path, &index, &hinting, &hintstyle, &size_in_pts, &xdpi, &ydpi)) return NULL;

    self = (Face *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->path = PyTuple_GET_ITEM(args, 0);
        Py_INCREF(self->path);
        error = FT_New_Face(library, path, index, &(self->face));
        if(error) { set_freetype_error("Failed to load face, with error:", error); Py_CLEAR(self); return NULL; }
#define CPY(n) self->n = self->face->n;
        CPY(units_per_EM); CPY(ascender); CPY(descender); CPY(height); CPY(max_advance_width); CPY(max_advance_height); CPY(underline_position); CPY(underline_thickness);
#undef CPY
        self->is_scalable = FT_IS_SCALABLE(self->face);
        self->hinting = hinting; self->hintstyle = hintstyle;
        if (!set_size_for_face((PyObject*)self, size_in_pts, xdpi, ydpi)) { Py_CLEAR(self); return NULL; }
        self->harfbuzz_font = hb_ft_font_create(self->face, NULL);
        if (self->harfbuzz_font == NULL) { Py_CLEAR(self); return PyErr_NoMemory(); }
    }
    return (PyObject*)self;
}
 
static void
dealloc(Face* self) {
    if (self->harfbuzz_font) hb_font_destroy(self->harfbuzz_font);
    if (self->face) FT_Done_Face(self->face);
    Py_CLEAR(self->path);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject *
repr(Face *self) {
    return PyUnicode_FromFormat(
        "Face(path=%S, is_scalable=%S, units_per_EM=%u, ascender=%i, descender=%i, height=%i, max_advance_width=%i max_advance_height=%i, underline_position=%i, underline_thickness=%i)",
        self->path, self->is_scalable ? Py_True : Py_False, 
        self->ascender, self->descender, self->height, self->max_advance_width, self->max_advance_height, self->underline_position, self->underline_thickness
    );
}


static inline int
get_load_flags(int hinting, int hintstyle, int base) {
    int flags = base;
    if (hinting) {
        if (hintstyle >= 3) flags |= FT_LOAD_TARGET_NORMAL;
        else if (0 < hintstyle  && hintstyle < 3) flags |= FT_LOAD_TARGET_LIGHT;
    } else flags |= FT_LOAD_NO_HINTING;
    return flags;
}

static inline bool 
load_glyph(Face *self, int glyph_index, int load_type) {
    int flags = get_load_flags(self->hinting, self->hintstyle, load_type);
    int error = FT_Load_Glyph(self->face, glyph_index, flags);
    if (error) { set_freetype_error("Failed to load glyph, with error:", error); Py_CLEAR(self); return false; }
    return true;
}

static inline unsigned int
calc_cell_width(Face *self) {
    unsigned int ans = 0;
    for (char_type i = 32; i < 128; i++) {
        int glyph_index = FT_Get_Char_Index(self->face, i);
        if (load_glyph(self, glyph_index, FT_LOAD_DEFAULT)) {
            ans = MAX(ans, (unsigned long)ceilf((float)self->face->glyph->metrics.horiAdvance / 64.f));
        }
    }
    return ans;
}

static inline int
font_units_to_pixels(Face *self, int x) {
    return (int)ceilf(((float)x * (((float)self->size_in_pts * (float)self->ydpi) / (72.f * (float)self->units_per_EM))));
}

void 
cell_metrics(PyObject *s, unsigned int* cell_width, unsigned int* cell_height, unsigned int* baseline, unsigned int* underline_position, unsigned int* underline_thickness) {
    Face *self = (Face*)s;
    *cell_width = calc_cell_width(self);
    *cell_height = font_units_to_pixels(self, self->height);
    *baseline = font_units_to_pixels(self, self->ascender);
    *underline_position = MIN(*cell_height - 1, *baseline - font_units_to_pixels(self, self->underline_position));
    *underline_thickness = font_units_to_pixels(self, self->underline_thickness);
}

bool 
face_has_codepoint(PyObject *s, char_type cp) {
    return FT_Get_Char_Index(((Face*)s)->face, cp) > 0;
}

hb_font_t*
harfbuzz_font_for_face(PyObject *self) { return ((Face*)self)->harfbuzz_font; }

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
    MEM(is_scalable, T_BOOL),
    MEM(path, T_OBJECT_EX),
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
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
    .tp_repr = (reprfunc)repr,
};

INIT_TYPE(Face)

static void
free_freetype() {
    FT_Done_FreeType(library);
}

bool 
init_freetype_library(PyObject *m) {
    FreeType_Exception = PyErr_NewException("fast_data_types.FreeTypeError", NULL, NULL);
    if (FreeType_Exception == NULL) return false;
    if (PyModule_AddObject(m, "FreeTypeError", FreeType_Exception) != 0) return false;
    int error = FT_Init_FreeType(&library);
    if (error) {
        set_freetype_error("Failed to initialize FreeType library, with error:", error);
        return false;
    }
    if (Py_AtExit(free_freetype) != 0) {
        PyErr_SetString(FreeType_Exception, "Failed to register the freetype library at exit handler");
        return false;
    }
    return true;
}

// }}}
