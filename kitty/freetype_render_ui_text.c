/*
 * freetype_render_ui_text.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "freetype_render_ui_text.h"
#include <hb.h>
#include <hb-ft.h>

typedef struct FamilyInformation {
    char *name;
    bool bold, italic;
} FamilyInformation;

FT_Face main_face = NULL;
FontConfigFace main_face_information = {0};
FamilyInformation main_face_family = {0};

static inline FT_UInt
glyph_id_for_codepoint(FT_Face face, char_type cp) {
    return FT_Get_Char_Index(face, cp);
}

static void
cleanup(void) {
    if (main_face) FT_Done_Face(main_face);
    main_face = NULL;
    free(main_face_information.path); main_face_information.path = NULL;
    free(main_face_family.name);
    memset(&main_face_family, 0, sizeof(FamilyInformation));
}

void
set_main_face_family(const char *family, bool bold, bool italic) {
    cleanup();
    main_face_family.name = strdup(family);
    main_face_family.bold = bold; main_face_family.italic = italic;
}

static inline bool
ensure_state(void) {
    if (main_face) return false;
    if (!information_for_font_family(main_face_family.name, main_face_family.bold, main_face_family.italic, &main_face_information)) return false;
    main_face = native_face_from_path(main_face_information.path, main_face_information.index);
    return !!main_face;
}

static PyObject*
path_for_font(PyObject *self UNUSED, PyObject *args) {
    const char *family = NULL; int bold = 0, italic = 0;
    if (!PyArg_ParseTuple(args, "|zpp", &family, &bold, &italic)) return NULL;
    FontConfigFace f;
    if (!information_for_font_family(family, bold, italic, &f)) return NULL;
    PyObject *ret = Py_BuildValue("{ss si si si}", "path", f.path, "index", f.index, "hinting", f.hinting, "hintstyle", f.hintstyle);
    free(f.path);
    return ret;
}

static PyObject*
fallback_for_char(PyObject *self UNUSED, PyObject *args) {
    const char *family = NULL; int bold = 0, italic = 0;
    unsigned int ch;
    if (!PyArg_ParseTuple(args, "I|zpp", &ch, &family, &bold, &italic)) return NULL;
    FontConfigFace f;
    if (!fallback_font(ch, family, bold, italic, &f)) return NULL;
    PyObject *ret = Py_BuildValue("{ss si si si}", "path", f.path, "index", f.index, "hinting", f.hinting, "hintstyle", f.hintstyle);
    free(f.path);
    return ret;
}

static PyMethodDef module_methods[] = {
    METHODB(path_for_font, METH_VARARGS),
    METHODB(fallback_for_char, METH_VARARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_freetype_render_ui_text(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (Py_AtExit(cleanup) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to register the fontconfig library at exit handler");
        return false;
    }
    return true;
}
