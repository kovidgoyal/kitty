/*
 * fonts.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"
#include "state.h"

#define MISSING_GLYPH 4

typedef uint16_t glyph_index;
typedef void (*send_sprite_to_gpu_func)(unsigned int, unsigned int, unsigned int, uint8_t*);
send_sprite_to_gpu_func current_send_sprite_to_gpu = NULL;
static PyObject *python_send_to_gpu_impl = NULL;
extern PyTypeObject Line_Type;

typedef struct SpritePosition SpritePosition;

struct SpritePosition {
    SpritePosition *next;
    bool filled, rendered;
    sprite_index x, y, z;
    uint8_t ligature_index;
    glyph_index glyph;
    uint64_t extra_glyphs;
};


typedef struct {
    size_t max_array_len, max_texture_size, max_y;
    unsigned int x, y, z, xnum, ynum;
} GPUSpriteTracker;


static GPUSpriteTracker sprite_tracker = {0};
static hb_buffer_t *harfbuzz_buffer = NULL;
static char_type shape_buffer[2048] = {0};


typedef struct {
    PyObject *face;
    hb_font_t *hb_font;
    // Map glyphs to sprite map co-ords
    SpritePosition sprite_map[1024]; 
    uint8_t dummy_glyph_cache[1 << (8 * sizeof(glyph_index))];
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


static SpritePosition*
sprite_position_for(Font *font, glyph_index glyph, uint64_t extra_glyphs, uint8_t ligature_index, int *error) {
    glyph_index idx = glyph & 0x3ff;
    SpritePosition *s = font->sprite_map + idx;
    // Optimize for the common case of glyph under 1024 already in the cache
    if (LIKELY(s->glyph == glyph && s->filled && s->extra_glyphs == extra_glyphs && s->ligature_index == ligature_index)) return s;  // Cache hit
    while(true) {
        if (s->filled) {
            if (s->glyph == glyph && s->extra_glyphs == extra_glyphs && s->ligature_index == ligature_index) return s;  // Cache hit
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
    s->ligature_index = ligature_index;
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
#define CLEAR(s) s->filled = false; s->rendered = false; s->glyph = 0; s->extra_glyphs = 0; s->x = 0; s->y = 0; s->z = 0; s->ligature_index = 0;
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

static inline PyObject*
desc_to_face(PyObject *desc) {
    PyObject *d = specialize_font_descriptor(desc);
    if (d == NULL) return NULL;
    PyObject *ans = face_from_descriptor(d);
    Py_DECREF(d);
    return ans;
}


static inline bool
alloc_font(Font *f, PyObject *descriptor, bool bold, bool italic, bool is_face) {
    PyObject *face;
    if (is_face) { face = descriptor; Py_INCREF(face); }
    else { face = desc_to_face(descriptor); if (face == NULL) return false; }
    f->face = face; 
    f->hb_font = harfbuzz_font_for_face(face);
    if (f->hb_font == NULL) { PyErr_NoMemory(); return false; }
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

static inline void
clear_font(Font *f) { 
    f->hb_font = NULL;
    Py_CLEAR(f->face); 
    clear_sprite_map(f);
    f->bold = false; f->italic = false;
}


static Font medium_font = {0}, bold_font = {0}, italic_font = {0}, bi_font = {0}, box_font = {0};
static Font fallback_fonts[256] = {{0}};
typedef enum { FONT, BLANK_FONT, BOX_FONT, MISSING_FONT } FontType;

typedef struct {
    char_type left, right;
    size_t font_idx;
} SymbolMap;
static SymbolMap* symbol_maps = NULL;
static Font *symbol_map_fonts = NULL;
static size_t symbol_maps_count = 0, symbol_map_fonts_count = 0;

static unsigned int cell_width = 0, cell_height = 0, baseline = 0, underline_position = 0, underline_thickness = 0;
static uint8_t *canvas = NULL;
#define CELLS_IN_CANVAS 16
static inline void 
clear_canvas(void) { memset(canvas, 0, CELLS_IN_CANVAS * cell_width * cell_height); }

static void
python_send_to_gpu(unsigned int x, unsigned int y, unsigned int z, uint8_t* buf) {
    if (python_send_to_gpu_impl != NULL && python_send_to_gpu_impl != Py_None) {
        PyObject *ret = PyObject_CallFunction(python_send_to_gpu_impl, "IIIN", x, y, z, PyBytes_FromStringAndSize((const char*)buf, cell_width * cell_height));
        if (ret == NULL) PyErr_Print();
        else Py_DECREF(ret);
    }
}


static inline PyObject*
update_cell_metrics() {
#define CALL(f, desired_height, force) { if ((f)->face) { if(!set_size_for_face((f)->face, desired_height, force)) return NULL; (f)->hb_font = harfbuzz_font_for_face((f)->face); } clear_sprite_map((f)); }
    CALL(&medium_font, 0, false); CALL(&bold_font, 0, false); CALL(&italic_font, 0, false); CALL(&bi_font, 0, false); CALL(&box_font, 0, false);
    cell_metrics(medium_font.face, &cell_width, &cell_height, &baseline, &underline_position, &underline_thickness);
    if (!cell_width) { PyErr_SetString(PyExc_ValueError, "Failed to calculate cell width for the specified font."); return NULL; }
    if (OPT(adjust_line_height_px) != 0) cell_height += OPT(adjust_line_height_px);
    if (OPT(adjust_line_height_frac) != 0.f) cell_height *= OPT(adjust_line_height_frac);
    if (cell_height < 4) { PyErr_SetString(PyExc_ValueError, "line height too small after adjustment"); return NULL; }
    if (cell_height > 1000) { PyErr_SetString(PyExc_ValueError, "line height too large after adjustment"); return NULL; }
    underline_position = MIN(cell_height - 1, underline_position);
    sprite_tracker_set_layout(cell_width, cell_height);
    global_state.cell_width = cell_width; global_state.cell_height = cell_height;
    free(canvas); canvas = malloc(CELLS_IN_CANVAS * cell_width * cell_height);
    if (canvas == NULL) return PyErr_NoMemory();
    for (size_t i = 0; fallback_fonts[i].face != NULL; i++)  {
        CALL(fallback_fonts + i, cell_height, true);
    }
    for (size_t i = 0; i < symbol_map_fonts_count; i++)  {
        CALL(symbol_map_fonts + i, cell_height, true);
    }
    return Py_BuildValue("IIIII", cell_width, cell_height, baseline, underline_position, underline_thickness);
#undef CALL
}

static PyObject*
set_font_size(PyObject UNUSED *m, PyObject *args) {
    if (!PyArg_ParseTuple(args, "f", &global_state.font_sz_in_pts)) return NULL;
    return update_cell_metrics();
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
    if (i == (sizeof(fallback_fonts)/sizeof(fallback_fonts[0])-1)) { return NULL; }
    Font* base_font;
    if (bold) base_font = italic ? &bi_font : &bold_font;
    else base_font = italic ? &italic_font : &medium_font;
    if (!base_font->face) base_font = &medium_font;
    PyObject *face = create_fallback_face(base_font->face, cell, bold, italic);
    if (face == NULL) { PyErr_Print(); return NULL; }
    if (face == Py_None) { Py_DECREF(face); return NULL; }
    if (!alloc_font(fallback_fonts + i, face, bold, italic, true)) { Py_DECREF(face); fatal("Out of memory"); }
    set_size_for_face(face, cell_height, true);
    Py_DECREF(face);
    return fallback_fonts + i;
}

static inline Font*
in_symbol_maps(char_type ch) {
    for (size_t i = 0; i < symbol_maps_count; i++) {
        if (symbol_maps[i].left <= ch && ch <= symbol_maps[i].right) return symbol_map_fonts + symbol_maps[i].font_idx;
    }
    return NULL;
}

static FontType
font_for_cell(Cell *cell, Font** font) {
START_ALLOW_CASE_RANGE
    switch(cell->ch) {
        case 0:
            return BLANK_FONT;
        case 0x2500 ... 0x2570:
        case 0x2574 ... 0x257f:
        case 0xe0b0:
        case 0xe0b2:
            return BOX_FONT;
        default:
            *font = in_symbol_maps(cell->ch);
            if (*font != NULL) return FONT;
            switch(BI_VAL(cell->attrs)) {
                case 0:
                    *font = &medium_font;
                    break;
                case 1:
                    *font = bold_font.face ? &bold_font : &medium_font;
                    break;
                case 2:
                    *font = italic_font.face ? &italic_font : &medium_font;
                    break;
                case 3:
                    *font = bi_font.face ? &bi_font : &medium_font;
                    break;
            }
            if (has_cell_text(*font, cell)) return FONT;
            *font = fallback_font(cell);
            return *font ? FONT : MISSING_FONT;
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
        case 0x2500 ... 0x257f:
            return ch - 0x2500;
        case 0xe0b0:
            return 0x80;
        case 0xe0b2:
            return 0x81;
        default:
            return 0x82;
    }
END_ALLOW_CASE_RANGE
}

static PyObject* box_drawing_function = NULL;

static void 
render_box_cell(Cell *cell) {
    int error = 0;
    glyph_index glyph = box_glyph_id(cell->ch);
    SpritePosition *sp = sprite_position_for(&box_font, glyph, 0, false, &error);
    if (sp == NULL) {
        sprite_map_set_error(error); PyErr_Print();
        set_sprite(cell, 0, 0, 0);
        return;
    }
    set_sprite(cell, sp->x, sp->y, sp->z);
    if (sp->rendered) return;
    sp->rendered = true;
    PyObject *ret = PyObject_CallFunction(box_drawing_function, "I", cell->ch);
    if (ret == NULL) { PyErr_Print(); return; }
    current_send_sprite_to_gpu(sp->x, sp->y, sp->z, PyLong_AsVoidPtr(PyTuple_GET_ITEM(ret, 0)));
    Py_DECREF(ret);
}

static inline void
load_hb_buffer(Cell *first_cell, index_type num_cells) {  
    index_type num;
    hb_buffer_clear_contents(harfbuzz_buffer);
    while (num_cells) {
        attrs_type prev_width = 0;
        for (num = 0; num_cells && num < sizeof(shape_buffer)/sizeof(shape_buffer[0]) - 20; first_cell++, num_cells--) {
            if (prev_width == 2) { prev_width = 0; continue; }
            shape_buffer[num++] = first_cell->ch;
            prev_width = first_cell->attrs & WIDTH_MASK;
            if (first_cell->cc) {
                shape_buffer[num++] = first_cell->cc & CC_MASK;
                combining_type cc2 = first_cell->cc >> 16;
                if (cc2) shape_buffer[num++] = cc2 & CC_MASK;
            }
        }
        hb_buffer_add_utf32(harfbuzz_buffer, shape_buffer, num, 0, num);
    }
    hb_buffer_guess_segment_properties(harfbuzz_buffer);
}


static inline void
set_cell_sprite(Cell *cell, SpritePosition *sp) {
    cell->sprite_x = sp->x; cell->sprite_y = sp->y; cell->sprite_z = sp->z;
}

static inline uint8_t*
extract_cell_from_canvas(unsigned int i, unsigned int num_cells) {
    uint8_t *ans = canvas + (cell_width * cell_height * (CELLS_IN_CANVAS - 1)), *dest = ans, *src = canvas + (i * cell_width);
    unsigned int stride = cell_width * num_cells;
    for (unsigned int r = 0; r < cell_height; r++, dest += cell_width, src += stride) memcpy(dest, src, cell_width);
    return ans;
}

static inline void
render_group(unsigned int num_cells, unsigned int num_glyphs, Cell *cells, hb_glyph_info_t *info, hb_glyph_position_t *positions, Font *font, glyph_index glyph, uint64_t extra_glyphs) {
    static SpritePosition* sprite_position[16];
    int error = 0;
    for (unsigned int i = 0; i < num_cells; i++) {
        sprite_position[i] = sprite_position_for(font, glyph, extra_glyphs, (uint8_t)i, &error);
        if (error != 0) { sprite_map_set_error(error); PyErr_Print(); return; }
    }
    if (sprite_position[0]->rendered) {
        for (unsigned int i = 0; i < num_cells; i++) { set_cell_sprite(cells + i, sprite_position[i]); }
        return;
    }

    clear_canvas();
    render_glyphs_in_cells(font->face, font->bold, font->italic, info, positions, num_glyphs, canvas, cell_width, cell_height, num_cells, baseline);

    for (unsigned int i = 0; i < num_cells; i++) { 
        sprite_position[i]->rendered = true;
        set_cell_sprite(cells + i, sprite_position[i]); 
        uint8_t *buf = num_cells == 1 ? canvas : extract_cell_from_canvas(i, num_cells);
        current_send_sprite_to_gpu(sprite_position[i]->x, sprite_position[i]->y, sprite_position[i]->z, buf);
    }

}

static inline bool
is_dummy_glyph(glyph_index glyph_id, Font *font) {
    // we assume glyphs with no width are dummy glyphs used for a contextual ligature, so skip it
    if (!font->dummy_glyph_cache[glyph_id]) {
        static hb_glyph_extents_t extents;
        hb_font_get_glyph_extents(font->hb_font, glyph_id, &extents);
        font->dummy_glyph_cache[glyph_id] = extents.width == 0 ? 1 : 2;
    } 
    return font->dummy_glyph_cache[glyph_id] & 1;
}

static inline int
num_codepoints_in_cell(Cell *cell) {
    unsigned int ans = 1;
    if (cell->cc) ans += ((cell->cc >> CC_SHIFT) & CC_MASK) ? 2 : 1;
    return ans;
}

typedef struct {
    Cell *cell;
    int num_codepoints;
} CellData;

static inline unsigned int
check_cell_consumed(CellData *cell_data, Cell *last_cell) {
    cell_data->num_codepoints--;
    if (cell_data->num_codepoints <= 0) {
        attrs_type width = cell_data->cell->attrs & WIDTH_MASK;
        cell_data->cell += MAX(1, width);
        if (cell_data->cell <= last_cell) cell_data->num_codepoints = num_codepoints_in_cell(cell_data->cell);
        return width;
    }
    return 0;
}

static inline glyph_index
next_group(Font *font, unsigned int *num_group_cells, unsigned int *num_group_glyphs, Cell *cells, hb_glyph_info_t *info, unsigned int max_num_glyphs, unsigned int max_num_cells, uint64_t *extra_glyphs) {
    // See https://github.com/behdad/harfbuzz/issues/615 for a discussion of
    // how to break text into cells. In addition, we have to deal with
    // monospace ligature fonts that use dummy glyphs of zero size to implement
    // their ligatures.
    
    CellData cell_data;
    cell_data.cell = cells; cell_data.num_codepoints = num_codepoints_in_cell(cells);
    glyph_index significant_glyphs[5];
    significant_glyphs[0] = 0;
    unsigned int num_significant_glyphs = 0;
    unsigned int ncells = 0, nglyphs = 0, n;
    uint32_t previous_cluster = UINT32_MAX, cluster;
    Cell *last_cell = cells + max_num_cells;
    while(num_significant_glyphs < sizeof(significant_glyphs)/sizeof(significant_glyphs[0]) && ncells < max_num_cells && nglyphs < max_num_glyphs) {
        glyph_index glyph_id = info[nglyphs].codepoint;
        cluster = info[nglyphs].cluster;
        nglyphs += 1;
        bool is_dummy = is_dummy_glyph(glyph_id, font);
        if (!is_dummy) significant_glyphs[num_significant_glyphs++] = glyph_id;
        if (cluster > previous_cluster || nglyphs == 1) {
            n = nglyphs == 1 ? 1 : cluster - previous_cluster;
            unsigned int before = ncells;
            while(n-- && ncells < max_num_cells) ncells += check_cell_consumed(&cell_data, last_cell);
            if (ncells > before && !is_dummy) break;
        }
        previous_cluster = cluster;
    }
    *num_group_cells = MAX(1, MIN(ncells, max_num_cells));
    *num_group_glyphs = MAX(1, MIN(nglyphs, max_num_glyphs));

#define G(n) ((uint64_t)(significant_glyphs[n] & 0xffff))
    switch(num_significant_glyphs) {
        case 0:
        case 1:
            *extra_glyphs = 0;
            break;
        case 2:
            *extra_glyphs = G(1);
            break;
        case 3:
            *extra_glyphs = G(1) | (G(2) << 16);
            break;
        case 4:
            *extra_glyphs = G(1) | (G(2) << 16) | (G(3) << 32);
            break;
        default:  // we only support a maximum of four extra glyphs per cell
            *extra_glyphs = G(1) | (G(2) << 16) | (G(3) << 32) | (G(4) << 48);
            break;
    }
#undef G
    return significant_glyphs[0];
}

static inline unsigned int
shape(Cell *first_cell, index_type num_cells, hb_font_t *font, hb_glyph_info_t **info, hb_glyph_position_t **positions) {
    load_hb_buffer(first_cell, num_cells);
    hb_shape(font, harfbuzz_buffer, NULL, 0);
    unsigned int info_length, positions_length;
    *info = hb_buffer_get_glyph_infos(harfbuzz_buffer, &info_length);
    *positions = hb_buffer_get_glyph_positions(harfbuzz_buffer, &positions_length);
    if (!info || !positions) return 0;
    return MIN(info_length, positions_length);
}


static inline void
shape_run(Cell *first_cell, index_type num_cells, Font *font) {
    hb_glyph_info_t *info;
    hb_glyph_position_t *positions;
    unsigned int num_glyphs = shape(first_cell, num_cells, font->hb_font, &info, &positions);
#if 0
        // You can also generate this easily using hb-shape --show-flags --show-extents --cluster-level=1 --shapers=ot /path/to/font/file text
        hb_buffer_serialize_glyphs(harfbuzz_buffer, 0, num_glyphs, (char*)canvas, CELLS_IN_CANVAS * cell_width * cell_height, NULL, font->hb_font, HB_BUFFER_SERIALIZE_FORMAT_TEXT, HB_BUFFER_SERIALIZE_FLAG_DEFAULT | HB_BUFFER_SERIALIZE_FLAG_GLYPH_EXTENTS | HB_BUFFER_SERIALIZE_FLAG_GLYPH_FLAGS);
        printf("\n%s\n", canvas);
        clear_canvas();
#endif
    unsigned int run_pos = 0, cell_pos = 0, num_group_glyphs, num_group_cells;
    uint64_t extra_glyphs; glyph_index first_glyph;
    while(run_pos < num_glyphs && cell_pos < num_cells) {
        first_glyph = next_group(font, &num_group_cells, &num_group_glyphs, first_cell + cell_pos, info + run_pos, num_glyphs - run_pos, num_cells - cell_pos, &extra_glyphs);
        /* printf("Group: num_group_cells: %u num_group_glyphs: %u\n", num_group_cells, num_group_glyphs); */
        render_group(num_group_cells, num_group_glyphs, first_cell + cell_pos, info + run_pos, positions + run_pos, font, first_glyph, extra_glyphs);
        run_pos += num_group_glyphs; cell_pos += num_group_cells;
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
    load_hb_buffer(line->cells, num);
    PyObject *face = NULL;
    Font *font = &medium_font;
    if (path) {
        face = face_from_path(path, index);
        if (face == NULL) return NULL;
        Font f = {0};
        font = &f;
        font->hb_font = harfbuzz_font_for_face(face); 
        if (!font->hb_font) return NULL;
    } 
    hb_shape(font->hb_font, harfbuzz_buffer, NULL, 0);
    hb_glyph_info_t *info;
    hb_glyph_position_t *positions;
    unsigned int num_glyphs = shape(line->cells, num, font->hb_font, &info, &positions);

    PyObject *ans = PyList_New(0);
    unsigned int run_pos = 0, cell_pos = 0, num_group_glyphs, num_group_cells;
    uint64_t extra_glyphs; glyph_index first_glyph;
    while(run_pos < num_glyphs && cell_pos < num) {
        first_glyph = next_group(font, &num_group_cells, &num_group_glyphs, line->cells + cell_pos, info + run_pos, num_glyphs - run_pos, num - cell_pos, &extra_glyphs);
        PyList_Append(ans, Py_BuildValue("IIIK", num_group_cells, num_group_glyphs, first_glyph, extra_glyphs));
        run_pos += num_group_glyphs; cell_pos += num_group_cells;
    }
    Py_CLEAR(face);
    return ans;
}

static inline void 
render_run(Cell *first_cell, index_type num_cells, Font *font, FontType ft) {
    switch(ft) {
        case FONT:
            shape_run(first_cell, num_cells, font);
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

void
render_line(Line *line) {
#define RENDER if ((run_font != NULL || run_font_type != FONT) && i > first_cell_in_run) render_run(line->cells + first_cell_in_run, i - first_cell_in_run, run_font, run_font_type);
    Font *run_font = NULL;
    FontType run_font_type = MISSING_FONT;
    index_type first_cell_in_run, i;
    attrs_type prev_width = 0;
    for (i=0, first_cell_in_run=0; i < line->xnum; i++) {
        if (prev_width == 2) { prev_width = 0; continue; }
        Cell *cell = line->cells + i;
        Font *cell_font = NULL;
        FontType cell_font_type = font_for_cell(cell, &cell_font);
        prev_width = cell->attrs & WIDTH_MASK;
        if (cell_font_type == run_font_type && cell_font == run_font) continue;
        RENDER;
        run_font = cell_font; run_font_type = cell_font_type;
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
    clear_font(&medium_font); clear_font(&bold_font); clear_font(&italic_font); clear_font(&bi_font); clear_sprite_map(&box_font);
    if (!alloc_font(&medium_font, medium, false, false, false)) return NULL;
    if (bold && !alloc_font(&bold_font, bold, true, false, false)) return NULL;
    if (italic && !alloc_font(&italic_font, italic, false, true, false)) return NULL;
    if (bi && !alloc_font(&bi_font, bi, true, true, false)) return NULL;
    for (size_t i = 0; fallback_fonts[i].face != NULL; i++) clear_font(fallback_fonts + i);
    for (size_t i = 0; symbol_map_fonts_count; i++) free_font(symbol_map_fonts + i);
    free(symbol_maps); free(symbol_map_fonts); symbol_maps = NULL; symbol_map_fonts = NULL;
    symbol_maps_count = 0; symbol_map_fonts_count = 0;

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
            if (!alloc_font(symbol_map_fonts + i, face, bold != 0, italic != 0, false)) return NULL;
        }
        for (size_t i = 0; i < symbol_maps_count; i++) {
            unsigned int left, right, font_idx;
            if (!PyArg_ParseTuple(PyTuple_GET_ITEM(sm, i), "III", &left, &right, &font_idx)) return NULL;
            symbol_maps[i].left = left; symbol_maps[i].right = right; symbol_maps[i].font_idx = font_idx;
        }
    }
    return update_cell_metrics();
}

static void
finalize(void) {
    Py_CLEAR(python_send_to_gpu_impl);
    free(canvas);
    Py_CLEAR(box_drawing_function);
    free_font(&medium_font); free_font(&bold_font); free_font(&italic_font); free_font(&bi_font); free_font(&box_font);
    for (size_t i = 0; fallback_fonts[i].face != NULL; i++) free_font(fallback_fonts + i); 
    for (size_t i = 0; i < symbol_map_fonts_count; i++) free_font(symbol_map_fonts + i);
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
    SpritePosition *pos = sprite_position_for(&medium_font, glyph, extra_glyphs, 0, &error);
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
        current_send_sprite_to_gpu(x, y, z, PyLong_AsVoidPtr(PyTuple_GET_ITEM(args, i)));
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
    unsigned int cell_width, cell_height;
    PyObject *cells;
    if (!PyArg_ParseTuple(args, "IIO!", &cell_width, &cell_height, &PyTuple_Type, &cells)) return NULL;
    size_t num_cells = PyTuple_GET_SIZE(cells), r, c, i;
    PyObject *ans = PyBytes_FromStringAndSize(NULL, 3 * cell_width * cell_height * num_cells);
    if (ans == NULL) return PyErr_NoMemory();
    uint8_t *dest = (uint8_t*)PyBytes_AS_STRING(ans), *src;
    for (r = 0; r < cell_height; r++) {
        for (c = 0; c < num_cells; c++) {
            src = ((uint8_t*)PyBytes_AS_STRING(PyTuple_GET_ITEM(cells, c))) + cell_width * r;
            for (i = 0; i < cell_width; i++, dest += 3) {
                dest[0] = src[i]; dest[1] = src[i]; dest[2] = src[i];
            }

        }
    }
    return ans;
}

static PyObject*
current_fonts(PyObject UNUSED *self) {
    PyObject *ans = PyDict_New();
    if (!ans) return NULL;
#define SET(key, val) {if (PyDict_SetItemString(ans, #key, val) != 0) { goto error; }}
    SET(medium, medium_font.face);
    if (bold_font.face) SET(bold, bold_font.face);
    if (italic_font.face) SET(italic, italic_font.face);
    if (bi_font.face) SET(bi, bi_font.face);
    int num = 0;
    while (fallback_fonts[num].face) num++;
    PyObject *ff = PyTuple_New(num);
    if (!ff) goto error;
    num = 0;
    while (fallback_fonts[num].face) {
        Py_INCREF(fallback_fonts[num].face);
        PyTuple_SET_ITEM(ff, num, fallback_fonts[num].face);
        num++;
    }
    SET(fallback, ff);
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
    static Py_UCS4 char_buf[16];
    if (!PyUnicode_AsUCS4(text, char_buf, sizeof(char_buf)/sizeof(char_buf[0]), 1)) return NULL;
    Cell cell = {0};
    cell.ch = char_buf[0];
    if (PyUnicode_GetLength(text) > 1) cell.cc |= char_buf[1] & CC_MASK;
    if (PyUnicode_GetLength(text) > 2) cell.cc |= (char_buf[2] & CC_MASK) << 16;
    if (bold) cell.attrs |= 1 << BOLD_SHIFT;
    if (italic) cell.attrs |= 1 << ITALIC_SHIFT;
    Font *ans = fallback_font(&cell);
    if (ans == NULL) { PyErr_SetString(PyExc_ValueError, "Too many fallback fonts"); return NULL; }
    return ans->face;
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
