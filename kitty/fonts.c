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
#include "char-props.h"
#include "decorations.h"
#include "glyph-cache.h"

#define MISSING_GLYPH 1
#define MAX_NUM_EXTRA_GLYPHS_PUA 4u

#define debug debug_fonts

static PyObject *python_send_to_gpu_impl = NULL;
extern PyTypeObject Line_Type;

enum {NO_FONT=-3, MISSING_FONT=-2, BLANK_FONT=-1, BOX_FONT=0};
typedef enum {
    LIGATURE_UNKNOWN, INFINITE_LIGATURE_START, INFINITE_LIGATURE_MIDDLE, INFINITE_LIGATURE_END
} LigatureType;


typedef struct {
    unsigned x, y, z, xnum, ynum, max_y;
} GPUSpriteTracker;

typedef struct RunFont {
    unsigned scale, subscale_n, subscale_d, multicell_y;
    union {
        struct { uint8_t vertical: 4; uint8_t horizontal: 4; };
        uint8_t val;
    } align;
    ssize_t font_idx;
} RunFont;

static hb_buffer_t *harfbuzz_buffer = NULL;
static hb_feature_t hb_features[3] = {{0}};
static struct { char_type *codepoints; size_t capacity; } shape_buffer = {0};
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

typedef struct Canvas {
    pixel *buf;
    uint8_t *alpha_mask;
    unsigned current_cells, alloced_cells, alloced_scale, current_scale;
    size_t size_in_bytes, alpha_mask_sz_in_bytes;
} Canvas;

#define NAME fallback_font_map_t
#define KEY_TY const char*
#define VAL_TY size_t
static void free_const(const void* x) { free((void*)x); }
#define KEY_DTOR_FN free_const
#include "kitty-verstable.h"

typedef struct ScaledFontData {
    FontCellMetrics fcm;
    double font_sz_in_pts;
} ScaledFontData;

#define NAME scaled_font_map_t
#define KEY_TY float
#define VAL_TY ScaledFontData
#define HASH_FN vt_hash_float
#define CMPR_FN vt_cmpr_float
#include "kitty-verstable.h"

typedef union DecorationsKey {
    struct { uint8_t scale : 8, subscale_n : 8, subscale_d : 8, align : 8, multicell_y : 8, u1 : 8, u2 : 8, u3 : 8; };
    uint64_t val;
} DecorationsKey;
static_assert(sizeof(DecorationsKey) == sizeof(uint64_t), "Fix the ordering of DecorationsKey");

typedef struct DecorationMetadata {
    sprite_index start_idx;
    DecorationGeometry underline_region;
} DecorationMetadata;

static uint64_t hash_decorations_key(DecorationsKey k) { return vt_hash_integer(k.val); }
static bool cmpr_decorations_key(DecorationsKey a, DecorationsKey b) { return a.val == b.val; }
#define NAME decorations_index_map_t
#define KEY_TY DecorationsKey
#define VAL_TY DecorationMetadata
#define HASH_FN hash_decorations_key
#define CMPR_FN cmpr_decorations_key
#include "kitty-verstable.h"


typedef struct {
    FONTS_DATA_HEAD
    id_type id;
    size_t fonts_capacity, fonts_count, fallback_fonts_count;
    ssize_t medium_font_idx, bold_font_idx, italic_font_idx, bi_font_idx, first_symbol_font_idx, first_fallback_font_idx;
    Font *fonts;
    Canvas canvas;
    GPUSpriteTracker sprite_tracker;
    fallback_font_map_t fallback_font_map;
    scaled_font_map_t scaled_font_map;
    decorations_index_map_t decorations_index_map;
} FontGroup;

static FontGroup* font_groups = NULL;
static size_t font_groups_capacity = 0;
static size_t num_font_groups = 0;
static id_type font_group_id_counter = 0;
static void initialize_font_group(FontGroup *fg);

static void
display_rgba_data(const pixel *b, unsigned width, unsigned height) {
    RAII_PyObject(m, PyImport_ImportModule("kitty.fonts.render"));
    RAII_PyObject(f, PyObject_GetAttrString(m, "show"));
    RAII_PyObject(data, PyMemoryView_FromMemory((char*)b, (Py_ssize_t)width * height * sizeof(b[0]), PyBUF_READ));
    RAII_PyObject(ret, PyObject_CallFunction(f, "OII", data, width, height));
    if (ret == NULL) PyErr_Print();
}

static void
dump_sprite(pixel *b, unsigned width, unsigned height) {
    for (unsigned y = 0; y < height; y++) {
        pixel *p = b + y * width;
        for (unsigned x = 0; x < width; x++) printf("%d ", p[x] != 0);
        printf("\n");
    }
}

static void
python_send_to_gpu(FontGroup *fg, sprite_index idx, pixel *buf) {
    if (0) dump_sprite(buf, fg->fcm.cell_width, fg->fcm.cell_height);
    unsigned int x, y, z;
    sprite_index_to_pos(idx, fg->sprite_tracker.xnum, fg->sprite_tracker.ynum, &x, &y, &z);
    const size_t sprite_size = (size_t)fg->fcm.cell_width * fg->fcm.cell_height;
    PyObject *ret = PyObject_CallFunction(python_send_to_gpu_impl, "IIIy#", x, y, z, buf, sprite_size * sizeof(buf[0]));
    if (ret == NULL) PyErr_Print();
    else Py_DECREF(ret);
}

static void
ensure_canvas_can_fit(FontGroup *fg, unsigned cells, unsigned scale) {
#define cs(cells, scale) (sizeof(fg->canvas.buf[0]) * 3u * cells * fg->fcm.cell_width * (fg->fcm.cell_height + 1) * scale * scale)
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
    if (fg->canvas.buf) memset(fg->canvas.buf, 0, cs(cells, scale));
#undef cs
    size_in_bytes = (sizeof(fg->canvas.alpha_mask[0]) * SUPERSAMPLE_FACTOR * SUPERSAMPLE_FACTOR * 2 * fg->fcm.cell_width * fg->fcm.cell_height * scale * scale);
    if (size_in_bytes > fg->canvas.alpha_mask_sz_in_bytes) {
        fg->canvas.alpha_mask_sz_in_bytes = size_in_bytes;
        fg->canvas.alpha_mask = malloc(fg->canvas.alpha_mask_sz_in_bytes);
        if (!fg->canvas.alpha_mask) fatal("Out of memory allocating canvas");
    }
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
    free(fg->canvas.buf); free(fg->canvas.alpha_mask); fg->canvas = (Canvas){0};
    free_sprite_data((FONTS_DATA_HANDLE)fg);
    vt_cleanup(&fg->fallback_font_map);
    vt_cleanup(&fg->scaled_font_map);
    vt_cleanup(&fg->decorations_index_map);
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

void
sprite_tracker_set_limits(size_t max_texture_size_, size_t max_array_len_) {
    max_texture_size = max_texture_size_;
    max_array_len = MIN(0xfffu, max_array_len_);
}

static bool
do_increment(FontGroup *fg) {
    fg->sprite_tracker.x++;
    if (fg->sprite_tracker.x >= fg->sprite_tracker.xnum) {
        fg->sprite_tracker.x = 0; fg->sprite_tracker.y++;
        fg->sprite_tracker.ynum = MIN(MAX(fg->sprite_tracker.ynum, fg->sprite_tracker.y + 1), fg->sprite_tracker.max_y);
        if (fg->sprite_tracker.y >= fg->sprite_tracker.max_y) {
            fg->sprite_tracker.y = 0; fg->sprite_tracker.z++;
            if (fg->sprite_tracker.z >= MIN((size_t)UINT16_MAX, max_array_len)) { PyErr_SetString(PyExc_RuntimeError, "Out of texture space for sprites"); return false; }
        }
    }
    return true;
}

static uint32_t
current_sprite_index(const GPUSpriteTracker *sprite_tracker) {
    return sprite_tracker->z * (sprite_tracker->xnum * sprite_tracker->ynum) + sprite_tracker->y * sprite_tracker->xnum + sprite_tracker->x;
}

static SpritePosition*
sprite_position_for(FontGroup *fg, RunFont rf, glyph_index *glyphs, unsigned glyph_count, uint8_t ligature_index, unsigned cell_count) {
    bool created;
    Font *font = fg->fonts + rf.font_idx;
    uint8_t subscale = ((rf.subscale_n & 0xf) << 4) | (rf.subscale_d & 0xf);
    SpritePosition *s = find_or_create_sprite_position(
        font->sprite_position_hash_table, glyphs, glyph_count, ligature_index, cell_count,
        rf.scale, subscale, rf.multicell_y, rf.align.val, &created);
    if (!s) { PyErr_NoMemory(); return NULL; }
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

static void
calculate_underline_exclusion_zones(pixel *buf, const FontGroup *fg, DecorationGeometry dg, FontCellMetrics scaled_metrics) {
    pixel *ans = buf + fg->fcm.cell_height * fg->fcm.cell_width;
    const unsigned bottom = MIN(dg.top + dg.height, fg->fcm.cell_height);
    unsigned thickness = scaled_metrics.underline_thickness;
    switch(OPT(underline_exclusion.unit)) {
        case 2:
            thickness = ((long)round((OPT(underline_exclusion).thickness * (fg->logical_dpi_x / 72.0)))); break;
        case 1:
            thickness = (unsigned)OPT(underline_exclusion).thickness; break;
        default:
            thickness = (unsigned)(OPT(underline_exclusion).thickness * thickness); break;
    }
    thickness = MAX(1u, thickness);
    if (0) printf("dg: %u %u cell_height: %u scaled_cell_height: %u\n", dg.top, dg.height, fg->fcm.cell_height, scaled_metrics.cell_height);
    if (0) { display_rgba_data(buf, fg->fcm.cell_width, fg->fcm.cell_height); printf("\n"); }
    unsigned max_overlap = 0;
#define is_rendered(x, y) ((buf[(y) * fg->fcm.cell_width + (x)] & 0x000000ff) > 0)
    for (unsigned x = 0; x < fg->fcm.cell_width; x++) {
        for (unsigned y = dg.top; y < bottom && !ans[x]; y++) {
            if (is_rendered(x, y)) {
                while (y + 1 < bottom && is_rendered(x, y + 1)) y++;
                max_overlap = MAX(max_overlap, y - dg.top + 1);
                unsigned start_x = x > thickness ? x - thickness : 0;
                for (unsigned dx = start_x; dx < MIN(x + thickness, fg->fcm.cell_width); dx++) ans[dx] = 0xffffffff;
                break;
            }
        }
    }
#undef is_rendered
    if (dg.height > 1 && max_overlap <= dg.height / 2) {
        // ignore half thickness overlap as this is likely a false positive not an actual descender
        memset(ans, 0, fg->fcm.cell_width * sizeof(ans[0]));
    }
    if (0) dump_sprite(ans, fg->fcm.cell_width, 1);
}

static sprite_index
current_send_sprite_to_gpu(FontGroup *fg, pixel *buf, DecorationMetadata dec, FontCellMetrics scaled_metrics) {
    sprite_index ans = current_sprite_index(&fg->sprite_tracker);
    if (!do_increment(fg)) return 0;
    if (python_send_to_gpu_impl) { python_send_to_gpu(fg, ans, buf); return ans; }
    if (dec.underline_region.height && OPT(underline_exclusion).thickness > 0) calculate_underline_exclusion_zones(
            buf, fg, dec.underline_region, scaled_metrics);
    send_sprite_to_gpu((FONTS_DATA_HANDLE)fg, ans, buf, dec.start_idx);
    if (0) { printf("Sprite: %u dec_idx: %u\n", ans, dec.start_idx); display_rgba_data(buf, fg->fcm.cell_width, fg->fcm.cell_height); printf("\n"); }
    return ans;
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
    if (features->count) memcpy(f->ffs_hb_features, features->features, sizeof(hb_feature_t) * features->count);
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
calc_cell_metrics(FontGroup *fg, PyObject *face) {
    fg->fcm = cell_metrics(face);
    if (!fg->fcm.cell_width) fatal("Failed to calculate cell width for the specified font");
    unsigned int before_cell_height = fg->fcm.cell_height;
    unsigned int cw = fg->fcm.cell_width, ch = fg->fcm.cell_height;
    adjust_metric(&cw, OPT(cell_width).val, OPT(cell_width).unit, fg->logical_dpi_x);
    adjust_metric(&ch, OPT(cell_height).val, OPT(cell_height).unit, fg->logical_dpi_y);
#define MAX_DIM 1000
#define MIN_WIDTH 2
#define MIN_HEIGHT 4
    if (cw >= MIN_WIDTH && cw <= MAX_DIM) fg->fcm.cell_width = cw;
    else log_error("Cell width invalid after adjustment, ignoring modify_font cell_width");
    if (ch >= MIN_HEIGHT && ch <= MAX_DIM) fg->fcm.cell_height = ch;
    else log_error("Cell height invalid after adjustment, ignoring modify_font cell_height");
    int line_height_adjustment = fg->fcm.cell_height - before_cell_height;
    if (fg->fcm.cell_height < MIN_HEIGHT) fatal("Line height too small: %u", fg->fcm.cell_height);
    if (fg->fcm.cell_height > MAX_DIM) fatal("Line height too large: %u", fg->fcm.cell_height);
    if (fg->fcm.cell_width < MIN_WIDTH) fatal("Cell width too small: %u", fg->fcm.cell_width);
    if (fg->fcm.cell_width > MAX_DIM) fatal("Cell width too large: %u", fg->fcm.cell_width);
#undef MIN_WIDTH
#undef MIN_HEIGHT
#undef MAX_DIM

    unsigned int baseline_before = fg->fcm.baseline;
#define A(which, dpi) adjust_metric(&fg->fcm.which, OPT(which).val, OPT(which).unit, fg->logical_dpi_##dpi);
    A(underline_thickness, y); A(underline_position, y); A(strikethrough_thickness, y); A(strikethrough_position, y); A(baseline, y);
#undef A

    if (baseline_before != fg->fcm.baseline) {
        int adjustment = fg->fcm.baseline - baseline_before;
        fg->fcm.baseline = adjust_ypos(baseline_before, fg->fcm.cell_height, adjustment);
        fg->fcm.underline_position = adjust_ypos(fg->fcm.underline_position, fg->fcm.cell_height, adjustment);
        fg->fcm.strikethrough_position = adjust_ypos(fg->fcm.strikethrough_position, fg->fcm.cell_height, adjustment);
    }

    fg->fcm.underline_position = MIN(fg->fcm.cell_height - 1, fg->fcm.underline_position);
    // ensure there is at least a couple of pixels available to render styled underlines
    // there should be at least one pixel on either side of the underline_position
    if (fg->fcm.underline_position > fg->fcm.baseline + 1 && fg->fcm.underline_position > fg->fcm.cell_height - 1)
      fg->fcm.underline_position = MAX(fg->fcm.baseline + 1, fg->fcm.cell_height - 1);
    if (line_height_adjustment > 1) {
        fg->fcm.baseline += MIN(fg->fcm.cell_height - 1, (unsigned)line_height_adjustment / 2);
        fg->fcm.underline_position += MIN(fg->fcm.cell_height - 1, (unsigned)line_height_adjustment / 2);
    }
}

static bool
face_has_codepoint(const void* face, char_type cp) {
    return glyph_id_for_codepoint(face, cp) > 0;
}

static bool
has_emoji_presentation(const CPUCell *c, const ListOfChars *lc) {
    bool is_text_presentation;
    CharProps cp;
    return c->is_multicell && lc->count && (cp = char_props_for(lc->chars[0])).is_emoji && (
        ( (is_text_presentation = wcwidth_std(cp) < 2) && lc->count > 1 && lc->chars[1] == VS16 ) ||
        ( !is_text_presentation && (lc->count == 1 || lc->chars[1] != VS15) )
    );
}

bool
has_cell_text(bool(*has_codepoint)(const void*, char_type ch), const void* face, bool do_debug, const ListOfChars *lc) {
    RAII_ListOfChars(llc);
    if (!has_codepoint(face, lc->chars[0])) goto not_found;
    for (unsigned i = 1; i < lc->count; i++) {
        if (!char_props_for(lc->chars[i]).is_non_rendered) {
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
    set_size_for_face(face, fg->fcm.cell_height, true, (FONTS_DATA_HANDLE)fg);

    ensure_space_for(fg, fonts, Font, fg->fonts_count + 1, fonts_capacity, 5, true);
    ssize_t ans = fg->first_fallback_font_idx + fg->fallback_fonts_count;
    Font *af = &fg->fonts[ans];
    if (!init_font(af, face, bold, italic, emoji_presentation)) fatal("Out of memory");
    Py_DECREF(face);
    fg->fallback_fonts_count++;
    fg->fonts_count++;
    return ans;
}

static size_t
chars_as_utf8(const ListOfChars *lc, char *buf, size_t bufsz, char_type zero_char) {
    size_t n;
    if (lc->count == 1) n = encode_utf8(lc->chars[0] ? lc->chars[0] : zero_char, buf);
    else {
        n = encode_utf8(lc->chars[0], buf);
        if (lc->chars[0] != '\t') for (unsigned i = 1; i < lc->count && n < bufsz - 4; i++) n += encode_utf8(lc->chars[i], buf + n);
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
    char cell_text[4u * (MAX_NUM_CODEPOINTS_PER_CELL + 8u)] = {style};
    const size_t cell_text_len = 1 + chars_as_utf8(lc, cell_text + 1, arraysz(cell_text) - 1, ' ');
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


static bool allow_use_of_box_fonts = true;

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
        case 0x1cd00 ... 0x1cde5: case 0x1fbe6: case 0x1fbe7:  // octants
        case 0xf5d0 ... 0xf60d:    // branch drawing characters
            if (allow_use_of_box_fonts) return BOX_FONT;
            /* fallthrough */
        default:
            if (lc->count == 1 && (lc->chars[0] == ' ' || lc->chars[0] == 0x2002 /* en-space */)) return BLANK_FONT;
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
        case 0x1cd00 ... 0x1cde5:
            return 0x1100 + ch - 0x1cd00; // IDs from 0x1100 to 0x11e5
        case 0x1fbe6: case 0x1fbe7: return 0x11e6 + ch - 0x1fbe6;
        case 0xf5d0 ... 0xf60d:
            return 0x2000 + ch - 0xf5d0; // IDs from 0x2000 to 0x203d
        default:
            return 0xffff;
    }
END_ALLOW_CASE_RANGE
}

static PyObject *descriptor_for_idx = NULL;

void
render_alpha_mask(const uint8_t *alpha_mask, pixel* dest, const Region *src_rect, const Region *dest_rect, size_t src_stride, size_t dest_stride, pixel color_rgb) {
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

static float
effective_scale(RunFont rf) {
    float ans = MAX(1u, rf.scale);
    if (rf.subscale_n && rf.subscale_d && rf.subscale_n < rf.subscale_d) {
        ans *= ((float)rf.subscale_n) / rf.subscale_d;
    }
    return ans;
}

static float
scaled_cell_dimensions(RunFont rf, unsigned *width, unsigned *height) {
    float frac = MAX(effective_scale(rf), MIN(4.f, (float)*width) / *width);
    *width = (unsigned)ceilf(frac * *width);
    *height = (unsigned)ceilf(frac * *height);
    return frac;
}

static float
apply_scale_to_font_group(FontGroup *fg, RunFont *rf) {
    unsigned int scaled_cell_width = fg->fcm.cell_width, scaled_cell_height = fg->fcm.cell_height;
    float scale = rf ? scaled_cell_dimensions(*rf, &scaled_cell_width, &scaled_cell_height) : 1.f;
    scaled_font_map_t_itr i = vt_get(&fg->scaled_font_map, scale);
    ScaledFontData sfd;
#define apply_scaling(which_fg) if (!face_apply_scaling(medium_font->face, (FONTS_DATA_HANDLE)(which_fg))) { \
            if (PyErr_Occurred()) PyErr_Print(); \
            fatal("Could not apply scale of %f to font group at size: %f", scale, (which_fg)->font_sz_in_pts); \
        }

    if (vt_is_end(i)) {
        Font *medium_font = &fg->fonts[fg->medium_font_idx];
        FontGroup copy = {.fcm=fg->fcm, .logical_dpi_x=fg->logical_dpi_x, .logical_dpi_y=fg->logical_dpi_y};
        copy.fcm.cell_width = scaled_cell_width; copy.fcm.cell_height = scaled_cell_height;
        copy.font_sz_in_pts = scale * fg->font_sz_in_pts;
        apply_scaling(&copy);
        calc_cell_metrics(&copy, medium_font->face);
        if (copy.fcm.cell_width > scaled_cell_width || copy.fcm.cell_height > scaled_cell_height) {
            float wfrac = (float)copy.fcm.cell_width / scaled_cell_width, hfrac = (float)copy.fcm.cell_height / scaled_cell_height;
            float frac = MIN(wfrac, hfrac);
            copy.font_sz_in_pts *= frac;
            while (true) {
                apply_scaling(&copy);
                calc_cell_metrics(&copy, medium_font->face);
                if (copy.fcm.cell_width <= scaled_cell_width && copy.fcm.cell_height <= scaled_cell_height) break;
                if (copy.font_sz_in_pts <= 1) break;
                copy.font_sz_in_pts -= 0.1;
            }
        }
        sfd.fcm = copy.fcm; sfd.font_sz_in_pts = copy.font_sz_in_pts;
        sfd.fcm.cell_width = scaled_cell_width; sfd.fcm.cell_height = scaled_cell_height;
        if (vt_is_end(vt_insert(&fg->scaled_font_map, scale, sfd))) fatal("Out of memory inserting scaled font data into map");
        apply_scaling(fg);
    } else sfd = i.data->val;
    fg->font_sz_in_pts = sfd.font_sz_in_pts;
    fg->fcm = sfd.fcm;
    return scale;
#undef apply_scaling
}

static pixel*
pointer_to_space_for_last_sprite(Canvas *canvas, FontCellMetrics fcm, unsigned *sz) {
    *sz = fcm.cell_width * (fcm.cell_height + 1);
    return canvas->buf + (canvas->size_in_bytes / sizeof(canvas->buf[0]) - *sz);
}

static pixel*
extract_cell_from_canvas(FontGroup *fg, unsigned int i, unsigned int num_cells) {
    unsigned sz;
    pixel *ans = pointer_to_space_for_last_sprite(&fg->canvas, fg->fcm, &sz);
    pixel *dest = ans, *src = fg->canvas.buf + (i * fg->fcm.cell_width);
    unsigned int stride = fg->fcm.cell_width * num_cells;
    for (unsigned int r = 0; r < fg->fcm.cell_height; r++, dest += fg->fcm.cell_width, src += stride) memcpy(dest, src, fg->fcm.cell_width * sizeof(fg->canvas.buf[0]));
    memset(ans + sz - fg->fcm.cell_width, 0, fg->fcm.cell_width * sizeof(ans[0]));  // underline_exclusion
    return ans;
}

static void
calculate_regions_for_line(RunFont rf, unsigned cell_height, Region *src, Region *dest) {
    unsigned src_height = src->bottom;
    Region src_in_full_coords = *src; unsigned full_dest_height = cell_height * rf.scale;
    if (rf.subscale_n && rf.subscale_d) {
        switch(rf.align.vertical) {
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

static pixel*
extract_cell_region(Canvas *canvas, unsigned i, Region *src, const Region *dest, unsigned src_width, FontCellMetrics unscaled_metrics) {
    src->left = i * unscaled_metrics.cell_width; src->right = MIN(src_width, src->left + unscaled_metrics.cell_width);
    unsigned sz;
    pixel *ans = pointer_to_space_for_last_sprite(canvas, unscaled_metrics, &sz);
    memset(ans, 0, sz * sizeof(ans[0]));
    unsigned width = MIN(src->right - src->left, unscaled_metrics.cell_width);
    for (unsigned srcy = src->top, desty = dest->top; srcy < src->bottom && desty < dest->bottom; srcy++, desty++) {
        pixel *srcp = canvas->buf + srcy * src_width, *destp = ans + desty * unscaled_metrics.cell_width;
        memcpy(destp, srcp + src->left, width * sizeof(destp[0]));
    }
    return ans;
}

static void
set_cell_sprite(GPUCell *cell, const SpritePosition *sp) {
    cell->sprite_idx = sp->idx & 0x7fffffff;
    if (sp->colored) cell->sprite_idx |= 0x80000000;
}

static Region
map_scaled_decoration_geometry(DecorationGeometry sdg, Region src, Region dest) {
    unsigned scaled_top = MAX(sdg.top, src.top), scaled_bottom = MIN(sdg.top + sdg.height, src.bottom);
    unsigned unscaled_top = dest.top + (scaled_top - src.top);
    unsigned unscaled_bottom = unscaled_top + (scaled_bottom > scaled_top ? scaled_bottom - scaled_top : 0);
    unscaled_bottom = MIN(unscaled_bottom, dest.bottom);
    /*printf("111111 src: (%u, %u) dest: (%u, %u) sdg: (%u, %u) scaled: (%u, %u) unscaled: (%u, %u)\n",*/
    /*    src.top, src.bottom, dest.top, dest.bottom, sdg.top, sdg.top + sdg.height, scaled_top, scaled_bottom, unscaled_top, unscaled_bottom);*/
    return (Region){.top=unscaled_top, .bottom=MAX(unscaled_top, unscaled_bottom)};
}

static void
render_scaled_decoration(FontCellMetrics unscaled_metrics, FontCellMetrics scaled_metrics, uint8_t *alpha_mask, pixel *output, Region src, Region dest) {
    memset(output, 0, sizeof(output[0]) * unscaled_metrics.cell_width * (unscaled_metrics.cell_height + 1));
    unsigned src_limit = MIN(scaled_metrics.cell_height, src.bottom), dest_limit = MIN(unscaled_metrics.cell_height, dest.bottom);
    unsigned cell_width = MIN(scaled_metrics.cell_width, unscaled_metrics.cell_width);
    for (unsigned srcy = src.top, desty=dest.top; srcy < src_limit && desty < dest_limit; srcy++, desty++) {
        uint8_t *srcp = alpha_mask + cell_width * srcy;
        pixel *destp = output + cell_width * desty;
        for (unsigned x = 0; x < cell_width; x++) destp[x] = 0xffffff00 | srcp[x];
    }
}

static sprite_index
render_decorations(FontGroup *fg, Region src, Region dest, FontCellMetrics scaled_metrics, DecorationGeometry *underline_region) {
    *underline_region = (DecorationGeometry){0};
    if ((src.bottom == src.top) || (dest.bottom == dest.top)) return 0;   // no overlap
    const FontCellMetrics unscaled_metrics = fg->fcm;
    scaled_metrics.cell_width = unscaled_metrics.cell_width;
    RAII_ALLOC(uint8_t, alpha_mask, malloc((size_t)scaled_metrics.cell_height * scaled_metrics.cell_width));
    RAII_ALLOC(pixel, buf, malloc(sizeof(pixel) * unscaled_metrics.cell_width * (unscaled_metrics.cell_height + 1)));
    if (!alpha_mask || !buf) fatal("Out of memory");
    sprite_index ans = 0;
    bool is_underline = false; uint32_t underline_top = unscaled_metrics.cell_height, underline_bottom = 0;
#define do_one(call) { \
    memset(alpha_mask, 0, sizeof(alpha_mask[0]) * scaled_metrics.cell_width * scaled_metrics.cell_height); \
    DecorationGeometry sdg = call; \
    render_scaled_decoration(unscaled_metrics, scaled_metrics, alpha_mask, buf, src, dest); \
    sprite_index q = current_send_sprite_to_gpu(fg, buf, (DecorationMetadata){0}, scaled_metrics); \
    if (!ans) ans = q; \
    if (is_underline) { \
        Region r = map_scaled_decoration_geometry(sdg, src, dest); \
        if (r.top < underline_top) underline_top = r.top; \
        if (r.bottom > underline_bottom) underline_bottom = r.bottom; \
    }; \
}

    do_one(add_strikethrough(alpha_mask, scaled_metrics));
    is_underline = true;
    do_one(add_straight_underline(alpha_mask, scaled_metrics));
    do_one(add_double_underline(alpha_mask, scaled_metrics));
    do_one(add_curl_underline(alpha_mask, scaled_metrics));
    do_one(add_dotted_underline(alpha_mask, scaled_metrics));
    do_one(add_dashed_underline(alpha_mask, scaled_metrics));

    underline_bottom = MIN(underline_bottom, unscaled_metrics.cell_height);
    if (underline_top < underline_bottom) {
        underline_region->top = underline_top;
        underline_region->height = underline_bottom - underline_top;
    }
    return ans;
#undef do_one
}

static DecorationMetadata
index_for_decorations(FontGroup *fg, RunFont rf, Region src, Region dest, FontCellMetrics scaled_metrics) {
    const DecorationsKey key = {.scale=rf.scale, .subscale_n = rf.subscale_n, .subscale_d = rf.subscale_d, .align = rf.align.val, .multicell_y = rf.multicell_y, .u1 = 0, .u2 = 0, .u3 = 0 };
    decorations_index_map_t_itr i = vt_get(&fg->decorations_index_map, key);
    if (!vt_is_end(i)) return i.data->val;
    DecorationMetadata val;
    val.start_idx = render_decorations(fg, src, dest, scaled_metrics, &val.underline_region);
    if (vt_is_end(vt_insert(&fg->decorations_index_map, key, val))) fatal("Out of memory");
    return val;
}

static void
render_box_cell(FontGroup *fg, RunFont rf, CPUCell *cpu_cell, GPUCell *gpu_cell, const TextCache *tc) {
    ensure_glyph_render_scratch_space(64);
    text_in_cell(cpu_cell, tc, global_glyph_render_scratch.lc);
    ensure_glyph_render_scratch_space(rf.scale * global_glyph_render_scratch.lc->count);
    unsigned num_glyphs = 0, num_cells = rf.scale;
    for (unsigned i = 0; i < global_glyph_render_scratch.lc->count; i++) {
        glyph_index glyph = box_glyph_id(global_glyph_render_scratch.lc->chars[i]);
        if (glyph != 0xffff) global_glyph_render_scratch.glyphs[num_glyphs++] = glyph;
        else global_glyph_render_scratch.lc->chars[i] = 0;
    }
#define failed {\
    if (PyErr_Occurred()) PyErr_Print(); \
    for (unsigned i = 0; i < num_cells; i++) gpu_cell[i].sprite_idx = 0; \
    return; \
}
    if (!num_glyphs) failed;
    bool all_rendered = true;
#define sp global_glyph_render_scratch.sprite_positions
    for (unsigned ligature_index = 0; ligature_index < num_cells; ligature_index++) {
        sp[ligature_index] = sprite_position_for(fg, rf, global_glyph_render_scratch.glyphs, num_glyphs, ligature_index, num_cells);
        if (sp[ligature_index] == NULL) failed;
        sp[ligature_index]->colored = false;
        if (!sp[ligature_index]->rendered) all_rendered = false;
    }
    if (all_rendered) {
        for (unsigned i = 0; i < num_cells; i++) set_cell_sprite(gpu_cell + i, sp[i]);
        return;
    }
    FontCellMetrics unscaled_metrics = fg->fcm;
    float scale = apply_scale_to_font_group(fg, &rf);
    ensure_canvas_can_fit(fg, num_glyphs + 1, rf.scale);
    FontCellMetrics scaled_metrics = fg->fcm;
    if (scale != 1) apply_scale_to_font_group(fg, NULL);
    ensure_canvas_can_fit(fg, num_glyphs + 1, rf.scale);  // in case unscaled size is larger is than scaled size
    unsigned mask_stride = scaled_metrics.cell_width * num_glyphs, right_shift = 0;
    if (rf.subscale_n && rf.subscale_d && rf.align.horizontal && scaled_metrics.cell_width <= unscaled_metrics.cell_width) {
        int delta = unscaled_metrics.cell_width * num_cells - mask_stride;
        if (rf.align.horizontal == 2) delta /= 2;
        if (delta > 0) {
            right_shift = delta;
            mask_stride += delta;
        }
    }
    Region src = {.right = scaled_metrics.cell_width, .bottom = scaled_metrics.cell_height }, dest = src;
    for (unsigned i = 0, cnum = 0; i < num_glyphs; i++) {
        unsigned int ch = global_glyph_render_scratch.lc->chars[cnum++];
        while (!ch) ch = global_glyph_render_scratch.lc->chars[cnum++];
        render_box_char(ch, fg->canvas.alpha_mask, src.right, src.bottom, fg->logical_dpi_x, fg->logical_dpi_y, scale);
        dest.left = i * scaled_metrics.cell_width + right_shift; dest.right = dest.left + scaled_metrics.cell_width;
        render_alpha_mask(fg->canvas.alpha_mask, fg->canvas.buf, &src, &dest, src.right, mask_stride, 0xffffff);
    }
    src.right = mask_stride; dest = src; dest.right = unscaled_metrics.cell_width * num_cells;
    /*printf("Rendered char sz: (%u, %u)\n", src.right, src.bottom); dump_sprite(fg->canvas.buf, src.right, src.bottom);*/
    calculate_regions_for_line(rf, unscaled_metrics.cell_height, &src, &dest);
    DecorationMetadata dm = index_for_decorations(fg, rf, src, dest, scaled_metrics);
    /*printf("width: %u height: %u unscaled_cell_width: %u unscaled_cell_height: %u src.top: %u src.bottom: %u num_cells: %u\n", width, height, fg->fcm.cell_width, fg->fcm.cell_height, src.top, src.bottom, num_cells);*/
    for (unsigned i = 0; i < num_cells; i++) {
        if (!sp[i]->rendered) {
            pixel *b = extract_cell_region(&fg->canvas, i, &src, &dest, mask_stride, unscaled_metrics);
            /*printf("cell %u src -> dest: (%u %u) -> (%u %u)\n", i, src.left, src.right, dest.left, dest.right);*/
            sp[i]->idx = current_send_sprite_to_gpu(fg, b, dm, scaled_metrics);
            if (!sp[i]->idx) failed;
            /*dump_sprite(b, unscaled_metrics.cell_width, unscaled_metrics.cell_height);*/
            sp[i]->rendered = true; sp[i]->colored = false;
        }
        set_cell_sprite(gpu_cell + i, sp[i]);
        /*printf("Sprite %u: pos: %u sz: (%u, %u)\n", i, sp[i]->idx, fg->fcm.cell_width, fg->fcm.cell_height); dump_sprite(b, fg->fcm.cell_width, fg->fcm.cell_height);*/
    }
#undef sp
#undef failed
}

static void
load_hb_buffer(CPUCell *first_cpu_cell, index_type num_cells, const TextCache *tc, ListOfChars *lc) {
    size_t num = 0;
    hb_buffer_clear_contents(harfbuzz_buffer);
    // Although hb_buffer_add_codepoints is supposedly an append, we have to
    // add all text in one call otherwise it breaks shaping, presumably because
    // of context??
    for (; num_cells; first_cpu_cell++, num_cells--) {
        if (first_cpu_cell->is_multicell && first_cpu_cell->x) continue;
        text_in_cell(first_cpu_cell, tc, lc);
        ensure_space_for((&shape_buffer), codepoints, shape_buffer.codepoints[0], lc->count + num, capacity, 512, false);
        memcpy(shape_buffer.codepoints + num, lc->chars, lc->count * sizeof(shape_buffer.codepoints[0]));
        num += lc->count;
    }
    hb_buffer_add_codepoints(harfbuzz_buffer, shape_buffer.codepoints, num, 0, num);
    hb_buffer_guess_segment_properties(harfbuzz_buffer);
    if (OPT(force_ltr)) hb_buffer_set_direction(harfbuzz_buffer, HB_DIRECTION_LTR);
}


static void
render_filled_sprite(pixel *buf, unsigned num_glyphs, FontCellMetrics scaled_metrics, unsigned num_scaled_cells) {
    if (num_scaled_cells > num_glyphs) {
        memset(buf, 0xff, sizeof(buf[0]) * num_glyphs * scaled_metrics.cell_width);
        memset(buf + num_glyphs * scaled_metrics.cell_width, 0, sizeof(buf[0]) * (num_scaled_cells - num_glyphs) * scaled_metrics.cell_width);
        for (unsigned y = 1; y < scaled_metrics.cell_height; y++) memcpy(
            buf + scaled_metrics.cell_width * num_scaled_cells * y, buf, sizeof(buf[0]) * scaled_metrics.cell_width * num_scaled_cells );
    } else memset(buf, 0xff, sizeof(buf[0]) * num_glyphs * scaled_metrics.cell_height * scaled_metrics.cell_width );
}

static void
apply_horizontal_alignment(pixel *canvas, RunFont rf, bool center_glyph, GlyphRenderInfo ri, unsigned canvas_height, unsigned num_cells, unsigned num_glyphs, bool was_colored) {
    int delta = 0;
    (void)was_colored;
#ifdef __APPLE__
    if (num_cells == 2 && was_colored) center_glyph = true;
#endif
    if (rf.subscale_n && rf.subscale_d && rf.align.horizontal) {
        delta = ri.canvas_width - ri.rendered_width;
        if (rf.align.horizontal == 2) delta /= 2;
    } else if (center_glyph && num_glyphs && num_cells > 1 && ri.rendered_width < ri.canvas_width) {
        unsigned half = (ri.canvas_width - ri.rendered_width) / 2;
        if (half > 1) delta = half;
    }
    delta -= ri.x;
    if (delta > 0) right_shift_canvas(canvas, ri.canvas_width, canvas_height, delta);
}



static void
render_group(
    FontGroup *fg, unsigned int num_cells, unsigned int num_glyphs, CPUCell *cpu_cells, GPUCell *gpu_cells,
    hb_glyph_info_t *info, hb_glyph_position_t *positions, RunFont rf, glyph_index *glyphs, unsigned glyph_count,
    bool center_glyph, const TextCache *tc, float scale, FontCellMetrics unscaled_metrics
) {
#define sp global_glyph_render_scratch.sprite_positions
    const FontCellMetrics scaled_metrics = fg->fcm;
    bool all_rendered = true;
    unsigned num_scaled_cells = (unsigned)ceil(num_cells / scale); if (!num_scaled_cells) num_scaled_cells = 1u;
    Font *font = fg->fonts + rf.font_idx;

#define failed { \
    if (PyErr_Occurred()) PyErr_Print(); \
    for (unsigned i = 0; i < num_cells; i++) gpu_cells[i].sprite_idx = 0; \
    return; \
}

    // One can have infinite ligatures with repeated groups of sprites when scaled size is an exact multiple or
    // divisor of unscaled size but I cant be bothered to implement that.
    bool is_infinite_ligature = num_cells == num_scaled_cells && num_cells > 9 && num_glyphs == num_cells;
    for (unsigned i = 0, ligature_index = 0; i < num_cells; i++) {
        bool is_repeat_sprite = is_infinite_ligature && i > 1 && i + 1 < num_glyphs && glyphs[i] == glyphs[i-1] && glyphs[i] == glyphs[i-2] && glyphs[i] == glyphs[i+1];
        sp[i] = is_repeat_sprite ? sp[i-1] : sprite_position_for(fg, rf, glyphs, glyph_count, ligature_index++, num_cells);
        if (!sp[i]) failed;
        if (!sp[i]->rendered) all_rendered = false;
    }
    if (all_rendered) {
        for (unsigned i = 0; i < num_cells; i++) set_cell_sprite(gpu_cells + i, sp[i]);
        return;
    }

    ensure_canvas_can_fit(fg, MAX(num_cells, num_scaled_cells) + 1, rf.scale);
    text_in_cell(cpu_cells, tc, global_glyph_render_scratch.lc);
    bool is_only_filled_boxes = false;
    bool was_colored = has_emoji_presentation(cpu_cells, global_glyph_render_scratch.lc);
    if (global_glyph_render_scratch.lc->chars[0] == 0x2588) {
        glyph_index box_glyph_id = global_glyph_render_scratch.glyphs[0];
        is_only_filled_boxes = true;
        for (unsigned i = 1; i < num_glyphs && is_only_filled_boxes; i++) if (global_glyph_render_scratch.glyphs[i] != box_glyph_id) is_only_filled_boxes = false;
    }
    /*printf("num_cells: %u num_scaled_cells: %u num_glyphs: %u scale: %f unscaled: %ux%u scaled: %ux%u\n", num_cells, num_scaled_cells, num_glyphs, scale, unscaled_metrics.cell_width, unscaled_metrics.cell_height, scaled_metrics.cell_width, scaled_metrics.cell_height);*/
    GlyphRenderInfo ri = {0};
    if (is_only_filled_boxes) { // special case rendering of █ for tests
        render_filled_sprite(fg->canvas.buf, num_glyphs, scaled_metrics, num_scaled_cells);
        was_colored = false;
        ri.canvas_width = num_cells * unscaled_metrics.cell_width; ri.rendered_width = num_glyphs * scaled_metrics.cell_width;
        /*dump_sprite(fg->canvas.buf, scaled_metrics.cell_width * num_scaled_cells, scaled_metrics.cell_height);*/
    } else {
        render_glyphs_in_cells(font->face, font->bold, font->italic, info, positions, num_glyphs, fg->canvas.buf, scaled_metrics.cell_width, scaled_metrics.cell_height, num_scaled_cells, scaled_metrics.baseline, &was_colored, (FONTS_DATA_HANDLE)fg, &ri);
    }
    apply_horizontal_alignment(fg->canvas.buf, rf, center_glyph, ri, scaled_metrics.cell_height, num_scaled_cells, num_glyphs, was_colored);
    if (PyErr_Occurred()) PyErr_Print();

    fg->fcm = unscaled_metrics;  // needed for current_send_sprite_to_gpu()

    if (num_cells == num_scaled_cells && rf.scale == 1.f) {
        Region src = {.bottom=unscaled_metrics.cell_height, .right=unscaled_metrics.cell_width}, dest = src;
        DecorationMetadata dm = index_for_decorations(fg, rf, src, dest, scaled_metrics);
        for (unsigned i = 0; i < num_cells; i++) {
            if (!sp[i]->rendered) {
                bool is_repeat_sprite = is_infinite_ligature && i > 0 && sp[i]->idx == sp[i-1]->idx;
                if (!is_repeat_sprite) {
                    pixel *b = num_cells == 1 ? fg->canvas.buf : extract_cell_from_canvas(fg, i, num_cells);
                    sp[i]->idx = current_send_sprite_to_gpu(fg, b, dm, scaled_metrics);
                    if (!sp[i]->idx) failed;
                } else sp[i]->idx = sp[i-1]->idx;
                sp[i]->rendered = true; sp[i]->colored = was_colored;
            }
            set_cell_sprite(gpu_cells + i, sp[i]);
        }
    } else {
        Region src={.bottom=scaled_metrics.cell_height, .right=scaled_metrics.cell_width * num_scaled_cells}, dest={.right=unscaled_metrics.cell_width};
        calculate_regions_for_line(rf, unscaled_metrics.cell_height, &src, &dest);
        DecorationMetadata dm = index_for_decorations(fg, rf, src, dest, scaled_metrics);
        /*printf("line: %u src -> dest: (%u %u) -> (%u %u)\n", rf.multicell_y, src.top, src.bottom, dest.top, dest.bottom);*/
        for (unsigned i = 0; i < num_cells; i++) {
            if (!sp[i]->rendered) {
                pixel *b = extract_cell_region(&fg->canvas, i, &src, &dest, scaled_metrics.cell_width * num_scaled_cells, unscaled_metrics);
                /*printf("cell %u src -> dest: (%u %u) -> (%u %u)\n", i, src.left, src.right, dest.left, dest.right);*/
                sp[i]->idx = current_send_sprite_to_gpu(fg, b, dm, scaled_metrics);
                if (!sp[i]->idx) failed;
                /*dump_sprite(b, unscaled_metrics.cell_width, unscaled_metrics.cell_height);*/
                sp[i]->rendered = true; sp[i]->colored = was_colored;
            }
            set_cell_sprite(gpu_cells + i, sp[i]);
        }
    }

    fg->fcm = scaled_metrics;
#undef sp
#undef failed
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
    load_hb_buffer(first_cpu_cell, num_cells, tc, &lc);

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
check_cell_consumed(CellData *cell_data, CPUCell *last_cpu_cell, const TextCache *tc, ListOfChars *lc) {
    cell_data->codepoints_consumed++;
    if (cell_data->codepoints_consumed >= cell_data->num_codepoints) {
        uint16_t width = 1;
        if (cell_data->cpu_cell->is_multicell) width = cell_data->cpu_cell->width * cell_data->cpu_cell->scale;
        cell_data->cpu_cell += width;
        cell_data->gpu_cell += width;
        cell_data->codepoints_consumed = 0;
        if (cell_data->cpu_cell <= last_cpu_cell) {
            text_in_cell(cell_data->cpu_cell, tc, lc);
            cell_data->num_codepoints = lc->count;
            cell_data->current_codepoint = lc->chars[0];
        } else cell_data->current_codepoint = 0;
        return width;
    }
    text_in_cell(cell_data->cpu_cell, tc, lc);
    char_type cc = lc->chars[cell_data->codepoints_consumed];
    // VS15/16 cause rendering to break, as they get marked as
    // special glyphs, so map to 0, to avoid that
    cell_data->current_codepoint = (cc == VS15 || cc == VS16) ? 0 : cc;
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
group_iosevka(Font *font, hb_font_t *hbf, const TextCache *tc, ListOfChars *lc) {
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
                unsigned int w = check_cell_consumed(&G(current_cell_data), G(last_cpu_cell), tc, lc);
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
group_normal(Font *font, hb_font_t *hbf, const TextCache *tc, ListOfChars *lc) {
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
                unsigned int w = check_cell_consumed(&G(current_cell_data), G(last_cpu_cell), tc, lc);
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


static float
shape_run(CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, Font *font, RunFont rf, FontGroup *fg, bool disable_ligature, const TextCache *tc, ListOfChars *lc) {
    float scale = apply_scale_to_font_group(fg, &rf);
    if (scale != 1.f) if (!face_apply_scaling(font->face, (FONTS_DATA_HANDLE)fg) && PyErr_Occurred()) PyErr_Print();
    hb_font_t *hbf = harfbuzz_font_for_face(font->face);
    if (font->spacer_strategy == SPACER_STRATEGY_UNKNOWN) detect_spacer_strategy(hbf, font, tc);
    shape(first_cpu_cell, first_gpu_cell, num_cells, hbf, font, disable_ligature, tc);
    if (font->spacer_strategy == SPACERS_IOSEVKA) group_iosevka(font, hbf, tc, lc);
    else group_normal(font, hbf, tc, lc);
#if 0
        static char dbuf[1024];
        // You can also generate this easily using hb-shape --show-extents --cluster-level=1 --shapers=ot /path/to/font/file text
        hb_buffer_serialize_glyphs(harfbuzz_buffer, 0, group_state.num_glyphs, dbuf, sizeof(dbuf), NULL, harfbuzz_font_for_face(font->face), HB_BUFFER_SERIALIZE_FORMAT_TEXT, HB_BUFFER_SERIALIZE_FLAG_DEFAULT | HB_BUFFER_SERIALIZE_FLAG_GLYPH_EXTENTS);
        printf("\n%s\n", dbuf);
#endif
    if (scale != 1.f) {
        apply_scale_to_font_group(fg, NULL);
        if (!face_apply_scaling(font->face, (FONTS_DATA_HANDLE)fg) && PyErr_Occurred()) PyErr_Print();
    }
    return scale;
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
group_has_more_than_one_scaled_cell(const Group *group, float scale) {
    return group->num_cells / scale > 1.0f;
}


static void
split_run_at_offset(index_type cursor_offset, index_type *left, index_type *right, float scale) {
    *left = 0; *right = 0;
    for (unsigned idx = 0; idx < G(group_idx) + 1; idx++) {
        Group *group = G(groups) + idx;
        if (group->first_cell_idx <= cursor_offset && cursor_offset < group->first_cell_idx + group->num_cells) {
            if (group->has_special_glyph && group_has_more_than_one_scaled_cell(group, scale)) {
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
    const FontCellMetrics unscaled_metrics = fg->fcm;
    float scale = apply_scale_to_font_group(fg, &rf);
    if (scale != 1.f) if (!face_apply_scaling(fg->fonts[rf.font_idx].face, (FONTS_DATA_HANDLE)fg) && PyErr_Occurred()) PyErr_Print();
    while (idx <= G(group_idx)) {
        Group *group = G(groups) + idx;
        if (!group->num_cells) break;
        /* printf("Group: idx: %u num_cells: %u num_glyphs: %u first_glyph_idx: %u first_cell_idx: %u total_num_glyphs: %zu\n", */
        /*         idx, group->num_cells, group->num_glyphs, group->first_glyph_idx, group->first_cell_idx, group_state.num_glyphs); */
        if (group->num_glyphs) {
            ensure_glyph_render_scratch_space(MAX(group->num_glyphs, group->num_cells));
            for (unsigned i = 0; i < group->num_glyphs; i++) global_glyph_render_scratch.glyphs[i] = G(info)[group->first_glyph_idx + i].codepoint;
            render_group(fg, group->num_cells, group->num_glyphs, G(first_cpu_cell) + group->first_cell_idx, G(first_gpu_cell) + group->first_cell_idx, G(info) + group->first_glyph_idx, G(positions) + group->first_glyph_idx, rf, global_glyph_render_scratch.glyphs, group->num_glyphs, center_glyph, tc, scale, unscaled_metrics);
        }
        idx++;
    }
    if (scale != 1.f) {
        apply_scale_to_font_group(fg, NULL);
        if (!face_apply_scaling(fg->fonts[rf.font_idx].face, (FONTS_DATA_HANDLE)fg) && PyErr_Occurred()) PyErr_Print();
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
    FontGroup *fg = font_groups;
    if (path) {
        face = face_from_path(path, index, (FONTS_DATA_HANDLE)font_groups);
        if (face == NULL) return NULL;
        font = calloc(1, sizeof(Font));
        font->face = face;
        if (!init_hash_tables(font)) return NULL;
    } else {
        font = fg->fonts + fg->medium_font_idx;
    }
    RunFont rf = {0};
    RAII_ListOfChars(lc);
    shape_run(line->cpu_cells, line->gpu_cells, num, font, rf, fg, false, line->text_cache, &lc);

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
render_run(FontGroup *fg, CPUCell *first_cpu_cell, GPUCell *first_gpu_cell, index_type num_cells, RunFont rf, bool pua_space_ligature, bool center_glyph, int cursor_offset, DisableLigature disable_ligature_strategy, const TextCache *tc, ListOfChars *lc) {
    float scale;
    switch(rf.font_idx) {
        default:
            scale = shape_run(first_cpu_cell, first_gpu_cell, num_cells, &fg->fonts[rf.font_idx], rf, fg, disable_ligature_strategy == DISABLE_LIGATURES_ALWAYS, tc, lc);
            if (pua_space_ligature) collapse_pua_space_ligature(num_cells);
            else if (cursor_offset > -1) { // false if DISABLE_LIGATURES_NEVER
                index_type left, right;
                split_run_at_offset(cursor_offset, &left, &right, scale);
                if (right > left) {
                    if (left) {
                        shape_run(first_cpu_cell, first_gpu_cell, left, &fg->fonts[rf.font_idx], rf, fg, false, tc, lc);
                        render_groups(fg, rf, center_glyph, tc);
                    }
                        shape_run(first_cpu_cell + left, first_gpu_cell + left, right - left, &fg->fonts[rf.font_idx], rf, fg, true, tc, lc);
                        render_groups(fg, rf, center_glyph, tc);
                    if (right < num_cells) {
                        shape_run(first_cpu_cell + right, first_gpu_cell + right, num_cells - right, &fg->fonts[rf.font_idx], rf, fg, false, tc, lc);
                        render_groups(fg, rf, center_glyph, tc);
                    }
                    break;
                }
            }
            render_groups(fg, rf, center_glyph, tc);
            break;
        case BLANK_FONT:
            while(num_cells--) { first_gpu_cell->sprite_idx = 0; first_cpu_cell++; first_gpu_cell++; }
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
            while(num_cells--) { first_gpu_cell->sprite_idx = MISSING_GLYPH; first_cpu_cell++; first_gpu_cell++; }
            break;
    }
}

static bool
is_non_emoji_dingbat(char_type ch, CharProps cp) {
    switch(ch) {
        START_ALLOW_CASE_RANGE
        case 0x2700 ... 0x27bf:
        case 0x1f100 ... 0x1f1ff:
            return !cp.is_emoji;
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
    return a->font_idx == b->font_idx && a->scale == b->scale && a->subscale_n == b->subscale_n && a->subscale_d == b->subscale_d && a->align.val == b->align.val && a->multicell_y == b->multicell_y;
}

static bool
multicell_intersects_cursor(const Line *line, index_type lnum, const Cursor *cursor) {
    const CPUCell *c = line->cpu_cells + cursor->x;
    if (c->is_multicell) {
        index_type min_y = lnum > c->y ? lnum - c->y : 0;
        index_type max_y = lnum + (c->scale - c->y - 1);
        return min_y <= cursor->y && cursor->y <= max_y;
    } else return lnum == cursor->y;
}

void
render_line(FONTS_DATA_HANDLE fg_, Line *line, index_type lnum, Cursor *cursor, DisableLigature disable_ligature_strategy, ListOfChars *lc) {
#define RENDER if (run_font.font_idx != NO_FONT && i > first_cell_in_run) { \
    int cursor_offset = -1; \
    if (disable_ligature_at_cursor && first_cell_in_run <= cursor->x && cursor->x <= i && cursor->x < line->xnum && \
            multicell_intersects_cursor(line, lnum, cursor)) cursor_offset = cursor->x - first_cell_in_run; \
    render_run(fg, line->cpu_cells + first_cell_in_run, line->gpu_cells + first_cell_in_run, i - first_cell_in_run, run_font, false, center_glyph, cursor_offset, disable_ligature_strategy, line->text_cache, lc); \
}
    FontGroup *fg = (FontGroup*)fg_;
    RunFont basic_font = {.scale=1, .font_idx = NO_FONT}, run_font = basic_font, cell_font = basic_font;
    bool center_glyph = false;
    bool disable_ligature_at_cursor = cursor != NULL && disable_ligature_strategy == DISABLE_LIGATURES_CURSOR;
    index_type first_cell_in_run, i;
    for (i=0, first_cell_in_run=0; i < line->xnum; i++) {
        cell_font = basic_font;
        CPUCell *cpu_cell = line->cpu_cells + i;
        if (cpu_cell->is_multicell) {
            if (cpu_cell->x) {
                if (cpu_cell->x + 1u < mcd_x_limit(cpu_cell)) i += mcd_x_limit(cpu_cell) - cpu_cell->x - 1u;
                continue;
            }
            cell_font.scale = cpu_cell->scale; cell_font.subscale_n = cpu_cell->subscale_n; cell_font.subscale_d = cpu_cell->subscale_d;
            cell_font.align.vertical = cpu_cell->valign; cell_font.align.horizontal = cpu_cell->halign;
            cell_font.multicell_y = cpu_cell->y;
        }
        text_in_cell(cpu_cell, line->text_cache, lc);
        bool is_main_font, is_emoji_presentation;
        GPUCell *gpu_cell = line->gpu_cells + i;
        const char_type first_ch = lc->chars[0];
        cell_font.font_idx = font_for_cell(fg, cpu_cell, gpu_cell, &is_main_font, &is_emoji_presentation, line->text_cache, lc);
        CharProps cp = char_props_for(first_ch);
        if (
                cell_font.font_idx != MISSING_FONT &&
                ((!is_main_font && !is_emoji_presentation && cp.is_symbol) || (cell_font.font_idx != BOX_FONT && (is_private_use(cp))) || is_non_emoji_dingbat(first_ch, cp))
        ) {
            unsigned int desired_cells = 1;
            if (cell_font.font_idx > 0) {
                Font *font = (fg->fonts + cell_font.font_idx);
                glyph_index glyph_id = glyph_id_for_codepoint(font->face, first_ch);

                int width = get_glyph_width(font->face, glyph_id);
                desired_cells = (unsigned int)ceilf((float)width / fg->fcm.cell_width);
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
                render_run(fg, line->cpu_cells + i, line->gpu_cells + i, num_spaces + 1, cell_font, true, center_glyph, -1, disable_ligature_strategy, line->text_cache, lc);
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
    if (fg->fonts_count && fg->medium_font_idx) return render_simple_text_impl(fg->fonts[fg->medium_font_idx].face, text, fg->fcm.baseline);
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
    Py_CLEAR(descriptor_for_idx);
    if (!PyArg_ParseTuple(args, "OIIIIO!dO!",
                &descriptor_for_idx,
                &descriptor_indices.bold, &descriptor_indices.italic, &descriptor_indices.bi, &descriptor_indices.num_symbol_fonts,
                &PyTuple_Type, &sm, &OPT(font_size), &PyTuple_Type, &ns)) return NULL;
    Py_INCREF(descriptor_for_idx);
    free_font_groups();
    clear_symbol_maps();
    set_symbol_maps(&symbol_maps, &num_symbol_maps, sm);
    set_symbol_maps(&narrow_symbols, &num_narrow_symbols, ns);
    Py_RETURN_NONE;
}

static void
send_prerendered_sprites(FontGroup *fg) {
    // blank cell
    ensure_canvas_can_fit(fg, 1, 1);
    DecorationMetadata dm = {.start_idx=5};
    current_send_sprite_to_gpu(fg, fg->canvas.buf, dm, fg->fcm);
    const unsigned cell_area = fg->fcm.cell_height * fg->fcm.cell_width;
    RAII_ALLOC(uint8_t, alpha_mask, malloc(cell_area));
    if (!alpha_mask) fatal("Out of memory");
    Region r = { .right = fg->fcm.cell_width, .bottom = fg->fcm.cell_height };
#define do_one(call) \
    memset(alpha_mask, 0, cell_area); \
    call; \
    ensure_canvas_can_fit(fg, 1, 1);  /* clear canvas */ \
    render_alpha_mask(alpha_mask, fg->canvas.buf, &r, &r, fg->fcm.cell_width, fg->fcm.cell_width, 0xffffff); \
    current_send_sprite_to_gpu(fg, fg->canvas.buf, dm, fg->fcm);

    // If you change the mapping of these cells you will need to change
    // BEAM_IDX in shader.c and STRIKE_SPRITE_INDEX in
    // shaders.py and MISSING_GLYPH in font.c and dec_idx above
    do_one(add_missing_glyph(alpha_mask, fg->fcm));
    do_one(add_beam_cursor(alpha_mask, fg->fcm, fg->logical_dpi_x));
    do_one(add_underline_cursor(alpha_mask, fg->fcm, fg->logical_dpi_y));
    do_one(add_hollow_cursor(alpha_mask, fg->fcm, fg->logical_dpi_x, fg->logical_dpi_y));
    RunFont rf = {.scale=1};
    Region rg = {.bottom = fg->fcm.cell_height, .right = fg->fcm.cell_width};
    sprite_index actual_dec_idx = index_for_decorations(fg, rf, rg, rg, fg->fcm).start_idx;
    if (actual_dec_idx != dm.start_idx) fatal("dec_idx: %u != actual_dec_idx: %u", dm.start_idx, actual_dec_idx);

#undef do_one
}

static size_t
initialize_font(FontGroup *fg, unsigned int desc_idx, const char *ftype) {
    PyObject *d = PyObject_CallFunction(descriptor_for_idx, "I", desc_idx);
    if (d == NULL) { PyErr_Print(); fatal("Failed for %s font", ftype); }
    bool bold = PyObject_IsTrue(PyTuple_GET_ITEM(d, 1));
    bool italic = PyObject_IsTrue(PyTuple_GET_ITEM(d, 2));
    PyObject *x = PyTuple_GET_ITEM(d, 0);
    PyObject *face  = PyUnicode_Check(x) ? face_from_path(PyUnicode_AsUTF8(x), 0, (FONTS_DATA_HANDLE)fg) : desc_to_face(x, (FONTS_DATA_HANDLE)fg);
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
    vt_init(&fg->scaled_font_map);
    vt_init(&fg->decorations_index_map);
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
    calc_cell_metrics(fg, fg->fonts[fg->medium_font_idx].face);
    ensure_canvas_can_fit(fg, 8, 1);
    sprite_tracker_set_layout(&fg->sprite_tracker, fg->fcm.cell_width, fg->fcm.cell_height);
    // rescale the symbol_map faces for the desired cell height, this is how fallback fonts are sized as well
    for (size_t i = 0; i < descriptor_indices.num_symbol_fonts; i++) {
        Font *font = fg->fonts + i + fg->first_symbol_font_idx;
        set_size_for_face(font->face, fg->fcm.cell_height, true, (FONTS_DATA_HANDLE)fg);
    }
    ScaledFontData sfd = {.fcm=fg->fcm, .font_sz_in_pts=fg->font_sz_in_pts};
    vt_insert(&fg->scaled_font_map, 1.f, sfd);
}


void
send_prerendered_sprites_for_window(OSWindow *w) {
    FontGroup *fg = (FontGroup*)w->fonts_data;
    if (!fg->sprite_map) {
        fg->sprite_map = alloc_sprite_map();
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
    Py_CLEAR(descriptor_for_idx);
    free_font_groups();
    free(ligature_types);
    if (harfbuzz_buffer) { hb_buffer_destroy(harfbuzz_buffer); harfbuzz_buffer = NULL; }
    free(group_state.groups); group_state.groups = NULL; group_state.groups_capacity = 0;
    free(global_glyph_render_scratch.glyphs);
    free(global_glyph_render_scratch.sprite_positions);
    if (global_glyph_render_scratch.lc) { cleanup_list_of_chars(global_glyph_render_scratch.lc); free(global_glyph_render_scratch.lc); }
    global_glyph_render_scratch = (GlyphRenderScratch){0};
    free(shape_buffer.codepoints); zero_at_ptr(&shape_buffer);
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
test_sprite_position_increment(PyObject UNUSED *self, PyObject *args UNUSED) {
    if (!num_font_groups) { PyErr_SetString(PyExc_RuntimeError, "must create font group first"); return NULL; }
    FontGroup *fg = font_groups;
    unsigned int x, y, z;
    sprite_index_to_pos(current_sprite_index(&fg->sprite_tracker), fg->sprite_tracker.xnum, fg->sprite_tracker.ynum, &x, &y, &z);
    if (!do_increment(fg)) return NULL;
    return Py_BuildValue("III", x, y, z);
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

static uint32_t
alpha_blend(uint32_t fg, uint32_t bg) {
    uint32_t r1 = (fg >> 16) & 0xFF, g1 = (fg >> 8) & 0xFF, b1 = fg & 0xFF, a = (fg >> 24) & 0xff;
    uint32_t r2 = (bg >> 16) & 0xFF, g2 = (bg >> 8) & 0xFF, b2 = bg & 0xFF;
    float alpha = a / 255.f;

#define mix(x) uint32_t x = ((uint32_t)(alpha * x##1 + (1.0f - alpha) * x##2)) & 0xff;
    mix(r); mix(g); mix(b);
#undef mix
    // Combine components into result color
    return (0xff000000) | (r << 16) | (g << 8) | b;
}

static PyObject*
render_decoration(PyObject *self UNUSED, PyObject *args) {
    const char *which;
    FontCellMetrics fcm = {0};
    double dpi = 96.0;
    if (!PyArg_ParseTuple(args, "sIIII|d", &which, &fcm.cell_width, &fcm.cell_height, &fcm.underline_position, &fcm.underline_thickness, &dpi)) return NULL;
    PyObject *ans = PyBytes_FromStringAndSize(NULL, (Py_ssize_t)fcm.cell_width * fcm.cell_height);
    if (!ans) return NULL;
    memset(PyBytes_AS_STRING(ans), 0, PyBytes_GET_SIZE(ans));
#define u(x) if (strcmp(which, #x) == 0) add_ ## x ## _underline((uint8_t*)PyBytes_AS_STRING(ans), fcm)
    u(curl);
    u(dashed);
    u(dotted);
    u(double);
    u(straight);
    else if (strcmp(which, "strikethrough") == 0) add_strikethrough((uint8_t*)PyBytes_AS_STRING(ans), fcm);
    else if (strcmp(which, "missing") == 0) add_missing_glyph((uint8_t*)PyBytes_AS_STRING(ans), fcm);
    else if (strcmp(which, "beam_cursor") == 0) add_beam_cursor((uint8_t*)PyBytes_AS_STRING(ans), fcm, dpi);
    else if (strcmp(which, "underline_cursor") == 0) add_underline_cursor((uint8_t*)PyBytes_AS_STRING(ans), fcm, dpi);
    else if (strcmp(which, "hollow_cursor") == 0) add_hollow_cursor((uint8_t*)PyBytes_AS_STRING(ans), fcm, dpi, dpi);
    else { Py_CLEAR(ans); PyErr_Format(PyExc_KeyError, "Unknown decoration type: %s", which); }
    return ans;
#undef u
}

static PyObject*
concat_cells(PyObject UNUSED *self, PyObject *args) {
    // Concatenate cells returning RGBA data
    unsigned int cell_width, cell_height;
    int is_32_bit;
    PyObject *cells;
    unsigned long bgcolor = 0;
    if (!PyArg_ParseTuple(args, "IIpO!|k", &cell_width, &cell_height, &is_32_bit, &PyTuple_Type, &cells, &bgcolor)) return NULL;
    size_t num_cells = PyTuple_GET_SIZE(cells), r, c, i;
    PyObject *ans = PyBytes_FromStringAndSize(NULL, (size_t)4 * cell_width * cell_height * num_cells);
    if (ans == NULL) return PyErr_NoMemory();
    pixel *dest = (pixel*)PyBytes_AS_STRING(ans);
    for (r = 0; r < cell_height; r++) {
        for (c = 0; c < num_cells; c++) {
            void *s = ((uint8_t*)PyBytes_AS_STRING(PyTuple_GET_ITEM(cells, c)));
            if (is_32_bit) {
                pixel *src = (pixel*)s + cell_width * r;
                for (i = 0; i < cell_width; i++, dest++) dest[0] = alpha_blend(src[0], bgcolor);
            } else {
                uint8_t *src = (uint8_t*)s + cell_width * r;
                for (i = 0; i < cell_width; i++, dest++) dest[0] = alpha_blend(0x00ffffff | ((src[i] & 0xff) << 24), bgcolor);
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
    return Py_BuildValue("III", fg->fcm.cell_width, fg->fcm.cell_height, fg->fcm.baseline);
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

static PyObject*
set_allow_use_of_box_fonts(PyObject *self UNUSED, PyObject *val) {
    allow_use_of_box_fonts = PyObject_IsTrue(val);
    Py_RETURN_NONE;
}

static PyObject*
sprite_idx_to_pos(PyObject *self UNUSED, PyObject *args) {
    unsigned x, y, z, idx, xnum, ynum;
    if (!PyArg_ParseTuple(args, "III", &idx, &xnum, &ynum)) return NULL;
    sprite_index_to_pos(idx, xnum, ynum, &x, &y, &z);
    return Py_BuildValue("III", x, y, z);
}

static PyObject*
pyrender_box_char(PyObject *self UNUSED, PyObject *args) {
    unsigned int ch;
    unsigned long width, height; double dpi_x = 96., dpi_y = 96., scale = 1.;
    if (!PyArg_ParseTuple(args, "Ikk|ddd", &ch, &width, &height, &scale, &dpi_x, &dpi_y)) return NULL;
    RAII_PyObject(ans, PyBytes_FromStringAndSize(NULL, width*16 * height*16));
    if (!ans) return NULL;
    render_box_char(ch, (uint8_t*)PyBytes_AS_STRING(ans), width, height, dpi_x, dpi_y, scale);
    if (_PyBytes_Resize(&ans, width * height) != 0) return NULL;
    return Py_NewRef(ans);
}

static PyMethodDef module_methods[] = {
    METHODB(set_font_data, METH_VARARGS),
    METHODB(sprite_idx_to_pos, METH_VARARGS),
    METHODB(free_font_data, METH_NOARGS),
    METHODB(create_test_font_group, METH_VARARGS),
    METHODB(sprite_map_set_layout, METH_VARARGS),
    METHODB(test_sprite_position_increment, METH_NOARGS),
    METHODB(concat_cells, METH_VARARGS),
    METHODB(render_decoration, METH_VARARGS),
    METHODB(set_send_sprite_to_gpu, METH_O),
    METHODB(set_allow_use_of_box_fonts, METH_O),
    METHODB(test_shape, METH_VARARGS),
    METHODB(current_fonts, METH_VARARGS),
    METHODB(test_render_line, METH_VARARGS),
    METHODB(get_fallback_font, METH_VARARGS),
    {"specialize_font_descriptor", (PyCFunction)pyspecialize_font_descriptor, METH_VARARGS, ""},
    {"render_box_char", (PyCFunction)pyrender_box_char, METH_VARARGS, ""},
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
