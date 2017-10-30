/*
 * fonts.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"
#include "state.h"

typedef uint16_t glyph_index;

typedef struct {
    sprite_index x, y, z;
} SpriteIndex;


typedef struct {
    PyObject *face;
    hb_font_t *hb_font;
    // Map glyph ids to sprite map co-ords
    SpriteIndex *sprite_map; 
    bool bold, italic;
} Font;

static Font medium_font = {0}, bold_font = {0}, italic_font = {0}, bi_font = {0}, box_font = {0}, missing_font = {0}, blank_font = {0};
static Font fallback_fonts[256] = {{0}};
static PyObject *get_fallback_font = NULL;

static inline bool
alloc_font(Font *f, PyObject *face, bool bold, bool italic) {
    f->sprite_map = calloc(1 << (sizeof(glyph_index) * 8), sizeof(SpriteIndex));
    if (f->sprite_map == NULL) return false;
    f->face = face; Py_INCREF(face);
    f->hb_font = harfbuzz_font_for_face(face);
    f->bold = bold; f->italic = italic;
    return true;
}

static inline void
clear_font(Font *f) { 
    Py_CLEAR(f->face); 
    free(f->sprite_map); f->sprite_map = NULL;
    f->hb_font = NULL;
    f->bold = false; f->italic = false;
}

static unsigned int cell_width = 0, cell_height = 0, baseline = 0, underline_position = 0, underline_thickness = 0;

static inline PyObject*
update_cell_metrics(float pt_sz, float xdpi, float ydpi) {
#define CALL(f) { if ((f)->face && !set_size_for_face((f)->face, pt_sz, xdpi, ydpi)) return NULL; }
    CALL(&medium_font); CALL(&bold_font); CALL(&italic_font); CALL(&bi_font);
    for (size_t i = 0; fallback_fonts[i].face != NULL; i++)  {
        CALL(fallback_fonts + i);
    }
#undef CALL
    cell_metrics(medium_font.face, &cell_width, &cell_height, &baseline, &underline_position, &underline_thickness);
    if (!cell_width) { PyErr_SetString(PyExc_ValueError, "Failed to calculate cell width for the specified font."); return NULL; }
    if (OPT(adjust_line_height_px) != 0) cell_height += OPT(adjust_line_height_px);
    if (OPT(adjust_line_height_frac) != 0.f) cell_height *= OPT(adjust_line_height_frac);
    if (cell_height < 4) { PyErr_SetString(PyExc_ValueError, "line height too small after adjustment"); return NULL; }
    if (cell_height > 1000) { PyErr_SetString(PyExc_ValueError, "line height too large after adjustment"); return NULL; }
    underline_position = MIN(cell_height - 1, underline_position);
    return Py_BuildValue("IIIII", cell_width, cell_height, baseline, underline_position, underline_thickness);
}

static PyObject*
set_font_size(PyObject UNUSED *m, PyObject *args) {
    float pt_sz, xdpi, ydpi;
    if (!PyArg_ParseTuple(args, "fff", &pt_sz, &xdpi, &ydpi)) return NULL;
    return update_cell_metrics(pt_sz, xdpi, ydpi);
}

static inline bool 
has_cell_text(Font *self, Cell *cell) {
    if (!face_has_codepoint(self->face, cell->ch)) return false;
    if (cell->cc) {
        if (!face_has_codepoint(self->face, cell->cc & CC_MASK)) return false;
        char_type cc = cell->cc >> 16;
        if (cc && !face_has_codepoint(self->face, cc)) return false;
    }
    return true;
}


static inline Font*
fallback_font(Cell *cell) {
    bool bold = (cell->attrs >> BOLD_SHIFT) & 1;
    bool italic = (cell->attrs >> ITALIC_SHIFT) & 1;
    size_t i;

    for (i = 0; fallback_fonts[i].face != NULL; i++)  {
        if (fallback_fonts[i].bold == bold && fallback_fonts[i].italic == italic && has_cell_text(fallback_fonts + i, cell)) {
            return fallback_fonts + i;
        }
    }
    if (get_fallback_font == NULL || i == (sizeof(fallback_fonts)/sizeof(fallback_fonts[0])-1)) return &missing_font;
    Py_UCS4 buf[10];
    size_t n = cell_as_unicode(cell, true, buf);
    PyObject *face = PyObject_CallFunction(get_fallback_font, "NOO", PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buf, n), bold ? Py_True : Py_False, italic ? Py_True : Py_False);
    if (face == NULL) { PyErr_Print(); return &missing_font; }
    if (face == Py_None) { Py_DECREF(face); return &missing_font; }
    if (!alloc_font(fallback_fonts + i, face, bold, italic)) { fatal("Out of memory"); }
    return fallback_fonts + i;
}

typedef struct {
    char_type left, right;
    size_t font_idx;
} SymbolMap;
static SymbolMap* symbol_maps = NULL;
static Font *symbol_map_fonts = NULL;
static size_t symbol_maps_count = 0, symbol_map_fonts_count = 0;

static inline Font*
in_symbol_maps(char_type ch) {
    for (size_t i = 0; i < symbol_maps_count; i++) {
        if (symbol_maps[i].left <= ch && ch <= symbol_maps[i].right) return symbol_map_fonts + symbol_maps[i].font_idx;
    }
    return NULL;
}


Font*
font_for_cell(Cell *cell) {
    Font *ans;
START_ALLOW_CASE_RANGE
    switch(cell->ch) {
        case 0:
            return &blank_font;
        case 0x2500 ... 0x2570:
        case 0x2574 ... 0x2577:
        case 0xe0b0:
        case 0xe0b2:
            return &box_font;
        default:
            ans = in_symbol_maps(cell->ch);
            if (ans != NULL) return ans;
            switch(BI_VAL(cell->attrs)) {
                case 0:
                    ans = &medium_font;
                    break;
                case 1:
                    ans = bold_font.face ? &bold_font : &medium_font;
                    break;
                case 2:
                    ans = italic_font.face ? &italic_font : &medium_font;
                    break;
                case 4:
                    ans = bi_font.face ? &bi_font : &medium_font;
                    break;
            }
            if (has_cell_text(ans, cell)) return ans;
            return fallback_font(cell);

    }
END_ALLOW_CASE_RANGE
}

static PyObject*
set_font(PyObject UNUSED *m, PyObject *args) {
    PyObject *sm, *smf, *medium, *bold = NULL, *italic = NULL, *bi = NULL;
    float xdpi, ydpi, pt_sz;
    if (!PyArg_ParseTuple(args, "OO!O!fffO|OOO", &get_fallback_font, &PyTuple_Type, &sm, &PyTuple_Type, &smf, &pt_sz, &xdpi, &ydpi, &medium, &bold, &italic, &bi)) return NULL;
    if (!alloc_font(&medium_font, medium, false, false)) return PyErr_NoMemory();
    if (bold && !alloc_font(&bold_font, bold, false, false)) return PyErr_NoMemory();
    if (italic && !alloc_font(&italic_font, italic, false, false)) return PyErr_NoMemory();
    if (bi && !alloc_font(&bi_font, bi, false, false)) return PyErr_NoMemory();

    symbol_maps_count = PyTuple_GET_SIZE(sm);
    if (symbol_maps_count > 0) {
        symbol_maps = malloc(symbol_maps_count * sizeof(SymbolMap));
        symbol_map_fonts_count = PyTuple_GET_SIZE(smf);
        symbol_map_fonts = calloc(symbol_map_fonts_count, sizeof(Font));
        if (symbol_maps == NULL || symbol_map_fonts == NULL) return PyErr_NoMemory();

        for (size_t i = 0; i < symbol_map_fonts_count; i++) {
            PyObject *face;
            int bold, italic;
            if (!PyArg_ParseTuple(PyTuple_GET_ITEM(smf, i), "Opp", &face, &bold, &italic)) return NULL;
            if (!alloc_font(symbol_map_fonts + i, face, bold != 0, italic != 0)) return PyErr_NoMemory();
        }
        for (size_t i = 0; i < symbol_maps_count; i++) {
            unsigned int left, right, font_idx;
            if (!PyArg_ParseTuple(PyTuple_GET_ITEM(sm, i), "III", &left, &right, &font_idx)) return NULL;
            symbol_maps[i].left = left; symbol_maps[i].right = right; symbol_maps[i].font_idx = font_idx;
        }
    }
    return update_cell_metrics(pt_sz, xdpi, ydpi);
}

static void
finalize(void) {
    Py_CLEAR(get_fallback_font);
    clear_font(&medium_font); clear_font(&bold_font); clear_font(&italic_font); clear_font(&bi_font);
    for (size_t i = 0; fallback_fonts[i].face != NULL; i++)  clear_font(fallback_fonts + i);
    for (size_t i = 0; symbol_map_fonts_count; i++) clear_font(symbol_map_fonts + i);
    free(symbol_maps); free(symbol_map_fonts);
}

static PyMethodDef module_methods[] = {
    METHODB(set_font_size, METH_VARARGS),
    METHODB(set_font, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool 
init_fonts(PyObject *module) {
    if (Py_AtExit(finalize) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to register the fonts module at exit handler");
        return false;
    }
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
