/*
 * vim:fileencoding=utf-8
 * fonts.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"
#include "pyport.h"
#include "charsets.h"
#include "state.h"
#include "emoji.h"
#include "unicode-data.h"
#include "glyph-cache.h"

#define MISSING_GLYPH (NUM_UNDERLINE_STYLES + 2)
#define MAX_NUM_EXTRA_GLYPHS_PUA 4u

#define debug debug_fonts

static PyObject *python_send_to_gpu_impl = NULL;
#define current_send_sprite_to_gpu(...) (python_send_to_gpu_impl ? python_send_to_gpu(__VA_ARGS__) : send_sprite_to_gpu(__VA_ARGS__))
extern PyTypeObject Line_Type;

enum {NO_FONT=-3, MISSING_FONT=-2, BLANK_FONT=-1, BOX_FONT=0};
typedef enum {
    LIGATURE_UNKNOWN, INFINITE_LIGATURE_START, INFINITE_LIGATURE_MIDDLE, INFINITE_LIGATURE_END
} LigatureType;


typedef struct {
    size_t max_y;
    unsigned int x, y, z, xnum, ynum;
} GPUSpriteTracker;


static hb_buffer_t *harfbuzz_buffer = NULL;
static hb_feature_t hb_features[3] = {{0}};
static char_type shape_buffer[4096] = {0};
static size_t max_texture_size = 1024, max_array_len = 1024;
typedef enum { LIGA_FEATURE, DLIG_FEATURE, CALT_FEATURE } HBFeature;

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
    SPRITE_POSITION_MAP_HANDLE sprite_position_hash_table;
    hb_feature_t* ffs_hb_features;
    size_t num_ffs_hb_features;
    GLYPH_PROPERTIES_MAP_HANDLE glyph_properties_hash_table;
    bool bold, italic, emoji_presentation;
    SpacerStrategy spacer_strategy;
} Font;

typedef struct RunFont {
    unsigned scale, subscale, vertical_align, multicell_y;
    ssize_t font_idx;
} RunFont;

typedef struct Canvas {
    pixel *buf;
    unsigned current_cells, alloced_cells, alloced_scale, current_scale;
    size_t size_in_bytes;
} Canvas;

#define NAME fallback_font_map_t
#define KEY_TY const char*
#define VAL_TY size_t
static void free_const(const void* x) { free((void*)x); }
#define KEY_DTOR_FN free_const
#include "kitty-verstable.h"

typedef struct {
    FONTS_DATA_HEAD
    id_type id;
    unsigned int baseline, underline_position, underline_thickness, strikethrough_position, strikethrough_thickness;
    size_t fonts_capacity, fonts_count, fallback_fonts_count;
    ssize_t medium_font_idx, bold_font_idx, italic_font_idx, bi_font_idx, first_symbol_font_idx, first_fallback_font_idx;
    Font *fonts;
    Canvas canvas;
    GPUSpriteTracker sprite_tracker;
    fallback_font_map_t fallback_font_map;
} FontGroup;

static FontGroup* font_groups = NULL;
static size_t font_groups_capacity = 0;
static size_t num_font_groups = 0;
static id_type font_group_id_counter = 0;
static void initialize_font_group(FontGroup *fg);

static void
ensure_canvas_can_fit(FontGroup *fg, unsigned cells, unsigned scale) {
#define cs(cells, scale) (sizeof(fg->canvas.buf[0]) * 3u * cells * fg->cell_width * fg->cell_height * scale * scale)
    size_t size_in_bytes = cs(cells, scale);
    if (size_in_bytes > fg->canvas.size_in_bytes) {
        free(fg->canvas.buf);
        fg->canvas.alloced_cells = MAX(8u, cells + 4u);
        fg->canvas.alloced_scale = MAX(scale, 4u);
        fg->canvas.size_in_bytes = cs(fg->canvas.alloced_cells, fg->canvas.alloced_scale);
        fg->canvas.buf = malloc(fg->canvas.size_in_bytes);
        if (!fg->canvas.buf) fatal("Out of memory allocating canvas");
    }
    fg->canvas.current_cells = cells;
    fg->canvas.current_scale = scale;
    if (fg->canvas.buf) memset(fg->canvas.buf, 0, cs(fg->canvas.current_cells, fg->canvas.alloced_scale));
#undef cs
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
    free_glyph_properties_hash_table(&font->glyph_properties_hash_table);
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
    vt_cleanup(&fg->fallback_font_map);
    for (size_t i = 0; i < fg->fonts_count; i++) del_font(fg->fonts + i);
    free(fg->fonts); fg->fonts = NULL; fg->fonts_count = 0;
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
sprite_position_for(FontGroup *fg, RunFont rf, glyph_index *glyphs, unsigned glyph_count, uint8_t ligature_index, unsigned cell_count, int *error) {
    bool created;
    Font *font = fg->fonts + rf.font_idx;
    SpritePosition *s = find_or_create_sprite_position(
        font->sprite_position_hash_table, glyphs, glyph_count, ligature_index, cell_count,
        rf.scale, rf.subscale, rf.multicell_y, rf.vertical_align, &created);
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
    PyObject *d = specialize_font_descriptor(desc, fg->font_sz_in_pts, fg->logical_dpi_x, fg->logical_dpi_y);
    if (d == NULL) return NULL;
    PyObject *ans = face_from_descriptor(d, fg);
    Py_DECREF(d);
    return ans;
}

static void
add_feature(FontFeatures *output, const hb_feature_t *feature) {
    for (size_t i = 0; i < output->count; i++) {
        if (output->features[i].tag == feature->tag) {
            output->features[i] = *feature;
            return;
        }
    }
    output->features[output->count++] = *feature;
}

static const char*
tag_to_string(uint32_t tag, uint8_t bytes[5]) {
    bytes[0] = (tag >> 24) & 0xff;
    bytes[1] = (tag >> 16) & 0xff;
    bytes[2] = (tag >> 8) & 0xff;
    bytes[3] = (tag) & 0xff;
    bytes[4] = 0;
    return (const char*)bytes;
}

PyObject*
font_features_as_dict(const FontFeatures *font_features) {
    RAII_PyObject(ans, PyDict_New());
    if (!ans) return NULL;
    char buf[256];
    char tag[5] = {0};
    for (size_t i = 0; i < font_features->count; i++) {
        tag_to_string(font_features->features[i].tag, (unsigned char*)tag);
        hb_feature_to_string(&font_features->features[i], buf, arraysz(buf));
        PyObject *t = PyUnicode_FromString(buf);
        if (!t) return NULL;
        if (PyDict_SetItemString(ans, tag, t) != 0) return NULL;
    }
    Py_INCREF(ans); return ans;
}

bool
create_features_for_face(const char *psname, PyObject *features, FontFeatures *output) {
    size_t count_from_descriptor = features ? PyTuple_GET_SIZE(features): 0;
    __typeof__(OPT(font_features).entries) from_opts = NULL;
    if (psname) {
        for (size_t i = 0; i < OPT(font_features).num && !from_opts; i++) {
            __typeof__(OPT(font_features).entries) e = OPT(font_features).entries + i;
            if (strcmp(e->psname, psname) == 0) from_opts = e;
        }
    }
    size_t count_from_opts = from_opts ? from_opts->num : 0;
    output->features = calloc(MAX(2u, count_from_opts + count_from_descriptor), sizeof(output->features[0]));
    if (!output->features) { PyErr_NoMemory(); return false; }
    for (size_t i = 0; i < count_from_opts; i++) {
        add_feature(output, &from_opts->features[i]);
    }
    for (size_t i = 0; i < count_from_descriptor; i++) {
        ParsedFontFeature *f = (ParsedFontFeature*)PyTuple_GET_ITEM(features, i);
        add_feature(output, &f->feature);
    }
    if (!output->count) {
        if (strstr(psname, "NimbusMonoPS-") == psname) {
            add_feature(output, &hb_features[LIGA_FEATURE]);
            add_feature(output, &hb_features[DLIG_FEATURE]);
        }
    }
    return true;
}

static bool
init_hash_tables(Font *f) {
    f->sprite_position_hash_table = create_sprite_position_hash_table();
    if (!f->sprite_position_hash_table) { PyErr_NoMemory(); return false; }
    f->glyph_properties_hash_table = create_glyph_properties_hash_table();
    if (!f->glyph_properties_hash_table) { PyErr_NoMemory(); return false; }
    return true;
}

static bool
init_font(Font *f, PyObject *face, bool bold, bool italic, bool emoji_presentation) {
    f->face = face; Py_INCREF(f->face);
    f->bold = bold; f->italic = italic; f->emoji_presentation = emoji_presentation;
    if (!init_hash_tables(f)) return false;
    const FontFeatures *features = features_for_face(face);
    f->ffs_hb_features = calloc(1 + features->count, sizeof(hb_feature_t));
    if (!f->ffs_hb_features) { PyErr_NoMemory(); return false; }
    f->num_ffs_hb_features = features->count;
    memcpy(f->ffs_hb_features, features->features, sizeof(hb_feature_t) * features->count);
    memcpy(f->ffs_hb_features + f->num_ffs_hb_features++, &hb_features[CALT_FEATURE], sizeof(hb_feature_t));
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
    ensure_canvas_can_fit(fg, 8, 1);
}

static bool
face_has_codepoint(const void* face, char_type cp) {
    return glyph_id_for_codepoint(face, cp) > 0;
}

static bool
has_emoji_presentation(const CPUCell *c, const ListOfChars *lc) {
    if (!c->is_multicell || c->x || c->y || !lc->count) return false;
    return is_emoji(lc->chars[0]) && (lc->count == 1 || lc->chars[1] != VS15);
}

bool
has_cell_text(bool(*has_codepoint)(const void*, char_type ch), const void* face, bool do_debug, const ListOfChars *lc) {
    RAII_ListOfChars(llc);
    if (!has_codepoint(face, lc->chars[0])) goto not_found;
    for (unsigned i = 1; i < lc->count; i++) {
        if (!is_non_rendered_char(lc->chars[i])) {
            ensure_space_for_chars(&llc, llc.count+1);
            llc.chars[llc.count++] = lc->chars[i];
        }
    }
    if (llc.count == 0) return true;
    if (llc.count == 1) {
        if (has_codepoint(face, llc.chars[0])) return true;
        char_type ch = 0;
        if (hb_unicode_compose(hb_unicode_funcs_get_default(), lc->chars[0], llc.chars[0], &ch) && face_has_codepoint(face, ch)) return true;
        goto not_found;
    }
    for (unsigned i = 0; i < llc.count; i++) {
        if (!has_codepoint(face, llc.chars[i])) goto not_found;
    }
    return true;
not_found:
    if (do_debug) {
        debug("The font chosen by the OS for the text: ");
        debug("U+%x ", lc->chars[0]);
        for (unsigned i = 1; i < lc->count; i++) {
            if (lc->chars[i]) debug("U+%x ", lc->chars[i]);
        }
        debug("is "); PyObject_Print((PyObject*)face, stderr, 0);
        debug(" but it does not actually contain glyphs for that text\n");
    }
    return false;
}

static void
output_cell_fallback_data(const ListOfChars *lc, bool bold, bool italic, bool emoji_presentation, PyObject *face) {
    debug("U+%x ", lc->chars[0]);
    for (unsigned i = 1; i < lc->count; i++) debug("U+%x ", lc->chars[i]);
    if (bold) debug("bold ");
    if (italic) debug("italic ");
    if (emoji_presentation) debug("emoji_presentation ");
    if (PyLong_Check(face)) debug("using previous fallback font at index: ");
    PyObject_Print(face, stderr, 0);
    debug("\n");
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
load_fallback_font(FontGroup *fg, const ListOfChars *lc, bool bold, bool italic, bool emoji_presentation) {
    if (fg->fallback_fonts_count > 100) { log_error("Too many fallback fonts"); return MISSING_FONT; }
    ssize_t f;

    if (bold) f = italic ? fg->bi_font_idx : fg->bold_font_idx;
    else f = italic ? fg->italic_font_idx : fg->medium_font_idx;
    if (f < 0) f = fg->medium_font_idx;

    PyObject *face = create_fallback_face(fg->fonts[f].face, lc, bold, italic, emoji_presentation, (FONTS_DATA_HANDLE)fg);
    if (face == NULL) { PyErr_Print(); return MISSING_FONT; }
    if (face == Py_None) { Py_DECREF(face); return MISSING_FONT; }
    if (global_state.debug_font_fallback) output_cell_fallback_data(lc, bold, italic, emoji_presentation, face);
    if (PyLong_Check(face)) { ssize_t ans = fg->first_fallback_font_idx + PyLong_AsSsize_t(face); Py_DECREF(face); return ans; }
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

size_t
chars_as_utf8(const ListOfChars *lc, char *buf, char_type zero_char) {
    size_t n;
    if (lc->count == 1) n = encode_utf8(lc->chars[0] ? lc->chars[0] : zero_char, buf);
    else {
        n = encode_utf8(lc->chars[0], buf);
        if (lc->chars[0] != '\t') for (unsigned i = 1; i < lc->count; i++) n += encode_utf8(lc->chars[i], buf + n);
    }
    buf[n] = 0;
    return n;
}

static ssize_t
fallback_font(FontGroup *fg, const CPUCell *cpu_cell, const GPUCell *gpu_cell, const ListOfChars *lc) {
    bool bold = gpu_cell->attrs.bold;
    bool italic = gpu_cell->attrs.italic;
    bool emoji_presentation = has_emoji_presentation(cpu_cell, lc);
    char style = emoji_presentation ? 'a' : 'A';
    if (bold) style += italic ? 3 : 2; else style += italic ? 1 : 0;
    char cell_text[4 * 32] = {style};
    const size_t cell_text_len = 1 + chars_as_utf8(lc, cell_text + 1, ' ');
    fallback_font_map_t_itr fi = vt_get(&fg->fallback_font_map, cell_text);
    if (!vt_is_end(fi)) return fi.data->val;
    ssize_t idx = load_fallback_font(fg, lc, bold, italic, emoji_presentation);
    const char *alloced_key = strndup(cell_text, cell_text_len);
    if (alloced_key) vt_insert(&fg->fallback_font_map, alloced_key, idx);
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
font_for_cell(FontGroup *fg, const CPUCell *cpu_cell, const GPUCell *gpu_cell, bool *is_main_font, bool *is_emoji_presentation, TextCache *tc, ListOfChars *lc) {
    *is_main_font = false;
    *is_emoji_presentation = false;
    text_in_cell(cpu_cell, tc, lc);
START_ALLOW_CASE_RANGE
    ssize_t ans;
    switch(lc->chars[0]) {
        case 0:
        case ' ':
        case 0x2002:  // en-space
        case '\t':
        case IMAGE_PLACEHOLDER_CHAR:
            return BLANK_FONT;
        case 0x2500 ... 0x2573:
        case 0x2574 ... 0x259f:
        case 0x25d6 ... 0x25d7:
        case 0x25cb: case 0x25c9: case 0x25cf:
        case 0x25dc ... 0x25e5:
        case 0x2800 ... 0x28ff:
        case 0xe0b0 ... 0xe0bf: case 0xe0d6 ... 0xe0d7:    // powerline box drawing
        case 0xee00 ... 0xee0b:    // fira code progress bar/spinner
        case 0x1fb00 ... 0x1fbae:  // symbols for legacy computing
        case 0xf5d0 ... 0xf60d:    // branch drawing characters
            return BOX_FONT;
        default:
            *is_emoji_presentation = has_emoji_presentation(cpu_cell, lc);
            ans = in_symbol_maps(fg, lc->chars[0]);
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
            if (!*is_emoji_presentation && has_cell_text((bool(*)(const void*, char_type))face_has_codepoint, (fg->fonts + ans)->face, false, lc)) { *is_main_font = true; return ans; }
            return fallback_font(fg, cpu_cell, gpu_cell, lc);
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
        case 0x2500 ... 0x25ff:
            return ch - 0x2500; // IDs from 0x00 to 0xff
        case 0xe0b0 ... 0xee0b:
            return 0x100 + ch - 0xe0b0;   // IDs from 0x100 to 0xe5b
        case 0x2800 ... 0x28ff:
            return 0xf00 + ch - 0x2800; // IDs from 0xf00 to 0xfff
        case 0x1fb00 ... 0x1fbae:
            return 0x1000 + ch - 0x1fb00; // IDs from 0x1000 to 0x10ae
        case 0xf5d0 ... 0xf60d:
            return 0x2000 + ch - 0xf5d0; // IDs from 0x2000 to 0x203d
        default:
            return 0xffff;
    }
END_ALLOW_CASE_RANGE
}

static PyObject* box_drawing_function = NULL, *prerender_function = NULL, *descriptor_for_idx = NULL;

void
render_alpha_mask(const uint8_t *alpha_mask, pixel* dest, Region *src_rect, Region *dest_rect, size_t src_stride, size_t dest_stride, pixel color_rgb) {
    pixel col = color_rgb << 8;
    for (size_t sr = src_rect->top, dr = dest_rect->top; sr < src_rect->bottom && dr < dest_rect->bottom; sr++, dr++) {
        pixel *d = dest + dest_stride * dr;
        const uint8_t *s = alpha_mask + src_stride * sr;
        for(size_t sc = src_rect->left, dc = dest_rect->left; sc < src_rect->right && dc < dest_rect->right; sc++, dc++) {
            uint8_t src_alpha = d[dc] & 0xff;
            uint8_t alpha = s[sc];
            d[dc] = col | MAX(alpha, src_alpha);
        }
    }
}

typedef struct GlyphRenderScratch {
    SpritePosition* *sprite_positions;
    glyph_index *glyphs;
    size_t sz;
    ListOfChars *lc;
} GlyphRenderScratch;
static GlyphRenderScratch global_glyph_render_scratch = {0};

static void
ensure_glyph_render_scratch_space(size_t sz) {
#define a global_glyph_render_scratch
    sz += 16;
    if (a.sz < sz) {
        free(a.glyphs); a.glyphs = malloc(sz * sizeof(a.glyphs[0])); if (!a.glyphs) fatal("Out of memory");
        free(a.sprite_positions); a.sprite_positions = malloc(sz * sizeof(SpritePosition*)); if (!a.sprite_positions) fatal("Out of memory");
        a.sz = sz;
        if (!a.lc) {
            a.lc = alloc_list_of_chars();
            if (!a.lc) fatal("Out of memory");
        }
    }
#undef a
}

static void
scaled_cell_dimensions(RunFont rf, unsigned *width, unsigned *height) {
    *width *= rf.scale;
    *height *= rf.scale;
    if (rf.subscale) {
        double frac = 1. / (rf.subscale + 1);
        *width = (unsigned)ceil(frac * *width);
        *height = (unsigned)ceil(frac * *height);
    }
}

static pixel*
extract_cell_from_canvas(FontGroup *fg, unsigned int i, unsigned int num_cells) {
    pixel *ans = fg->canvas.buf + (fg->canvas.size_in_bytes / sizeof(fg->canvas.buf[0]) - fg->cell_width * fg->cell_height);
    pixel *dest = ans, *src = fg->canvas.buf + (i * fg->cell_width);
    unsigned int stride = fg->cell_width * num_cells;
    for (unsigned int r = 0; r < fg->cell_height; r++, dest += fg->cell_width, src += stride) memcpy(dest, src, fg->cell_width * sizeof(fg->canvas.buf[0]));
    return ans;
}

static void
calculate_regions_for_line(RunFont rf, unsigned cell_height, Region *src, Region *dest) {
    unsigned src_height = src->bottom;
    Region src_in_full_coords = *src; unsigned full_dest_height = cell_height * rf.scale;
    if (rf.subscale) {
        switch(rf.vertical_align) {
            case 0: break; // top aligned no change
            case 1: // bottom aligned
                src_in_full_coords.top = full_dest_height - src_height;
                src_in_full_coords.bottom = full_dest_height;
                break;
            case 2: // centered
                src_in_full_coords.top = (full_dest_height - src_height) / 2;
                src_in_full_coords.bottom = src_in_full_coords.top + src_height;
                break;
        }
    }
    Region dest_in_full_coords = {.top = rf.multicell_y * cell_height, .bottom = (rf.multicell_y + 1) * cell_height};
    unsigned intersection_top = MAX(src_in_full_coords.top, dest_in_full_coords.top);
    unsigned intersection_bottom = MIN(src_in_full_coords.bottom, dest_in_full_coords.bottom);
    unsigned src_top_delta = intersection_top - src_in_full_coords.top, src_bottom_delta = src_in_full_coords.bottom - intersection_bottom;
    src->top += src_top_delta; src->bottom = src->bottom > src_bottom_delta ? src->bottom - src_bottom_delta : 0;
    unsigned dest_top_delta = intersection_top - dest_in_full_coords.top, dest_bottom_delta = dest_in_full_coords.bottom - intersection_bottom;
    dest->top = dest_top_delta; dest->bottom = cell_height > dest_bottom_delta ? cell_height - dest_bottom_delta : 0;
}

static void
render_box_cell(FontGroup *fg, RunFont rf, CPUCell *cpu_cell, GPUCell *gpu_cell, const TextCache *tc) {
    int error = 0;
    // We need to render multicell chars for multicell_y > 0 cell_first_char() returns 0 for such cells
    char_type ch = cpu_cell->ch_is_idx ? tc_first_char_at_index(tc, cpu_cell->ch_or_idx) : cpu_cell->ch_or_idx;
    glyph_index glyph = box_glyph_id(ch);
    ensure_glyph_render_scratch_space(rf.scale);
    bool all_rendered = true;
#define sp global_glyph_render_scratch.sprite_positions
    for (unsigned ligature_index = 0; ligature_index < rf.scale; ligature_index++) {
        sp[ligature_index] = sprite_position_for(fg, rf, &glyph, 1, ligature_index, rf.scale, &error);
        if (sp[ligature_index] == NULL) {
            sprite_map_set_error(error); PyErr_Print();
            set_sprite(gpu_cell + ligature_index, 0, 0, 0);
            return;
        }
        set_sprite(gpu_cell + ligature_index, sp[ligature_index]->x, sp[ligature_index]->y, sp[ligature_index]->z);
        sp[ligature_index]->colored = false;
        if (!sp[ligature_index]->rendered) {
            all_rendered = false; sp[ligature_index]->rendered = true;
        }
    }
    if (all_rendered) return;
    unsigned width = fg->cell_width, height = fg->cell_height;
    scaled_cell_dimensions(rf, &width, &height);
    RAII_PyObject(ret, PyObject_CallFunction(box_drawing_function, "IIId", (unsigned int)ch, width, height, (fg->logical_dpi_x + fg->logical_dpi_y) / 2.0));
    if (ret == NULL) { PyErr_Print(); return; }
    uint8_t *alpha_mask = PyLong_AsVoidPtr(PyTuple_GET_ITEM(ret, 0));
    ensure_canvas_can_fit(fg, 2, rf.scale);
    Region src = { .right = width, .bottom = height }, dest = src;
    unsigned dest_stride = rf.scale * fg->cell_width, src_stride = width;
    calculate_regions_for_line(rf, fg->cell_height, &src, &dest);
    render_alpha_mask(alpha_mask, fg->canvas.buf, &src, &dest, src_stride, dest_stride, 0xffffff);
    if (rf.scale == 1) {
        current_send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, sp[0]->x, sp[0]->y, sp[0]->z, fg->canvas.buf);
    } else {
        for (unsigned i = 0; i < rf.scale; i++) {
            pixel *b = extract_cell_from_canvas(fg, i, rf.scale);
            current_send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, sp[i]->x, sp[i]->y, sp[i]->z, b);
        }
    }
#undef sp
}

static void
load_hb_buffer(CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, const TextCache *tc) {
    index_type num;
    hb_buffer_clear_contents(harfbuzz_buffer);
    RAII_ListOfChars(lc);
    while (num_cells) {
        for (num = 0; num_cells; first_cpu_cell++, first_gpu_cell++, num_cells--) {
            text_in_cell(first_cpu_cell, tc, &lc);
            if (first_cpu_cell->is_multicell && (first_cpu_cell->x + first_cpu_cell->y)) continue;
            if (lc.count + num > arraysz(shape_buffer)) break;
            memcpy(shape_buffer + num, lc.chars, lc.count * sizeof(shape_buffer[0]));
            num += lc.count;
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

static void
render_group(FontGroup *fg, unsigned int num_cells, unsigned int num_glyphs, CPUCell *cpu_cells, GPUCell *gpu_cells, hb_glyph_info_t *info, hb_glyph_position_t *positions, RunFont rf, glyph_index *glyphs, unsigned glyph_count, bool center_glyph, const TextCache *tc) {
#define sp global_glyph_render_scratch.sprite_positions
    int error = 0;
    bool all_rendered = true;
    bool is_infinite_ligature = num_cells > 9 && num_glyphs == num_cells;
    Font *font = fg->fonts + rf.font_idx;
    for (unsigned i = 0, ligature_index = 0; i < num_cells; i++) {
        bool is_repeat_glyph = is_infinite_ligature && i > 1 && i + 1 < num_cells && glyphs[i] == glyphs[i-1] && glyphs[i] == glyphs[i-2] && glyphs[i] == glyphs[i+1];
        if (is_repeat_glyph) {
            sp[i] = sp[i-1];
        } else {
            sp[i] = sprite_position_for(fg, rf, glyphs, glyph_count, ligature_index++, num_cells, &error);
        }
        if (error != 0) { sprite_map_set_error(error); PyErr_Print(); return; }
        if (!sp[i]->rendered) all_rendered = false;
    }
    if (all_rendered) {
        for (unsigned i = 0; i < num_cells; i++) { set_cell_sprite(gpu_cells + i, sp[i]); }
        return;
    }

    ensure_canvas_can_fit(fg, num_cells + 1, rf.scale);
    text_in_cell(cpu_cells, tc, global_glyph_render_scratch.lc);
    bool was_colored = has_emoji_presentation(cpu_cells, global_glyph_render_scratch.lc);
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

static void
shape(CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, hb_font_t *font, Font *fobj, bool disable_ligature, const TextCache *tc) {
    if (group_state.groups_capacity <= 2 * num_cells) {
        group_state.groups_capacity = MAX(128u, 2 * num_cells);  // avoid unnecessary reallocs
        group_state.groups = realloc(group_state.groups, sizeof(Group) * group_state.groups_capacity);
        if (!group_state.groups) fatal("Out of memory");
    }
    RAII_ListOfChars(lc);
    text_in_cell(first_cpu_cell, tc, &lc);
    group_state.previous_cluster = UINT32_MAX;
    group_state.prev_was_special = false;
    group_state.prev_was_empty = false;
    group_state.current_cell_data.cpu_cell = first_cpu_cell;
    group_state.current_cell_data.gpu_cell = first_gpu_cell;
    group_state.current_cell_data.num_codepoints = MAX(1u, lc.count);
    group_state.current_cell_data.codepoints_consumed = 0;
    group_state.current_cell_data.current_codepoint = lc.chars[0];
    zero_at_ptr_count(group_state.groups, group_state.groups_capacity);
    group_state.group_idx = 0;
    group_state.glyph_idx = 0;
    group_state.cell_idx = 0;
    group_state.num_cells = num_cells;
    group_state.first_cpu_cell = first_cpu_cell;
    group_state.first_gpu_cell = first_gpu_cell;
    group_state.last_cpu_cell = first_cpu_cell + (num_cells ? num_cells - 1 : 0);
    group_state.last_gpu_cell = first_gpu_cell + (num_cells ? num_cells - 1 : 0);
    load_hb_buffer(first_cpu_cell, first_gpu_cell, num_cells, tc);

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
    GlyphProperties s = find_glyph_properties(font->glyph_properties_hash_table, glyph_id);
    if (!s.special_set) {
        bool is_special = cell_data->current_codepoint ? (
            glyph_id != glyph_id_for_codepoint(font->face, cell_data->current_codepoint) ? true : false)
            :
            false;
        s.special_set = 1; s.special_val = is_special;
        set_glyph_properties(font->glyph_properties_hash_table, glyph_id, s);
    }
    return s.special_val;
}

static bool
is_empty_glyph(glyph_index glyph_id, Font *font) {
    // A glyph is empty if its metrics have a width of zero
    GlyphProperties s = find_glyph_properties(font->glyph_properties_hash_table, glyph_id);
    if (!s.empty_set) {
        s.empty_val = is_glyph_empty(font->face, glyph_id) ? 1 : 0;
        s.empty_set = 1;
        set_glyph_properties(font->glyph_properties_hash_table, glyph_id, s);
    }
    return s.empty_val;
}

static unsigned int
check_cell_consumed(CellData *cell_data, CPUCell *last_cpu_cell, const TextCache *tc) {
    cell_data->codepoints_consumed++;
    if (cell_data->codepoints_consumed >= cell_data->num_codepoints) {
        uint16_t width = 1;
        if (cell_data->cpu_cell->is_multicell) {
            width = cell_data->cpu_cell->width * cell_data->cpu_cell->scale;
        }
        cell_data->cpu_cell += width;
        cell_data->gpu_cell += width;
        cell_data->codepoints_consumed = 0;
        if (cell_data->cpu_cell <= last_cpu_cell) {
            cell_data->num_codepoints = num_codepoints_in_cell(cell_data->cpu_cell, tc);
            cell_data->current_codepoint = cell_first_char(cell_data->cpu_cell, tc);
        } else cell_data->current_codepoint = 0;
        return width;
    } else {
        switch(cell_data->codepoints_consumed) {
            case 0:
                cell_data->current_codepoint = cell_first_char(cell_data->cpu_cell, tc);
                break;
            default: {
                RAII_ListOfChars(lc);
                text_in_cell(cell_data->cpu_cell, tc, &lc);
                char_type cc = lc.chars[cell_data->codepoints_consumed];
                // VS15/16 cause rendering to break, as they get marked as
                // special glyphs, so map to 0, to avoid that
                cell_data->current_codepoint = (cc == VS15 || cc == VS16) ? 0 : cc;
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
detect_spacer_strategy(hb_font_t *hbf, Font *font, const TextCache *tc) {
    CPUCell cpu_cells[3] = {0};
    for (unsigned i = 0; i < arraysz(cpu_cells); i++) cell_set_char(&cpu_cells[i], '=');
    const CellAttrs w1 = {0};
    GPUCell gpu_cells[3] = {{.attrs = w1}, {.attrs = w1}, {.attrs = w1}};
    shape(cpu_cells, gpu_cells, arraysz(cpu_cells), hbf, font, false, tc);
    font->spacer_strategy = SPACERS_BEFORE;
    if (G(num_glyphs) > 1) {
        glyph_index glyph_id = G(info)[G(num_glyphs) - 1].codepoint;
        bool is_special = is_special_glyph(glyph_id, font, &G(current_cell_data));
        bool is_empty = is_special && is_empty_glyph(glyph_id, font);
        if (is_empty) font->spacer_strategy = SPACERS_AFTER;
    }
    shape(cpu_cells, gpu_cells, 2, hbf, font, false, tc);
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

    // If spacer_strategy is still default, check ### glyph to confirm strategy
    // https://github.com/kovidgoyal/kitty/issues/4721
    if (font->spacer_strategy == SPACERS_BEFORE) {
        for (unsigned i = 0; i < arraysz(cpu_cells); i++) cell_set_char(&cpu_cells[i], '#');
        shape(cpu_cells, gpu_cells, arraysz(cpu_cells), hbf, font, false, tc);
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
group_iosevka(Font *font, hb_font_t *hbf, const TextCache *tc) {
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
                unsigned int w = check_cell_consumed(&G(current_cell_data), G(last_cpu_cell), tc);
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
group_normal(Font *font, hb_font_t *hbf, const TextCache *tc) {
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
                unsigned int w = check_cell_consumed(&G(current_cell_data), G(last_cpu_cell), tc);
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
shape_run(CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, Font *font, bool disable_ligature, const TextCache *tc) {
    hb_font_t *hbf = harfbuzz_font_for_face(font->face);
    if (font->spacer_strategy == SPACER_STRATEGY_UNKNOWN) detect_spacer_strategy(hbf, font, tc);
    shape(first_cpu_cell, first_gpu_cell, num_cells, hbf, font, disable_ligature, tc);
    if (font->spacer_strategy == SPACERS_IOSEVKA) group_iosevka(font, hbf, tc);
    else group_normal(font, hbf, tc);
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

static bool
is_group_calt_ligature(const Group *group) {
    if (group->num_cells < 2 || !group->has_special_glyph) return false;
    const CPUCell *first_cell = G(first_cpu_cell) + group->first_cell_idx;
    return !first_cell->is_multicell || first_cell->width == 1;
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
render_groups(FontGroup *fg, RunFont rf, bool center_glyph, const TextCache *tc) {
    unsigned idx = 0;
    while (idx <= G(group_idx)) {
        Group *group = G(groups) + idx;
        if (!group->num_cells) break;
        /* printf("Group: idx: %u num_cells: %u num_glyphs: %u first_glyph_idx: %u first_cell_idx: %u total_num_glyphs: %zu\n", */
        /*         idx, group->num_cells, group->num_glyphs, group->first_glyph_idx, group->first_cell_idx, group_state.num_glyphs); */
        if (group->num_glyphs) {
            ensure_glyph_render_scratch_space(MAX(group->num_glyphs, group->num_cells));
            for (unsigned i = 0; i < group->num_glyphs; i++) global_glyph_render_scratch.glyphs[i] = G(info)[group->first_glyph_idx + i].codepoint;
            render_group(fg, group->num_cells, group->num_glyphs, G(first_cpu_cell) + group->first_cell_idx, G(first_gpu_cell) + group->first_cell_idx, G(info) + group->first_glyph_idx, G(positions) + group->first_glyph_idx, rf, global_glyph_render_scratch.glyphs, group->num_glyphs, center_glyph, tc);
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
    const CPUCell *c;
    while(num < line->xnum && cell_has_text(line->cpu_cells + num)) {
        index_type width = 1;
        if ((c = line->cpu_cells + num)->is_multicell) {
            width = c->width * c->scale;
        }
        num += width;
    }
    PyObject *face = NULL;
    Font *font;
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create at least one font group first"); return NULL; }
    if (path) {
        face = face_from_path(path, index, (FONTS_DATA_HANDLE)font_groups);
        if (face == NULL) return NULL;
        font = calloc(1, sizeof(Font));
        font->face = face;
        if (!init_hash_tables(font)) return NULL;
    } else {
        FontGroup *fg = font_groups;
        font = fg->fonts + fg->medium_font_idx;
    }
    shape_run(line->cpu_cells, line->gpu_cells, num, font, false, line->text_cache);

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
render_run(FontGroup *fg, CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, RunFont rf, bool pua_space_ligature, bool center_glyph, int cursor_offset, DisableLigature disable_ligature_strategy, const TextCache *tc) {
    switch(rf.font_idx) {
        default:
            shape_run(first_cpu_cell, first_gpu_cell, num_cells, &fg->fonts[rf.font_idx], disable_ligature_strategy == DISABLE_LIGATURES_ALWAYS, tc);
            if (pua_space_ligature) collapse_pua_space_ligature(num_cells);
            else if (cursor_offset > -1) { // false if DISABLE_LIGATURES_NEVER
                index_type left, right;
                split_run_at_offset(cursor_offset, &left, &right);
                if (right > left) {
                    if (left) {
                        shape_run(first_cpu_cell, first_gpu_cell, left, &fg->fonts[rf.font_idx], false, tc);
                        render_groups(fg, rf, center_glyph, tc);
                    }
                        shape_run(first_cpu_cell + left, first_gpu_cell + left, right - left, &fg->fonts[rf.font_idx], true, tc);
                        render_groups(fg, rf, center_glyph, tc);
                    if (right < num_cells) {
                        shape_run(first_cpu_cell + right, first_gpu_cell + right, num_cells - right, &fg->fonts[rf.font_idx], false, tc);
                        render_groups(fg, rf, center_glyph, tc);
                    }
                    break;
                }
            }
            render_groups(fg, rf, center_glyph, tc);
            break;
        case BLANK_FONT:
            while(num_cells--) { set_sprite(first_gpu_cell, 0, 0, 0); first_cpu_cell++; first_gpu_cell++; }
            break;
        case BOX_FONT:
            while(num_cells) {
                render_box_cell(fg, rf, first_cpu_cell, first_gpu_cell, tc);
                num_cells -= rf.scale;
                first_cpu_cell += rf.scale;
                first_gpu_cell += rf.scale;
            }
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

static bool
run_fonts_are_equal(const RunFont *a, const RunFont *b) {
    return a->font_idx == b->font_idx && a->scale == b->scale && a->subscale == b->subscale && a->vertical_align == b->vertical_align && a->multicell_y == b->multicell_y;
}

void
render_line(FONTS_DATA_HANDLE fg_, Line *line, index_type lnum, Cursor *cursor, DisableLigature disable_ligature_strategy, ListOfChars *lc) {
#define RENDER if (run_font.font_idx != NO_FONT && i > first_cell_in_run) { \
    int cursor_offset = -1; \
    if (disable_ligature_at_cursor && first_cell_in_run <= cursor->x && cursor->x <= i) cursor_offset = cursor->x - first_cell_in_run; \
    render_run(fg, line->cpu_cells + first_cell_in_run, line->gpu_cells + first_cell_in_run, i - first_cell_in_run, run_font, false, center_glyph, cursor_offset, disable_ligature_strategy, line->text_cache); \
}
    FontGroup *fg = (FontGroup*)fg_;
    RunFont basic_font = {.scale=1, .font_idx = NO_FONT}, run_font = basic_font, cell_font = basic_font;
    bool center_glyph = false;
    bool disable_ligature_at_cursor = cursor != NULL && disable_ligature_strategy == DISABLE_LIGATURES_CURSOR && lnum == cursor->y;
    index_type first_cell_in_run, i;
    for (i=0, first_cell_in_run=0; i < line->xnum; i++) {
        cell_font = basic_font;
        CPUCell *cpu_cell = line->cpu_cells + i;
        if (cpu_cell->is_multicell) {
            if (cpu_cell->x) {
                i += mcd_x_limit(cpu_cell) - cpu_cell->x - 1;
                continue;
            }
            cell_font.scale = cpu_cell->scale; cell_font.subscale = cpu_cell->subscale; cell_font.vertical_align = cpu_cell->vertical_align;
            cell_font.multicell_y = cpu_cell->y;
        }
        text_in_cell(cpu_cell, line->text_cache, lc);
        bool is_main_font, is_emoji_presentation;
        GPUCell *gpu_cell = line->gpu_cells + i;
        const char_type first_ch = lc->chars[0];
        cell_font.font_idx = font_for_cell(fg, cpu_cell, gpu_cell, &is_main_font, &is_emoji_presentation, line->text_cache, lc);
        if (
                cell_font.font_idx != MISSING_FONT &&
                ((!is_main_font && !is_emoji_presentation && is_symbol(first_ch)) || (cell_font.font_idx != BOX_FONT && (is_private_use(first_ch))) || is_non_emoji_dingbat(first_ch))
        ) {
            unsigned int desired_cells = 1;
            if (cell_font.font_idx > 0) {
                Font *font = (fg->fonts + cell_font.font_idx);
                glyph_index glyph_id = glyph_id_for_codepoint(font->face, first_ch);

                int width = get_glyph_width(font->face, glyph_id);
                desired_cells = (unsigned int)ceilf((float)width / fg->cell_width);
            }
            desired_cells = MIN(desired_cells, cell_cap_for_codepoint(first_ch));

            unsigned int num_spaces = 0;
            while (
                    i + num_spaces + 1 < line->xnum
                    && (cell_is_char(line->cpu_cells + i + num_spaces + 1, ' ') || cell_is_char(line->cpu_cells + i + num_spaces + 1, 0x2002))  // space or en-space
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
                render_run(fg, line->cpu_cells + i, line->gpu_cells + i, num_spaces + 1, cell_font, true, center_glyph, -1, disable_ligature_strategy, line->text_cache);
                run_font = basic_font;
                first_cell_in_run = i + num_spaces + 1;
                i += num_spaces;
                continue;
            }
        }
        if (run_font.font_idx == NO_FONT) run_font = cell_font;
        if (run_fonts_are_equal(&run_font, &cell_font)) continue;
        RENDER
        run_font = cell_font;
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
    Py_CLEAR(box_drawing_function); Py_CLEAR(prerender_function); Py_CLEAR(descriptor_for_idx);
    if (!PyArg_ParseTuple(args, "OOOIIIIO!dO!",
                &box_drawing_function, &prerender_function, &descriptor_for_idx,
                &descriptor_indices.bold, &descriptor_indices.italic, &descriptor_indices.bi, &descriptor_indices.num_symbol_fonts,
                &PyTuple_Type, &sm, &OPT(font_size), &PyTuple_Type, &ns)) return NULL;
    Py_INCREF(box_drawing_function); Py_INCREF(prerender_function); Py_INCREF(descriptor_for_idx);
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
    ensure_canvas_can_fit(fg, 1, 1);
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
        ensure_canvas_can_fit(fg, 1, 1);  // clear canvas
        Region r = { .right = fg->cell_width, .bottom = fg->cell_height };
        render_alpha_mask(alpha_mask, fg->canvas.buf, &r, &r, fg->cell_width, fg->cell_width, 0xffffff);
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
    if (!init_hash_tables(fg->fonts)) fatal("Out of memory");
    vt_init(&fg->fallback_font_map);
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
    free_font_groups();
    free(ligature_types);
    if (harfbuzz_buffer) { hb_buffer_destroy(harfbuzz_buffer); harfbuzz_buffer = NULL; }
    free(group_state.groups); group_state.groups = NULL; group_state.groups_capacity = 0;
    free(global_glyph_render_scratch.glyphs);
    free(global_glyph_render_scratch.sprite_positions);
    if (global_glyph_render_scratch.lc) { cleanup_list_of_chars(global_glyph_render_scratch.lc); free(global_glyph_render_scratch.lc); }
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
    RunFont rf = {.scale = 1, .font_idx=fg->medium_font_idx};
    SpritePosition *pos = sprite_position_for(fg, rf, glyphs, PyTuple_GET_SIZE(args), 0, 1, &error);
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
    Py_RETURN_NONE;
}

static PyObject*
test_render_line(PyObject UNUSED *self, PyObject *args) {
    PyObject *line;
    if (!PyArg_ParseTuple(args, "O!", &Line_Type, &line)) return NULL;
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create font group first"); return NULL; }
    RAII_ListOfChars(lc);
    render_line((FONTS_DATA_HANDLE)font_groups, (Line*)line, 0, NULL, DISABLE_LIGATURES_NEVER, &lc);
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
current_fonts(PyObject *self UNUSED, PyObject *args) {
    unsigned long long os_window_id = 0;
    if (!PyArg_ParseTuple(args, "|K", &os_window_id)) return NULL;
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create font group first"); return NULL; }
    FontGroup *fg = font_groups;
    if (os_window_id) {
        OSWindow *os_window = os_window_for_id(os_window_id);
        if (!os_window) { PyErr_SetString(PyExc_KeyError, "no oswindow with the specified id exists"); return NULL; }
        fg = (FontGroup*)os_window->fonts_data;
    }
    RAII_PyObject(ans, PyDict_New());
    if (!ans) return NULL;
#define SET(key, val) {if (PyDict_SetItemString(ans, #key, fg->fonts[val].face) != 0) { return NULL; }}
    SET(medium, fg->medium_font_idx);
    if (fg->bold_font_idx > 0) SET(bold, fg->bold_font_idx);
    if (fg->italic_font_idx > 0) SET(italic, fg->italic_font_idx);
    if (fg->bi_font_idx > 0) SET(bi, fg->bi_font_idx);
    unsigned num_symbol_fonts = fg->first_fallback_font_idx - fg->first_symbol_font_idx;
    RAII_PyObject(ss, PyTuple_New(num_symbol_fonts));
    if (!ss) return NULL;
    for (size_t i = 0; i < num_symbol_fonts; i++) {
        Py_INCREF(fg->fonts[fg->first_symbol_font_idx + i].face);
        PyTuple_SET_ITEM(ss, i, fg->fonts[fg->first_symbol_font_idx + i].face);
    }
    if (PyDict_SetItemString(ans, "symbol", ss) != 0) return NULL;
    RAII_PyObject(ff, PyTuple_New(fg->fallback_fonts_count));
    if (!ff) return NULL;
    for (size_t i = 0; i < fg->fallback_fonts_count; i++) {
        Py_INCREF(fg->fonts[fg->first_fallback_font_idx + i].face);
        PyTuple_SET_ITEM(ff, i, fg->fonts[fg->first_fallback_font_idx + i].face);
    }
    if (PyDict_SetItemString(ans, "fallback", ff) != 0) return NULL;
#define p(x) { RAII_PyObject(t, PyFloat_FromDouble(fg->x)); if (!t) return NULL; if (PyDict_SetItemString(ans, #x, t) != 0) return NULL; }
    p(font_sz_in_pts); p(logical_dpi_x); p(logical_dpi_y);
#undef p
    Py_INCREF(ans);
    return ans;
#undef SET
}

static PyObject*
get_fallback_font(PyObject UNUSED *self, PyObject *args) {
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create font group first"); return NULL; }
    PyObject *text;
    int bold, italic;
    if (!PyArg_ParseTuple(args, "Upp", &text, &bold, &italic)) return NULL;
    GPUCell gpu_cell = {0}; CPUCell cpu_cell = {0};
    RAII_ListOfChars(lc); lc.count = PyUnicode_GET_LENGTH(text);
    ensure_space_for_chars(&lc, lc.count);
    if (!PyUnicode_AsUCS4(text, lc.chars, lc.capacity, 1)) return NULL;
    if (bold) gpu_cell.attrs.bold = true;
    if (italic) gpu_cell.attrs.italic = true;
    FontGroup *fg = font_groups;
    ssize_t ans = fallback_font(fg, &cpu_cell, &gpu_cell, &lc);
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

PyTypeObject ParsedFontFeature_Type;

ParsedFontFeature*
parse_font_feature(const char *spec) {
    ParsedFontFeature *self = (ParsedFontFeature*)ParsedFontFeature_Type.tp_alloc(&ParsedFontFeature_Type, 0);
    if (self != NULL) {
        if (!hb_feature_from_string(spec, -1, &self->feature)) {
            PyErr_Format(PyExc_ValueError, "%s is not a valid font feature", self);
            Py_CLEAR(self);
        }
    }
    return self;
}

static PyObject *
parsed_font_feature_new(PyTypeObject *type UNUSED, PyObject *args, PyObject *kwds UNUSED) {
    const char *s;
    if (!PyArg_ParseTuple(args, "s", &s)) return NULL;
    return (PyObject*)parse_font_feature(s);
}

static PyObject*
parsed_font_feature_str(PyObject *self_) {
    char buf[128];
    hb_feature_to_string(&((ParsedFontFeature*)self_)->feature, buf, arraysz(buf));
    return PyUnicode_FromString(buf);
}

static PyObject*
parsed_font_feature_repr(PyObject *self_) {
    RAII_PyObject(s, parsed_font_feature_str(self_));
    return s ? PyObject_Repr(s) : NULL;
}


static PyObject*
parsed_font_feature_cmp(PyObject *self, PyObject *other, int op) {
    if (op != Py_EQ && op != Py_NE) return Py_NotImplemented;
    if (!PyObject_TypeCheck(other, &ParsedFontFeature_Type)) {
        if (op == Py_EQ) Py_RETURN_FALSE;
        Py_RETURN_TRUE;
    }
    ParsedFontFeature *a = (ParsedFontFeature*)self, *b = (ParsedFontFeature*)other;
    PyObject *ret = Py_True;
    if (memcmp(&a->feature, &b->feature, sizeof(hb_feature_t)) == 0) {
        if (op == Py_NE) ret = Py_False;
    } else {
        if (op == Py_EQ) ret = Py_False;
    }
    Py_INCREF(ret); return ret;
}

static Py_hash_t
parsed_font_feature_hash(PyObject *s) {
    ParsedFontFeature *self = (ParsedFontFeature*)s;
    if (!self->hash_computed) {
        self->hash_computed = true;
        self->hashval = vt_hash_bytes(&self->feature, sizeof(hb_feature_t));
    }
    return self->hashval;
}

static PyObject*
parsed_font_feature_call(PyObject *s, PyObject *args, PyObject *kwargs UNUSED) {
    ParsedFontFeature *self = (ParsedFontFeature*)s;
    void *dest = PyLong_AsVoidPtr(args);
    memcpy(dest, &self->feature, sizeof(hb_feature_t));
    Py_RETURN_NONE;
}

PyTypeObject ParsedFontFeature_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "kitty.fast_data_types.ParsedFontFeature",
    .tp_basicsize = sizeof(ParsedFontFeature),
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "FontFeature",
    .tp_new = parsed_font_feature_new,
    .tp_str = parsed_font_feature_str,
    .tp_repr = parsed_font_feature_repr,
    .tp_richcompare = parsed_font_feature_cmp,
    .tp_hash = parsed_font_feature_hash,
    .tp_call = parsed_font_feature_call,
};

static PyObject*
pyspecialize_font_descriptor(PyObject *self UNUSED, PyObject *args) {
    PyObject *desc; double font_sz, dpi_x, dpi_y;
    if (!PyArg_ParseTuple(args, "Offf", &desc, &font_sz, &dpi_x, &dpi_y)) return NULL;
    return specialize_font_descriptor(desc, font_sz, dpi_x, dpi_y);
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
    METHODB(current_fonts, METH_VARARGS),
    METHODB(test_render_line, METH_VARARGS),
    METHODB(get_fallback_font, METH_VARARGS),
    {"specialize_font_descriptor", (PyCFunction)pyspecialize_font_descriptor, METH_VARARGS, ""},
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
    if (PyType_Ready(&ParsedFontFeature_Type) < 0) return 0;
    if (PyModule_AddObject(module, "ParsedFontFeature", (PyObject *)&ParsedFontFeature_Type) != 0) return 0;
    Py_INCREF(&ParsedFontFeature_Type);

    return true;
}
