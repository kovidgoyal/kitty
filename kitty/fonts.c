/*
 * fonts.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"
#include "state.h"

typedef uint16_t glyph_index;

typedef struct SpritePosition SpritePosition;

struct SpritePosition {
    SpritePosition *next;
    bool filled, rendered, is_second;
    sprite_index x, y, z;
    glyph_index glyph;
    uint64_t extra_glyphs;
};


typedef struct {
    size_t max_array_len, max_texture_size, max_y;
    unsigned int x, y, z, xnum, ynum;
} GPUSpriteTracker;


static GPUSpriteTracker sprite_tracker = {
    .max_array_len = 1000,
    .max_texture_size = 1000,
    .max_y = 100,
};


typedef struct {
    PyObject *face;
    hb_font_t *hb_font;
    // Map glyphs to sprite map co-ords
    SpritePosition sprite_map[1024]; 
    bool bold, italic;
} Font;


static inline void 
sprite_map_set_error(int error) {
    switch(error) {
        case 1:
            PyErr_NoMemory(); break;
        case 2:
            PyErr_SetString(PyExc_RuntimeError, "Out of texture space for sprites"); break;
        default:
            PyErr_SetString(PyExc_RuntimeError, "Unknown error occurred while allocating sprites"); break;
    }
}

void
sprite_tracker_set_limits(size_t max_texture_size, size_t max_array_len) {
    sprite_tracker.max_texture_size = max_texture_size;
    sprite_tracker.max_array_len = max_array_len;
}

static inline void
do_increment(int *error) {
    sprite_tracker.x++;
    if (sprite_tracker.x >= sprite_tracker.xnum) {
        sprite_tracker.x = 0; sprite_tracker.y++;
        sprite_tracker.ynum = MIN(MAX(sprite_tracker.ynum, sprite_tracker.y + 1), sprite_tracker.max_y);
        if (sprite_tracker.y >= sprite_tracker.max_y) {
            sprite_tracker.y = 0; sprite_tracker.z++;
            if (sprite_tracker.z >= MIN(UINT16_MAX, sprite_tracker.max_array_len)) *error = 2;
        }
    }
}


SpritePosition*
sprite_position_for(Font *font, glyph_index glyph, uint64_t extra_glyphs, bool is_second, int *error) {
    glyph_index idx = glyph & 0x3ff;
    SpritePosition *s = font->sprite_map + idx;
    // Optimize for the common case of glyph under 1024 already in the cache
    if (LIKELY(s->glyph == glyph && s->filled && s->extra_glyphs == extra_glyphs && s->is_second == is_second)) return s;  // Cache hit
    while(true) {
        if (s->filled) {
            if (s->glyph == glyph && s->extra_glyphs == extra_glyphs && s->is_second == is_second) return s;  // Cache hit
        } else {
            break;
        }
        if (!s->next) {
            s->next = calloc(1, sizeof(SpritePosition));
            if (s->next == NULL) { *error = 1; return NULL; }
        }
        s = s->next;
    }
    s->glyph = glyph;
    s->extra_glyphs = extra_glyphs;
    s->is_second = is_second;
    s->filled = true;
    s->rendered = false;
    s->x = sprite_tracker.x; s->y = sprite_tracker.y; s->z = sprite_tracker.z;
    do_increment(error);
    return s;
}

void
sprite_tracker_current_layout(unsigned int *x, unsigned int *y, unsigned int *z) {
    *x = sprite_tracker.xnum; *y = sprite_tracker.ynum; *z = sprite_tracker.z;
}

int 
sprite_tracker_increment(sprite_index *x, sprite_index *y, sprite_index *z) {
    int error = 0;
    *x = sprite_tracker.x; *y = sprite_tracker.y; *z = sprite_tracker.z;
    do_increment(&error);
    return error;
}

void
sprite_map_free(Font *font) {
    SpritePosition *s, *t;
    for (size_t i = 0; i < sizeof(font->sprite_map)/sizeof(font->sprite_map[0]); i++) {
        s = font->sprite_map + i;
        s = s->next;
        while (s) {
            t = s;
            s = s->next;
            free(t);
        }
    }
}

void
clear_sprite_map(Font *font) {
#define CLEAR(s) s->filled = false; s->rendered = false; s->glyph = 0; s->extra_glyphs = 0; s->x = 0; s->y = 0; s->z = 0; s->is_second = false;
    SpritePosition *s;
    for (size_t i = 0; i < sizeof(font->sprite_map)/sizeof(font->sprite_map[0]); i++) {
        s = font->sprite_map + i;
        CLEAR(s);
        while ((s = s->next)) {
            CLEAR(s);
        }
    }
#undef CLEAR
}

void
sprite_tracker_set_layout(unsigned int cell_width, unsigned int cell_height) {
    sprite_tracker.xnum = MIN(MAX(1, sprite_tracker.max_texture_size / cell_width), UINT16_MAX);
    sprite_tracker.max_y = MIN(MAX(1, sprite_tracker.max_texture_size / cell_height), UINT16_MAX);
    sprite_tracker.ynum = 1;
    sprite_tracker.x = 0; sprite_tracker.y = 0; sprite_tracker.z = 0;
}


static inline bool
alloc_font(Font *f, PyObject *face, bool bold, bool italic) {
    f->face = face; Py_INCREF(face);
    f->hb_font = harfbuzz_font_for_face(face);
    if (f->hb_font == NULL) return false;
    f->bold = bold; f->italic = italic;
    return true;
}

static inline void
free_font(Font *f) { 
    f->hb_font = NULL;
    Py_CLEAR(f->face); 
    sprite_map_free(f);
    f->bold = false; f->italic = false;
}

static Font medium_font = {0}, bold_font = {0}, italic_font = {0}, bi_font = {0}, box_font = {0}, missing_font = {0}, blank_font = {0};
static Font fallback_fonts[256] = {{0}};
static PyObject *get_fallback_font = NULL;

typedef struct {
    char_type left, right;
    size_t font_idx;
} SymbolMap;
static SymbolMap* symbol_maps = NULL;
static Font *symbol_map_fonts = NULL;
static size_t symbol_maps_count = 0, symbol_map_fonts_count = 0;

static unsigned int cell_width = 0, cell_height = 0, baseline = 0, underline_position = 0, underline_thickness = 0;

static inline PyObject*
update_cell_metrics(float pt_sz, float xdpi, float ydpi) {
#define CALL(f) { if ((f)->face) { if(!set_size_for_face((f)->face, pt_sz, xdpi, ydpi)) return NULL; clear_sprite_map(f); } }
    CALL(&medium_font); CALL(&bold_font); CALL(&italic_font); CALL(&bi_font);
    for (size_t i = 0; fallback_fonts[i].face != NULL; i++)  {
        CALL(fallback_fonts + i);
    }
    for (size_t i = 0; i < symbol_map_fonts_count; i++)  {
        CALL(symbol_map_fonts + i);
    }
#undef CALL
    cell_metrics(medium_font.face, &cell_width, &cell_height, &baseline, &underline_position, &underline_thickness);
    if (!cell_width) { PyErr_SetString(PyExc_ValueError, "Failed to calculate cell width for the specified font."); return NULL; }
    if (OPT(adjust_line_height_px) != 0) cell_height += OPT(adjust_line_height_px);
    if (OPT(adjust_line_height_frac) != 0.f) cell_height *= OPT(adjust_line_height_frac);
    if (cell_height < 4) { PyErr_SetString(PyExc_ValueError, "line height too small after adjustment"); return NULL; }
    if (cell_height > 1000) { PyErr_SetString(PyExc_ValueError, "line height too large after adjustment"); return NULL; }
    underline_position = MIN(cell_height - 1, underline_position);
    sprite_tracker_set_layout(cell_width, cell_height);
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
    size_t n = cell_as_unicode(cell, true, buf, ' ');
    PyObject *face = PyObject_CallFunction(get_fallback_font, "NOO", PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buf, n), bold ? Py_True : Py_False, italic ? Py_True : Py_False);
    if (face == NULL) { PyErr_Print(); return &missing_font; }
    if (face == Py_None) { Py_DECREF(face); return &missing_font; }
    if (!alloc_font(fallback_fonts + i, face, bold, italic)) { fatal("Out of memory"); }
    return fallback_fonts + i;
}

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

static hb_buffer_t *harfbuzz_buffer = NULL;

static void
finalize(void) {
    Py_CLEAR(get_fallback_font);
    free_font(&medium_font); free_font(&bold_font); free_font(&italic_font); free_font(&bi_font);
    for (size_t i = 0; fallback_fonts[i].face != NULL; i++)  free_font(fallback_fonts + i);
    for (size_t i = 0; symbol_map_fonts_count; i++) free_font(symbol_map_fonts + i);
    free(symbol_maps); free(symbol_map_fonts);
    if (harfbuzz_buffer) hb_buffer_destroy(harfbuzz_buffer);
}

static PyObject*
sprite_map_set_limits(PyObject UNUSED *self, PyObject *args) {
    unsigned int w, h;
    if(!PyArg_ParseTuple(args, "II", &w, &h)) return NULL;
    sprite_tracker_set_limits(w, h);
    Py_RETURN_NONE;
}

static PyObject*
sprite_map_set_layout(PyObject UNUSED *self, PyObject *args) {
    unsigned int w, h;
    if(!PyArg_ParseTuple(args, "II", &w, &h)) return NULL;
    sprite_tracker_set_layout(w, h);
    Py_RETURN_NONE;
}

static PyObject*
test_sprite_position_for(PyObject UNUSED *self, PyObject *args) {
    glyph_index glyph;
    uint64_t extra_glyphs = 0;
    if (!PyArg_ParseTuple(args, "H|I", &glyph, &extra_glyphs)) return NULL;
    int error;
    SpritePosition *pos = sprite_position_for(&box_font, glyph, extra_glyphs, false, &error);
    if (pos == NULL) { sprite_map_set_error(error); return NULL; }
    return Py_BuildValue("HHH", pos->x, pos->y, pos->z);
}

static PyMethodDef module_methods[] = {
    METHODB(set_font_size, METH_VARARGS),
    METHODB(set_font, METH_VARARGS),
    METHODB(sprite_map_set_limits, METH_VARARGS),
    METHODB(sprite_map_set_layout, METH_VARARGS),
    METHODB(test_sprite_position_for, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool 
init_fonts(PyObject *module) {
    if (Py_AtExit(finalize) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to register the fonts module at exit handler");
        return false;
    }
    harfbuzz_buffer = hb_buffer_create();
    if (harfbuzz_buffer == NULL || !hb_buffer_allocation_successful(harfbuzz_buffer) || !hb_buffer_pre_allocate(harfbuzz_buffer, 2000)) { PyErr_NoMemory(); return false; }
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
