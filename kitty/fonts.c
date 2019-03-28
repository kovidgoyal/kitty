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
#define CELLS_IN_CANVAS ((MAX_NUM_EXTRA_GLYPHS + 1) * 3)
#define MAX_NUM_EXTRA_GLYPHS_PUA 4

typedef void (*send_sprite_to_gpu_func)(FONTS_DATA_HANDLE fg, unsigned int, unsigned int, unsigned int, pixel*);
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
    size_t max_y;
    unsigned int x, y, z, xnum, ynum;
} GPUSpriteTracker;


static hb_buffer_t *harfbuzz_buffer = NULL;
static hb_feature_t no_calt_feature = {0};
static char_type shape_buffer[4096] = {0};
static size_t max_texture_size = 1024, max_array_len = 1024;

typedef struct {
    char_type left, right;
    size_t font_idx;
} SymbolMap;

static SymbolMap *symbol_maps = NULL;
static size_t num_symbol_maps = 0;



typedef struct {
    PyObject *face;
    // Map glyphs to sprite map co-ords
    SpritePosition sprite_map[1024];
    SpecialGlyphCache special_glyph_cache[SPECIAL_GLYPH_CACHE_SIZE];
    bool bold, italic, emoji_presentation;
} Font;

typedef struct {
    FONTS_DATA_HEAD
    id_type id;
    unsigned int baseline, underline_position, underline_thickness;
    size_t fonts_capacity, fonts_count, fallback_fonts_count;
    ssize_t medium_font_idx, bold_font_idx, italic_font_idx, bi_font_idx, first_symbol_font_idx, first_fallback_font_idx;
    Font *fonts;
    pixel *canvas;
    GPUSpriteTracker sprite_tracker;
} FontGroup;

static FontGroup* font_groups = NULL;
static size_t font_groups_capacity = 0;
static size_t num_font_groups = 0;
static id_type font_group_id_counter = 0;
static void initialize_font_group(FontGroup *fg);

static inline void
save_window_font_groups() {
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *w = global_state.os_windows + o;
        w->temp_font_group_id = w->fonts_data ? ((FontGroup*)(w->fonts_data))->id : 0;
    }
}

static inline void
restore_window_font_groups() {
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *w = global_state.os_windows + o;
        w->fonts_data = NULL;
        for (size_t i = 0; i < num_font_groups; i++) {
            if (font_groups[i].id == w->temp_font_group_id) {
                w->fonts_data = (FONTS_DATA_HANDLE)(font_groups + i);
                break;
            }
        }
    }
}

static inline bool
font_group_is_unused(FontGroup *fg) {
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *w = global_state.os_windows + o;
        if (w->temp_font_group_id == fg->id) return false;
    }
    return true;
}

static inline void
trim_unused_font_groups() {
    save_window_font_groups();
    size_t i = 0;
    while (i < num_font_groups) {
        if (font_group_is_unused(font_groups + i)) {
            size_t num_to_right = (--num_font_groups) - i;
            if (!num_to_right) break;
            memmove(font_groups + i, font_groups + 1 + i, num_to_right * sizeof(FontGroup));
        } else i++;
    }
    restore_window_font_groups();
}

static inline void
add_font_group() {
    if (num_font_groups) trim_unused_font_groups();
    if (num_font_groups >= font_groups_capacity) {
        save_window_font_groups();
        font_groups_capacity += 5;
        font_groups = realloc(font_groups, sizeof(FontGroup) * font_groups_capacity);
        if (font_groups == NULL) fatal("Out of memory creating a new font group");
        restore_window_font_groups();
    }
    num_font_groups++;
}

static inline FontGroup*
font_group_for(double font_sz_in_pts, double logical_dpi_x, double logical_dpi_y) {
    for (size_t i = 0; i < num_font_groups; i++) {
        FontGroup *fg = font_groups + i;
        if (fg->font_sz_in_pts == font_sz_in_pts && fg->logical_dpi_x == logical_dpi_x && fg->logical_dpi_y == logical_dpi_y) return fg;
    }
    add_font_group();
    FontGroup *fg = font_groups + num_font_groups - 1;
    memset(fg, 0, sizeof(FontGroup));
    fg->font_sz_in_pts = font_sz_in_pts;
    fg->logical_dpi_x = logical_dpi_x;
    fg->logical_dpi_y = logical_dpi_y;
    fg->id = ++font_group_id_counter;
    initialize_font_group(fg);
    return fg;
}

static inline void
clear_canvas(FontGroup *fg) {
    if (fg->canvas) memset(fg->canvas, 0, CELLS_IN_CANVAS * fg->cell_width * fg->cell_height * sizeof(pixel));
}



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
sprite_tracker_set_limits(size_t max_texture_size_, size_t max_array_len_) {
    max_texture_size = max_texture_size_;
    max_array_len = MIN(0xfff, max_array_len_);
}

static inline void
do_increment(FontGroup *fg, int *error) {
    fg->sprite_tracker.x++;
    if (fg->sprite_tracker.x >= fg->sprite_tracker.xnum) {
        fg->sprite_tracker.x = 0; fg->sprite_tracker.y++;
        fg->sprite_tracker.ynum = MIN(MAX(fg->sprite_tracker.ynum, fg->sprite_tracker.y + 1), fg->sprite_tracker.max_y);
        if (fg->sprite_tracker.y >= fg->sprite_tracker.max_y) {
            fg->sprite_tracker.y = 0; fg->sprite_tracker.z++;
            if (fg->sprite_tracker.z >= MIN(UINT16_MAX, max_array_len)) *error = 2;
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
sprite_position_for(FontGroup *fg, Font *font, glyph_index glyph, ExtraGlyphs *extra_glyphs, uint8_t ligature_index, int *error) {
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
    s->x = fg->sprite_tracker.x; s->y = fg->sprite_tracker.y; s->z = fg->sprite_tracker.z;
    do_increment(fg, error);
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
sprite_tracker_current_layout(FONTS_DATA_HANDLE data, unsigned int *x, unsigned int *y, unsigned int *z) {
    FontGroup *fg = (FontGroup*)data;
    *x = fg->sprite_tracker.xnum; *y = fg->sprite_tracker.ynum; *z = fg->sprite_tracker.z;
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

static void
sprite_tracker_set_layout(GPUSpriteTracker *sprite_tracker, unsigned int cell_width, unsigned int cell_height) {
    sprite_tracker->xnum = MIN(MAX(1, max_texture_size / cell_width), UINT16_MAX);
    sprite_tracker->max_y = MIN(MAX(1, max_texture_size / cell_height), UINT16_MAX);
    sprite_tracker->ynum = 1;
    sprite_tracker->x = 0; sprite_tracker->y = 0; sprite_tracker->z = 0;
}
// }}}

static inline PyObject*
desc_to_face(PyObject *desc, FONTS_DATA_HANDLE fg) {
    PyObject *d = specialize_font_descriptor(desc, fg);
    if (d == NULL) return NULL;
    PyObject *ans = face_from_descriptor(d, fg);
    Py_DECREF(d);
    return ans;
}


static inline bool
init_font(Font *f, PyObject *face, bool bold, bool italic, bool emoji_presentation) {
    f->face = face; Py_INCREF(f->face);
    f->bold = bold; f->italic = italic; f->emoji_presentation = emoji_presentation;
    return true;
}

static inline void
del_font(Font *f) {
    Py_CLEAR(f->face);
    free_maps(f);
    f->bold = false; f->italic = false;
}

static inline void
del_font_group(FontGroup *fg) {
    free(fg->canvas); fg->canvas = NULL;
    fg->sprite_map = free_sprite_map(fg->sprite_map);
    for (size_t i = 0; i < fg->fonts_count; i++) del_font(fg->fonts + i);
    free(fg->fonts); fg->fonts = NULL;
}

static inline void
free_font_groups() {
    if (font_groups) {
        for (size_t i = 0; i < num_font_groups; i++) del_font_group(font_groups + i);
        free(font_groups); font_groups = NULL;
        font_groups_capacity = 0; num_font_groups = 0;
    }
}

static void
python_send_to_gpu(FONTS_DATA_HANDLE fg, unsigned int x, unsigned int y, unsigned int z, pixel* buf) {
    if (python_send_to_gpu_impl) {
        if (!num_font_groups) fatal("Cannot call send to gpu with no font groups");
        PyObject *ret = PyObject_CallFunction(python_send_to_gpu_impl, "IIIN", x, y, z, PyBytes_FromStringAndSize((const char*)buf, sizeof(pixel) * fg->cell_width * fg->cell_height));
        if (ret == NULL) PyErr_Print();
        else Py_DECREF(ret);
    }
}


static inline void
calc_cell_metrics(FontGroup *fg) {
    unsigned int cell_height, cell_width, baseline, underline_position, underline_thickness;
    cell_metrics(fg->fonts[fg->medium_font_idx].face, &cell_width, &cell_height, &baseline, &underline_position, &underline_thickness);
    if (!cell_width) fatal("Failed to calculate cell width for the specified font");
    unsigned int before_cell_height = cell_height;
    int cw = cell_width, ch = cell_height;
    if (OPT(adjust_line_height_px) != 0) ch += OPT(adjust_line_height_px);
    if (OPT(adjust_line_height_frac) != 0.f) ch *= OPT(adjust_line_height_frac);
    if (OPT(adjust_column_width_px != 0)) cw += OPT(adjust_column_width_px);
    if (OPT(adjust_column_width_frac) != 0.f) cw *= OPT(adjust_column_width_frac);
#define MAX_DIM 1000
#define MIN_WIDTH 2
#define MIN_HEIGHT 4
    if (cw >= MIN_WIDTH && cw <= MAX_DIM) cell_width = cw;
    else log_error("Cell width invalid after adjustment, ignoring adjust_column_width");
    if (ch >= MIN_HEIGHT && ch <= MAX_DIM) cell_height = ch;
    else log_error("Cell height invalid after adjustment, ignoring adjust_line_height");
    int line_height_adjustment = cell_height - before_cell_height;
    if (cell_height < MIN_HEIGHT) fatal("Line height too small: %u", cell_height);
    if (cell_height > MAX_DIM) fatal("Line height too large: %u", cell_height);
    if (cell_width < MIN_WIDTH) fatal("Cell width too small: %u", cell_width);
    if (cell_width > MAX_DIM) fatal("Cell width too large: %u", cell_width);
#undef MIN_WIDTH
#undef MIN_HEIGHT
#undef MAX_DIM
    underline_position = MIN(cell_height - 1, underline_position);
    // ensure there is at least a couple of pixels available to render styled underlines
    while (underline_position > baseline + 1 && cell_height - underline_position < 2) underline_position--;
    if (line_height_adjustment > 1) {
        baseline += MIN(cell_height - 1, (unsigned)line_height_adjustment / 2);
        underline_position += MIN(cell_height - 1, (unsigned)line_height_adjustment / 2);
    }
    sprite_tracker_set_layout(&fg->sprite_tracker, cell_width, cell_height);
    fg->cell_width = cell_width; fg->cell_height = cell_height;
    fg->baseline = baseline; fg->underline_position = underline_position; fg->underline_thickness = underline_thickness;
    free(fg->canvas);
    fg->canvas = calloc(CELLS_IN_CANVAS * fg->cell_width * fg->cell_height, sizeof(pixel));
    if (!fg->canvas) fatal("Out of memory allocating canvas for font group");
}

static inline bool
face_has_codepoint(PyObject* face, char_type cp) {
    return glyph_id_for_codepoint(face, cp) > 0;
}

static inline bool
has_emoji_presentation(CPUCell *cpu_cell, GPUCell *gpu_cell) {
    return (gpu_cell->attrs & WIDTH_MASK) == 2 && is_emoji(cpu_cell->ch) && cpu_cell->cc_idx[0] != VS15;
}

static inline bool
has_cell_text(Font *self, CPUCell *cell) {
    if (!face_has_codepoint(self->face, cell->ch)) return false;
    for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) {
        combining_type cc_idx = cell->cc_idx[i];
        if (cc_idx == VS15 || cc_idx == VS16) continue;
        if (!face_has_codepoint(self->face, codepoint_for_mark(cc_idx))) return false;
    }
    return true;
}

static inline void
output_cell_fallback_data(CPUCell *cell, bool bold, bool italic, bool emoji_presentation, PyObject *face, bool new_face) {
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
load_fallback_font(FontGroup *fg, CPUCell *cell, bool bold, bool italic, bool emoji_presentation) {
    if (fg->fallback_fonts_count > 100) { log_error("Too many fallback fonts"); return MISSING_FONT; }
    ssize_t f;

    if (bold) f = fg->italic_font_idx > 0 ? fg->bi_font_idx : fg->bold_font_idx;
    else f = italic ? fg->italic_font_idx : fg->medium_font_idx;
    if (f < 0) f = fg->medium_font_idx;

    PyObject *face = create_fallback_face(fg->fonts[f].face, cell, bold, italic, emoji_presentation, (FONTS_DATA_HANDLE)fg);
    if (face == NULL) { PyErr_Print(); return MISSING_FONT; }
    if (face == Py_None) { Py_DECREF(face); return MISSING_FONT; }
    if (global_state.debug_font_fallback) output_cell_fallback_data(cell, bold, italic, emoji_presentation, face, true);
    set_size_for_face(face, fg->cell_height, true, (FONTS_DATA_HANDLE)fg);

    ensure_space_for(fg, fonts, Font, fg->fonts_count + 1, fonts_capacity, 5, true);
    ssize_t ans = fg->first_fallback_font_idx + fg->fallback_fonts_count;
    Font *af = &fg->fonts[ans];
    if (!init_font(af, face, bold, italic, emoji_presentation)) fatal("Out of memory");
    Py_DECREF(face);
    fg->fallback_fonts_count++;
    fg->fonts_count++;
    return ans;
}

static inline ssize_t
fallback_font(FontGroup *fg, CPUCell *cpu_cell, GPUCell *gpu_cell) {
    bool bold = (gpu_cell->attrs >> BOLD_SHIFT) & 1;
    bool italic = (gpu_cell->attrs >> ITALIC_SHIFT) & 1;
    bool emoji_presentation = has_emoji_presentation(cpu_cell, gpu_cell);

    // Check if one of the existing fallback fonts has this text
    for (size_t i = 0, j = fg->first_fallback_font_idx; i < fg->fallback_fonts_count; i++, j++)  {
        Font *ff = fg->fonts +j;
        if (ff->bold == bold && ff->italic == italic && ff->emoji_presentation == emoji_presentation && has_cell_text(ff, cpu_cell)) {
            if (global_state.debug_font_fallback) output_cell_fallback_data(cpu_cell, bold, italic, emoji_presentation, ff->face, false);
            return j;
        }
    }

    return load_fallback_font(fg, cpu_cell, bold, italic, emoji_presentation);
}

static inline ssize_t
in_symbol_maps(FontGroup *fg, char_type ch) {
    for (size_t i = 0; i < num_symbol_maps; i++) {
        if (symbol_maps[i].left <= ch && ch <= symbol_maps[i].right) return fg->first_symbol_font_idx + symbol_maps[i].font_idx;
    }
    return NO_FONT;
}


static ssize_t
font_for_cell(FontGroup *fg, CPUCell *cpu_cell, GPUCell *gpu_cell) {
START_ALLOW_CASE_RANGE
    ssize_t ans;
    switch(cpu_cell->ch) {
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
            ans = in_symbol_maps(fg, cpu_cell->ch);
            if (ans > -1) return ans;
            switch(BI_VAL(gpu_cell->attrs)) {
                case 0:
                    ans = fg->medium_font_idx; break;
                case 1:
                    ans = fg->bold_font_idx ; break;
                case 2:
                    ans = fg->italic_font_idx; break;
                case 3:
                    ans = fg->bi_font_idx; break;
            }
            if (ans < 0) ans = fg->medium_font_idx;
            if (!has_emoji_presentation(cpu_cell, gpu_cell) && has_cell_text(fg->fonts + ans, cpu_cell)) return ans;
            return fallback_font(fg, cpu_cell, gpu_cell);
    }
END_ALLOW_CASE_RANGE
}

static inline void
set_sprite(GPUCell *cell, sprite_index x, sprite_index y, sprite_index z) {
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

static PyObject* box_drawing_function = NULL, *prerender_function = NULL, *descriptor_for_idx = NULL;

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
render_box_cell(FontGroup *fg, CPUCell *cpu_cell, GPUCell *gpu_cell) {
    int error = 0;
    glyph_index glyph = box_glyph_id(cpu_cell->ch);
    static ExtraGlyphs extra_glyphs = {{0}};
    SpritePosition *sp = sprite_position_for(fg, &fg->fonts[BOX_FONT], glyph, &extra_glyphs, false, &error);
    if (sp == NULL) {
        sprite_map_set_error(error); PyErr_Print();
        set_sprite(gpu_cell, 0, 0, 0);
        return;
    }
    set_sprite(gpu_cell, sp->x, sp->y, sp->z);
    if (sp->rendered) return;
    sp->rendered = true;
    sp->colored = false;
    PyObject *ret = PyObject_CallFunction(box_drawing_function, "IIId", cpu_cell->ch, fg->cell_width, fg->cell_height, (fg->logical_dpi_x + fg->logical_dpi_y) / 2.0);
    if (ret == NULL) { PyErr_Print(); return; }
    uint8_t *alpha_mask = PyLong_AsVoidPtr(PyTuple_GET_ITEM(ret, 0));
    clear_canvas(fg);
    Region r = { .right = fg->cell_width, .bottom = fg->cell_height };
    render_alpha_mask(alpha_mask, fg->canvas, &r, &r, fg->cell_width, fg->cell_width);
    current_send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, sp->x, sp->y, sp->z, fg->canvas);
    Py_DECREF(ret);
}

static inline void
load_hb_buffer(CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells) {
    index_type num;
    hb_buffer_clear_contents(harfbuzz_buffer);
    while (num_cells) {
        attrs_type prev_width = 0;
        for (num = 0; num_cells && num < arraysz(shape_buffer) - 20 - arraysz(first_cpu_cell->cc_idx); first_cpu_cell++, first_gpu_cell++, num_cells--) {
            if (prev_width == 2) { prev_width = 0; continue; }
            shape_buffer[num++] = first_cpu_cell->ch;
            prev_width = first_gpu_cell->attrs & WIDTH_MASK;
            for (unsigned i = 0; i < arraysz(first_cpu_cell->cc_idx) && first_cpu_cell->cc_idx[i]; i++) {
                shape_buffer[num++] = codepoint_for_mark(first_cpu_cell->cc_idx[i]);
            }
        }
        hb_buffer_add_utf32(harfbuzz_buffer, shape_buffer, num, 0, num);
    }
    hb_buffer_guess_segment_properties(harfbuzz_buffer);
}


static inline void
set_cell_sprite(GPUCell *cell, SpritePosition *sp) {
    cell->sprite_x = sp->x; cell->sprite_y = sp->y; cell->sprite_z = sp->z;
    if (sp->colored) cell->sprite_z |= 0x4000;
}

static inline pixel*
extract_cell_from_canvas(FontGroup *fg, unsigned int i, unsigned int num_cells) {
    pixel *ans = fg->canvas + (fg->cell_width * fg->cell_height * (CELLS_IN_CANVAS - 1)), *dest = ans, *src = fg->canvas + (i * fg->cell_width);
    unsigned int stride = fg->cell_width * num_cells;
    for (unsigned int r = 0; r < fg->cell_height; r++, dest += fg->cell_width, src += stride) memcpy(dest, src, fg->cell_width * sizeof(pixel));
    return ans;
}

static inline bool
is_private_use(char_type ch) {
    return (0xe000 <= ch && ch <= 0xf8ff) || (0xF0000 <= ch && ch <= 0xFFFFF) || (0x100000 <= ch && ch <= 0x10FFFF);
}

static inline void
render_group(FontGroup *fg, unsigned int num_cells, unsigned int num_glyphs, CPUCell *cpu_cells, GPUCell *gpu_cells, hb_glyph_info_t *info, hb_glyph_position_t *positions, Font *font, glyph_index glyph, ExtraGlyphs *extra_glyphs, bool center_glyph) {
    static SpritePosition* sprite_position[16];
    int error = 0;
    num_cells = MIN(sizeof(sprite_position)/sizeof(sprite_position[0]), num_cells);
    for (unsigned int i = 0; i < num_cells; i++) {
        sprite_position[i] = sprite_position_for(fg, font, glyph, extra_glyphs, (uint8_t)i, &error);
        if (error != 0) { sprite_map_set_error(error); PyErr_Print(); return; }
    }
    if (sprite_position[0]->rendered) {
        for (unsigned int i = 0; i < num_cells; i++) { set_cell_sprite(gpu_cells + i, sprite_position[i]); }
        return;
    }

    clear_canvas(fg);
    bool was_colored = (gpu_cells->attrs & WIDTH_MASK) == 2 && is_emoji(cpu_cells->ch);
    render_glyphs_in_cells(font->face, font->bold, font->italic, info, positions, num_glyphs, fg->canvas, fg->cell_width, fg->cell_height, num_cells, fg->baseline, &was_colored, (FONTS_DATA_HANDLE)fg, center_glyph);
    if (PyErr_Occurred()) PyErr_Print();

    for (unsigned int i = 0; i < num_cells; i++) {
        sprite_position[i]->rendered = true;
        sprite_position[i]->colored = was_colored;
        set_cell_sprite(gpu_cells + i, sprite_position[i]);
        pixel *buf = num_cells == 1 ? fg->canvas : extract_cell_from_canvas(fg, i, num_cells);
        current_send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, sprite_position[i]->x, sprite_position[i]->y, sprite_position[i]->z, buf);
    }

}

typedef struct {
    CPUCell *cpu_cell;
    GPUCell *gpu_cell;
    unsigned int num_codepoints;
    unsigned int codepoints_consumed;
    char_type current_codepoint;
} CellData;

typedef struct {
    unsigned int first_glyph_idx, first_cell_idx, num_glyphs, num_cells;
    bool has_special_glyph;
} Group;

typedef struct {
    uint32_t previous_cluster;
    bool prev_was_special, prev_was_empty;
    CellData current_cell_data;
    Group *groups;
    size_t groups_capacity, group_idx, glyph_idx, cell_idx, num_cells, num_glyphs;
    CPUCell *first_cpu_cell, *last_cpu_cell;
    GPUCell *first_gpu_cell, *last_gpu_cell;
    hb_glyph_info_t *info;
    hb_glyph_position_t *positions;
} GroupState;

static GroupState group_state = {0};

static inline unsigned int
num_codepoints_in_cell(CPUCell *cell) {
    unsigned int ans = 1;
    for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) ans++;
    return ans;
}

static inline void
shape(CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, hb_font_t *font, bool disable_ligature) {
    if (group_state.groups_capacity <= 2 * num_cells) {
        group_state.groups_capacity = MAX(128, 2 * num_cells);  // avoid unnecessary reallocs
        group_state.groups = realloc(group_state.groups, sizeof(Group) * group_state.groups_capacity);
        if (!group_state.groups) fatal("Out of memory");
    }
    group_state.previous_cluster = UINT32_MAX;
    group_state.prev_was_special = false;
    group_state.prev_was_empty = false;
    group_state.current_cell_data.cpu_cell = first_cpu_cell;
    group_state.current_cell_data.gpu_cell = first_gpu_cell;
    group_state.current_cell_data.num_codepoints = num_codepoints_in_cell(first_cpu_cell);
    group_state.current_cell_data.codepoints_consumed = 0;
    group_state.current_cell_data.current_codepoint = first_cpu_cell->ch;
    memset(group_state.groups, 0, sizeof(Group) * group_state.groups_capacity);
    group_state.group_idx = 0;
    group_state.glyph_idx = 0;
    group_state.cell_idx = 0;
    group_state.num_cells = num_cells;
    group_state.first_cpu_cell = first_cpu_cell;
    group_state.first_gpu_cell = first_gpu_cell;
    group_state.last_cpu_cell = first_cpu_cell + (num_cells ? num_cells - 1 : 0);
    group_state.last_gpu_cell = first_gpu_cell + (num_cells ? num_cells - 1 : 0);
    load_hb_buffer(first_cpu_cell, first_gpu_cell, num_cells);

    if (disable_ligature) {
        hb_shape(font, harfbuzz_buffer, &no_calt_feature, 1);
    } else {
        hb_shape(font, harfbuzz_buffer, NULL, 0);
    }

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
check_cell_consumed(CellData *cell_data, CPUCell *last_cpu_cell) {
    cell_data->codepoints_consumed++;
    if (cell_data->codepoints_consumed >= cell_data->num_codepoints) {
        attrs_type width = cell_data->gpu_cell->attrs & WIDTH_MASK;
        cell_data->cpu_cell += MAX(1, width);
        cell_data->gpu_cell += MAX(1, width);
        cell_data->codepoints_consumed = 0;
        if (cell_data->cpu_cell <= last_cpu_cell) {
            cell_data->num_codepoints = num_codepoints_in_cell(cell_data->cpu_cell);
            cell_data->current_codepoint = cell_data->cpu_cell->ch;
        } else cell_data->current_codepoint = 0;
        return width;
    } else {
        switch(cell_data->codepoints_consumed) {
            case 0:
                cell_data->current_codepoint = cell_data->cpu_cell->ch;
                break;
            default:
                cell_data->current_codepoint = codepoint_for_mark(cell_data->cpu_cell->cc_idx[cell_data->codepoints_consumed - 1]);
                break;
        }
    }
    return 0;
}


static inline void
shape_run(CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, Font *font, bool disable_ligature) {
    shape(first_cpu_cell, first_gpu_cell, num_cells, harfbuzz_font_for_face(font->face), disable_ligature);
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
        if (is_special) current_group->has_special_glyph = true;
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
                unsigned int w = check_cell_consumed(&G(current_cell_data), G(last_cpu_cell));
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
    while (G(group_idx) > 0) {
        Group *g = G(groups), *g1 = G(groups) + 1;
        g->num_cells += g1->num_cells;
        g->num_glyphs += g1->num_glyphs;
        g->num_glyphs = MIN(g->num_glyphs, MAX_NUM_EXTRA_GLYPHS + 1);
        G(group_idx)--;
    }
}

static inline void
split_run_at_offset(index_type cursor_offset, index_type *left, index_type *right) {
    *left = 0; *right = 0;
    for (unsigned idx = 0; idx < G(group_idx) + 1; idx++) {
        Group *group = G(groups) + idx;
        if (group->first_cell_idx <= cursor_offset && cursor_offset < group->first_cell_idx + group->num_cells) {
            GPUCell *first_cell = G(first_gpu_cell) + group->first_cell_idx;
            if (group->num_cells > 1 && group->has_special_glyph && (first_cell->attrs & WIDTH_MASK) == 1) {
                // likely a calt ligature
                *left = group->first_cell_idx; *right = group->first_cell_idx + group->num_cells;
            }
            break;
        }
    }
}


static inline void
render_groups(FontGroup *fg, Font *font, bool center_glyph) {
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
        render_group(fg, group->num_cells, group->num_glyphs, G(first_cpu_cell) + group->first_cell_idx, G(first_gpu_cell) + group->first_cell_idx, G(info) + group->first_glyph_idx, G(positions) + group->first_glyph_idx, font, primary, &ed, center_glyph);
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
    while(num < line->xnum && line->cpu_cells[num].ch) num += line->gpu_cells[num].attrs & WIDTH_MASK;
    PyObject *face = NULL;
    Font *font;
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create at least one font group first"); return NULL; }
    if (path) {
        face = face_from_path(path, index, (FONTS_DATA_HANDLE)font_groups);
        if (face == NULL) return NULL;
        font = calloc(1, sizeof(Font));
        font->face = face;
    } else {
        FontGroup *fg = font_groups;
        font = fg->fonts + fg->medium_font_idx;
    }
    shape_run(line->cpu_cells, line->gpu_cells, num, font, false);

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
    if (face) { Py_CLEAR(face); free_maps(font); free(font); }
    return ans;
}
#undef G

static inline void
render_run(FontGroup *fg, CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, ssize_t font_idx, bool pua_space_ligature, bool center_glyph, int cursor_offset) {
    switch(font_idx) {
        default:
            shape_run(first_cpu_cell, first_gpu_cell, num_cells, &fg->fonts[font_idx], false);
            if (pua_space_ligature) merge_groups_for_pua_space_ligature();
            else if (cursor_offset > -1) {
                index_type left, right;
                split_run_at_offset(cursor_offset, &left, &right);
                if (right > left) {
                    if (left) {
                        shape_run(first_cpu_cell, first_gpu_cell, left, &fg->fonts[font_idx], false);
                        render_groups(fg, &fg->fonts[font_idx], center_glyph);
                    }
                        shape_run(first_cpu_cell + left, first_gpu_cell + left, right - left, &fg->fonts[font_idx], true);
                        render_groups(fg, &fg->fonts[font_idx], center_glyph);
                    if (right < num_cells) {
                        shape_run(first_cpu_cell + right, first_gpu_cell + right, num_cells - right, &fg->fonts[font_idx], false);
                        render_groups(fg, &fg->fonts[font_idx], center_glyph);
                    }
                    break;
                }
            }
            render_groups(fg, &fg->fonts[font_idx], center_glyph);
            break;
        case BLANK_FONT:
            while(num_cells--) { set_sprite(first_gpu_cell, 0, 0, 0); first_cpu_cell++; first_gpu_cell++; }
            break;
        case BOX_FONT:
            while(num_cells--) { render_box_cell(fg, first_cpu_cell, first_gpu_cell); first_cpu_cell++; first_gpu_cell++; }
            break;
        case MISSING_FONT:
            while(num_cells--) { set_sprite(first_gpu_cell, MISSING_GLYPH, 0, 0); first_cpu_cell++; first_gpu_cell++; }
            break;
    }
}

void
render_line(FONTS_DATA_HANDLE fg_, Line *line, index_type lnum, Cursor *cursor) {
#define RENDER if (run_font_idx != NO_FONT && i > first_cell_in_run) { \
    int cursor_offset = -1; \
    if (disable_ligature_in_line && first_cell_in_run <= cursor->x && cursor->x <= i) cursor_offset = cursor->x - first_cell_in_run; \
    render_run(fg, line->cpu_cells + first_cell_in_run, line->gpu_cells + first_cell_in_run, i - first_cell_in_run, run_font_idx, false, center_glyph, cursor_offset); \
}
    FontGroup *fg = (FontGroup*)fg_;
    ssize_t run_font_idx = NO_FONT;
    bool center_glyph = false;
    bool disable_ligature_in_line = false;
    index_type first_cell_in_run, i;
    attrs_type prev_width = 0;
    if (cursor != NULL && OPT(disable_ligatures_under_cursor)) {
        if (lnum == cursor->y) disable_ligature_in_line = true;
    }
    for (i=0, first_cell_in_run=0; i < line->xnum; i++) {
        if (prev_width == 2) { prev_width = 0; continue; }
        CPUCell *cpu_cell = line->cpu_cells + i;
        GPUCell *gpu_cell = line->gpu_cells + i;
        ssize_t cell_font_idx = font_for_cell(fg, cpu_cell, gpu_cell);

        if (is_private_use(cpu_cell->ch)
                && cell_font_idx != BOX_FONT
                && cell_font_idx != MISSING_FONT) {
            int desired_cells = 1;
            if (cell_font_idx > 0) {
                Font *font = (fg->fonts + cell_font_idx);
                glyph_index glyph_id = glyph_id_for_codepoint(font->face, cpu_cell->ch);

                int width = get_glyph_width(font->face, glyph_id);
                desired_cells = ceilf((float)width / fg->cell_width);
            }

            int num_spaces = 0;
            while ((line->cpu_cells[i+num_spaces+1].ch == ' ')
                    && num_spaces < MAX_NUM_EXTRA_GLYPHS_PUA
                    && num_spaces < desired_cells
                    && i + num_spaces + 1 < line->xnum) {
                num_spaces++;
                // We have a private use char followed by space(s), render it as a multi-cell ligature.
                GPUCell *space_cell = line->gpu_cells + i + num_spaces;
                // Ensure the space cell uses the foreground color from the PUA cell.
                // This is needed because there are applications like
                // Powerline that use PUA+space with different foreground colors
                // for the space and the PUA. See for example: https://github.com/kovidgoyal/kitty/issues/467
                space_cell->fg = gpu_cell->fg;
                space_cell->decoration_fg = gpu_cell->decoration_fg;
            }
            if (num_spaces) {
                center_glyph = true;
                RENDER
                center_glyph = false;
                render_run(fg, line->cpu_cells + i, line->gpu_cells + i, num_spaces + 1, cell_font_idx, true, center_glyph, -1);
                run_font_idx = NO_FONT;
                first_cell_in_run = i + num_spaces + 1;
                prev_width = line->gpu_cells[i+num_spaces].attrs & WIDTH_MASK;
                i += num_spaces;
                continue;
            }
        }
        prev_width = gpu_cell->attrs & WIDTH_MASK;
        if (run_font_idx == NO_FONT) run_font_idx = cell_font_idx;
        if (run_font_idx == cell_font_idx) continue;
        RENDER
        run_font_idx = cell_font_idx;
        first_cell_in_run = i;
    }
    RENDER
#undef RENDER
}

StringCanvas
render_simple_text(FONTS_DATA_HANDLE fg_, const char *text) {
    FontGroup *fg = (FontGroup*)fg_;
    if (fg->fonts_count && fg->medium_font_idx) return render_simple_text_impl(fg->fonts[fg->medium_font_idx].face, text, fg->baseline);
    StringCanvas ans = {0};
    return ans;
}

static inline void
clear_symbol_maps() {
    if (symbol_maps) { free(symbol_maps); symbol_maps = NULL; num_symbol_maps = 0; }
}

typedef struct {
    unsigned int main, bold, italic, bi, num_symbol_fonts;
} DescriptorIndices;

DescriptorIndices descriptor_indices = {0};

static PyObject*
set_font_data(PyObject UNUSED *m, PyObject *args) {
    PyObject *sm;
    Py_CLEAR(box_drawing_function); Py_CLEAR(prerender_function); Py_CLEAR(descriptor_for_idx);
    if (!PyArg_ParseTuple(args, "OOOIIIIO!d",
                &box_drawing_function, &prerender_function, &descriptor_for_idx,
                &descriptor_indices.bold, &descriptor_indices.italic, &descriptor_indices.bi, &descriptor_indices.num_symbol_fonts,
                &PyTuple_Type, &sm, &global_state.font_sz_in_pts)) return NULL;
    Py_INCREF(box_drawing_function); Py_INCREF(prerender_function); Py_INCREF(descriptor_for_idx);
    free_font_groups();
    clear_symbol_maps();
    num_symbol_maps = PyTuple_GET_SIZE(sm);
    symbol_maps = calloc(num_symbol_maps, sizeof(SymbolMap));
    if (symbol_maps == NULL) return PyErr_NoMemory();
    for (size_t s = 0; s < num_symbol_maps; s++) {
        unsigned int left, right, font_idx;
        SymbolMap *x = symbol_maps + s;
        if (!PyArg_ParseTuple(PyTuple_GET_ITEM(sm, s), "III", &left, &right, &font_idx)) return NULL;
        x->left = left; x->right = right; x->font_idx = font_idx;
    }
    Py_RETURN_NONE;
}

static inline void
send_prerendered_sprites(FontGroup *fg) {
    int error = 0;
    sprite_index x = 0, y = 0, z = 0;
    // blank cell
    clear_canvas(fg);
    current_send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, x, y, z, fg->canvas);
    do_increment(fg, &error);
    if (error != 0) { sprite_map_set_error(error); PyErr_Print(); fatal("Failed"); }
    PyObject *args = PyObject_CallFunction(prerender_function, "IIIIIdd", fg->cell_width, fg->cell_height, fg->baseline, fg->underline_position, fg->underline_thickness, fg->logical_dpi_x, fg->logical_dpi_y);
    if (args == NULL) { PyErr_Print(); fatal("Failed to pre-render cells"); }
    for (ssize_t i = 0; i < PyTuple_GET_SIZE(args) - 1; i++) {
        x = fg->sprite_tracker.x; y = fg->sprite_tracker.y; z = fg->sprite_tracker.z;
        if (y > 0) { fatal("Too many pre-rendered sprites for your GPU or the font size is too large"); }
        do_increment(fg, &error);
        if (error != 0) { sprite_map_set_error(error); PyErr_Print(); fatal("Failed"); }
        uint8_t *alpha_mask = PyLong_AsVoidPtr(PyTuple_GET_ITEM(args, i));
        clear_canvas(fg);
        Region r = { .right = fg->cell_width, .bottom = fg->cell_height };
        render_alpha_mask(alpha_mask, fg->canvas, &r, &r, fg->cell_width, fg->cell_width);
        current_send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, x, y, z, fg->canvas);
    }
    Py_CLEAR(args);
}

static inline size_t
initialize_font(FontGroup *fg, unsigned int desc_idx, const char *ftype) {
    PyObject *d = PyObject_CallFunction(descriptor_for_idx, "I", desc_idx);
    if (d == NULL) { PyErr_Print(); fatal("Failed for %s font", ftype); }
    bool bold = PyObject_IsTrue(PyTuple_GET_ITEM(d, 1));
    bool italic = PyObject_IsTrue(PyTuple_GET_ITEM(d, 2));
    PyObject *face = desc_to_face(PyTuple_GET_ITEM(d, 0), (FONTS_DATA_HANDLE)fg);
    Py_CLEAR(d);
    if (face == NULL) { PyErr_Print(); fatal("Failed to convert descriptor to face for %s font", ftype); }
    size_t idx = fg->fonts_count++;
    bool ok = init_font(fg->fonts + idx, face, bold, italic, false);
    Py_CLEAR(face);
    if (!ok) {
        if (PyErr_Occurred()) { PyErr_Print(); }
        fatal("Failed to initialize %s font: %zu", ftype, idx);
    }
    return idx;
}

static void
initialize_font_group(FontGroup *fg) {
    fg->fonts_capacity = 10 + descriptor_indices.num_symbol_fonts;
    fg->fonts = calloc(fg->fonts_capacity, sizeof(Font));
    if (fg->fonts == NULL) fatal("Out of memory allocating fonts array");
    fg->fonts_count = 1;  // the 0 index font is the box font
#define I(attr)  if (descriptor_indices.attr) fg->attr##_font_idx = initialize_font(fg, descriptor_indices.attr, #attr); else fg->attr##_font_idx = -1;
    fg->medium_font_idx = initialize_font(fg, 0, "medium");
    I(bold); I(italic); I(bi);
#undef I
    fg->first_symbol_font_idx = fg->fonts_count; fg->first_fallback_font_idx = fg->fonts_count;
    fg->fallback_fonts_count = 0;
    for (size_t i = 0; i < descriptor_indices.num_symbol_fonts; i++) {
        initialize_font(fg, descriptor_indices.bi + 1 + i, "symbol_map");
        fg->first_fallback_font_idx++;
    }
#undef I
    calc_cell_metrics(fg);
}


void
send_prerendered_sprites_for_window(OSWindow *w) {
    FontGroup *fg = (FontGroup*)w->fonts_data;
    if (!fg->sprite_map) {
        fg->sprite_map = alloc_sprite_map(fg->cell_width, fg->cell_height);
        if (!fg->sprite_map) fatal("Out of memory allocating a sprite map");
        send_prerendered_sprites(fg);
    }
}

FONTS_DATA_HANDLE
load_fonts_data(double font_sz_in_pts, double dpi_x, double dpi_y) {
    FontGroup *fg = font_group_for(font_sz_in_pts, dpi_x, dpi_y);
    return (FONTS_DATA_HANDLE)fg;
}

static void
finalize(void) {
    Py_CLEAR(python_send_to_gpu_impl);
    clear_symbol_maps();
    Py_CLEAR(box_drawing_function);
    Py_CLEAR(prerender_function);
    Py_CLEAR(descriptor_for_idx);
    free_font_groups();
    if (harfbuzz_buffer) { hb_buffer_destroy(harfbuzz_buffer); harfbuzz_buffer = NULL; }
    free(group_state.groups); group_state.groups = NULL; group_state.groups_capacity = 0;
}

static PyObject*
sprite_map_set_layout(PyObject UNUSED *self, PyObject *args) {
    unsigned int w, h;
    if(!PyArg_ParseTuple(args, "II", &w, &h)) return NULL;
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create font group first"); return NULL; }
    sprite_tracker_set_layout(&font_groups->sprite_tracker, w, h);
    Py_RETURN_NONE;
}

static PyObject*
test_sprite_position_for(PyObject UNUSED *self, PyObject *args) {
    glyph_index glyph;
    ExtraGlyphs extra_glyphs = {{0}};
    if (!PyArg_ParseTuple(args, "H|H", &glyph, &extra_glyphs.data)) return NULL;
    int error;
    FontGroup *fg = font_groups;
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create font group first"); return NULL; }
    SpritePosition *pos = sprite_position_for(fg, &fg->fonts[fg->medium_font_idx], glyph, &extra_glyphs, 0, &error);
    if (pos == NULL) { sprite_map_set_error(error); return NULL; }
    return Py_BuildValue("HHH", pos->x, pos->y, pos->z);
}

static PyObject*
set_send_sprite_to_gpu(PyObject UNUSED *self, PyObject *func) {
    Py_CLEAR(python_send_to_gpu_impl);
    if (func != Py_None) {
        python_send_to_gpu_impl = func;
        Py_INCREF(python_send_to_gpu_impl);
    }
    current_send_sprite_to_gpu = python_send_to_gpu_impl ? python_send_to_gpu : send_sprite_to_gpu;
    Py_RETURN_NONE;
}

static PyObject*
test_render_line(PyObject UNUSED *self, PyObject *args) {
    PyObject *line;
    if (!PyArg_ParseTuple(args, "O!", &Line_Type, &line)) return NULL;
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create font group first"); return NULL; }
    render_line((FONTS_DATA_HANDLE)font_groups, (Line*)line, 0, NULL);
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
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create font group first"); return NULL; }
    PyObject *ans = PyDict_New();
    if (!ans) return NULL;
    FontGroup *fg = font_groups;
#define SET(key, val) {if (PyDict_SetItemString(ans, #key, fg->fonts[val].face) != 0) { goto error; }}
    SET(medium, fg->medium_font_idx);
    if (fg->bold_font_idx > 0) SET(bold, fg->bold_font_idx);
    if (fg->italic_font_idx > 0) SET(italic, fg->italic_font_idx);
    if (fg->bi_font_idx > 0) SET(bi, fg->bi_font_idx);
    PyObject *ff = PyTuple_New(fg->fallback_fonts_count);
    if (!ff) goto error;
    for (size_t i = 0; i < fg->fallback_fonts_count; i++) {
        Py_INCREF(fg->fonts[fg->first_fallback_font_idx + i].face);
        PyTuple_SET_ITEM(ff, i, fg->fonts[fg->first_fallback_font_idx + i].face);
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
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create font group first"); return NULL; }
    PyObject *text;
    int bold, italic;
    if (!PyArg_ParseTuple(args, "Upp", &text, &bold, &italic)) return NULL;
    CPUCell cpu_cell = {0};
    GPUCell gpu_cell = {0};
    static Py_UCS4 char_buf[2 + arraysz(cpu_cell.cc_idx)];
    if (!PyUnicode_AsUCS4(text, char_buf, arraysz(char_buf), 1)) return NULL;
    cpu_cell.ch = char_buf[0];
    for (unsigned i = 0; i + 1 < (unsigned) PyUnicode_GetLength(text) && i < arraysz(cpu_cell.cc_idx); i++) cpu_cell.cc_idx[i] = mark_for_codepoint(char_buf[i + 1]);
    if (bold) gpu_cell.attrs |= 1 << BOLD_SHIFT;
    if (italic) gpu_cell.attrs |= 1 << ITALIC_SHIFT;
    FontGroup *fg = font_groups;
    ssize_t ans = fallback_font(fg, &cpu_cell, &gpu_cell);
    if (ans == MISSING_FONT) { PyErr_SetString(PyExc_ValueError, "No fallback font found"); return NULL; }
    if (ans < 0) { PyErr_SetString(PyExc_ValueError, "Too many fallback fonts"); return NULL; }
    return fg->fonts[ans].face;
}

static PyObject*
create_test_font_group(PyObject *self UNUSED, PyObject *args) {
    double sz, dpix, dpiy;
    if (!PyArg_ParseTuple(args, "ddd", &sz, &dpix, &dpiy)) return NULL;
    FontGroup *fg = font_group_for(sz, dpix, dpiy);
    if (!fg->sprite_map) send_prerendered_sprites(fg);
    return Py_BuildValue("II", fg->cell_width, fg->cell_height);
}

static PyObject*
free_font_data(PyObject *self UNUSED, PyObject *args UNUSED) {
    finalize();
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    METHODB(set_font_data, METH_VARARGS),
    METHODB(free_font_data, METH_NOARGS),
    METHODB(create_test_font_group, METH_VARARGS),
    METHODB(sprite_map_set_layout, METH_VARARGS),
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
    harfbuzz_buffer = hb_buffer_create();
    if (harfbuzz_buffer == NULL || !hb_buffer_allocation_successful(harfbuzz_buffer) || !hb_buffer_pre_allocate(harfbuzz_buffer, 2048)) { PyErr_NoMemory(); return false; }
    hb_buffer_set_cluster_level(harfbuzz_buffer, HB_BUFFER_CLUSTER_LEVEL_MONOTONE_CHARACTERS);
#define feature_str "-calt"
    if (!hb_feature_from_string(feature_str, sizeof(feature_str) - 1, &no_calt_feature)) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to create -calt harfbuzz feature");
        return false;
    }
#undef feature_str
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    current_send_sprite_to_gpu = send_sprite_to_gpu;
    return true;
}
