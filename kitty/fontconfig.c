/*
 * fontconfig.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "cleanup.h"
#include "lineops.h"
#include "fonts.h"
#include <fontconfig/fontconfig.h>
#include <dlfcn.h>
#include "freetype_render_ui_text.h"
#ifndef FC_COLOR
#define FC_COLOR "color"
#endif


static bool initialized = false;
static void* libfontconfig_handle = NULL;
static struct {PyObject *face, *descriptor;} builtin_nerd_font = {0};

#define FcInit dynamically_loaded_fc_symbol.Init
#define FcFini dynamically_loaded_fc_symbol.Fini
#define FcCharSetAddChar dynamically_loaded_fc_symbol.CharSetAddChar
#define FcPatternDestroy dynamically_loaded_fc_symbol.PatternDestroy
#define FcObjectSetDestroy dynamically_loaded_fc_symbol.ObjectSetDestroy
#define FcPatternAddDouble dynamically_loaded_fc_symbol.PatternAddDouble
#define FcPatternAddString dynamically_loaded_fc_symbol.PatternAddString
#define FcFontMatch dynamically_loaded_fc_symbol.FontMatch
#define FcCharSetCreate dynamically_loaded_fc_symbol.CharSetCreate
#define FcPatternGetString dynamically_loaded_fc_symbol.PatternGetString
#define FcFontSetDestroy dynamically_loaded_fc_symbol.FontSetDestroy
#define FcPatternGetInteger dynamically_loaded_fc_symbol.PatternGetInteger
#define FcPatternAddBool dynamically_loaded_fc_symbol.PatternAddBool
#define FcFontList dynamically_loaded_fc_symbol.FontList
#define FcObjectSetBuild dynamically_loaded_fc_symbol.ObjectSetBuild
#define FcCharSetDestroy dynamically_loaded_fc_symbol.CharSetDestroy
#define FcConfigSubstitute dynamically_loaded_fc_symbol.ConfigSubstitute
#define FcDefaultSubstitute dynamically_loaded_fc_symbol.DefaultSubstitute
#define FcPatternAddInteger dynamically_loaded_fc_symbol.PatternAddInteger
#define FcPatternCreate dynamically_loaded_fc_symbol.PatternCreate
#define FcPatternGetBool dynamically_loaded_fc_symbol.PatternGetBool
#define FcPatternAddCharSet dynamically_loaded_fc_symbol.PatternAddCharSet
#define FcConfigAppFontAddFile dynamically_loaded_fc_symbol.ConfigAppFontAddFile

static struct {
    FcBool(*Init)(void);
    void(*Fini)(void);
    FcBool (*CharSetAddChar) (FcCharSet *fcs, FcChar32 ucs4);
    void (*PatternDestroy) (FcPattern *p);
    void (*ObjectSetDestroy) (FcObjectSet *os);
    FcBool (*PatternAddDouble) (FcPattern *p, const char *object, double d);
    FcBool (*PatternAddString) (FcPattern *p, const char *object, const FcChar8 *s);
    FcPattern * (*FontMatch) (FcConfig	*config, FcPattern	*p, FcResult	*result);
    FcCharSet* (*CharSetCreate) (void);
    FcResult (*PatternGetString) (const FcPattern *p, const char *object, int n, FcChar8 ** s);
    void (*FontSetDestroy) (FcFontSet *s);
    FcResult (*PatternGetInteger) (const FcPattern *p, const char *object, int n, int *i);
    FcBool (*PatternAddBool) (FcPattern *p, const char *object, FcBool b);
    FcFontSet * (*FontList) (FcConfig	*config, FcPattern	*p, FcObjectSet *os);
    FcObjectSet * (*ObjectSetBuild) (const char *first, ...);
    void (*CharSetDestroy) (FcCharSet *fcs);
    FcBool (*ConfigSubstitute) (FcConfig	*config, FcPattern	*p, FcMatchKind	kind);
    void (*DefaultSubstitute) (FcPattern *pattern);
    FcBool (*PatternAddInteger) (FcPattern *p, const char *object, int i);
    FcPattern * (*PatternCreate) (void);
    FcResult (*PatternGetBool) (const FcPattern *p, const char *object, int n, FcBool *b);
    FcBool (*PatternAddCharSet) (FcPattern *p, const char *object, const FcCharSet *c);
    FcBool (*ConfigAppFontAddFile) (FcConfig *config, const FcChar8 *file);
} dynamically_loaded_fc_symbol = {0};
#define LOAD_FUNC(name) {\
    *(void **) (&dynamically_loaded_fc_symbol.name) = dlsym(libfontconfig_handle, "Fc" #name); \
    if (!dynamically_loaded_fc_symbol.name) { \
        const char* error = dlerror(); \
        fatal("Failed to load the function Fc" #name " with error: %s", error ? error : ""); \
    } \
}


static void
load_fontconfig_lib(void) {
        const char* libnames[] = {
#if defined(_KITTY_FONTCONFIG_LIBRARY)
            _KITTY_FONTCONFIG_LIBRARY,
#else
            "libfontconfig.so",
            // some installs are missing the .so symlink, so try the full name
            "libfontconfig.so.1",
#endif
            NULL
        };
        for (int i = 0; libnames[i]; i++) {
            libfontconfig_handle = dlopen(libnames[i], RTLD_LAZY);
            if (libfontconfig_handle) break;
        }
        if (libfontconfig_handle == NULL) { fatal("Failed to find and load fontconfig"); }
        dlerror();    /* Clear any existing error */
        LOAD_FUNC(Init);
        LOAD_FUNC(Fini);
        LOAD_FUNC(CharSetAddChar);
        LOAD_FUNC(PatternDestroy);
        LOAD_FUNC(ObjectSetDestroy);
        LOAD_FUNC(PatternAddDouble);
        LOAD_FUNC(PatternAddString);
        LOAD_FUNC(FontMatch);
        LOAD_FUNC(CharSetCreate);
        LOAD_FUNC(PatternGetString);
        LOAD_FUNC(FontSetDestroy);
        LOAD_FUNC(PatternGetInteger);
        LOAD_FUNC(PatternAddBool);
        LOAD_FUNC(FontList);
        LOAD_FUNC(ObjectSetBuild);
        LOAD_FUNC(CharSetDestroy);
        LOAD_FUNC(ConfigSubstitute);
        LOAD_FUNC(DefaultSubstitute);
        LOAD_FUNC(PatternAddInteger);
        LOAD_FUNC(PatternCreate);
        LOAD_FUNC(PatternGetBool);
        LOAD_FUNC(PatternAddCharSet);
        LOAD_FUNC(ConfigAppFontAddFile);
}
#undef LOAD_FUNC

static void
ensure_initialized(void) {
    if (!initialized) {
        load_fontconfig_lib();
        if (!FcInit()) fatal("Failed to initialize fontconfig library");
        initialized = true;
    }
}

static void
finalize(void) {
    if (initialized) {
        Py_CLEAR(builtin_nerd_font.face);
        Py_CLEAR(builtin_nerd_font.descriptor);
        FcFini();
        dlclose(libfontconfig_handle);
        libfontconfig_handle = NULL;
        initialized = false;
    }
}

static PyObject*
pybool(FcBool x) { PyObject *ans = x ? Py_True: Py_False; Py_INCREF(ans); return ans; }

static PyObject*
pyspacing(int val) {
#define S(x) case FC_##x: return PyUnicode_FromString(#x)
    switch(val) { S(PROPORTIONAL); S(DUAL); S(MONO); S(CHARCELL); default: return PyUnicode_FromString("UNKNOWN"); }
#undef S
}

static PyObject*
increment_and_return(PyObject *x) { if (x) Py_INCREF(x); return x; }

static PyObject*
pattern_as_dict(FcPattern *pat) {
    RAII_PyObject(ans, Py_BuildValue("{ss}", "descriptor_type", "fontconfig"));
    if (ans == NULL) return NULL;

#define PS(x) PyUnicode_Decode((const char*)x, strlen((const char*)x), "UTF-8", "replace")

#define G(type, get, which, conv, name, default) { \
    type out; \
    if (get(pat, which, 0, &out) == FcResultMatch) { \
        RAII_PyObject(p, conv(out)); \
        if (!p || PyDict_SetItemString(ans, #name, p) != 0) return NULL; \
    } else { RAII_PyObject(d, default); if (!d || PyDict_SetItemString(ans, #name, d) != 0) return NULL; } \
}

#define L(type, get, which, conv, name) { \
    type out; int n = 0; \
    RAII_PyObject(list, PyList_New(0)); \
    if (!list) return NULL; \
    while (get(pat, which, n++, &out) == FcResultMatch) { \
        RAII_PyObject(p, conv(out));  \
        if (!p || PyList_Append(list, p) != 0) return NULL; \
    } \
    if (PyDict_SetItemString(ans, #name, list) != 0) return NULL; \
}
#define S(which, key) G(FcChar8*, FcPatternGetString, which, PS, key, PyUnicode_FromString(""))
#define LS(which, key) L(FcChar8*, FcPatternGetString, which, PS, key)
#define I(which, key) G(int, FcPatternGetInteger, which, PyLong_FromLong, key, PyLong_FromUnsignedLong(0))
#define B(which, key) G(FcBool, FcPatternGetBool, which, pybool, key, increment_and_return(Py_False))
#define E(which, key, conv) G(int, FcPatternGetInteger, which, conv, key, PyLong_FromUnsignedLong(0))
    S(FC_FILE, path);
    S(FC_FAMILY, family);
    S(FC_STYLE, style);
    S(FC_FULLNAME, full_name);
    S(FC_POSTSCRIPT_NAME, postscript_name);
    LS(FC_FONT_FEATURES, fontfeatures);
    B(FC_VARIABLE, variable);
#ifdef FC_NAMED_INSTANCE
    B(FC_NAMED_INSTANCE, named_instance);
#else
    PyDict_SetItemString(ans, "named_instance", Py_False);
#endif
    I(FC_WEIGHT, weight);
    I(FC_WIDTH, width)
    I(FC_SLANT, slant);
    I(FC_HINT_STYLE, hint_style);
    I(FC_INDEX, index);
    I(FC_RGBA, subpixel);
    I(FC_LCD_FILTER, lcdfilter);
    B(FC_HINTING, hinting);
    B(FC_SCALABLE, scalable);
    B(FC_OUTLINE, outline);
    B(FC_COLOR, color);
    E(FC_SPACING, spacing, pyspacing);

    Py_INCREF(ans);
    return ans;
#undef PS
#undef S
#undef I
#undef B
#undef E
#undef G
#undef L
#undef LS
}

static PyObject*
font_set(FcFontSet *fs) {
    PyObject *ans = PyTuple_New(fs->nfont);
    if (ans == NULL) return NULL;
    for (int i = 0; i < fs->nfont; i++) {
        PyObject *d = pattern_as_dict(fs->fonts[i]);
        if (d == NULL) { Py_CLEAR(ans); break; }
        PyTuple_SET_ITEM(ans, i, d);
    }
    return ans;
}

#define AP(func, which, in, desc) if (!func(pat, which, in)) { PyErr_Format(PyExc_ValueError, "Failed to add %s to fontconfig pattern", desc, NULL); goto end; }

static PyObject*
fc_list(PyObject UNUSED *self, PyObject *args, PyObject *kw) {
    ensure_initialized();
    int allow_bitmapped_fonts = 0, spacing = -1, only_variable = 0;
    PyObject *ans = NULL;
    FcObjectSet *os = NULL;
    FcPattern *pat = NULL;
    FcFontSet *fs = NULL;
    static char *kwds[] = {"spacing", "allow_bitmapped_fonts", "only_variable", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kw, "|ipp", kwds, &spacing, &allow_bitmapped_fonts, &only_variable)) return NULL;
    pat = FcPatternCreate();
    if (pat == NULL) return PyErr_NoMemory();
    if (!allow_bitmapped_fonts) {
        AP(FcPatternAddBool, FC_OUTLINE, FcTrue, "outline");
        AP(FcPatternAddBool, FC_SCALABLE, FcTrue, "scalable");
    }
    if (spacing > -1) AP(FcPatternAddInteger, FC_SPACING, spacing, "spacing");
    if (only_variable) AP(FcPatternAddBool, FC_VARIABLE, FcTrue, "variable");
    os = FcObjectSetBuild(FC_FILE, FC_POSTSCRIPT_NAME, FC_FAMILY, FC_STYLE, FC_FULLNAME, FC_WEIGHT, FC_WIDTH, FC_SLANT, FC_HINT_STYLE, FC_INDEX, FC_HINTING, FC_SCALABLE, FC_OUTLINE, FC_COLOR, FC_SPACING, FC_VARIABLE,
#ifdef FC_NAMED_INSTANCE
    FC_NAMED_INSTANCE,
#endif
    NULL);
    if (!os) { PyErr_SetString(PyExc_ValueError, "Failed to create fontconfig object set"); goto end; }
    fs = FcFontList(NULL, pat, os);
    if (!fs) { PyErr_SetString(PyExc_ValueError, "Failed to create fontconfig font set"); goto end; }
    ans = font_set(fs);
end:
    if (pat != NULL) FcPatternDestroy(pat);
    if (os != NULL) FcObjectSetDestroy(os);
    if (fs != NULL) FcFontSetDestroy(fs);
    return ans;
}

static PyObject*
_fc_match(FcPattern *pat) {
    FcPattern *match = NULL;
    PyObject *ans = NULL;
    FcResult result;
    FcConfigSubstitute(NULL, pat, FcMatchPattern);
    FcDefaultSubstitute(pat);
    /* printf("fc_match = %s\n", FcNameUnparse(pat)); */
    match = FcFontMatch(NULL, pat, &result);
    if (match == NULL) { PyErr_SetString(PyExc_KeyError, "FcFontMatch() failed"); goto end; }
    ans = pattern_as_dict(match);
end:
    if (match) FcPatternDestroy(match);
    return ans;
}

static char_type char_buf[1024];

static void
add_charset(FcPattern *pat, size_t num) {
    FcCharSet *charset = NULL;
    if (num) {
        charset = FcCharSetCreate();
        if (charset == NULL) { PyErr_NoMemory(); goto end; }
        for (size_t i = 0; i < num; i++) {
            if (!FcCharSetAddChar(charset, char_buf[i])) {
                PyErr_SetString(PyExc_RuntimeError, "Failed to add character to fontconfig charset");
                goto end;
            }
        }
        AP(FcPatternAddCharSet, FC_CHARSET, charset, "charset");
    }
end:
    if (charset != NULL) FcCharSetDestroy(charset);
}

static bool
_native_fc_match(FcPattern *pat, FontConfigFace *ans) {
    bool ok = false;
    FcPattern *match = NULL;
    FcResult result;
    FcConfigSubstitute(NULL, pat, FcMatchPattern);
    FcDefaultSubstitute(pat);
    /* printf("fc_match = %s\n", FcNameUnparse(pat)); */
    match = FcFontMatch(NULL, pat, &result);
    if (match == NULL) { PyErr_SetString(PyExc_KeyError, "FcFontMatch() failed"); goto end; }
    FcChar8 *out;
#define g(func, prop, output) if (func(match, prop, 0, &output) != FcResultMatch) { PyErr_SetString(PyExc_ValueError, "No " #prop " found in fontconfig match result"); goto end; }
    g(FcPatternGetString, FC_FILE, out);
    g(FcPatternGetInteger, FC_INDEX, ans->index);
    g(FcPatternGetInteger, FC_HINT_STYLE, ans->hintstyle);
    g(FcPatternGetBool, FC_HINTING, ans->hinting);
#undef g
    ans->path = strdup((char*)out);
    if (!ans->path) { PyErr_NoMemory(); goto end; }
    ok = true;
end:
    if (match != NULL) FcPatternDestroy(match);
    return ok;
}


bool
information_for_font_family(const char *family, bool bold, bool italic, FontConfigFace *ans) {
    ensure_initialized();
    memset(ans, 0, sizeof(FontConfigFace));
    FcPattern *pat = FcPatternCreate();
    bool ok = false;
    if (pat == NULL) { PyErr_NoMemory(); return ok; }
    if (family && strlen(family) > 0) AP(FcPatternAddString, FC_FAMILY, (const FcChar8*)family, "family");
    if (bold) { AP(FcPatternAddInteger, FC_WEIGHT, FC_WEIGHT_BOLD, "weight"); }
    if (italic) { AP(FcPatternAddInteger, FC_SLANT, FC_SLANT_ITALIC, "slant"); }
    ok = _native_fc_match(pat, ans);
end:
    if (pat != NULL) FcPatternDestroy(pat);
    return ok;
}


static PyObject*
fc_match(PyObject UNUSED *self, PyObject *args) {
    ensure_initialized();
    char *family = NULL;
    int bold = 0, italic = 0, allow_bitmapped_fonts = 0, spacing = FC_MONO;
    double size_in_pts = 0, dpi = 0;
    FcPattern *pat = NULL;
    PyObject *ans = NULL;

    if (!PyArg_ParseTuple(args, "|zppipdd", &family, &bold, &italic, &spacing, &allow_bitmapped_fonts, &size_in_pts, &dpi)) return NULL;
    pat = FcPatternCreate();
    if (pat == NULL) return PyErr_NoMemory();

    if (family && strlen(family) > 0) AP(FcPatternAddString, FC_FAMILY, (const FcChar8*)family, "family");
    if (spacing >= FC_DUAL) {
        // pass the family,monospace as the family parameter to fc-match,
        // which will fallback to using monospace if the family does not match.
        AP(FcPatternAddString, FC_FAMILY, (const FcChar8*)"monospace", "family");
        AP(FcPatternAddInteger, FC_SPACING, spacing, "spacing");
    }
    if (!allow_bitmapped_fonts) {
        AP(FcPatternAddBool, FC_OUTLINE, true, "outline");
        AP(FcPatternAddBool, FC_SCALABLE, true, "scalable");
    }
    if (size_in_pts > 0) { AP(FcPatternAddDouble, FC_SIZE, size_in_pts, "size"); }
    if (dpi > 0) { AP(FcPatternAddDouble, FC_DPI, dpi, "dpi"); }
    if (bold) { AP(FcPatternAddInteger, FC_WEIGHT, FC_WEIGHT_BOLD, "weight"); }
    if (italic) { AP(FcPatternAddInteger, FC_SLANT, FC_SLANT_ITALIC, "slant"); }
    ans = _fc_match(pat);

end:
    if (pat != NULL) FcPatternDestroy(pat);
    return ans;
}

static PyObject*
fc_match_postscript_name(PyObject UNUSED *self, PyObject *args) {
    ensure_initialized();
    const char *postscript_name = NULL;
    FcPattern *pat = NULL;
    PyObject *ans = NULL;

    if (!PyArg_ParseTuple(args, "s", &postscript_name)) return NULL;
    if (!postscript_name || !postscript_name[0]) { PyErr_SetString(PyExc_KeyError, "postscript_name must not be empty"); return NULL; }

    pat = FcPatternCreate();
    if (pat == NULL) return PyErr_NoMemory();

    AP(FcPatternAddString, FC_POSTSCRIPT_NAME, (const FcChar8*)postscript_name, "postscript_name");

    ans = _fc_match(pat);

end:
    if (pat != NULL) FcPatternDestroy(pat);
    return ans;
}

PyObject*
specialize_font_descriptor(PyObject *base_descriptor, double font_sz_in_pts, double dpi_x, double dpi_y) {
    ensure_initialized();
    PyObject *p = PyDict_GetItemString(base_descriptor, "path");
    PyObject *idx = PyDict_GetItemString(base_descriptor, "index");
    if (p == NULL) { PyErr_SetString(PyExc_ValueError, "Base descriptor has no path"); return NULL; }
    if (idx == NULL) { PyErr_SetString(PyExc_ValueError, "Base descriptor has no index"); return NULL; }
    unsigned long face_idx = PyLong_AsUnsignedLong(idx);
    if (PyErr_Occurred()) return NULL;

    FcPattern *pat = FcPatternCreate();
    if (pat == NULL) return PyErr_NoMemory();
    RAII_PyObject(features, PyList_New(0));
    if (!features) return NULL;
    RAII_PyObject(final_features, NULL);
    RAII_PyObject(ans, NULL);
    AP(FcPatternAddString, FC_FILE, (const FcChar8*)PyUnicode_AsUTF8(p), "path");
    AP(FcPatternAddInteger, FC_INDEX, face_idx, "index");
    AP(FcPatternAddDouble, FC_SIZE, font_sz_in_pts, "size");
    AP(FcPatternAddDouble, FC_DPI, (dpi_x + dpi_y) / 2.0, "dpi");
    ans = _fc_match(pat);
    FcPatternDestroy(pat); pat = NULL;
    if (!ans) return NULL;
    // fontconfig returns a completely random font if the base descriptor
    // points to a font that fontconfig hasnt indexed, for example the built-in
    // NERD font
    PyObject *new_path = PyDict_GetItemString(ans, "path");
    if (!new_path || PyObject_RichCompareBool(p, new_path, Py_EQ) != 1) { Py_CLEAR(ans); ans = PyDict_Copy(base_descriptor); if (!ans) return NULL;  }

    if (face_idx > 0) {
        // For some reason FcFontMatch sets the index to zero, so manually restore it.
        if (PyDict_SetItemString(ans, "index", idx) != 0) return NULL;
    }
    PyObject *named_style = PyDict_GetItemString(base_descriptor, "named_style");
    if (named_style) {
        if (PyDict_SetItemString(ans, "named_style", named_style) != 0) return NULL;
    }
    PyObject *axes = PyDict_GetItemString(base_descriptor, "axes");
    if (axes) {
        if (PyDict_SetItemString(ans, "axes", axes) != 0) return NULL;
    }
    PyObject *ff = PyDict_GetItemString(ans, "fontfeatures");
    if (ff && PyList_GET_SIZE(ff)) {
        for (Py_ssize_t i = 0; i < PyList_GET_SIZE(ff); i++) {
            RAII_PyObject(pff, (PyObject*)parse_font_feature(PyUnicode_AsUTF8(PyList_GET_ITEM(ff, i))));
            if (pff == NULL) {
                PyErr_Print(); fprintf(stderr, "\n");
            } else if (PyList_Append(features, pff) != 0) return NULL;
        }
    }
    PyObject *base_features = PyDict_GetItemString(base_descriptor, "features");
    final_features = PyTuple_New(PyList_GET_SIZE(features) + (base_features ? PyTuple_GET_SIZE(base_features) : 0));
    if (!final_features) return NULL;
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(features); i++) { PyTuple_SET_ITEM(final_features, i, Py_NewRef(PyList_GET_ITEM(features, i))); }
    if (base_features) {
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(base_features); i++) { PyTuple_SET_ITEM(final_features, i + PyList_GET_SIZE(features), Py_NewRef(PyTuple_GET_ITEM(base_features, i))); }
    }
    if (PyDict_SetItemString(ans, "features", final_features) != 0) return NULL;
    Py_INCREF(ans);
    return ans;
end:
    if (pat) FcPatternDestroy(pat);
    return NULL;
}

bool
fallback_font(char_type ch, const char *family, bool bold, bool italic, bool prefer_color, FontConfigFace *ans) {
    ensure_initialized();
    memset(ans, 0, sizeof(FontConfigFace));
    bool ok = false;
    FcPattern *pat = FcPatternCreate();
    if (pat == NULL) { PyErr_NoMemory(); return ok; }
    if (family) AP(FcPatternAddString, FC_FAMILY, (const FcChar8*)family, "family");
    if (bold) { AP(FcPatternAddInteger, FC_WEIGHT, FC_WEIGHT_BOLD, "weight"); }
    if (italic) { AP(FcPatternAddInteger, FC_SLANT, FC_SLANT_ITALIC, "slant"); }
    if (prefer_color) { AP(FcPatternAddBool, FC_COLOR, true, "color"); }
    char_buf[0] = ch;
    add_charset(pat, 1);
    ok = _native_fc_match(pat, ans);
end:
    if (pat != NULL) FcPatternDestroy(pat);
    return ok;
}

static bool face_has_codepoint(const void *face, char_type cp) { return glyph_id_for_codepoint(face, cp) > 0; }

PyObject*
create_fallback_face(PyObject UNUSED *base_face, const ListOfChars *lc, bool bold, bool italic, bool emoji_presentation, FONTS_DATA_HANDLE fg) {
    ensure_initialized();
    PyObject *ans = NULL;
    RAII_PyObject(d, NULL);
    FcPattern *pat = FcPatternCreate();
    if (pat == NULL) return PyErr_NoMemory();
    bool glyph_found = false;
    AP(FcPatternAddString, FC_FAMILY, (const FcChar8*)(emoji_presentation ? "emoji" : "monospace"), "family");
    if (!emoji_presentation && bold) { AP(FcPatternAddInteger, FC_WEIGHT, FC_WEIGHT_BOLD, "weight"); }
    if (!emoji_presentation && italic) { AP(FcPatternAddInteger, FC_SLANT, FC_SLANT_ITALIC, "slant"); }
    if (emoji_presentation) { AP(FcPatternAddBool, FC_COLOR, true, "color"); }
    size_t num = cell_as_unicode_for_fallback(lc, char_buf, arraysz(char_buf));
    add_charset(pat, num);
    d = _fc_match(pat);
face_from_descriptor:
    if (d) {
        ssize_t idx = -1;
        PyObject *q;
        while ((q = iter_fallback_faces(fg, &idx))) {
            if (face_equals_descriptor(q, d)) {
                ans = PyLong_FromSsize_t(idx);
                if (!glyph_found) glyph_found = has_cell_text(face_has_codepoint, q, false, lc);
                goto end;
            }
        }
        ans = face_from_descriptor(d, fg);
        if (!glyph_found && ans) glyph_found = has_cell_text(face_has_codepoint, ans, false, lc);
    }
end:
    Py_CLEAR(d);
    if (pat != NULL) { FcPatternDestroy(pat); pat = NULL; }
    if (!glyph_found && !PyErr_Occurred()) {
        if (builtin_nerd_font.face && has_cell_text(face_has_codepoint, builtin_nerd_font.face, false, lc)) {
            Py_CLEAR(ans);
            d = builtin_nerd_font.descriptor; Py_INCREF(d); glyph_found = true; goto face_from_descriptor;
        } else {
            if (global_state.debug_font_fallback && ans) has_cell_text(face_has_codepoint, ans, true, lc);
            Py_CLEAR(ans); ans = Py_None; Py_INCREF(ans);
        }
    }
    return ans;
}


static PyObject*
set_builtin_nerd_font(PyObject UNUSED *self, PyObject *pypath) {
    if (!PyUnicode_Check(pypath)) { PyErr_SetString(PyExc_TypeError, "path must be a string"); return NULL; }
    ensure_initialized();
    const char *path = PyUnicode_AsUTF8(pypath);
    FcPattern *pat = FcPatternCreate();
    if (pat == NULL) return PyErr_NoMemory();
    Py_CLEAR(builtin_nerd_font.face);
    Py_CLEAR(builtin_nerd_font.descriptor);

    builtin_nerd_font.face = face_from_path(path, 0, NULL);
    if (builtin_nerd_font.face) {
        // Copy whatever hinting settings fontconfig returns for the nerd font postscript name
        AP(FcPatternAddString, FC_POSTSCRIPT_NAME, (const unsigned char*)postscript_name_for_face(builtin_nerd_font.face), "postscript_name");
        RAII_PyObject(d, _fc_match(pat));
        if (!d) goto end;
        builtin_nerd_font.descriptor = PyDict_New();
        if (!builtin_nerd_font.descriptor) goto end;
#define copy(key) { PyObject *t = PyDict_GetItemString(d, #key); if (t) { if (PyDict_SetItemString(builtin_nerd_font.descriptor, #key, t) != 0)goto end; } }
        copy(hinting); copy(hint_style);
#undef copy
        if (PyDict_SetItemString(builtin_nerd_font.descriptor, "path", pypath) != 0) goto end;
        if (PyDict_SetItemString(builtin_nerd_font.descriptor, "index", PyLong_FromLong(0)) != 0) goto end;
    }
end:
    if (pat) FcPatternDestroy(pat);
    if (PyErr_Occurred()) {
        Py_CLEAR(builtin_nerd_font.face);
        Py_CLEAR(builtin_nerd_font.descriptor);
        return NULL;
    }
    Py_INCREF(builtin_nerd_font.descriptor);
    return builtin_nerd_font.descriptor;
}


static PyObject*
add_font_file(PyObject UNUSED *self, PyObject *args) {
    ensure_initialized();
    const char *path = NULL;
    if (!PyArg_ParseTuple(args, "s", &path)) return NULL;
    if (FcConfigAppFontAddFile(NULL, (const unsigned char*)path)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}


#undef AP

static PyMethodDef module_methods[] = {
    {"fc_list", (PyCFunction)(void (*) (void))(fc_list), METH_VARARGS | METH_KEYWORDS, NULL},
    METHODB(fc_match, METH_VARARGS),
    METHODB(fc_match_postscript_name, METH_VARARGS),
    METHODB(add_font_file, METH_VARARGS),
    METHODB(set_builtin_nerd_font, METH_O),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_fontconfig_library(PyObject *module) {
    register_at_exit_cleanup_func(FONTCONFIG_CLEANUP_FUNC, finalize);
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    PyModule_AddIntMacro(module, FC_WEIGHT_REGULAR);
    PyModule_AddIntMacro(module, FC_WEIGHT_MEDIUM);
    PyModule_AddIntMacro(module, FC_WEIGHT_SEMIBOLD);
    PyModule_AddIntMacro(module, FC_WEIGHT_BOLD);
    PyModule_AddIntMacro(module, FC_SLANT_ITALIC);
    PyModule_AddIntMacro(module, FC_SLANT_ROMAN);
    PyModule_AddIntMacro(module, FC_PROPORTIONAL);
    PyModule_AddIntMacro(module, FC_DUAL);
    PyModule_AddIntMacro(module, FC_MONO);
    PyModule_AddIntMacro(module, FC_CHARCELL);
    PyModule_AddIntMacro(module, FC_WIDTH_NORMAL);

    return true;
}
