/*
 * vim:fileencoding=utf-8
 * fonts.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"
#include "state.h"
#include "emoji.h"
#include "unicode-data.h"

#define MISSING_GLYPH 4
#define MAX_NUM_EXTRA_GLYPHS 8

typedef void (*send_sprite_to_gpu_func)(unsigned int, unsigned int, unsigned int, pixel*);
send_sprite_to_gpu_func current_send_sprite_to_gpu = NULL;
static PyObject *python_send_to_gpu_impl = NULL;
extern PyTypeObject Line_Type;

typedef struct SpecialGlyphCache SpecialGlyphCache;
enum {NO_FONT=-3, MISSING_FONT=-2, BLANK_FONT=-1, BOX_FONT=0};


typedef struct {
    glyph_index data[MAX_NUM_EXTRA_GLYPHS];
} ExtraGlyphs;

typedef struct SpritePosition SpritePosition;
struct SpritePosition {
    SpritePosition *next;
    bool filled, rendered, colored;
    sprite_index x, y, z;
    uint8_t ligature_index;
    glyph_index glyph;
    ExtraGlyphs extra_glyphs;
};

#define SPECIAL_FILLED_MASK 1
#define SPECIAL_VALUE_MASK 2
#define EMPTY_FILLED_MASK 4
#define EMPTY_VALUE_MASK 8
#define SPECIAL_GLYPH_CACHE_SIZE 1024

struct SpecialGlyphCache {
    SpecialGlyphCache *next;
    glyph_index glyph;
    uint8_t data;
};

typedef struct {
    size_t max_array_len, max_texture_size, max_y;
    unsigned int x, y, z, xnum, ynum;
} GPUSpriteTracker;


static GPUSpriteTracker sprite_tracker = {0};
static hb_buffer_t *harfbuzz_buffer = NULL;
static char_type shape_buffer[4096] = {0};


typedef struct {
    PyObject *face;
    // Map glyphs to sprite map co-ords
    SpritePosition sprite_map[1024];
    SpecialGlyphCache special_glyph_cache[SPECIAL_GLYPH_CACHE_SIZE];
    bool bold, italic, emoji_presentation;
} Font;

typedef struct {
    char_type left, right;
    size_t font_idx;
} SymbolMap;

typedef struct {
    Font *fonts;
    SymbolMap* symbol_maps;
    size_t fonts_capacity, fonts_count, symbol_maps_capacity, symbol_maps_count, symbol_map_fonts_count, fallback_fonts_count;
    ssize_t box_font_idx, medium_font_idx, bold_font_idx, italic_font_idx, bi_font_idx, first_symbol_font_idx, first_fallback_font_idx;
} Fonts;

static Fonts fonts = {0};


// Sprites {{{

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
    sprite_tracker.max_array_len = MIN(0xfff, max_array_len);
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


static inline bool
extra_glyphs_equal(ExtraGlyphs *a, ExtraGlyphs *b) {
    for (size_t i = 0; i < MAX_NUM_EXTRA_GLYPHS; i++) {
        if (a->data[i] != b->data[i]) return false;
        if (a->data[i] == 0) return true;
    }
    return true;
}


static SpritePosition*
sprite_position_for(Font *font, glyph_index glyph, ExtraGlyphs *extra_glyphs, uint8_t ligature_index, int *error) {
    glyph_index idx = glyph & (SPECIAL_GLYPH_CACHE_SIZE - 1);
    SpritePosition *s = font->sprite_map + idx;
    // Optimize for the common case of glyph under 1024 already in the cache
    if (LIKELY(s->glyph == glyph && s->filled && extra_glyphs_equal(&s->extra_glyphs, extra_glyphs) && s->ligature_index == ligature_index)) return s;  // Cache hit
    while(true) {
        if (s->filled) {
            if (s->glyph == glyph && extra_glyphs_equal(&s->extra_glyphs, extra_glyphs) && s->ligature_index == ligature_index) return s;  // Cache hit
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
    memcpy(&s->extra_glyphs, extra_glyphs, sizeof(ExtraGlyphs));
    s->ligature_index = ligature_index;
    s->filled = true;
    s->rendered = false;
    s->colored = false;
    s->x = sprite_tracker.x; s->y = sprite_tracker.y; s->z = sprite_tracker.z;
    do_increment(error);
    return s;
}

static inline SpecialGlyphCache*
special_glyph_cache_for(Font *font, glyph_index glyph, uint8_t filled_mask) {
    SpecialGlyphCache *s = font->special_glyph_cache + (glyph & 0x3ff);
    // Optimize for the common case of glyph under SPECIAL_GLYPH_CACHE_SIZE already in the cache
    if (LIKELY(s->glyph == glyph && s->data & filled_mask)) return s;  // Cache hit
    while(true) {
        if (s->data & filled_mask) {
            if (s->glyph == glyph) return s;  // Cache hit
        } else {
            if (!s->glyph) break;  // Empty cache slot
            else if (s->glyph == glyph) return s;  // Cache slot that contains other data than the data indicated by filled_mask
        }
        if (!s->next) {
            s->next = calloc(1, sizeof(SpecialGlyphCache));
            if (s->next == NULL) return NULL;
        }
        s = s->next;
    }
    s->glyph = glyph;
    return s;
}

void
sprite_tracker_current_layout(unsigned int *x, unsigned int *y, unsigned int *z) {
    *x = sprite_tracker.xnum; *y = sprite_tracker.ynum; *z = sprite_tracker.z;
}

void
free_maps(Font *font) {
#define free_a_map(type, attr) {\
    type *s, *t; \
    for (size_t i = 0; i < sizeof(font->attr)/sizeof(font->attr[0]); i++) { \
        s = font->attr[i].next; \
        while (s) { \
            t = s; \
            s = s->next; \
            free(t); \
        } \
    }\
    memset(font->attr, 0, sizeof(font->attr)); \
}
    free_a_map(SpritePosition, sprite_map);
    free_a_map(SpecialGlyphCache, special_glyph_cache);
#undef free_a_map
}

void
clear_sprite_map(Font *font) {
#define CLEAR(s) s->filled = false; s->rendered = false; s->colored = false; s->glyph = 0; memset(&s->extra_glyphs, 0, sizeof(ExtraGlyphs)); s->x = 0; s->y = 0; s->z = 0; s->ligature_index = 0;
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
clear_special_glyph_cache(Font *font) {
#define CLEAR(s) s->data = 0; s->glyph = 0;
    SpecialGlyphCache *s;
    for (size_t i = 0; i < sizeof(font->special_glyph_cache)/sizeof(font->special_glyph_cache[0]); i++) {
        s = font->special_glyph_cache + i;
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
// }}}

static inline PyObject*
desc_to_face(PyObject *desc) {
    PyObject *d = specialize_font_descriptor(desc);
    if (d == NULL) return NULL;
    PyObject *ans = face_from_descriptor(d);
    Py_DECREF(d);
    return ans;
}


static inline bool
init_font(Font *f, PyObject *descriptor, bool bold, bool italic, bool is_face, bool emoji_presentation) {
    PyObject *face;
    if (is_face) { face = descriptor; Py_INCREF(face); }
    else { face = desc_to_face(descriptor); if (face == NULL) return false; }
    f->face = face;
    f->bold = bold; f->italic = italic; f->emoji_presentation = emoji_presentation;
    return true;
}

static inline void
del_font(Font *f) {
    Py_CLEAR(f->face);
    free_maps(f);
    f->bold = false; f->italic = false;
}

static unsigned int cell_width = 0, cell_height = 0, baseline = 0, underline_position = 0, underline_thickness = 0;
static pixel *canvas = NULL;
#define CELLS_IN_CANVAS ((MAX_NUM_EXTRA_GLYPHS + 1) * 3)
static inline void
clear_canvas(void) { memset(canvas, 0, CELLS_IN_CANVAS * cell_width * cell_height * sizeof(pixel)); }

static void
python_send_to_gpu(unsigned int x, unsigned int y, unsigned int z, pixel* buf) {
    if (python_send_to_gpu_impl != NULL && python_send_to_gpu_impl != Py_None) {
        PyObject *ret = PyObject_CallFunction(python_send_to_gpu_impl, "IIIN", x, y, z, PyBytes_FromStringAndSize((const char*)buf, sizeof(pixel) * cell_width * cell_height));
        if (ret == NULL) PyErr_Print();
        else Py_DECREF(ret);
    }
}


static inline PyObject*
update_cell_metrics(bool on_dpi_change UNUSED) {
#define CALL(idx, desired_height, force) { if (idx >= 0) { Font *f = fonts.fonts + idx; if ((f)->face) { if(!set_size_for_face((f)->face, desired_height, force)) return NULL; } clear_sprite_map((f)); }}
    CALL(BOX_FONT, 0, false); CALL(fonts.medium_font_idx, 0, false);
    CALL(fonts.bold_font_idx, 0, false); CALL(fonts.italic_font_idx, 0, false); CALL(fonts.bi_font_idx, 0, false);
    cell_metrics(fonts.fonts[fonts.medium_font_idx].face, &cell_width, &cell_height, &baseline, &underline_position, &underline_thickness);
    if (!cell_width) { PyErr_SetString(PyExc_ValueError, "Failed to calculate cell width for the specified font."); return NULL; }
    unsigned int before_cell_height = cell_height;
    if (OPT(adjust_line_height_px) != 0) cell_height += OPT(adjust_line_height_px);
    if (OPT(adjust_line_height_frac) != 0.f) cell_height *= OPT(adjust_line_height_frac);
    if (OPT(adjust_column_width_px != 0)) cell_width += OPT(adjust_column_width_px);
    if (OPT(adjust_column_width_frac) != 0.f) cell_height *= OPT(adjust_column_width_frac);
    int line_height_adjustment = cell_height - before_cell_height;
    if (cell_height < 4) { PyErr_SetString(PyExc_ValueError, "line height too small after adjustment"); return NULL; }
    if (cell_height > 1000) { PyErr_SetString(PyExc_ValueError, "line height too large after adjustment"); return NULL; }
    underline_position = MIN(cell_height - 1, underline_position);
    // ensure there is at least a couple of pixels available to render styled underlines
    while (underline_position > baseline + 1 && cell_height - underline_position < 2) underline_position--;
    if (line_height_adjustment > 1) {
        baseline += MIN(cell_height - 1, (unsigned)line_height_adjustment / 2);
        underline_position += MIN(cell_height - 1, (unsigned)line_height_adjustment / 2);
    }
    sprite_tracker_set_layout(cell_width, cell_height);
    global_state.cell_width = cell_width; global_state.cell_height = cell_height;
    free(canvas); canvas = malloc(CELLS_IN_CANVAS * cell_width * cell_height * sizeof(pixel));
    if (canvas == NULL) return PyErr_NoMemory();
    for (ssize_t i = 0, j = fonts.first_symbol_font_idx; i < (ssize_t)fonts.symbol_map_fonts_count; i++, j++)  {
        CALL(j, cell_height, true);
    }
    for (ssize_t i = 0, j = fonts.first_fallback_font_idx; i < (ssize_t)fonts.fallback_fonts_count; i++, j++)  {
        CALL(j, cell_height, true);
    }
    return Py_BuildValue("IIIII", cell_width, cell_height, baseline, underline_position, underline_thickness);
#undef CALL
}

static PyObject*
set_font_size(PyObject UNUSED *m, PyObject *args) {
    int on_dpi_change = 0;
    if (!PyArg_ParseTuple(args, "f|p", &global_state.font_sz_in_pts, &on_dpi_change)) return NULL;
    return update_cell_metrics(on_dpi_change != 0);
}

static inline bool
face_has_codepoint(PyObject* face, char_type cp) {
    return glyph_id_for_codepoint(face, cp) > 0;
}

static inline bool
has_emoji_presentation(Cell *cell) {
    return (cell->attrs & WIDTH_MASK) == 2 && is_emoji(cell->ch) && cell->cc_idx[0] != VS15;
}

static inline bool
has_cell_text(Font *self, Cell *cell) {
    if (!face_has_codepoint(self->face, cell->ch)) return false;
    for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) {
        combining_type cc_idx = cell->cc_idx[i];
        if (cc_idx == VS15 || cc_idx == VS16) continue;
        if (!face_has_codepoint(self->face, codepoint_for_mark(cc_idx))) return false;
    }
    return true;
}

static inline void
output_cell_fallback_data(Cell *cell, bool bold, bool italic, bool emoji_presentation, PyObject *face, bool new_face) {
    printf("U+%x ", cell->ch);
    for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) {
        printf("U+%x ", codepoint_for_mark(cell->cc_idx[i]));
    }
    if (bold) printf("bold ");
    if (italic) printf("italic ");
    if (emoji_presentation) printf("emoji_presentation ");
    PyObject_Print(face, stdout, 0);
    if (new_face) printf(" (new face)");
    printf("\n");
}

static inline ssize_t
load_fallback_font(Cell *cell, bool bold, bool italic, bool emoji_presentation) {
    if (fonts.fallback_fonts_count > 100) { log_error("Too many fallback fonts"); return MISSING_FONT; }
    ssize_t f;

    if (bold) f = fonts.italic_font_idx > 0 ? fonts.bi_font_idx : fonts.bold_font_idx;
    else f = italic ? fonts.italic_font_idx : fonts.medium_font_idx;
    if (f < 0) f = fonts.medium_font_idx;

    PyObject *face = create_fallback_face(fonts.fonts[f].face, cell, bold, italic, emoji_presentation);
    if (face == NULL) { PyErr_Print(); return MISSING_FONT; }
    if (face == Py_None) { Py_DECREF(face); return MISSING_FONT; }
    if (global_state.debug_font_fallback) output_cell_fallback_data(cell, bold, italic, emoji_presentation, face, true);
    set_size_for_face(face, cell_height, true);

    ensure_space_for(&fonts, fonts, Font, fonts.fonts_count + 1, fonts_capacity, 5, true);
    ssize_t ans = fonts.first_fallback_font_idx + fonts.fallback_fonts_count;
    Font *af = &fonts.fonts[ans];
    if (!init_font(af, face, bold, italic, true, emoji_presentation)) fatal("Out of memory");
    Py_DECREF(face);
    fonts.fallback_fonts_count++;
    fonts.fonts_count++;
    return ans;
}

static inline ssize_t
fallback_font(Cell *cell) {
    bool bold = (cell->attrs >> BOLD_SHIFT) & 1;
    bool italic = (cell->attrs >> ITALIC_SHIFT) & 1;
    bool emoji_presentation = has_emoji_presentation(cell);

    // Check if one of the existing fallback fonts has this text
    for (size_t i = 0, j = fonts.first_fallback_font_idx; i < fonts.fallback_fonts_count; i++, j++)  {
        Font *ff = fonts.fonts +j;
        if (ff->bold == bold && ff->italic == italic && ff->emoji_presentation == emoji_presentation && has_cell_text(ff, cell)) {
            if (global_state.debug_font_fallback) output_cell_fallback_data(cell, bold, italic, emoji_presentation, ff->face, false);
            return j;
        }
    }

    return load_fallback_font(cell, bold, italic, emoji_presentation);
}

static inline ssize_t
in_symbol_maps(char_type ch) {
    for (size_t i = 0; i < fonts.symbol_maps_count; i++) {
        if (fonts.symbol_maps[i].left <= ch && ch <= fonts.symbol_maps[i].right) return fonts.first_symbol_font_idx + fonts.symbol_maps[i].font_idx;
    }
    return NO_FONT;
}


static ssize_t
font_for_cell(Cell *cell) {
START_ALLOW_CASE_RANGE
    ssize_t ans;
    switch(cell->ch) {
        case 0:
        case ' ':
            return BLANK_FONT;
        case 0x2500 ... 0x2570:
        case 0x2574 ... 0x259f:
        case 0xe0b0:
        case 0xe0b2:
        case 0xe0b4:
        case 0xe0b6:
            return BOX_FONT;
        default:
            ans = in_symbol_maps(cell->ch);
            if (ans > -1) return ans;
            switch(BI_VAL(cell->attrs)) {
                case 0:
                    ans = fonts.medium_font_idx; break;
                case 1:
                    ans = fonts.bold_font_idx ; break;
                case 2:
                    ans = fonts.italic_font_idx; break;
                case 3:
                    ans = fonts.bi_font_idx; break;
            }
            if (ans < 0) ans = fonts.medium_font_idx;
            if (!has_emoji_presentation(cell) && has_cell_text(fonts.fonts + ans, cell)) return ans;
            return fallback_font(cell);
    }
END_ALLOW_CASE_RANGE
}

static inline void
set_sprite(Cell *cell, sprite_index x, sprite_index y, sprite_index z) {
    cell->sprite_x = x; cell->sprite_y = y; cell->sprite_z = z;
}

static inline glyph_index
box_glyph_id(char_type ch) {
START_ALLOW_CASE_RANGE
    switch(ch) {
        case 0x2500 ... 0x259f:
            return ch - 0x2500;
        case 0xe0b0:
            return 0xfa;
        case 0xe0b2:
            return 0xfb;
        case 0xe0b4:
            return 0xfc;
        case 0xe0b6:
            return 0xfd;
        default:
            return 0xff;
    }
END_ALLOW_CASE_RANGE
}

static PyObject* box_drawing_function = NULL;

void
render_alpha_mask(uint8_t *alpha_mask, pixel* dest, Region *src_rect, Region *dest_rect, size_t src_stride, size_t dest_stride) {
    for (size_t sr = src_rect->top, dr = dest_rect->top; sr < src_rect->bottom && dr < dest_rect->bottom; sr++, dr++) {
        pixel *d = dest + dest_stride * dr;
        uint8_t *s = alpha_mask + src_stride * sr;
        for(size_t sc = src_rect->left, dc = dest_rect->left; sc < src_rect->right && dc < dest_rect->right; sc++, dc++) {
            pixel val = d[dc];
            uint8_t alpha = s[sc];
            d[dc] = 0xffffff00 | MIN(0xff, alpha + (val & 0xff));
        }
    }
}

static void
render_box_cell(Cell *cell) {
    int error = 0;
    glyph_index glyph = box_glyph_id(cell->ch);
    static ExtraGlyphs extra_glyphs = {{0}};
    SpritePosition *sp = sprite_position_for(&fonts.fonts[BOX_FONT], glyph, &extra_glyphs, false, &error);
    if (sp == NULL) {
        sprite_map_set_error(error); PyErr_Print();
        set_sprite(cell, 0, 0, 0);
        return;
    }
    set_sprite(cell, sp->x, sp->y, sp->z);
    if (sp->rendered) return;
    sp->rendered = true;
    sp->colored = false;
    PyObject *ret = PyObject_CallFunction(box_drawing_function, "I", cell->ch);
    if (ret == NULL) { PyErr_Print(); return; }
    uint8_t *alpha_mask = PyLong_AsVoidPtr(PyTuple_GET_ITEM(ret, 0));
    clear_canvas();
    Region r = { .right = cell_width, .bottom = cell_height };
    render_alpha_mask(alpha_mask, canvas, &r, &r, cell_width, cell_width);
    current_send_sprite_to_gpu(sp->x, sp->y, sp->z, canvas);
    Py_DECREF(ret);
}

static inline void
load_hb_buffer(Cell *first_cell, index_type num_cells) {
    index_type num;
    hb_buffer_clear_contents(harfbuzz_buffer);
    while (num_cells) {
        attrs_type prev_width = 0;
        for (num = 0; num_cells && num < arraysz(shape_buffer) - 20 - arraysz(first_cell->cc_idx); first_cell++, num_cells--) {
            if (prev_width == 2) { prev_width = 0; continue; }
            shape_buffer[num++] = first_cell->ch;
            prev_width = first_cell->attrs & WIDTH_MASK;
            for (unsigned i = 0; i < arraysz(first_cell->cc_idx) && first_cell->cc_idx[i]; i++) {
                shape_buffer[num++] = codepoint_for_mark(first_cell->cc_idx[i]);
            }
        }
        hb_buffer_add_utf32(harfbuzz_buffer, shape_buffer, num, 0, num);
    }
    hb_buffer_guess_segment_properties(harfbuzz_buffer);
}


static inline void
set_cell_sprite(Cell *cell, SpritePosition *sp) {
    cell->sprite_x = sp->x; cell->sprite_y = sp->y; cell->sprite_z = sp->z;
    if (sp->colored) cell->sprite_z |= 0x4000;
}

static inline pixel*
extract_cell_from_canvas(unsigned int i, unsigned int num_cells) {
    pixel *ans = canvas + (cell_width * cell_height * (CELLS_IN_CANVAS - 1)), *dest = ans, *src = canvas + (i * cell_width);
    unsigned int stride = cell_width * num_cells;
    for (unsigned int r = 0; r < cell_height; r++, dest += cell_width, src += stride) memcpy(dest, src, cell_width * sizeof(pixel));
    return ans;
}

static inline void
render_group(unsigned int num_cells, unsigned int num_glyphs, Cell *cells, hb_glyph_info_t *info, hb_glyph_position_t *positions, Font *font, glyph_index glyph, ExtraGlyphs *extra_glyphs) {
    static SpritePosition* sprite_position[16];
    int error = 0;
    num_cells = MIN(sizeof(sprite_position)/sizeof(sprite_position[0]), num_cells);
    for (unsigned int i = 0; i < num_cells; i++) {
        sprite_position[i] = sprite_position_for(font, glyph, extra_glyphs, (uint8_t)i, &error);
        if (error != 0) { sprite_map_set_error(error); PyErr_Print(); return; }
    }
    if (sprite_position[0]->rendered) {
        for (unsigned int i = 0; i < num_cells; i++) { set_cell_sprite(cells + i, sprite_position[i]); }
        return;
    }

    clear_canvas();
    bool was_colored = (cells->attrs & WIDTH_MASK) == 2 && is_emoji(cells->ch);
    render_glyphs_in_cells(font->face, font->bold, font->italic, info, positions, num_glyphs, canvas, cell_width, cell_height, num_cells, baseline, &was_colored);
    if (PyErr_Occurred()) PyErr_Print();

    for (unsigned int i = 0; i < num_cells; i++) {
        sprite_position[i]->rendered = true;
        sprite_position[i]->colored = was_colored;
        set_cell_sprite(cells + i, sprite_position[i]);
        pixel *buf = num_cells == 1 ? canvas : extract_cell_from_canvas(i, num_cells);
        current_send_sprite_to_gpu(sprite_position[i]->x, sprite_position[i]->y, sprite_position[i]->z, buf);
    }

}

typedef struct {
    Cell *cell;
    unsigned int num_codepoints;
    unsigned int codepoints_consumed;
    char_type current_codepoint;
} CellData;

typedef struct {
    unsigned int first_glyph_idx, first_cell_idx, num_glyphs, num_cells;
} Group;

typedef struct {
    uint32_t previous_cluster;
    bool prev_was_special, prev_was_empty;
    CellData current_cell_data;
    Group *groups;
    size_t groups_capacity, group_idx, glyph_idx, cell_idx, num_cells, num_glyphs;
    Cell *first_cell, *last_cell;
    hb_glyph_info_t *info;
    hb_glyph_position_t *positions;
} GroupState;

static GroupState group_state = {0};

static inline unsigned int
num_codepoints_in_cell(Cell *cell) {
    unsigned int ans = 1;
    for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) ans++;
    return ans;
}

static inline void
shape(Cell *first_cell, index_type num_cells, hb_font_t *font) {
    if (group_state.groups_capacity <= 2 * num_cells) {
        group_state.groups_capacity = MAX(128, 2 * num_cells);  // avoid unnecessary reallocs
        group_state.groups = realloc(group_state.groups, sizeof(Group) * group_state.groups_capacity);
        if (!group_state.groups) fatal("Out of memory");
    }
    group_state.previous_cluster = UINT32_MAX;
    group_state.prev_was_special = false;
    group_state.prev_was_empty = false;
    group_state.current_cell_data.cell = first_cell; group_state.current_cell_data.num_codepoints = num_codepoints_in_cell(first_cell); group_state.current_cell_data.codepoints_consumed = 0; group_state.current_cell_data.current_codepoint = first_cell->ch;
    memset(group_state.groups, 0, sizeof(Group) * group_state.groups_capacity);
    group_state.group_idx = 0;
    group_state.glyph_idx = 0;
    group_state.cell_idx = 0;
    group_state.num_cells = num_cells;
    group_state.first_cell = first_cell;
    group_state.last_cell = first_cell + (num_cells ? num_cells - 1 : 0);
    load_hb_buffer(first_cell, num_cells);
    hb_shape(font, harfbuzz_buffer, NULL, 0);
    unsigned int info_length, positions_length;
    group_state.info = hb_buffer_get_glyph_infos(harfbuzz_buffer, &info_length);
    group_state.positions = hb_buffer_get_glyph_positions(harfbuzz_buffer, &positions_length);
    if (!group_state.info || !group_state.positions) group_state.num_glyphs = 0;
    else group_state.num_glyphs = MIN(info_length, positions_length);
}

static inline bool
is_special_glyph(glyph_index glyph_id, Font *font, CellData* cell_data) {
    // A glyph is special if the codepoint it corresponds to matches a
    // different glyph in the font
    SpecialGlyphCache *s = special_glyph_cache_for(font, glyph_id, SPECIAL_FILLED_MASK);
    if (s == NULL) return false;
    if (!(s->data & SPECIAL_FILLED_MASK)) {
        bool is_special = cell_data->current_codepoint ? (
            glyph_id != glyph_id_for_codepoint(font->face, cell_data->current_codepoint) ? true : false)
            :
            false;
        uint8_t val = is_special ? SPECIAL_VALUE_MASK : 0;
        s->data |= val | SPECIAL_FILLED_MASK;
    }
    return s->data & SPECIAL_VALUE_MASK;
}

static inline bool
is_empty_glyph(glyph_index glyph_id, Font *font) {
    // A glyph is empty if its metrics have a width of zero
    SpecialGlyphCache *s = special_glyph_cache_for(font, glyph_id, EMPTY_FILLED_MASK);
    if (s == NULL) return false;
    if (!(s->data & EMPTY_FILLED_MASK)) {
        uint8_t val = is_glyph_empty(font->face, glyph_id) ? EMPTY_VALUE_MASK : 0;
        s->data |= val | EMPTY_FILLED_MASK;
    }
    return s->data & EMPTY_VALUE_MASK;
}

static inline unsigned int
check_cell_consumed(CellData *cell_data, Cell *last_cell) {
    cell_data->codepoints_consumed++;
    if (cell_data->codepoints_consumed >= cell_data->num_codepoints) {
        attrs_type width = cell_data->cell->attrs & WIDTH_MASK;
        cell_data->cell += MAX(1, width);
        cell_data->codepoints_consumed = 0;
        if (cell_data->cell <= last_cell) {
            cell_data->num_codepoints = num_codepoints_in_cell(cell_data->cell);
            cell_data->current_codepoint = cell_data->cell->ch;
        } else cell_data->current_codepoint = 0;
        return width;
    } else {
        switch(cell_data->codepoints_consumed) {
            case 0:
                cell_data->current_codepoint = cell_data->cell->ch;
                break;
            default:
                cell_data->current_codepoint = codepoint_for_mark(cell_data->cell->cc_idx[cell_data->codepoints_consumed - 1]);
                break;
        }
    }
    return 0;
}


static inline void
shape_run(Cell *first_cell, index_type num_cells, Font *font) {
    shape(first_cell, num_cells, harfbuzz_font_for_face(font->face));
#if 0
        // You can also generate this easily using hb-shape --show-extents --cluster-level=1 --shapers=ot /path/to/font/file text
        hb_buffer_serialize_glyphs(harfbuzz_buffer, 0, group_state.num_glyphs, (char*)canvas, sizeof(pixel) * CELLS_IN_CANVAS * cell_width * cell_height, NULL, harfbuzz_font_for_face(font->face), HB_BUFFER_SERIALIZE_FORMAT_TEXT, HB_BUFFER_SERIALIZE_FLAG_DEFAULT | HB_BUFFER_SERIALIZE_FLAG_GLYPH_EXTENTS);
        printf("\n%s\n", (char*)canvas);
        clear_canvas();
#endif
    /* Now distribute the glyphs into groups of cells
     * Considerations to keep in mind:
     * Group sizes should be as small as possible for best performance
     * Combining chars can result in multiple glyphs rendered into a single cell
     * Emoji and East Asian wide chars can cause a single glyph to be rendered over multiple cells
     * Ligature fonts, take two common approaches:
     * 1. ABC becomes EMPTY, EMPTY, WIDE GLYPH this means we have to render N glyphs in N cells (example Fira Code)
     * 2. ABC becomes WIDE GLYPH this means we have to render one glyph in N cells (example Operator Mono Lig)
     *
     * We rely on the cluster numbers from harfbuzz to tell us how many unicode codepoints a glyph corresponds to.
     * Then we check if the glyph is a ligature glyph (is_special_glyph) and if it is an empty glyph. These three
     * datapoints give us enough information to satisfy the constraint above, for a wide variety of fonts.
     */
    uint32_t cluster, next_cluster;
    bool add_to_current_group;
#define G(x) (group_state.x)
#define MAX_GLYPHS_IN_GROUP (MAX_NUM_EXTRA_GLYPHS + 1)
    while (G(glyph_idx) < G(num_glyphs) && G(cell_idx) < G(num_cells)) {
        glyph_index glyph_id = G(info)[G(glyph_idx)].codepoint;
        cluster = G(info)[G(glyph_idx)].cluster;
        bool is_special = is_special_glyph(glyph_id, font, &G(current_cell_data));
        bool is_empty = is_special && is_empty_glyph(glyph_id, font);
        uint32_t num_codepoints_used_by_glyph = 0;
        bool is_last_glyph = G(glyph_idx) == G(num_glyphs) - 1;
        Group *current_group = G(groups) + G(group_idx);
        if (is_last_glyph) {
            num_codepoints_used_by_glyph = UINT32_MAX;
        } else {
            next_cluster = G(info)[G(glyph_idx) + 1].cluster;
            // RTL languages like Arabic have decreasing cluster numbers
            if (next_cluster != cluster) num_codepoints_used_by_glyph = cluster > next_cluster ? cluster - next_cluster : next_cluster - cluster;
        }
        if (!current_group->num_glyphs) {
            add_to_current_group = true;
        } else {
            if (is_special) {
                add_to_current_group = G(prev_was_empty);
            } else {
                add_to_current_group = !G(prev_was_special);
            }
        }
        if (current_group->num_glyphs >= MAX_GLYPHS_IN_GROUP || current_group->num_cells >= MAX_GLYPHS_IN_GROUP) add_to_current_group = false;

        if (!add_to_current_group) { G(group_idx)++; current_group = G(groups) + G(group_idx); }
        if (!current_group->num_glyphs++) {
            current_group->first_glyph_idx = G(glyph_idx);
            current_group->first_cell_idx = G(cell_idx);
        }
#define MOVE_GLYPH_TO_NEXT_GROUP(start_cell_idx) { \
    current_group->num_glyphs--; \
    G(group_idx)++; current_group = G(groups) + G(group_idx); \
    current_group->first_cell_idx = start_cell_idx; \
    current_group->num_glyphs = 1; \
    current_group->first_glyph_idx = G(glyph_idx); \
}
        if (is_last_glyph) {
            // soak up all remaining cells
            if (G(cell_idx) < G(num_cells)) {
                unsigned int num_left = G(num_cells) - G(cell_idx);
                if (current_group->num_cells + num_left > MAX_GLYPHS_IN_GROUP) MOVE_GLYPH_TO_NEXT_GROUP(G(cell_idx));
                current_group->num_cells += num_left;
                if (current_group->num_cells > MAX_GLYPHS_IN_GROUP) current_group->num_cells = MAX_GLYPHS_IN_GROUP;  // leave any trailing cells empty
                G(cell_idx) += num_left;
            }
        } else {
            unsigned int num_cells_consumed = 0, start_cell_idx = G(cell_idx);
            while (num_codepoints_used_by_glyph && G(cell_idx) < G(num_cells)) {
                unsigned int w = check_cell_consumed(&G(current_cell_data), G(last_cell));
                G(cell_idx) += w;
                num_cells_consumed += w;
                num_codepoints_used_by_glyph--;
            }
            if (num_cells_consumed) {
                if (num_cells_consumed > MAX_GLYPHS_IN_GROUP) {
                    // Nasty, a single glyph used more than MAX_GLYPHS_IN_GROUP cells, we cannot render this case correctly
                    log_error("The glyph: %u needs more than %u cells, cannot render it", glyph_id, MAX_GLYPHS_IN_GROUP);
                    current_group->num_glyphs--;
                    while (num_cells_consumed) {
                        G(group_idx)++; current_group = G(groups) + G(group_idx);
                        current_group->num_glyphs = 1; current_group->first_glyph_idx = G(glyph_idx);
                        current_group->num_cells = MIN(num_cells_consumed, MAX_GLYPHS_IN_GROUP);
                        current_group->first_cell_idx = start_cell_idx;
                        start_cell_idx += current_group->num_cells;
                        num_cells_consumed -= current_group->num_cells;
                    }
                } else {
                    if (num_cells_consumed + current_group->num_cells > MAX_GLYPHS_IN_GROUP) MOVE_GLYPH_TO_NEXT_GROUP(start_cell_idx);
                    current_group->num_cells += num_cells_consumed;
                    if (!is_special) {  // not a ligature, end the group
                        G(group_idx)++; current_group = G(groups) + G(group_idx);
                    }
                }
            }
        }

        G(prev_was_special) = is_special;
        G(prev_was_empty) = is_empty;
        G(previous_cluster) = cluster;
        G(glyph_idx)++;
    }
#undef MOVE_GLYPH_TO_NEXT_GROUP
#undef MAX_GLYPHS_IN_GROUP
}

static inline void
merge_groups_for_pua_space_ligature() {
    if (G(group_idx) == 1) {
        Group *g = G(groups), *g1 = G(groups) + 1;
        g->num_cells += g1->num_cells;
        g->num_glyphs += g1->num_glyphs;
        g->num_glyphs = MIN(g->num_glyphs, MAX_NUM_EXTRA_GLYPHS + 1);
        G(group_idx) = 0;
    }
}

static inline void
render_groups(Font *font) {
    unsigned idx = 0;
    ExtraGlyphs ed;
    while (idx <= G(group_idx)) {
        Group *group = G(groups) + idx;
        if (!group->num_cells) break;
        /* printf("Group: idx: %u num_cells: %u num_glyphs: %u first_glyph_idx: %u first_cell_idx: %u total_num_glyphs: %zu\n", */
        /*         idx, group->num_cells, group->num_glyphs, group->first_glyph_idx, group->first_cell_idx, group_state.num_glyphs); */
        glyph_index primary = group->num_glyphs ? G(info)[group->first_glyph_idx].codepoint : 0;
        unsigned int i;
        int last = -1;
        for (i = 1; i < MIN(arraysz(ed.data) + 1, group->num_glyphs); i++) { last = i - 1; ed.data[last] = G(info)[group->first_glyph_idx + i].codepoint; }
        if ((size_t)(last + 1) < arraysz(ed.data)) ed.data[last + 1] = 0;
        render_group(group->num_cells, group->num_glyphs, G(first_cell) + group->first_cell_idx, G(info) + group->first_glyph_idx, G(positions) + group->first_glyph_idx, font, primary, &ed);
        idx++;
    }
}

static PyObject*
test_shape(PyObject UNUSED *self, PyObject *args) {
    Line *line;
    char *path = NULL;
    int index = 0;
    if(!PyArg_ParseTuple(args, "O!|zi", &Line_Type, &line, &path, &index)) return NULL;
    index_type num = 0;
    while(num < line->xnum && line->cells[num].ch) num += line->cells[num].attrs & WIDTH_MASK;
    PyObject *face = NULL;
    Font *font = fonts.fonts + fonts.medium_font_idx;
    if (path) {
        face = face_from_path(path, index);
        if (face == NULL) return NULL;
        font = calloc(1, sizeof(Font));
        font->face = face;
    }
    shape_run(line->cells, num, font);

    PyObject *ans = PyList_New(0);
    unsigned int idx = 0;
    glyph_index first_glyph;
    while (idx <= G(group_idx)) {
        Group *group = G(groups) + idx;
        if (!group->num_cells) break;
        first_glyph = group->num_glyphs ? G(info)[group->first_glyph_idx].codepoint : 0;

        PyObject *eg = PyTuple_New(MAX_NUM_EXTRA_GLYPHS);
        for (size_t g = 0; g < MAX_NUM_EXTRA_GLYPHS; g++) PyTuple_SET_ITEM(eg, g, Py_BuildValue("H", g + 1 < group->num_glyphs ? G(info)[group->first_glyph_idx + g].codepoint : 0));
        PyList_Append(ans, Py_BuildValue("IIHN", group->num_cells, group->num_glyphs, first_glyph, eg));
        idx++;
    }
    if (face) { Py_CLEAR(face); free(font); }
    return ans;
}
#undef G

static inline void
render_run(Cell *first_cell, index_type num_cells, ssize_t font_idx, bool pua_space_ligature) {
    switch(font_idx) {
        default:
            shape_run(first_cell, num_cells, &fonts.fonts[font_idx]);
            if (pua_space_ligature) merge_groups_for_pua_space_ligature();
            render_groups(&fonts.fonts[font_idx]);
            break;
        case BLANK_FONT:
            while(num_cells--) set_sprite(first_cell++, 0, 0, 0);
            break;
        case BOX_FONT:
            while(num_cells--) render_box_cell(first_cell++);
            break;
        case MISSING_FONT:
            while(num_cells--) set_sprite(first_cell++, MISSING_GLYPH, 0, 0);
            break;
    }
}

static inline bool
is_private_use(char_type ch) {
    return (0xe000 <= ch && ch <= 0xf8ff) || (0xF0000 <= ch && ch <= 0xFFFFF) || (0x100000 <= ch && ch <= 0x10FFFF);
}

void
render_line(Line *line) {
#define RENDER if (run_font_idx != NO_FONT && i > first_cell_in_run) render_run(line->cells + first_cell_in_run, i - first_cell_in_run, run_font_idx, false);
    ssize_t run_font_idx = NO_FONT;
    index_type first_cell_in_run, i;
    attrs_type prev_width = 0;
    for (i=0, first_cell_in_run=0; i < line->xnum; i++) {
        if (prev_width == 2) { prev_width = 0; continue; }
        Cell *cell = line->cells + i;
        ssize_t cell_font_idx = font_for_cell(cell);
        if (is_private_use(cell->ch) && i + 1 < line->xnum && (line->cells[i+1].ch == ' ' || line->cells[i+1].ch == 0) && cell_font_idx != BOX_FONT && cell_font_idx != MISSING_FONT) {
            // We have a private use char followed by a space char, render it as a two cell ligature.
            Cell *space_cell = line->cells + i+1;
            // Ensure the space cell uses the foreground colors from the PUA cell
            // This is needed because there are stupid applications like
            // powerline that use PUA+space with different foreground colors
            // for the space and the PUA. See for example: https://github.com/kovidgoyal/kitty/issues/467
            space_cell->fg = cell->fg; space_cell->decoration_fg = cell->decoration_fg;
            RENDER;
            render_run(line->cells + i, 2, cell_font_idx, true);
            run_font_idx = NO_FONT;
            first_cell_in_run = i + 2;
            prev_width = line->cells[i+1].attrs & WIDTH_MASK;
            i++;
            continue;
        }
        prev_width = cell->attrs & WIDTH_MASK;
        if (run_font_idx == NO_FONT) run_font_idx = cell_font_idx;
        if (run_font_idx == cell_font_idx) continue;
        RENDER;
        run_font_idx = cell_font_idx;
        first_cell_in_run = i;
    }
    RENDER;
#undef RENDER
}

static PyObject*
set_font(PyObject UNUSED *m, PyObject *args) {
    PyObject *sm, *smf, *medium, *bold = NULL, *italic = NULL, *bi = NULL;
    Py_CLEAR(box_drawing_function);
    if (!PyArg_ParseTuple(args, "OO!O!fO|OOO", &box_drawing_function, &PyTuple_Type, &sm, &PyTuple_Type, &smf, &global_state.font_sz_in_pts, &medium, &bold, &italic, &bi)) return NULL;
    Py_INCREF(box_drawing_function);
    fonts.symbol_map_fonts_count = PyTuple_GET_SIZE(smf);
    size_t num_fonts = 5 + fonts.symbol_map_fonts_count;
    for (size_t i = 0; i < fonts.fonts_count; i++) del_font(fonts.fonts + i);
    ensure_space_for(&fonts, fonts, Font, num_fonts, fonts_capacity, 5, true);
    fonts.fonts_count = 1;
#define A(attr, bold, italic) { if(attr) { if (!init_font(&fonts.fonts[fonts.fonts_count], attr, bold, italic, false, false)) return NULL; fonts.attr##_font_idx = fonts.fonts_count++; } else fonts.attr##_font_idx = -1; }
    A(medium, false, false);
    A(bold, true, false); A(italic, false, true); A(bi, true, true);
#undef A

    fonts.first_symbol_font_idx = fonts.fonts_count;
    fonts.symbol_maps_count = PyTuple_GET_SIZE(sm);
    ensure_space_for(&fonts, symbol_maps, SymbolMap, fonts.symbol_maps_count, symbol_maps_capacity, 5, true);
    for (size_t i = 0; i < fonts.symbol_map_fonts_count; i++) {
        PyObject *face;
        int bold, italic;
        if (!PyArg_ParseTuple(PyTuple_GET_ITEM(smf, i), "Opp", &face, &bold, &italic)) return NULL;
        if (!init_font(fonts.fonts + fonts.fonts_count++, face, bold != 0, italic != 0, false, false)) return NULL;
    }
    for (size_t i = 0; i < fonts.symbol_maps_count; i++) {
        unsigned int left, right, font_idx;
        if (!PyArg_ParseTuple(PyTuple_GET_ITEM(sm, i), "III", &left, &right, &font_idx)) return NULL;
        fonts.symbol_maps[i].left = left; fonts.symbol_maps[i].right = right; fonts.symbol_maps[i].font_idx = font_idx;
    }
    fonts.first_fallback_font_idx = fonts.fonts_count;
    fonts.fallback_fonts_count = 0;
    return update_cell_metrics(false);
}

static void
finalize(void) {
    Py_CLEAR(python_send_to_gpu_impl);
    free(canvas);
    Py_CLEAR(box_drawing_function);
    for (size_t i = 0; i < fonts.fonts_count; i++) del_font(fonts.fonts + i);
    free(fonts.symbol_maps); free(fonts.fonts);
    if (harfbuzz_buffer) hb_buffer_destroy(harfbuzz_buffer);
    free(group_state.groups);
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
    ExtraGlyphs extra_glyphs = {{0}};
    if (!PyArg_ParseTuple(args, "H|H", &glyph, &extra_glyphs.data)) return NULL;
    int error;
    SpritePosition *pos = sprite_position_for(&fonts.fonts[fonts.medium_font_idx], glyph, &extra_glyphs, 0, &error);
    if (pos == NULL) { sprite_map_set_error(error); return NULL; }
    return Py_BuildValue("HHH", pos->x, pos->y, pos->z);
}

static PyObject*
send_prerendered_sprites(PyObject UNUSED *s, PyObject *args) {
    int error = 0;
    sprite_index x = 0, y = 0, z = 0;
    // blank cell
    clear_canvas();
    current_send_sprite_to_gpu(x, y, z, canvas);
    do_increment(&error);
    if (error != 0) { sprite_map_set_error(error); return NULL; }
    for (ssize_t i = 0; i < PyTuple_GET_SIZE(args); i++) {
        x = sprite_tracker.x; y = sprite_tracker.y; z = sprite_tracker.z;
        do_increment(&error);
        if (error != 0) { sprite_map_set_error(error); return NULL; }
        uint8_t *alpha_mask = PyLong_AsVoidPtr(PyTuple_GET_ITEM(args, i));
        clear_canvas();
        Region r = { .right = cell_width, .bottom = cell_height };
        render_alpha_mask(alpha_mask, canvas, &r, &r, cell_width, cell_width);
        current_send_sprite_to_gpu(x, y, z, canvas);
    }
    return Py_BuildValue("H", x);
}

static PyObject*
set_send_sprite_to_gpu(PyObject UNUSED *self, PyObject *func) {
    Py_CLEAR(python_send_to_gpu_impl);
    python_send_to_gpu_impl = func;
    Py_INCREF(func);
    current_send_sprite_to_gpu = func == Py_None ? send_sprite_to_gpu : python_send_to_gpu;
    Py_RETURN_NONE;
}

static PyObject*
test_render_line(PyObject UNUSED *self, PyObject *args) {
    PyObject *line;
    if (!PyArg_ParseTuple(args, "O!", &Line_Type, &line)) return NULL;
    render_line((Line*)line);
    Py_RETURN_NONE;
}

static PyObject*
concat_cells(PyObject UNUSED *self, PyObject *args) {
    // Concatenate cells returning RGBA data
    unsigned int cell_width, cell_height;
    int is_32_bit;
    PyObject *cells;
    if (!PyArg_ParseTuple(args, "IIpO!", &cell_width, &cell_height, &is_32_bit, &PyTuple_Type, &cells)) return NULL;
    size_t num_cells = PyTuple_GET_SIZE(cells), r, c, i;
    PyObject *ans = PyBytes_FromStringAndSize(NULL, 4 * cell_width * cell_height * num_cells);
    if (ans == NULL) return PyErr_NoMemory();
    pixel *dest = (pixel*)PyBytes_AS_STRING(ans);
    for (r = 0; r < cell_height; r++) {
        for (c = 0; c < num_cells; c++) {
            void *s = ((uint8_t*)PyBytes_AS_STRING(PyTuple_GET_ITEM(cells, c)));
            if (is_32_bit) {
                pixel *src = (pixel*)s + cell_width * r;
                for (i = 0; i < cell_width; i++, dest++) {
                    uint8_t *rgba = (uint8_t*)dest;
                    rgba[0] = (src[i] >> 24) & 0xff;
                    rgba[1] = (src[i] >> 16) & 0xff;
                    rgba[2] = (src[i] >> 8) & 0xff;
                    rgba[3] = src[i] & 0xff;
                }
            } else {
                uint8_t *src = (uint8_t*)s + cell_width * r;
                for (i = 0; i < cell_width; i++, dest++) {
                    uint8_t *rgba = (uint8_t*)dest;
                    if (src[i]) { memset(rgba, 0xff, 3); rgba[3] = src[i]; }
                    else *dest = 0;
                }
            }

        }
    }
    return ans;
}

static PyObject*
current_fonts(PYNOARG) {
    PyObject *ans = PyDict_New();
    if (!ans) return NULL;
#define SET(key, val) {if (PyDict_SetItemString(ans, #key, fonts.fonts[val].face) != 0) { goto error; }}
    SET(medium, fonts.medium_font_idx);
    if (fonts.bold_font_idx) SET(bold, fonts.bold_font_idx);
    if (fonts.italic_font_idx) SET(italic, fonts.italic_font_idx);
    if (fonts.bi_font_idx) SET(bi, fonts.bi_font_idx);
    PyObject *ff = PyTuple_New(fonts.fallback_fonts_count);
    if (!ff) goto error;
    for (size_t i = 0; i < fonts.fallback_fonts_count; i++) {
        Py_INCREF(fonts.fonts[fonts.first_fallback_font_idx + i].face);
        PyTuple_SET_ITEM(ff, i, fonts.fonts[fonts.first_fallback_font_idx + i].face);
    }
    PyDict_SetItemString(ans, "fallback", ff);
    Py_CLEAR(ff);
    return ans;
error:
    Py_CLEAR(ans); return NULL;
#undef SET
}

static PyObject*
get_fallback_font(PyObject UNUSED *self, PyObject *args) {
    PyObject *text;
    int bold, italic;
    if (!PyArg_ParseTuple(args, "Upp", &text, &bold, &italic)) return NULL;
    Cell cell = {0};
    static Py_UCS4 char_buf[2 + arraysz(cell.cc_idx)];
    if (!PyUnicode_AsUCS4(text, char_buf, arraysz(char_buf), 1)) return NULL;
    cell.ch = char_buf[0];
    for (unsigned i = 0; i + 1 < (unsigned) PyUnicode_GetLength(text) && i < arraysz(cell.cc_idx); i++) cell.cc_idx[i] = mark_for_codepoint(char_buf[i + 1]);
    if (bold) cell.attrs |= 1 << BOLD_SHIFT;
    if (italic) cell.attrs |= 1 << ITALIC_SHIFT;
    ssize_t ans = fallback_font(&cell);
    if (ans < 0) { PyErr_SetString(PyExc_ValueError, "Too many fallback fonts"); return NULL; }
    return fonts.fonts[ans].face;
}


static PyMethodDef module_methods[] = {
    METHODB(set_font_size, METH_VARARGS),
    METHODB(set_font, METH_VARARGS),
    METHODB(sprite_map_set_limits, METH_VARARGS),
    METHODB(sprite_map_set_layout, METH_VARARGS),
    METHODB(send_prerendered_sprites, METH_VARARGS),
    METHODB(test_sprite_position_for, METH_VARARGS),
    METHODB(concat_cells, METH_VARARGS),
    METHODB(set_send_sprite_to_gpu, METH_O),
    METHODB(test_shape, METH_VARARGS),
    METHODB(current_fonts, METH_NOARGS),
    METHODB(test_render_line, METH_VARARGS),
    METHODB(get_fallback_font, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_fonts(PyObject *module) {
    if (Py_AtExit(finalize) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to register the fonts module at exit handler");
        return false;
    }
    harfbuzz_buffer = hb_buffer_create();
    if (harfbuzz_buffer == NULL || !hb_buffer_allocation_successful(harfbuzz_buffer) || !hb_buffer_pre_allocate(harfbuzz_buffer, 2048)) { PyErr_NoMemory(); return false; }
    hb_buffer_set_cluster_level(harfbuzz_buffer, HB_BUFFER_CLUSTER_LEVEL_MONOTONE_CHARACTERS);
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    current_send_sprite_to_gpu = send_sprite_to_gpu;
    sprite_tracker_set_limits(2000, 2000);
    return true;
}
