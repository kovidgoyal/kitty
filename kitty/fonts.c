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
#include "glyph-cache.h"

#define MISSING_GLYPH (NUM_UNDERLINE_STYLES + 2)
#define MAX_NUM_EXTRA_GLYPHS_PUA 4u

typedef void (*send_sprite_to_gpu_func)(FONTS_DATA_HANDLE fg, unsigned int, unsigned int, unsigned int, pixel*);
send_sprite_to_gpu_func current_send_sprite_to_gpu = NULL;
static PyObject *python_send_to_gpu_impl = NULL;
extern PyTypeObject Line_Type;

enum {NO_FONT=-3, MISSING_FONT=-2, BLANK_FONT=-1, BOX_FONT=0};
typedef enum {
    LIGATURE_UNKNOWN, INFINITE_LIGATURE_START, INFINITE_LIGATURE_MIDDLE, INFINITE_LIGATURE_END
} LigatureType;


#define SPECIAL_FILLED_MASK 1
#define SPECIAL_VALUE_MASK 2
#define EMPTY_FILLED_MASK 4
#define EMPTY_VALUE_MASK 8

typedef struct {
    size_t max_y;
    unsigned int x, y, z, xnum, ynum;
} GPUSpriteTracker;


static hb_buffer_t *harfbuzz_buffer = NULL;
static hb_feature_t hb_features[3] = {{0}};
static char_type shape_buffer[4096] = {0};
static size_t max_texture_size = 1024, max_array_len = 1024;
typedef enum { LIGA_FEATURE, DLIG_FEATURE, CALT_FEATURE } HBFeature;
static PyObject* font_feature_settings = NULL;

typedef struct {
    char_type left, right;
    size_t font_idx;
} SymbolMap;

static SymbolMap *symbol_maps = NULL, *narrow_symbols = NULL;
static size_t num_symbol_maps = 0, num_narrow_symbols = 0;

typedef enum { SPACER_STRATEGY_UNKNOWN, SPACERS_BEFORE, SPACERS_AFTER, SPACERS_IOSEVKA } SpacerStrategy;

typedef struct {
    PyObject *face;
    // Map glyphs to sprite map co-ords
    SpritePosition *sprite_position_hash_table;
    hb_feature_t* ffs_hb_features;
    size_t num_ffs_hb_features;
    GlyphProperties *glyph_properties_hash_table;
    bool bold, italic, emoji_presentation;
    SpacerStrategy spacer_strategy;
} Font;

typedef struct Canvas {
    pixel *buf;
    unsigned current_cells, alloced_cells;
} Canvas;

typedef struct fallback_font_map {
    const char *cell_text;
    size_t font_idx;
    UT_hash_handle hh;
} fallback_font_map_t;

typedef struct {
    FONTS_DATA_HEAD
    id_type id;
    unsigned int baseline, underline_position, underline_thickness, strikethrough_position, strikethrough_thickness;
    size_t fonts_capacity, fonts_count, fallback_fonts_count;
    ssize_t medium_font_idx, bold_font_idx, italic_font_idx, bi_font_idx, first_symbol_font_idx, first_fallback_font_idx;
    Font *fonts;
    Canvas canvas;
    GPUSpriteTracker sprite_tracker;
    fallback_font_map_t *fallback_font_map;
} FontGroup;

static FontGroup* font_groups = NULL;
static size_t font_groups_capacity = 0;
static size_t num_font_groups = 0;
static id_type font_group_id_counter = 0;
static void initialize_font_group(FontGroup *fg);

static void
ensure_canvas_can_fit(FontGroup *fg, unsigned cells) {
    if (fg->canvas.alloced_cells < cells) {
        free(fg->canvas.buf);
        fg->canvas.alloced_cells = cells + 4;
        fg->canvas.buf = malloc(sizeof(fg->canvas.buf[0]) * 3u * fg->canvas.alloced_cells * fg->cell_width * fg->cell_height);
        if (!fg->canvas.buf) fatal("Out of memory allocating canvas");
    }
    fg->canvas.current_cells = cells;
    if (fg->canvas.buf) memset(fg->canvas.buf, 0, sizeof(fg->canvas.buf[0]) * fg->canvas.current_cells * 3u * fg->cell_width * fg->cell_height);
}


static void
save_window_font_groups(void) {
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *w = global_state.os_windows + o;
        w->temp_font_group_id = w->fonts_data ? ((FontGroup*)(w->fonts_data))->id : 0;
    }
}

static void
restore_window_font_groups(void) {
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

static bool
font_group_is_unused(FontGroup *fg) {
    for (size_t o = 0; o < global_state.num_os_windows; o++) {
        OSWindow *w = global_state.os_windows + o;
        if (w->temp_font_group_id == fg->id) return false;
    }
    return true;
}

void
free_maps(Font *font) {
    free_sprite_position_hash_table(&font->sprite_position_hash_table);
    font->sprite_position_hash_table = NULL;
    free_glyph_properties_hash_table(&font->glyph_properties_hash_table);
    font->glyph_properties_hash_table = NULL;
}

static void
del_font(Font *f) {
    Py_CLEAR(f->face);
    free(f->ffs_hb_features); f->ffs_hb_features = NULL;
    free_maps(f);
    f->bold = false; f->italic = false;
}

static void
del_font_group(FontGroup *fg) {
    free(fg->canvas.buf); fg->canvas.buf = NULL; fg->canvas = (Canvas){0};
    fg->sprite_map = free_sprite_map(fg->sprite_map);
    if (fg->fallback_font_map) {
        fallback_font_map_t *current, *tmp;
        HASH_ITER(hh, fg->fallback_font_map, current, tmp) {
            free((void*)current->cell_text);
            HASH_DEL(fg->fallback_font_map, current);
            free(current);
        }
        fg->fallback_font_map = NULL;
    }
    for (size_t i = 0; i < fg->fonts_count; i++) del_font(fg->fonts + i);
    free(fg->fonts); fg->fonts = NULL;
}

static void
trim_unused_font_groups(void) {
    save_window_font_groups();
    size_t i = 0;
    while (i < num_font_groups) {
        if (font_group_is_unused(font_groups + i)) {
            del_font_group(font_groups + i);
            size_t num_to_right = (--num_font_groups) - i;
            if (!num_to_right) break;
            memmove(font_groups + i, font_groups + 1 + i, num_to_right * sizeof(FontGroup));
        } else i++;
    }
    restore_window_font_groups();
}

static void
add_font_group(void) {
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

static FontGroup*
font_group_for(double font_sz_in_pts, double logical_dpi_x, double logical_dpi_y) {
    for (size_t i = 0; i < num_font_groups; i++) {
        FontGroup *fg = font_groups + i;
        if (fg->font_sz_in_pts == font_sz_in_pts && fg->logical_dpi_x == logical_dpi_x && fg->logical_dpi_y == logical_dpi_y) return fg;
    }
    add_font_group();
    FontGroup *fg = font_groups + num_font_groups - 1;
    zero_at_ptr(fg);
    fg->font_sz_in_pts = font_sz_in_pts;
    fg->logical_dpi_x = logical_dpi_x;
    fg->logical_dpi_y = logical_dpi_y;
    fg->id = ++font_group_id_counter;
    initialize_font_group(fg);
    return fg;
}



// Sprites {{{

static void
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
    max_array_len = MIN(0xfffu, max_array_len_);
}

static void
do_increment(FontGroup *fg, int *error) {
    fg->sprite_tracker.x++;
    if (fg->sprite_tracker.x >= fg->sprite_tracker.xnum) {
        fg->sprite_tracker.x = 0; fg->sprite_tracker.y++;
        fg->sprite_tracker.ynum = MIN(MAX(fg->sprite_tracker.ynum, fg->sprite_tracker.y + 1), fg->sprite_tracker.max_y);
        if (fg->sprite_tracker.y >= fg->sprite_tracker.max_y) {
            fg->sprite_tracker.y = 0; fg->sprite_tracker.z++;
            if (fg->sprite_tracker.z >= MIN((size_t)UINT16_MAX, max_array_len)) *error = 2;
        }
    }
}


static SpritePosition*
sprite_position_for(FontGroup *fg, Font *font, glyph_index *glyphs, unsigned glyph_count, uint8_t ligature_index, unsigned cell_count, int *error) {
    bool created;
    SpritePosition *s = find_or_create_sprite_position(&font->sprite_position_hash_table, glyphs, glyph_count, ligature_index, cell_count, &created);
    if (!s) { *error = 1; return NULL; }
    if (created) {
        s->x = fg->sprite_tracker.x; s->y = fg->sprite_tracker.y; s->z = fg->sprite_tracker.z;
        do_increment(fg, error);
    }
    return s;
}

void
sprite_tracker_current_layout(FONTS_DATA_HANDLE data, unsigned int *x, unsigned int *y, unsigned int *z) {
    FontGroup *fg = (FontGroup*)data;
    *x = fg->sprite_tracker.xnum; *y = fg->sprite_tracker.ynum; *z = fg->sprite_tracker.z;
}


static void
sprite_tracker_set_layout(GPUSpriteTracker *sprite_tracker, unsigned int cell_width, unsigned int cell_height) {
    sprite_tracker->xnum = MIN(MAX(1u, max_texture_size / cell_width), (size_t)UINT16_MAX);
    sprite_tracker->max_y = MIN(MAX(1u, max_texture_size / cell_height), (size_t)UINT16_MAX);
    sprite_tracker->ynum = 1;
    sprite_tracker->x = 0; sprite_tracker->y = 0; sprite_tracker->z = 0;
}
// }}}

static PyObject*
desc_to_face(PyObject *desc, FONTS_DATA_HANDLE fg) {
    PyObject *d = specialize_font_descriptor(desc, fg);
    if (d == NULL) return NULL;
    PyObject *ans = face_from_descriptor(d, fg);
    Py_DECREF(d);
    return ans;
}

static bool
init_font(Font *f, PyObject *face, bool bold, bool italic, bool emoji_presentation) {
    f->face = face; Py_INCREF(f->face);
    f->bold = bold; f->italic = italic; f->emoji_presentation = emoji_presentation;
    f->num_ffs_hb_features = 0;
    const char *psname = postscript_name_for_face(face);
    if (font_feature_settings != NULL){
        PyObject* o = PyDict_GetItemString(font_feature_settings, psname);
        if (o != NULL && PyTuple_Check(o)) {
            Py_ssize_t len = PyTuple_GET_SIZE(o);
            if (len > 0) {
                f->num_ffs_hb_features = len + 1;
                f->ffs_hb_features = calloc(f->num_ffs_hb_features, sizeof(hb_feature_t));
                if (!f->ffs_hb_features) return false;
                for (Py_ssize_t i = 0; i < len; i++) {
                    PyObject* parsed = PyObject_GetAttrString(PyTuple_GET_ITEM(o, i), "parsed");
                    if (parsed) {
                        memcpy(f->ffs_hb_features + i, PyBytes_AS_STRING(parsed), sizeof(hb_feature_t));
                        Py_DECREF(parsed);
                    }
                }
                memcpy(f->ffs_hb_features + len, &hb_features[CALT_FEATURE], sizeof(hb_feature_t));
            }
        }
    }
    if (!f->num_ffs_hb_features) {
        f->ffs_hb_features = calloc(4, sizeof(hb_feature_t));
        if (!f->ffs_hb_features) return false;
        if (strstr(psname, "NimbusMonoPS-") == psname) {
            memcpy(f->ffs_hb_features + f->num_ffs_hb_features++, &hb_features[LIGA_FEATURE], sizeof(hb_feature_t));
            memcpy(f->ffs_hb_features + f->num_ffs_hb_features++, &hb_features[DLIG_FEATURE], sizeof(hb_feature_t));
        }
        memcpy(f->ffs_hb_features + f->num_ffs_hb_features++, &hb_features[CALT_FEATURE], sizeof(hb_feature_t));
    }
    return true;
}

static void
free_font_groups(void) {
    if (font_groups) {
        for (size_t i = 0; i < num_font_groups; i++) del_font_group(font_groups + i);
        free(font_groups); font_groups = NULL;
        font_groups_capacity = 0; num_font_groups = 0;
    }
    free_glyph_cache_global_resources();
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

static void
adjust_metric(unsigned int *metric, float adj, AdjustmentUnit unit, double dpi) {
    if (adj == 0.f) return;
    int a = 0;
    switch (unit) {
        case POINT:
            a = ((long)round((adj * (dpi / 72.0)))); break;
        case PERCENT:
            *metric = (int)roundf((fabsf(adj) * (float)*metric) / 100.f); return;
        case PIXEL:
            a = (int)roundf(adj); break;
    }
    *metric = (a < 0 && -a > (int)*metric) ? 0 : *metric + a;
}

static unsigned int
adjust_ypos(unsigned int pos, unsigned int cell_height, int adjustment) {
    if (adjustment >= 0) adjustment = MIN(adjustment, (int)pos - 1);
    else adjustment = MAX(adjustment, (int)pos - (int)cell_height + 1);
    return pos - adjustment;
}

static void
calc_cell_metrics(FontGroup *fg) {
    unsigned int cell_height, cell_width, baseline, underline_position, underline_thickness, strikethrough_position, strikethrough_thickness;
    cell_metrics(fg->fonts[fg->medium_font_idx].face, &cell_width, &cell_height, &baseline, &underline_position, &underline_thickness, &strikethrough_position, &strikethrough_thickness);
    if (!cell_width) fatal("Failed to calculate cell width for the specified font");
    unsigned int before_cell_height = cell_height;
    unsigned int cw = cell_width, ch = cell_height;
    adjust_metric(&cw, OPT(cell_width).val, OPT(cell_width).unit, fg->logical_dpi_x);
    adjust_metric(&ch, OPT(cell_height).val, OPT(cell_height).unit, fg->logical_dpi_y);
#define MAX_DIM 1000
#define MIN_WIDTH 2
#define MIN_HEIGHT 4
    if (cw >= MIN_WIDTH && cw <= MAX_DIM) cell_width = cw;
    else log_error("Cell width invalid after adjustment, ignoring modify_font cell_width");
    if (ch >= MIN_HEIGHT && ch <= MAX_DIM) cell_height = ch;
    else log_error("Cell height invalid after adjustment, ignoring modify_font cell_height");
    int line_height_adjustment = cell_height - before_cell_height;
    if (cell_height < MIN_HEIGHT) fatal("Line height too small: %u", cell_height);
    if (cell_height > MAX_DIM) fatal("Line height too large: %u", cell_height);
    if (cell_width < MIN_WIDTH) fatal("Cell width too small: %u", cell_width);
    if (cell_width > MAX_DIM) fatal("Cell width too large: %u", cell_width);
#undef MIN_WIDTH
#undef MIN_HEIGHT
#undef MAX_DIM

    unsigned int baseline_before = baseline;
#define A(which, dpi) adjust_metric(&which, OPT(which).val, OPT(which).unit, fg->logical_dpi_##dpi);
    A(underline_thickness, y); A(underline_position, y); A(strikethrough_thickness, y); A(strikethrough_position, y); A(baseline, y);
#undef A

    if (baseline_before != baseline) {
        int adjustment = baseline - baseline_before;
        baseline = adjust_ypos(baseline_before, cell_height, adjustment);
        underline_position = adjust_ypos(underline_position, cell_height, adjustment);
        strikethrough_position = adjust_ypos(strikethrough_position, cell_height, adjustment);
    }

    underline_position = MIN(cell_height - 1, underline_position);
    // ensure there is at least a couple of pixels available to render styled underlines
    // there should be at least one pixel on either side of the underline_position
    if (underline_position > baseline + 1 && underline_position > cell_height - 1)
      underline_position = MAX(baseline + 1, cell_height - 1);
    if (line_height_adjustment > 1) {
        baseline += MIN(cell_height - 1, (unsigned)line_height_adjustment / 2);
        underline_position += MIN(cell_height - 1, (unsigned)line_height_adjustment / 2);
    }
    sprite_tracker_set_layout(&fg->sprite_tracker, cell_width, cell_height);
    fg->cell_width = cell_width; fg->cell_height = cell_height;
    fg->baseline = baseline; fg->underline_position = underline_position; fg->underline_thickness = underline_thickness, fg->strikethrough_position = strikethrough_position, fg->strikethrough_thickness = strikethrough_thickness;
    ensure_canvas_can_fit(fg, 8);
}

static bool
face_has_codepoint(PyObject* face, char_type cp) {
    return glyph_id_for_codepoint(face, cp) > 0;
}

static bool
has_emoji_presentation(CPUCell *cpu_cell, GPUCell *gpu_cell) {
    return gpu_cell->attrs.width == 2 && is_emoji(cpu_cell->ch) && cpu_cell->cc_idx[0] != VS15;
}

static bool
has_cell_text(Font *self, CPUCell *cell) {
    if (!face_has_codepoint(self->face, cell->ch)) return false;
    char_type combining_chars[arraysz(cell->cc_idx)];
    unsigned num_cc = 0;
    for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) {
        const char_type ccp = codepoint_for_mark(cell->cc_idx[i]);
        if (!is_non_rendered_char(ccp)) combining_chars[num_cc++] = ccp;
    }
    if (num_cc == 0) return true;
    if (num_cc == 1) {
        if (face_has_codepoint(self->face, combining_chars[0])) return true;
        char_type ch = 0;
        if (hb_unicode_compose(hb_unicode_funcs_get_default(), cell->ch, combining_chars[0], &ch) && face_has_codepoint(self->face, ch)) return true;
        return false;
    }
    for (unsigned i = 0; i < num_cc; i++) {
        if (!face_has_codepoint(self->face, combining_chars[i])) return false;
    }
    return true;
}

static void
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

PyObject*
iter_fallback_faces(FONTS_DATA_HANDLE fgh, ssize_t *idx) {
    FontGroup *fg = (FontGroup*)fgh;
    if (*idx + 1 < (ssize_t)fg->fallback_fonts_count) {
        *idx += 1;
        return fg->fonts[fg->first_fallback_font_idx + *idx].face;
    }
    return NULL;
}

static ssize_t
load_fallback_font(FontGroup *fg, CPUCell *cell, bool bold, bool italic, bool emoji_presentation) {
    if (fg->fallback_fonts_count > 100) { log_error("Too many fallback fonts"); return MISSING_FONT; }
    ssize_t f;

    if (bold) f = italic ? fg->bi_font_idx : fg->bold_font_idx;
    else f = italic ? fg->italic_font_idx : fg->medium_font_idx;
    if (f < 0) f = fg->medium_font_idx;

    PyObject *face = create_fallback_face(fg->fonts[f].face, cell, bold, italic, emoji_presentation, (FONTS_DATA_HANDLE)fg);
    if (face == NULL) { PyErr_Print(); return MISSING_FONT; }
    if (face == Py_None) { Py_DECREF(face); return MISSING_FONT; }
    if (global_state.debug_font_fallback) output_cell_fallback_data(cell, bold, italic, emoji_presentation, face, true);
    if (PyLong_Check(face)) { ssize_t ans = fg->first_fallback_font_idx + PyLong_AsSsize_t(face); Py_DECREF(face); return ans; }
    set_size_for_face(face, fg->cell_height, true, (FONTS_DATA_HANDLE)fg);

    ensure_space_for(fg, fonts, Font, fg->fonts_count + 1, fonts_capacity, 5, true);
    ssize_t ans = fg->first_fallback_font_idx + fg->fallback_fonts_count;
    Font *af = &fg->fonts[ans];
    if (!init_font(af, face, bold, italic, emoji_presentation)) fatal("Out of memory");
    Py_DECREF(face);
    if (!has_cell_text(af, cell)) {
        if (global_state.debug_font_fallback) {
            printf("The font chosen by the OS for the text: ");
            printf("U+%x ", cell->ch);
            for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) {
                printf("U+%x ", codepoint_for_mark(cell->cc_idx[i]));
            }
            printf("is ");
            PyObject_Print(af->face, stdout, 0);
            printf(" but it does not actually contain glyphs for that text\n");
        }
        del_font(af);
        return MISSING_FONT;
    }
    fg->fallback_fonts_count++;
    fg->fonts_count++;
    return ans;
}

static ssize_t
fallback_font(FontGroup *fg, CPUCell *cpu_cell, GPUCell *gpu_cell) {
    bool bold = gpu_cell->attrs.bold;
    bool italic = gpu_cell->attrs.italic;
    bool emoji_presentation = has_emoji_presentation(cpu_cell, gpu_cell);
    char style = emoji_presentation ? 'a' : 'A';
    if (bold) style += italic ? 3 : 2; else style += italic ? 1 : 0;
    char cell_text[8 + arraysz(cpu_cell->cc_idx) * 4] = {style};
    const size_t cell_text_len = 1 + cell_as_utf8(cpu_cell, true, cell_text + 1, ' ');
    if (fg->fallback_font_map) {
        fallback_font_map_t *s;
        HASH_FIND_STR(fg->fallback_font_map, cell_text, s);
        /* printf("cache %s\n", (s ? "hit" : "miss")); */
        if (s) return s->font_idx;
    }
    ssize_t idx = load_fallback_font(fg, cpu_cell, bold, italic, emoji_presentation);
    fallback_font_map_t *ffm = calloc(1, sizeof(fallback_font_map_t));
    if (ffm) {
        ffm->font_idx = idx;
        ffm->cell_text = strndup(cell_text, cell_text_len);
        if (ffm->cell_text) {
            HASH_ADD_KEYPTR(hh, fg->fallback_font_map, ffm->cell_text, cell_text_len, ffm);
        }
    }
    return idx;
}

static ssize_t
in_symbol_maps(FontGroup *fg, char_type ch) {
    for (size_t i = 0; i < num_symbol_maps; i++) {
        if (symbol_maps[i].left <= ch && ch <= symbol_maps[i].right) return fg->first_symbol_font_idx + symbol_maps[i].font_idx;
    }
    return NO_FONT;
}


// Decides which 'font' to use for a given cell.
//
// Possible results:
// - NO_FONT
// - MISSING_FONT
// - BLANK_FONT
// - BOX_FONT
// - an index in the fonts list
static ssize_t
font_for_cell(FontGroup *fg, CPUCell *cpu_cell, GPUCell *gpu_cell, bool *is_main_font, bool *is_emoji_presentation) {
    *is_main_font = false;
    *is_emoji_presentation = false;
START_ALLOW_CASE_RANGE
    ssize_t ans;
    switch(cpu_cell->ch) {
        case 0:
        case ' ':
        case 0x2002:  // en-space
        case '\t':
        case IMAGE_PLACEHOLDER_CHAR:
            return BLANK_FONT;
        case 0x2500 ... 0x2573:
        case 0x2574 ... 0x259f:
        case 0x2800 ... 0x28ff:
        case 0xe0b0 ... 0xe0bf:    // powerline box drawing
        case 0x1fb00 ... 0x1fb97:  // symbols for legacy computing
        case 0x1fb9a ... 0x1fbae:  // symbols for legacy computing
            if (OPT(box_drawing_main_font) && has_cell_text(fg->fonts + fg->medium_font_idx, cpu_cell)) {
                *is_main_font = true;
                return fg->medium_font_idx;
            }
            return BOX_FONT;
        default:
            *is_emoji_presentation = has_emoji_presentation(cpu_cell, gpu_cell);
            ans = in_symbol_maps(fg, cpu_cell->ch);
            if (ans > -1) return ans;
            switch(gpu_cell->attrs.bold | (gpu_cell->attrs.italic << 1)) {
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
            if (!*is_emoji_presentation && has_cell_text(fg->fonts + ans, cpu_cell)) { *is_main_font = true; return ans; }
            return fallback_font(fg, cpu_cell, gpu_cell);
    }
END_ALLOW_CASE_RANGE
}

static void
set_sprite(GPUCell *cell, sprite_index x, sprite_index y, sprite_index z) {
    cell->sprite_x = x; cell->sprite_y = y; cell->sprite_z = z;
}

// Gives a unique (arbitrary) id to a box glyph
static glyph_index
box_glyph_id(char_type ch) {
START_ALLOW_CASE_RANGE
    switch(ch) {
        case 0x2500 ... 0x259f:
            return ch - 0x2500; // IDs from 0x00 to 0x9f
        case 0xe0b0 ... 0xe0d4:
            return 0xa0 + ch - 0xe0b0;  // IDs from 0xa0 to 0xc4
        case 0x2800 ... 0x28ff:
            return 0xc5 + ch - 0x2800; // IDs from 0xc5 to 0x1c4
        case 0x1fb00 ... 0x1fbae:
            return 0x1c5 + ch - 0x1fb00;  // IDs from 0x1c5 to 0x273
        default:
            return 0xffff;
    }
END_ALLOW_CASE_RANGE
}

static PyObject* box_drawing_function = NULL, *prerender_function = NULL, *descriptor_for_idx = NULL;

void
render_alpha_mask(const uint8_t *alpha_mask, pixel* dest, Region *src_rect, Region *dest_rect, size_t src_stride, size_t dest_stride) {
    for (size_t sr = src_rect->top, dr = dest_rect->top; sr < src_rect->bottom && dr < dest_rect->bottom; sr++, dr++) {
        pixel *d = dest + dest_stride * dr;
        const uint8_t *s = alpha_mask + src_stride * sr;
        for(size_t sc = src_rect->left, dc = dest_rect->left; sc < src_rect->right && dc < dest_rect->right; sc++, dc++) {
            uint8_t src_alpha = d[dc] & 0xff;
            uint8_t alpha = s[sc];
            d[dc] = 0xffffff00 | MAX(alpha, src_alpha);
        }
    }
}

static void
render_box_cell(FontGroup *fg, CPUCell *cpu_cell, GPUCell *gpu_cell) {
    int error = 0;
    glyph_index glyph = box_glyph_id(cpu_cell->ch);
    SpritePosition *sp = sprite_position_for(fg, &fg->fonts[BOX_FONT], &glyph, 1, 0, 1, &error);
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
    ensure_canvas_can_fit(fg, 1);
    Region r = { .right = fg->cell_width, .bottom = fg->cell_height };
    render_alpha_mask(alpha_mask, fg->canvas.buf, &r, &r, fg->cell_width, fg->cell_width);
    current_send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, sp->x, sp->y, sp->z, fg->canvas.buf);
    Py_DECREF(ret);
}

static void
load_hb_buffer(CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells) {
    index_type num;
    hb_buffer_clear_contents(harfbuzz_buffer);
    while (num_cells) {
        uint16_t prev_width = 0;
        for (num = 0; num_cells && num < arraysz(shape_buffer) - 20 - arraysz(first_cpu_cell->cc_idx); first_cpu_cell++, first_gpu_cell++, num_cells--) {
            if (prev_width == 2) { prev_width = 0; continue; }
            shape_buffer[num++] = first_cpu_cell->ch;
            prev_width = first_gpu_cell->attrs.width;
            for (unsigned i = 0; i < arraysz(first_cpu_cell->cc_idx) && first_cpu_cell->cc_idx[i]; i++) {
                shape_buffer[num++] = codepoint_for_mark(first_cpu_cell->cc_idx[i]);
            }
        }
        hb_buffer_add_utf32(harfbuzz_buffer, shape_buffer, num, 0, num);
    }
    hb_buffer_guess_segment_properties(harfbuzz_buffer);
    if (OPT(force_ltr)) hb_buffer_set_direction(harfbuzz_buffer, HB_DIRECTION_LTR);
}


static void
set_cell_sprite(GPUCell *cell, const SpritePosition *sp) {
    cell->sprite_x = sp->x; cell->sprite_y = sp->y; cell->sprite_z = sp->z;
    if (sp->colored) cell->sprite_z |= 0x4000;
}

static pixel*
extract_cell_from_canvas(FontGroup *fg, unsigned int i, unsigned int num_cells) {
    pixel *ans = fg->canvas.buf + (fg->cell_width * fg->cell_height * (fg->canvas.current_cells - 1)), *dest = ans, *src = fg->canvas.buf + (i * fg->cell_width);
    unsigned int stride = fg->cell_width * num_cells;
    for (unsigned int r = 0; r < fg->cell_height; r++, dest += fg->cell_width, src += stride) memcpy(dest, src, fg->cell_width * sizeof(fg->canvas.buf[0]));
    return ans;
}

typedef struct GlyphRenderScratch {
    SpritePosition* *sprite_positions;
    glyph_index *glyphs;
    size_t sz;
} GlyphRenderScratch;
static GlyphRenderScratch global_glyph_render_scratch = {0};

static void
render_group(FontGroup *fg, unsigned int num_cells, unsigned int num_glyphs, CPUCell *cpu_cells, GPUCell *gpu_cells, hb_glyph_info_t *info, hb_glyph_position_t *positions, Font *font, glyph_index *glyphs, unsigned glyph_count, bool center_glyph) {
#define sp global_glyph_render_scratch.sprite_positions
    int error = 0;
    bool all_rendered = true;
    bool is_infinite_ligature = num_cells > 9 && num_glyphs == num_cells;
    for (unsigned i = 0, ligature_index = 0; i < num_cells; i++) {
        bool is_repeat_glyph = is_infinite_ligature && i > 1 && i + 1 < num_cells && glyphs[i] == glyphs[i-1] && glyphs[i] == glyphs[i-2] && glyphs[i] == glyphs[i+1];
        if (is_repeat_glyph) {
            sp[i] = sp[i-1];
        } else {
            sp[i] = sprite_position_for(fg, font, glyphs, glyph_count, ligature_index++, num_cells, &error);
        }
        if (error != 0) { sprite_map_set_error(error); PyErr_Print(); return; }
        if (!sp[i]->rendered) all_rendered = false;
    }
    if (all_rendered) {
        for (unsigned i = 0; i < num_cells; i++) { set_cell_sprite(gpu_cells + i, sp[i]); }
        return;
    }

    ensure_canvas_can_fit(fg, num_cells + 1);
    bool was_colored = gpu_cells->attrs.width == 2 && is_emoji(cpu_cells->ch);
    render_glyphs_in_cells(font->face, font->bold, font->italic, info, positions, num_glyphs, fg->canvas.buf, fg->cell_width, fg->cell_height, num_cells, fg->baseline, &was_colored, (FONTS_DATA_HANDLE)fg, center_glyph);
    if (PyErr_Occurred()) PyErr_Print();

    for (unsigned i = 0; i < num_cells; i++) {
        if (!sp[i]->rendered) {
            sp[i]->rendered = true;
            sp[i]->colored = was_colored;
            pixel *buf = num_cells == 1 ? fg->canvas.buf : extract_cell_from_canvas(fg, i, num_cells);
            current_send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, sp[i]->x, sp[i]->y, sp[i]->z, buf);
        }
        set_cell_sprite(gpu_cells + i, sp[i]);
    }
#undef sp
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
    bool has_special_glyph, started_with_infinite_ligature;
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

static unsigned int
num_codepoints_in_cell(CPUCell *cell) {
    unsigned int ans = 1;
    for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) ans++;
    return ans;
}

static void
shape(CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, hb_font_t *font, Font *fobj, bool disable_ligature) {
    if (group_state.groups_capacity <= 2 * num_cells) {
        group_state.groups_capacity = MAX(128u, 2 * num_cells);  // avoid unnecessary reallocs
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
    zero_at_ptr_count(group_state.groups, group_state.groups_capacity);
    group_state.group_idx = 0;
    group_state.glyph_idx = 0;
    group_state.cell_idx = 0;
    group_state.num_cells = num_cells;
    group_state.first_cpu_cell = first_cpu_cell;
    group_state.first_gpu_cell = first_gpu_cell;
    group_state.last_cpu_cell = first_cpu_cell + (num_cells ? num_cells - 1 : 0);
    group_state.last_gpu_cell = first_gpu_cell + (num_cells ? num_cells - 1 : 0);
    load_hb_buffer(first_cpu_cell, first_gpu_cell, num_cells);

    size_t num_features = fobj->num_ffs_hb_features;
    if (num_features && !disable_ligature) num_features--;  // the last feature is always -calt
    hb_shape(font, harfbuzz_buffer, fobj->ffs_hb_features, num_features);

    unsigned int info_length, positions_length;
    group_state.info = hb_buffer_get_glyph_infos(harfbuzz_buffer, &info_length);
    group_state.positions = hb_buffer_get_glyph_positions(harfbuzz_buffer, &positions_length);
    if (!group_state.info || !group_state.positions) group_state.num_glyphs = 0;
    else group_state.num_glyphs = MIN(info_length, positions_length);
}

static bool
is_special_glyph(glyph_index glyph_id, Font *font, CellData* cell_data) {
    // A glyph is special if the codepoint it corresponds to matches a
    // different glyph in the font
    GlyphProperties *s = find_or_create_glyph_properties(&font->glyph_properties_hash_table, glyph_id);
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

static bool
is_empty_glyph(glyph_index glyph_id, Font *font) {
    // A glyph is empty if its metrics have a width of zero
    GlyphProperties *s = find_or_create_glyph_properties(&font->glyph_properties_hash_table, glyph_id);
    if (s == NULL) return false;
    if (!(s->data & EMPTY_FILLED_MASK)) {
        uint8_t val = is_glyph_empty(font->face, glyph_id) ? EMPTY_VALUE_MASK : 0;
        s->data |= val | EMPTY_FILLED_MASK;
    }
    return s->data & EMPTY_VALUE_MASK;
}

static unsigned int
check_cell_consumed(CellData *cell_data, CPUCell *last_cpu_cell) {
    cell_data->codepoints_consumed++;
    if (cell_data->codepoints_consumed >= cell_data->num_codepoints) {
        uint16_t width = cell_data->gpu_cell->attrs.width;
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
            default: {
                index_type mark = cell_data->cpu_cell->cc_idx[cell_data->codepoints_consumed - 1];
                // VS15/16 cause rendering to break, as they get marked as
                // special glyphs, so map to 0, to avoid that
                cell_data->current_codepoint = (mark == VS15 || mark == VS16) ? 0 : codepoint_for_mark(mark);
                break;
            }
        }
    }
    return 0;
}

static LigatureType
ligature_type_from_glyph_name(const char *glyph_name, SpacerStrategy strategy) {
    const char *p, *m, *s, *e;
    if (strategy == SPACERS_IOSEVKA) {
        p = strrchr(glyph_name, '.');
        m = ".join-m"; s = ".join-l"; e = ".join-r";
    } else {
        p = strrchr(glyph_name, '_');
        m = "_middle.seq"; s = "_start.seq"; e = "_end.seq";
    }
    if (p) {
        if (strcmp(p, m) == 0) return INFINITE_LIGATURE_MIDDLE;
        if (strcmp(p, s) == 0) return INFINITE_LIGATURE_START;
        if (strcmp(p, e) == 0) return INFINITE_LIGATURE_END;
    }
    return LIGATURE_UNKNOWN;
}

#define G(x) (group_state.x)

static void
detect_spacer_strategy(hb_font_t *hbf, Font *font) {
    CPUCell cpu_cells[3] = {{.ch = '='}, {.ch = '='}, {.ch = '='}};
    const CellAttrs w1 = {.width=1};
    GPUCell gpu_cells[3] = {{.attrs = w1}, {.attrs = w1}, {.attrs = w1}};
    shape(cpu_cells, gpu_cells, arraysz(cpu_cells), hbf, font, false);
    font->spacer_strategy = SPACERS_BEFORE;
    if (G(num_glyphs) > 1) {
        glyph_index glyph_id = G(info)[G(num_glyphs) - 1].codepoint;
        bool is_special = is_special_glyph(glyph_id, font, &G(current_cell_data));
        bool is_empty = is_special && is_empty_glyph(glyph_id, font);
        if (is_empty) font->spacer_strategy = SPACERS_AFTER;
    }
    shape(cpu_cells, gpu_cells, 2, hbf, font, false);
    if (G(num_glyphs)) {
        char glyph_name[128]; glyph_name[arraysz(glyph_name)-1] = 0;
        for (unsigned i = 0; i < G(num_glyphs); i++) {
            glyph_index glyph_id = G(info)[i].codepoint;
            hb_font_glyph_to_string(hbf, glyph_id, glyph_name, arraysz(glyph_name)-1);
            char *dot = strrchr(glyph_name, '.');
            if (dot && (!strcmp(dot, ".join-l") || !strcmp(dot, ".join-r") || !strcmp(dot, ".join-m"))) {
                font->spacer_strategy = SPACERS_IOSEVKA;
                break;
            }
        }
    }

    // If spacer_strategy is still default, check ### glyph to to confirm strategy
    // https://github.com/kovidgoyal/kitty/issues/4721
    if (font->spacer_strategy == SPACERS_BEFORE) {
        cpu_cells[0].ch = '#'; cpu_cells[1].ch = '#'; cpu_cells[2].ch = '#';
        shape(cpu_cells, gpu_cells, arraysz(cpu_cells), hbf, font, false);
        if (G(num_glyphs) > 1) {
            glyph_index glyph_id = G(info)[G(num_glyphs) - 1].codepoint;
            bool is_special = is_special_glyph(glyph_id, font, &G(current_cell_data));
            bool is_empty = is_special && is_empty_glyph(glyph_id, font);
            if (is_empty) font->spacer_strategy = SPACERS_AFTER;
        }
    }
}

static LigatureType
ligature_type_for_glyph(hb_font_t *hbf, glyph_index glyph_id, SpacerStrategy strategy) {
    static char glyph_name[128]; glyph_name[arraysz(glyph_name)-1] = 0;
    hb_font_glyph_to_string(hbf, glyph_id, glyph_name, arraysz(glyph_name)-1);
    return ligature_type_from_glyph_name(glyph_name, strategy);
}

#define L INFINITE_LIGATURE_START
#define M INFINITE_LIGATURE_MIDDLE
#define R INFINITE_LIGATURE_END
#define I LIGATURE_UNKNOWN
static bool
is_iosevka_lig_starter(LigatureType before, LigatureType current, LigatureType after) {
    return (current == R || (current == I && (after == L || after == M))) \
                     && \
           !(before == R || before == M);
}

static bool
is_iosevka_lig_ender(LigatureType before, LigatureType current, LigatureType after) {
    return (current == L || (current == I && (before == R || before == M))) \
                     && \
            !(after == L || after == M);
}
#undef L
#undef M
#undef R
#undef I

static LigatureType *ligature_types = NULL;
static size_t ligature_types_sz = 0;

static void
group_iosevka(Font *font, hb_font_t *hbf) {
    // Group as per algorithm discussed in: https://github.com/be5invis/Iosevka/issues/1007
    if (ligature_types_sz <= G(num_glyphs)) {
        ligature_types_sz = G(num_glyphs) + 16;
        ligature_types = realloc(ligature_types, ligature_types_sz * sizeof(ligature_types[0]));
        if (!ligature_types) fatal("Out of memory allocating ligature types array");
    }
    for (size_t i = G(glyph_idx); i < G(num_glyphs); i++) {
        ligature_types[i] = ligature_type_for_glyph(hbf, G(info)[i].codepoint, font->spacer_strategy);
    }

    uint32_t cluster, next_cluster;
    while (G(glyph_idx) < G(num_glyphs) && G(cell_idx) < G(num_cells)) {
        cluster = G(info)[G(glyph_idx)].cluster;
        uint32_t num_codepoints_used_by_glyph = 0;
        bool is_last_glyph = G(glyph_idx) == G(num_glyphs) - 1;
        Group *current_group = G(groups) + G(group_idx);
        if (is_last_glyph) {
            num_codepoints_used_by_glyph = UINT32_MAX;
            next_cluster = 0;
        } else {
            next_cluster = G(info)[G(glyph_idx) + 1].cluster;
            // RTL languages like Arabic have decreasing cluster numbers
            if (next_cluster != cluster) num_codepoints_used_by_glyph = cluster > next_cluster ? cluster - next_cluster : next_cluster - cluster;
        }
        const LigatureType before = G(glyph_idx) ? ligature_types[G(glyph_idx - 1)] : LIGATURE_UNKNOWN;
        const LigatureType current = ligature_types[G(glyph_idx)];
        const LigatureType after = is_last_glyph ? LIGATURE_UNKNOWN : ligature_types[G(glyph_idx + 1)];
        bool end_current_group = false;
        if (current_group->num_glyphs) {
            if (is_iosevka_lig_ender(before, current, after)) end_current_group = true;
            else {
                if (!current_group->num_cells && !current_group->has_special_glyph) {
                    if (is_iosevka_lig_starter(before, current, after)) current_group->has_special_glyph = true;
                    else end_current_group = true;
                }
            }
        }
        if (!current_group->num_glyphs++) {
            if (is_iosevka_lig_starter(before, current, after)) current_group->has_special_glyph = true;
            else end_current_group = true;
            current_group->first_glyph_idx = G(glyph_idx);
            current_group->first_cell_idx = G(cell_idx);
        }
        if (is_last_glyph) {
            // soak up all remaining cells
            if (G(cell_idx) < G(num_cells)) {
                unsigned int num_left = G(num_cells) - G(cell_idx);
                current_group->num_cells += num_left;
                G(cell_idx) += num_left;
            }
        } else {
            unsigned int num_cells_consumed = 0;
            while (num_codepoints_used_by_glyph && G(cell_idx) < G(num_cells)) {
                unsigned int w = check_cell_consumed(&G(current_cell_data), G(last_cpu_cell));
                G(cell_idx) += w;
                num_cells_consumed += w;
                num_codepoints_used_by_glyph--;
            }
            current_group->num_cells += num_cells_consumed;
        }
        if (end_current_group && current_group->num_cells) G(group_idx)++;
        G(glyph_idx)++;
    }
}

static void
group_normal(Font *font, hb_font_t *hbf) {
    /* Now distribute the glyphs into groups of cells
     * Considerations to keep in mind:
     * Group sizes should be as small as possible for best performance
     * Combining chars can result in multiple glyphs rendered into a single cell
     * Emoji and East Asian wide chars can cause a single glyph to be rendered over multiple cells
     * Ligature fonts, take two common approaches:
     * 1. ABC becomes EMPTY, EMPTY, WIDE GLYPH this means we have to render N glyphs in N cells (example Fira Code)
     * 2. ABC becomes WIDE GLYPH this means we have to render one glyph in N cells (example Operator Mono Lig)
     * 3. ABC becomes WIDE GLYPH, EMPTY, EMPTY this means we have to render N glyphs in N cells (example Cascadia Code)
     * 4. Variable length ligatures are identified by a glyph naming convention of _start.seq, _middle.seq and _end.seq
     *    with EMPTY glyphs in the middle or after (both Fira Code and Cascadia Code)
     *
     * We rely on the cluster numbers from harfbuzz to tell us how many unicode codepoints a glyph corresponds to.
     * Then we check if the glyph is a ligature glyph (is_special_glyph) and if it is an empty glyph.
     * We detect if the font uses EMPTY glyphs before or after ligature glyphs (1. or 3. above) by checking what it does for === and ###.
     * Finally we look at the glyph name. These five datapoints give us enough information to satisfy the constraint above,
     * for a wide variety of fonts.
     */
    uint32_t cluster, next_cluster;
    bool add_to_current_group;
    bool prev_glyph_was_inifinte_ligature_end = false;
    while (G(glyph_idx) < G(num_glyphs) && G(cell_idx) < G(num_cells)) {
        glyph_index glyph_id = G(info)[G(glyph_idx)].codepoint;
        LigatureType ligature_type = ligature_type_for_glyph(hbf, glyph_id, font->spacer_strategy);
        cluster = G(info)[G(glyph_idx)].cluster;
        bool is_special = is_special_glyph(glyph_id, font, &G(current_cell_data));
        bool is_empty = is_special && is_empty_glyph(glyph_id, font);
        uint32_t num_codepoints_used_by_glyph = 0;
        bool is_last_glyph = G(glyph_idx) == G(num_glyphs) - 1;
        Group *current_group = G(groups) + G(group_idx);

        if (is_last_glyph) {
            num_codepoints_used_by_glyph = UINT32_MAX;
            next_cluster = 0;
        } else {
            next_cluster = G(info)[G(glyph_idx) + 1].cluster;
            // RTL languages like Arabic have decreasing cluster numbers
            if (next_cluster != cluster) num_codepoints_used_by_glyph = cluster > next_cluster ? cluster - next_cluster : next_cluster - cluster;
        }
        if (!current_group->num_glyphs) {
            add_to_current_group = true;
        } else if (current_group->started_with_infinite_ligature) {
            if (prev_glyph_was_inifinte_ligature_end) add_to_current_group = is_empty && font->spacer_strategy == SPACERS_AFTER;
            else add_to_current_group = ligature_type == INFINITE_LIGATURE_MIDDLE || ligature_type == INFINITE_LIGATURE_END || is_empty;
        } else {
            if (is_special) {
                if (!current_group->num_cells) add_to_current_group = true;
                else if (font->spacer_strategy == SPACERS_BEFORE) add_to_current_group = G(prev_was_empty);
                else add_to_current_group = is_empty;
            } else {
                add_to_current_group = !G(prev_was_special) || !current_group->num_cells;
            }
        }
#if 0
        char ch[8] = {0};
        encode_utf8(G(current_cell_data).current_codepoint, ch);
        printf("\x1b[32m→ %s\x1b[m glyph_idx: %zu glyph_id: %u group_idx: %zu cluster: %u -> %u is_special: %d\n"
                "  num_codepoints_used_by_glyph: %u current_group: (%u cells, %u glyphs) add_to_current_group: %d\n",
                ch, G(glyph_idx), glyph_id, G(group_idx), cluster, next_cluster, is_special,
                num_codepoints_used_by_glyph, current_group->num_cells, current_group->num_glyphs, add_to_current_group);
#endif

        if (!add_to_current_group) { current_group = G(groups) + ++G(group_idx); }
        if (!current_group->num_glyphs++) {
            if (ligature_type == INFINITE_LIGATURE_START || ligature_type == INFINITE_LIGATURE_MIDDLE) current_group->started_with_infinite_ligature = true;
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
                current_group->num_cells += num_left;
                G(cell_idx) += num_left;
            }
        } else {
            unsigned int num_cells_consumed = 0;
            while (num_codepoints_used_by_glyph && G(cell_idx) < G(num_cells)) {
                unsigned int w = check_cell_consumed(&G(current_cell_data), G(last_cpu_cell));
                G(cell_idx) += w;
                num_cells_consumed += w;
                num_codepoints_used_by_glyph--;
            }
            if (num_cells_consumed) {
                current_group->num_cells += num_cells_consumed;
                if (!is_special) {  // not a ligature, end the group
                    G(group_idx)++; current_group = G(groups) + G(group_idx);
                }
            }
        }

        G(prev_was_special) = is_special;
        G(prev_was_empty) = is_empty;
        G(previous_cluster) = cluster;
        prev_glyph_was_inifinte_ligature_end = ligature_type == INFINITE_LIGATURE_END;
        G(glyph_idx)++;
    }
}


static void
shape_run(CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, Font *font, bool disable_ligature) {
    hb_font_t *hbf = harfbuzz_font_for_face(font->face);
    if (font->spacer_strategy == SPACER_STRATEGY_UNKNOWN) detect_spacer_strategy(hbf, font);
    shape(first_cpu_cell, first_gpu_cell, num_cells, hbf, font, disable_ligature);
    if (font->spacer_strategy == SPACERS_IOSEVKA) group_iosevka(font, hbf);
    else group_normal(font, hbf);
#if 0
        static char dbuf[1024];
        // You can also generate this easily using hb-shape --show-extents --cluster-level=1 --shapers=ot /path/to/font/file text
        hb_buffer_serialize_glyphs(harfbuzz_buffer, 0, group_state.num_glyphs, dbuf, sizeof(dbuf), NULL, harfbuzz_font_for_face(font->face), HB_BUFFER_SERIALIZE_FORMAT_TEXT, HB_BUFFER_SERIALIZE_FLAG_DEFAULT | HB_BUFFER_SERIALIZE_FLAG_GLYPH_EXTENTS);
        printf("\n%s\n", dbuf);
#endif
}

static void
collapse_pua_space_ligature(index_type num_cells) {
    Group *g = G(groups);
    G(group_idx) = 0;
    g->num_cells = num_cells;
    // We dont want to render the spaces in a space ligature because
    // there exist stupid fonts like Powerline that have no space glyph,
    // so special case it: https://github.com/kovidgoyal/kitty/issues/1225
    g->num_glyphs = 1;
}

#undef MOVE_GLYPH_TO_NEXT_GROUP

static bool
is_group_calt_ligature(const Group *group) {
    GPUCell *first_cell = G(first_gpu_cell) + group->first_cell_idx;
    return group->num_cells > 1 && group->has_special_glyph && first_cell->attrs.width == 1;
}


static void
split_run_at_offset(index_type cursor_offset, index_type *left, index_type *right) {
    *left = 0; *right = 0;
    for (unsigned idx = 0; idx < G(group_idx) + 1; idx++) {
        Group *group = G(groups) + idx;
        if (group->first_cell_idx <= cursor_offset && cursor_offset < group->first_cell_idx + group->num_cells) {
            if (is_group_calt_ligature(group)) {
                // likely a calt ligature
                *left = group->first_cell_idx; *right = group->first_cell_idx + group->num_cells;
            }
            break;
        }
    }
}


static void
render_groups(FontGroup *fg, Font *font, bool center_glyph) {
    unsigned idx = 0;
    while (idx <= G(group_idx)) {
        Group *group = G(groups) + idx;
        if (!group->num_cells) break;
        /* printf("Group: idx: %u num_cells: %u num_glyphs: %u first_glyph_idx: %u first_cell_idx: %u total_num_glyphs: %zu\n", */
        /*         idx, group->num_cells, group->num_glyphs, group->first_glyph_idx, group->first_cell_idx, group_state.num_glyphs); */
        if (group->num_glyphs) {
            size_t sz = MAX(group->num_glyphs, group->num_cells) + 16;
            if (global_glyph_render_scratch.sz < sz) {
#define a(what) free(global_glyph_render_scratch.what); global_glyph_render_scratch.what = malloc(sz * sizeof(global_glyph_render_scratch.what[0])); if (!global_glyph_render_scratch.what) fatal("Out of memory");
                a(glyphs); a(sprite_positions);
#undef a
                global_glyph_render_scratch.sz = sz;
            }
            for (unsigned i = 0; i < group->num_glyphs; i++) global_glyph_render_scratch.glyphs[i] = G(info)[group->first_glyph_idx + i].codepoint;
            render_group(fg, group->num_cells, group->num_glyphs, G(first_cpu_cell) + group->first_cell_idx, G(first_gpu_cell) + group->first_cell_idx, G(info) + group->first_glyph_idx, G(positions) + group->first_glyph_idx, font, global_glyph_render_scratch.glyphs, group->num_glyphs, center_glyph);
        }
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
    while(num < line->xnum && line->cpu_cells[num].ch) num += line->gpu_cells[num].attrs.width;
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

        PyObject *eg = PyTuple_New(group->num_glyphs);
        for (size_t g = 0; g < group->num_glyphs; g++) PyTuple_SET_ITEM(eg, g, Py_BuildValue("H", G(info)[group->first_glyph_idx + g].codepoint));
        PyList_Append(ans, Py_BuildValue("IIHN", group->num_cells, group->num_glyphs, first_glyph, eg));
        idx++;
    }
    if (face) { Py_CLEAR(face); free_maps(font); free(font); }
    return ans;
}
#undef G

static void
render_run(FontGroup *fg, CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, ssize_t font_idx, bool pua_space_ligature, bool center_glyph, int cursor_offset, DisableLigature disable_ligature_strategy) {
    switch(font_idx) {
        default:
            shape_run(first_cpu_cell, first_gpu_cell, num_cells, &fg->fonts[font_idx], disable_ligature_strategy == DISABLE_LIGATURES_ALWAYS);
            if (pua_space_ligature) collapse_pua_space_ligature(num_cells);
            else if (cursor_offset > -1) { // false if DISABLE_LIGATURES_NEVER
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

static bool
is_non_emoji_dingbat(char_type ch) {
    switch(ch) {
        START_ALLOW_CASE_RANGE
        case 0x2700 ... 0x27bf:
        case 0x1f100 ... 0x1f1ff:
            return !is_emoji(ch);
        END_ALLOW_CASE_RANGE
    }
    return false;
}

static unsigned int
cell_cap_for_codepoint(const char_type cp) {
    unsigned int ans = UINT_MAX;
    for (size_t i = 0; i < num_narrow_symbols; i++) {
        SymbolMap *sm = narrow_symbols + i;
        if (sm->left <= cp && cp <= sm->right) ans = sm->font_idx;
    }
    return ans;
}


void
render_line(FONTS_DATA_HANDLE fg_, Line *line, index_type lnum, Cursor *cursor, DisableLigature disable_ligature_strategy) {
#define RENDER if (run_font_idx != NO_FONT && i > first_cell_in_run) { \
    int cursor_offset = -1; \
    if (disable_ligature_at_cursor && first_cell_in_run <= cursor->x && cursor->x <= i) cursor_offset = cursor->x - first_cell_in_run; \
    render_run(fg, line->cpu_cells + first_cell_in_run, line->gpu_cells + first_cell_in_run, i - first_cell_in_run, run_font_idx, false, center_glyph, cursor_offset, disable_ligature_strategy); \
}
    FontGroup *fg = (FontGroup*)fg_;
    ssize_t run_font_idx = NO_FONT;
    bool center_glyph = false;
    bool disable_ligature_at_cursor = cursor != NULL && disable_ligature_strategy == DISABLE_LIGATURES_CURSOR && lnum == cursor->y;
    index_type first_cell_in_run, i;
    uint16_t prev_width = 0;
    for (i=0, first_cell_in_run=0; i < line->xnum; i++) {
        if (prev_width == 2) { prev_width = 0; continue; }
        CPUCell *cpu_cell = line->cpu_cells + i;
        GPUCell *gpu_cell = line->gpu_cells + i;
        bool is_main_font, is_emoji_presentation;
        ssize_t cell_font_idx = font_for_cell(fg, cpu_cell, gpu_cell, &is_main_font, &is_emoji_presentation);

        if (
                cell_font_idx != MISSING_FONT &&
                ((!is_main_font && !is_emoji_presentation && is_symbol(cpu_cell->ch)) || (cell_font_idx != BOX_FONT && (is_private_use(cpu_cell->ch))) || is_non_emoji_dingbat(cpu_cell->ch))
        ) {
            unsigned int desired_cells = 1;
            if (cell_font_idx > 0) {
                Font *font = (fg->fonts + cell_font_idx);
                glyph_index glyph_id = glyph_id_for_codepoint(font->face, cpu_cell->ch);

                int width = get_glyph_width(font->face, glyph_id);
                desired_cells = (unsigned int)ceilf((float)width / fg->cell_width);
            }
            desired_cells = MIN(desired_cells, cell_cap_for_codepoint(cpu_cell->ch));

            unsigned int num_spaces = 0;
            while (
                    i + num_spaces + 1 < line->xnum
                    && (line->cpu_cells[i+num_spaces+1].ch == ' ' || line->cpu_cells[i+num_spaces+1].ch == 0x2002)  // space or en-space
                    && num_spaces < MAX_NUM_EXTRA_GLYPHS_PUA
                    && num_spaces + 1 < desired_cells
                    ) {
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
                render_run(fg, line->cpu_cells + i, line->gpu_cells + i, num_spaces + 1, cell_font_idx, true, center_glyph, -1, disable_ligature_strategy);
                run_font_idx = NO_FONT;
                first_cell_in_run = i + num_spaces + 1;
                prev_width = line->gpu_cells[i+num_spaces].attrs.width;
                i += num_spaces;
                continue;
            }
        }
        prev_width = gpu_cell->attrs.width;
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

static void
clear_symbol_maps(void) {
    if (symbol_maps) { free(symbol_maps); symbol_maps = NULL; num_symbol_maps = 0; }
    if (narrow_symbols) { free(narrow_symbols); narrow_symbols = NULL; num_narrow_symbols = 0; }
}

typedef struct {
    unsigned int main, bold, italic, bi, num_symbol_fonts;
} DescriptorIndices;

DescriptorIndices descriptor_indices = {0};

static bool
set_symbol_maps(SymbolMap **maps, size_t *num, const PyObject *sm) {
    *num = PyTuple_GET_SIZE(sm);
    *maps = calloc(*num, sizeof(SymbolMap));
    if (*maps == NULL) { PyErr_NoMemory(); return false; }
    for (size_t s = 0; s < *num; s++) {
        unsigned int left, right, font_idx;
        SymbolMap *x = *maps + s;
        if (!PyArg_ParseTuple(PyTuple_GET_ITEM(sm, s), "III", &left, &right, &font_idx)) return NULL;
        x->left = left; x->right = right; x->font_idx = font_idx;
    }
    return true;
}

static PyObject*
set_font_data(PyObject UNUSED *m, PyObject *args) {
    PyObject *sm, *ns;
    Py_CLEAR(box_drawing_function); Py_CLEAR(prerender_function); Py_CLEAR(descriptor_for_idx); Py_CLEAR(font_feature_settings);
    if (!PyArg_ParseTuple(args, "OOOIIIIO!dOO!",
                &box_drawing_function, &prerender_function, &descriptor_for_idx,
                &descriptor_indices.bold, &descriptor_indices.italic, &descriptor_indices.bi, &descriptor_indices.num_symbol_fonts,
                &PyTuple_Type, &sm, &OPT(font_size), &font_feature_settings, &PyTuple_Type, &ns)) return NULL;
    Py_INCREF(box_drawing_function); Py_INCREF(prerender_function); Py_INCREF(descriptor_for_idx); Py_INCREF(font_feature_settings);
    free_font_groups();
    clear_symbol_maps();
    set_symbol_maps(&symbol_maps, &num_symbol_maps, sm);
    set_symbol_maps(&narrow_symbols, &num_narrow_symbols, ns);
    Py_RETURN_NONE;
}

static void
send_prerendered_sprites(FontGroup *fg) {
    int error = 0;
    sprite_index x = 0, y = 0, z = 0;
    // blank cell
    ensure_canvas_can_fit(fg, 1);
    current_send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, x, y, z, fg->canvas.buf);
    do_increment(fg, &error);
    if (error != 0) { sprite_map_set_error(error); PyErr_Print(); fatal("Failed"); }
    PyObject *args = PyObject_CallFunction(prerender_function, "IIIIIIIffdd", fg->cell_width, fg->cell_height, fg->baseline, fg->underline_position, fg->underline_thickness, fg->strikethrough_position, fg->strikethrough_thickness, OPT(cursor_beam_thickness), OPT(cursor_underline_thickness), fg->logical_dpi_x, fg->logical_dpi_y);
    if (args == NULL) { PyErr_Print(); fatal("Failed to pre-render cells"); }
    PyObject *cell_addresses = PyTuple_GET_ITEM(args, 0);
    for (ssize_t i = 0; i < PyTuple_GET_SIZE(cell_addresses); i++) {
        x = fg->sprite_tracker.x; y = fg->sprite_tracker.y; z = fg->sprite_tracker.z;
        if (y > 0) { fatal("Too many pre-rendered sprites for your GPU or the font size is too large"); }
        do_increment(fg, &error);
        if (error != 0) { sprite_map_set_error(error); PyErr_Print(); fatal("Failed"); }
        uint8_t *alpha_mask = PyLong_AsVoidPtr(PyTuple_GET_ITEM(cell_addresses, i));
        ensure_canvas_can_fit(fg, 1);  // clear canvas
        Region r = { .right = fg->cell_width, .bottom = fg->cell_height };
        render_alpha_mask(alpha_mask, fg->canvas.buf, &r, &r, fg->cell_width, fg->cell_width);
        current_send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, x, y, z, fg->canvas.buf);
    }
    Py_CLEAR(args);
}

static size_t
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
    // rescale the symbol_map faces for the desired cell height, this is how fallback fonts are sized as well
    for (size_t i = 0; i < descriptor_indices.num_symbol_fonts; i++) {
        Font *font = fg->fonts + i + fg->first_symbol_font_idx;
        set_size_for_face(font->face, fg->cell_height, true, (FONTS_DATA_HANDLE)fg);
    }
}


void
send_prerendered_sprites_for_window(OSWindow *w) {
    FontGroup *fg = (FontGroup*)w->fonts_data;
    if (!fg->sprite_map) {
        fg->sprite_map = alloc_sprite_map(fg->cell_width, fg->cell_height);
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
    Py_CLEAR(font_feature_settings);
    free_font_groups();
    free(ligature_types);
    if (harfbuzz_buffer) { hb_buffer_destroy(harfbuzz_buffer); harfbuzz_buffer = NULL; }
    free(group_state.groups); group_state.groups = NULL; group_state.groups_capacity = 0;
    free(global_glyph_render_scratch.glyphs);
    free(global_glyph_render_scratch.sprite_positions);
    global_glyph_render_scratch = (GlyphRenderScratch){0};
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
    int error;
    RAII_ALLOC(glyph_index, glyphs, calloc(PyTuple_GET_SIZE(args), sizeof(glyph_index)));
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(args); i++) {
        if (!PyLong_Check(PyTuple_GET_ITEM(args, i))) {
            PyErr_SetString(PyExc_TypeError, "glyph indices must be integers");
            return NULL;
        }
        glyphs[i] = (glyph_index)PyLong_AsUnsignedLong(PyTuple_GET_ITEM(args, i));
        if (PyErr_Occurred()) return NULL;
    }
    FontGroup *fg = font_groups;
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create font group first"); return NULL; }
    SpritePosition *pos = sprite_position_for(fg, &fg->fonts[fg->medium_font_idx], glyphs, PyTuple_GET_SIZE(args), 0, 1, &error);
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
    render_line((FONTS_DATA_HANDLE)font_groups, (Line*)line, 0, NULL, DISABLE_LIGATURES_NEVER);
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
    PyObject *ans = PyBytes_FromStringAndSize(NULL, (size_t)4 * cell_width * cell_height * num_cells);
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
    if (bold) gpu_cell.attrs.bold = true;
    if (italic) gpu_cell.attrs.italic = true;
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

static PyObject*
parse_font_feature(PyObject *self UNUSED, PyObject *feature) {
    if (!PyUnicode_Check(feature)) {
        PyErr_SetString(PyExc_TypeError, "feature must be a unicode object");
        return NULL;
    }
    PyObject *ans = PyBytes_FromStringAndSize(NULL, sizeof(hb_feature_t));
    if (!ans) return NULL;
    if (!hb_feature_from_string(PyUnicode_AsUTF8(feature), -1, (hb_feature_t*)PyBytes_AS_STRING(ans))) {
        Py_CLEAR(ans);
        PyErr_Format(PyExc_ValueError, "%U is not a valid font feature", feature);
        return NULL;
    }
    return ans;
}

static PyMethodDef module_methods[] = {
    METHODB(set_font_data, METH_VARARGS),
    METHODB(free_font_data, METH_NOARGS),
    METHODB(parse_font_feature, METH_O),
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
#define create_feature(feature, where) {\
    if (!hb_feature_from_string(feature, sizeof(feature) - 1, &hb_features[where])) { \
        PyErr_SetString(PyExc_RuntimeError, "Failed to create " feature " harfbuzz feature"); \
        return false; \
    }}
    create_feature("-liga", LIGA_FEATURE);
    create_feature("-dlig", DLIG_FEATURE);
    create_feature("-calt", CALT_FEATURE);
#undef create_feature
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    current_send_sprite_to_gpu = send_sprite_to_gpu;
    return true;
}
