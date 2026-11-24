/*
 * line.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "text-cache.h"
#include "style-table.h"


#define WIDTH_MASK (3u)
#define DECORATION_MASK (7u)
#define SGR_MASK (~(((CellAttrs){.mark = MARK_MASK}).val))
#define MAX_NUM_CODEPOINTS_PER_CELL 24u
// Text presentation selector
#define VS15 0xfe0e
// Emoji presentation selector
#define VS16 0xfe0f

typedef struct {
    color_type fg, bg, decoration_fg;
    sprite_index sprite_idx;
    CellAttrs attrs;
} GPUCell;
static_assert(sizeof(GPUCell) == 20, "Fix the ordering of GPUCell");
// GPUCell is used when rendering lines, see render_line()

// The data for a cell uploaded to the GPU. The shaders get the style of the
// cell from a texture holding the CellStyleTable of the screen.
typedef struct CellGPUData {
    sprite_index sprite_idx;
    uint32_t style_and_mark; // style_idx << CELL_GPU_STYLE_SHIFT | mark
} CellGPUData;
static_assert(sizeof(CellGPUData) == 8, "Fix the ordering of CellGPUData");
#define CELL_GPU_STYLE_SHIFT 2u

// Data computed when rendering a cell. The style of a cell is stored in its CPUCell.
typedef struct RenderCell {
    sprite_index sprite_idx;
    uint8_t mark;
    // the embedding level the cell was shaped at: written by the bidi upload, by the region code for kept rows and strip
    // lines, and cleared by bidi_unstamp(); 0 without bidi
    uint8_t level;
    uint8_t padding[2];
} RenderCell;
// The level of cells that are never reordered and are shaped in the direction guessed from their text, such as scaled
// cells, cells of a horizontally scrolling region, multicells across a span edge, the pre-edit text and the rows with a
// record of a paragraph that is left unreordered. Even, and above the levels FriBidi resolves.
#define BIDI_LEVEL_FIXED 0x80
static_assert(sizeof(RenderCell) == 8, "Fix the ordering of RenderCell");

#define SCALE_BITS 3
#define WIDTH_BITS 3
#define SUBSCALE_BITS 4
#define VALIGN_BITS 2
#define HALIGN_BITS 2

typedef union CPUCell {
    struct {
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
        char_type ch_or_idx : sizeof(char_type) * 8 - 1;
        char_type ch_is_idx : 1;
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
        char_type ch_is_idx : 1;
        char_type ch_or_idx : sizeof(char_type) * 8 - 1;
#else
#error "Unsupported endianness"
#endif
        // the fields below are ordered so that none of them straddles a 32
        // bit boundary, the style index uses all the bits remaining at the end
        char_type hyperlink_id : sizeof(hyperlink_id_type) * 8;
        char_type scale : SCALE_BITS;
        char_type subscale_n : SUBSCALE_BITS;
        char_type subscale_d : SUBSCALE_BITS;
        char_type valign : VALIGN_BITS;
        char_type halign : HALIGN_BITS;
        char_type next_char_was_wrapped : 1;
        char_type is_multicell : 1;
        char_type natural_width : 1;
        char_type x : WIDTH_BITS + SCALE_BITS;
        char_type y : SCALE_BITS;
        char_type width : WIDTH_BITS;
        // Index of the formatting of this cell in the CellStyleTable of the screen
        char_type style_idx : STYLE_IDX_BITS;
    };
    struct {
        char_type ch_and_idx : sizeof(char_type) * 8;
        char_type : 32;
        char_type : 32;
    };
} CPUCell;
static_assert(sizeof(CPUCell) == 12, "Fix the ordering of CPUCell");

typedef union LineAttrs {
    struct {
        uint8_t has_dirty_text : 1;
        uint8_t has_image_placeholders : 1;
        uint8_t prompt_kind : 2;
        // the bidi controls the line was first written under in implicit mode. On a line without a stamp the other two are
        // zero, unless a leading mark set bidi_auto: then bidi_rtl is the direction its first text written in implicit mode
        // takes.
        uint8_t bidi_stamp : 1;
        // Clear only when no cell of the line may reorder, see bidi_cells_may_reorder(). Kept up to date only in a paragraph
        // holding a stamp; elsewhere it may be stale, which costs only work.
        uint8_t bidi_may_reorder : 1;
        uint8_t bidi_rtl : 1;
        uint8_t bidi_auto : 1;
    };
    uint8_t val;
} LineAttrs;
enum { BIDI_STAMP_NONE, BIDI_STAMP_IMPLICIT };
static_assert(sizeof(LineAttrs) == sizeof(uint8_t), "Fix the ordering of LineAttrs");

// A record, or the direction a leading mark set for the line's first text
static inline bool
line_has_bidi_bits(LineAttrs a) {
    return a.bidi_stamp != BIDI_STAMP_NONE || a.bidi_rtl || a.bidi_auto;
}

// Copies the record of src, or clears it when src has none
static inline void
line_attrs_set_bidi(LineAttrs *dest, LineAttrs src) {
    dest->bidi_stamp = src.bidi_stamp;
    dest->bidi_rtl = src.bidi_rtl;
    dest->bidi_auto = src.bidi_auto;
}


typedef struct {
    PyObject_HEAD

        // Render data, NULL for lines in the history buffer that are not being rendered
        RenderCell *render_cells;
    CPUCell *cpu_cells;
    index_type xnum, ynum;
    bool needs_free;
    LineAttrs attrs;
    TextCache *text_cache;
    // For lines that are copies, the generation of the style table when the
    // copy was made, zero for lines that are views into a buffer. The style
    // indices in a copy are invalid after the style table is garbage collected.
    uint32_t style_generation;
} Line;

typedef struct MultiCellCommand {
    unsigned int width, scale, subscale_n, subscale_d, vertical_align, horizontal_align;
    size_t payload_sz;
} MultiCellCommand;

typedef struct ANSILineOutput {
    CellStyle prev_style; // style of the previous cell output, zero (the default style) at the start
    const CPUCell *current_multicell_state;
    index_type pos, limit;
    ANSIBuf *output_buf;
    bool escape_code_written;
    // The bidi record of the paragraph being written, see ansi_bidi_row_start(), 0 when none is open, and the record whose
    // controls line_as_ansi() is to write before the text of the next line it writes
    uint8_t bidi_open, bidi_prefix;
} ANSILineState;

static inline void
cleanup_ansibuf(ANSIBuf *b) {
    free(b->buf);
    zero_at_ptr(b);
}
#define RAII_ANSIBuf(name) __attribute__((cleanup(cleanup_ansibuf))) ANSIBuf name = {0}

Line *alloc_line(TextCache *text_cache);
void apply_sgr_to_cells(CellStyleTable *t, CPUCell *cells, unsigned int cell_count, int *params, unsigned int count, bool is_group);
const char *style_as_sgr(const CellStyle *, const CellStyle *);
static inline bool
cell_has_text(const CPUCell *c) {
    return c->ch_and_idx != 0;
}
static inline void
cell_set_char(CPUCell *c, char_type ch) {
    c->ch_and_idx = ch & 0x7fffffff;
}
static inline bool
cell_is_char(const CPUCell *c, char_type ch) {
    return c->ch_and_idx == ch;
}
static inline index_type
cell_scale(const CPUCell *c) {
    return c->is_multicell ? c->scale : 1;
}
static inline unsigned
num_codepoints_in_cell(const CPUCell *c, const TextCache *tc) {
    unsigned ans;
    if (c->ch_is_idx) {
        ans = tc_num_codepoints(tc, c->ch_or_idx);
        if (c->is_multicell) ans--;
    } else ans = c->ch_or_idx ? 1 : 0;
    return ans;
}
static inline unsigned
mcd_x_limit(const CPUCell *mcd) {
    return mcd->scale * mcd->width;
}

static inline void
cell_clear_multicell(CPUCell *c) {
    // Make c an ordinary cell, clearing all the multicell fields, so that they
    // are not mistaken for those of a multicell char by code that does not
    // check is_multicell
    c->is_multicell = false;
    c->natural_width = false;
    c->scale = 0;
    c->subscale_n = 0;
    c->subscale_d = 0;
    c->valign = 0;
    c->halign = 0;
    c->x = 0;
    c->y = 0;
    c->width = 0;
}

static inline bool
continues_multicell_char(const CPUCell *c, const CPUCell *ref, index_type y) {
    // Whether c is the cell in row y of the same multicell char as ref in the same column.
    // Use this rather than trusting the y and scale of a cell when walking the rows of a
    // multiline char, as the char may be partial or torn.
    return c->is_multicell && c->y == y && c->x == ref->x && c->scale == ref->scale && c->width == ref->width && c->subscale_n == ref->subscale_n &&
           c->subscale_d == ref->subscale_d && c->ch_and_idx == ref->ch_and_idx;
}

static inline bool
continues_multicell_char_horizontally(const CPUCell *c, const CPUCell *ref, index_type x) {
    // Whether c is the cell in column x of the same multicell char as ref in the same row.
    return c->is_multicell && c->x == x && c->y == ref->y && c->scale == ref->scale && c->width == ref->width && c->subscale_n == ref->subscale_n &&
           c->subscale_d == ref->subscale_d && c->ch_and_idx == ref->ch_and_idx;
}

typedef struct MulticellColumns {
    index_type start, limit;
} MulticellColumns;

static inline MulticellColumns
multicell_char_columns(const CPUCell *cells, index_type xnum, index_type x) {
    // The columns [start, limit) of the cells of the multicell char whose cell
    // is at x in a line of xnum cells. Only the cells that actually continue
    // the char are included, rather than trusting the x and width of cells, as
    // the char may be split, with some of its cells elsewhere, by a
    // horizontally scrolled smooth scroll region, or cut off by the end of the
    // line.
    const CPUCell *ref = cells + x;
    MulticellColumns ans = {.start = x, .limit = x + 1};
    if (!ref->is_multicell) return ans;
    while (ans.start > 0 && cells[ans.start].x && continues_multicell_char_horizontally(cells + ans.start - 1, ref, cells[ans.start].x - 1u)) ans.start--;
    while (ans.limit < xnum && cells[ans.limit - 1].x + 1u < mcd_x_limit(ref) &&
           continues_multicell_char_horizontally(cells + ans.limit, ref, cells[ans.limit - 1].x + 1u))
        ans.limit++;
    return ans;
}

static inline bool
multicell_char_columns_are_complete(const CPUCell *cells, MulticellColumns c) {
    // Whether all the columns of the char are present
    return cells[c.start].x == 0 && c.limit - c.start == mcd_x_limit(cells + c.start);
}

static inline void
text_in_cell(const CPUCell *c, const TextCache *tc, ListOfChars *ans) {
    if (c->ch_is_idx) {
        tc_chars_at_index(tc, c->ch_or_idx, ans);
    } else {
        ans->count = 1;
        ans->chars[0] = c->ch_or_idx;
    }
}

static inline bool
text_in_cell_without_alloc(const CPUCell *c, const TextCache *tc, ListOfChars *ans) {
    if (c->ch_is_idx) {
        if (!tc_chars_at_index_without_alloc(tc, c->ch_or_idx, ans)) return false;
        return true;
    }
    ans->count = 1;
    if (ans->capacity < 1) return false;
    ans->chars[0] = c->ch_or_idx;
    return true;
}

static inline void
cell_set_chars(CPUCell *c, TextCache *tc, const ListOfChars *lc) {
    if (lc->count <= 1) cell_set_char(c, lc->chars[0]);
    else {
        c->ch_or_idx = tc_get_or_insert_chars(tc, lc);
        c->ch_is_idx = true;
    }
}

// The glyph registered with the glyph protocol bound to the cell when its text was printed
static inline struct VGGlyph *
cell_registered_glyph(const CPUCell *c, const TextCache *tc) {
    return c->ch_is_idx ? tc_glyph_at_index(tc, c->ch_or_idx) : NULL;
}

static inline char_type
cell_first_char(const CPUCell *c, const TextCache *tc) {
    if (c->ch_is_idx) {
        if (c->is_multicell && (c->x || c->y)) return 0;
        return tc_first_char_at_index(tc, c->ch_or_idx);
    }
    return c->ch_or_idx;
}

static inline CellStyleTable *
line_style_table(const Line *l) {
    return tc_style_table(l->text_cache);
}

static inline bool
line_styles_are_valid(const Line *l) {
    // Sets a Python exception and returns false if l is a copy made before the style table was garbage collected
    if (l->style_generation && l->style_generation != line_style_table(l)->generation) {
        PyErr_SetString(PyExc_ValueError, "The formatting of this copy of a line is no longer valid, as the style table changed after it was copied");
        return false;
    }
    return true;
}

static inline const CellStyle *
line_cell_style(const Line *l, index_type x) {
    return style_table_get(line_style_table(l), l->cpu_cells[x].style_idx);
}

static inline uint32_t
cursor_style_idx_in(CellStyleTable *t, const Cursor *cursor) {
    // Uses the cache in the cursor without updating it
    uint32_t idx = cursor->style_idx;
    return style_table_intern_cached(t, &cursor->style, &idx);
}

static inline void
fill_blank_cpu_cells(CPUCell *c, index_type num, uint32_t style_idx) {
    if (style_idx) {
        const CPUCell blank = {.style_idx = style_idx};
        for (index_type i = 0; i < num; i++) c[i] = blank;
    } else memset(c, 0, num * sizeof(CPUCell));
}

static inline void
remap_style_idx_range(CellStyleTable *dest, const CellStyleTable *src, CPUCell *c, index_type num) {
    // Change the style indices of cells copied from a buffer with a different style table
    uint32_t cache = 0;
    for (index_type i = 0; i < num; i++) c[i].style_idx = style_table_intern_cached(dest, style_table_get(src, c[i].style_idx), &cache);
}

static inline void
cells_for_gpu(const CPUCell *c, const RenderCell *r, index_type num, CellGPUData *dest) {
    // Build the cell data uploaded to the GPU. dest may be write combined memory so it is only written to, sequentially.
    static_assert(MARK_MASK < (1u << CELL_GPU_STYLE_SHIFT), "Increase CELL_GPU_STYLE_SHIFT");
    for (index_type i = 0; i < num; i++) {
        const CellGPUData d = {.sprite_idx = r[i].sprite_idx, .style_and_mark = (c[i].style_idx << CELL_GPU_STYLE_SHIFT) | r[i].mark};
        memcpy(dest + i, &d, sizeof(d));
    }
}

static inline void
cells_for_gpu_permuted(const CPUCell *c, const RenderCell *r, const uint16_t *v2l, index_type num, CellGPUData *dest) {
    for (index_type i = 0; i < num; i++) {
        const index_type l = v2l[i];
        const CellGPUData d = {.sprite_idx = r[l].sprite_idx, .style_and_mark = (c[l].style_idx << CELL_GPU_STYLE_SHIFT) | r[l].mark};
        memcpy(dest + i, &d, sizeof(d));
    }
}
