/*
 * fontconfig.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <fontconfig/fontconfig.h>

PyObject*
get_fontconfig_font(PyObject UNUSED *self, PyObject *args) {
    char *family;
    int bold, italic, allow_bitmapped_fonts, index = 0, hint_style=0, weight=0, slant=0;
    double size_in_pts, dpi;
    unsigned int character;
    FcBool hinting, scalable, outline;
    FcChar8 *path = NULL;
    FcPattern *pat = NULL, *match = NULL;
    FcResult result;
    FcCharSet *charset = NULL;
    PyObject *ans = NULL;

    if (!PyArg_ParseTuple(args, "spppdId", &family, &bold, &italic, &allow_bitmapped_fonts, &size_in_pts, &character, &dpi)) return NULL;
    pat = FcPatternCreate();
    if (pat == NULL) return PyErr_NoMemory();

#define AP(func, which, in, desc) if (!func(pat, which, in)) { PyErr_Format(PyExc_RuntimeError, "Failed to add %s to fontconfig patter", desc, NULL); goto end; }
    AP(FcPatternAddString, FC_FAMILY, (const FcChar8*)family, "family");
    if (!allow_bitmapped_fonts) {
        AP(FcPatternAddBool, FC_OUTLINE, true, "outline");
        AP(FcPatternAddBool, FC_SCALABLE, true, "scalable");
    }
    if (size_in_pts > 0) { AP(FcPatternAddDouble, FC_SIZE, size_in_pts, "size"); }
    if (dpi > 0) { AP(FcPatternAddDouble, FC_DPI, dpi, "dpi"); }
    if (bold) { AP(FcPatternAddInteger, FC_WEIGHT, FC_WEIGHT_BOLD, "weight"); }
    if (italic) { AP(FcPatternAddInteger, FC_SLANT, FC_SLANT_ITALIC, "slant"); }
    if (character > 0) {
        charset = FcCharSetCreate();
        if (charset == NULL) { PyErr_NoMemory(); goto end; }
        if (!FcCharSetAddChar(charset, character)) { PyErr_SetString(PyExc_RuntimeError, "Failed to add character to fontconfig charset"); goto end; }
        AP(FcPatternAddCharSet, FC_CHARSET, charset, "charset");
    }
#undef AP
    FcConfigSubstitute(NULL, pat, FcMatchPattern);
    FcDefaultSubstitute(pat);
    match = FcFontMatch(NULL, pat, &result);
    if (match == NULL) { PyErr_SetString(PyExc_KeyError, "FcFontMatch() failed"); goto end; }

#define GI(func, which, out, desc) \
    if (func(match, which, 0, & out) != FcResultMatch) { \
        PyErr_Format(PyExc_RuntimeError, "Failed to get %s from match object", desc, NULL); goto end; \
    }

    GI(FcPatternGetString, FC_FILE, path, "file path");
    GI(FcPatternGetInteger, FC_INDEX, index, "face index");
    GI(FcPatternGetInteger, FC_WEIGHT, weight, "weight");
    GI(FcPatternGetInteger, FC_SLANT, slant, "slant");
    GI(FcPatternGetInteger, FC_HINT_STYLE, hint_style, "hint style");
    GI(FcPatternGetBool, FC_HINTING, hinting, "hinting");
    GI(FcPatternGetBool, FC_SCALABLE, scalable, "scalable");
    GI(FcPatternGetBool, FC_OUTLINE, outline, "outline");
#undef GI

#define BP(x) (x ? Py_True : Py_False)
    ans = Py_BuildValue("siiOOOii", path, index, hint_style, BP(hinting), BP(scalable), BP(outline), weight, slant);
#undef BP

end:
    if (pat != NULL) FcPatternDestroy(pat);
    if (match != NULL) FcPatternDestroy(match);
    if (charset != NULL) FcCharSetDestroy(charset);
    if (PyErr_Occurred()) return NULL;
    return ans;
}

bool 
init_fontconfig_library(PyObject UNUSED *m) {
    if (!FcInit()) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to initialize the fontconfig library");
        return false;
    }
    return true;
}
