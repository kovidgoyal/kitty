/*
 * line.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "text-cache.h"

// TODO: Handle selection with multicell
// TODO: URL detection with multicell
// TODO: Handle rewrap and restitch of multiline chars
// TODO: Handle rewrap when a character is too wide/tall to fit on resized screen

typedef union CellAttrs {
    struct {
        uint16_t decoration : 3;
        uint16_t bold : 1;
        uint16_t italic : 1;
        uint16_t reverse : 1;
        uint16_t strike : 1;
        uint16_t dim : 1;
        uint16_t mark : 2;
        uint32_t : 22;
    };
    uint32_t val;
} CellAttrs;
static_assert(sizeof(CellAttrs) == sizeof(uint32_t), "Fix the ordering of CellAttrs");

#define WIDTH_MASK (3u)
#define DECORATION_MASK (7u)
#define SGR_MASK (~(((CellAttrs){.mark=MARK_MASK}).val))
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

typedef union CPUCell {
    struct {
        char_type ch_or_idx: sizeof(char_type) * 8 - 1;
        char_type ch_is_idx: 1;
        char_type hyperlink_id: sizeof(hyperlink_id_type) * 8;
        char_type next_char_was_wrapped : 1;
        char_type is_multicell : 1;
        char_type natural_width: 1;
        char_type x : 8;
        char_type y : 4;
        char_type subscale_n: 4;
        char_type subscale_d: 4;
        char_type scale: 3;
        char_type width: 3;
        char_type vertical_align: 3;
        char_type : 15;
    };
    struct {
        char_type ch_and_idx: sizeof(char_type) * 8;
        char_type : 32;
        char_type : 32;
    };
} CPUCell;
static_assert(sizeof(CPUCell) == 12, "Fix the ordering of CPUCell");

typedef union LineAttrs {
    struct {
        uint8_t is_continued : 1;
        uint8_t has_dirty_text : 1;
        uint8_t has_image_placeholders : 1;
        uint8_t prompt_kind : 2;
        uint8_t : 3;
    };
    uint8_t val;
} LineAttrs ;
static_assert(sizeof(LineAttrs) == sizeof(uint8_t), "Fix the ordering of LineAttrs");


typedef struct {
    PyObject_HEAD

    GPUCell *gpu_cells;
    CPUCell *cpu_cells;
    index_type xnum, ynum;
    bool needs_free;
    LineAttrs attrs;
    TextCache *text_cache;
} Line;

typedef struct MultiCellCommand {
    unsigned int width, scale, subscale_n, subscale_d, vertical_align;
    size_t payload_sz;
} MultiCellCommand;

typedef struct ANSILineOutput {
    const GPUCell *prev_gpu_cell;
    const CPUCell *current_multicell_state;
    index_type pos, limit;
    ANSIBuf *output_buf;
    bool escape_code_written;
} ANSILineState;


Line* alloc_line(TextCache *text_cache);
void apply_sgr_to_cells(GPUCell *first_cell, unsigned int cell_count, int *params, unsigned int count, bool is_group);
const char* cell_as_sgr(const GPUCell *, const GPUCell *);
static inline bool cell_has_text(const CPUCell *c) { return c->ch_and_idx != 0; }
static inline void cell_set_char(CPUCell *c, char_type ch) { c->ch_and_idx = ch & 0x7fffffff; }
static inline bool cell_is_char(const CPUCell *c, char_type ch) { return c->ch_and_idx == ch; }
static inline unsigned num_codepoints_in_cell(const CPUCell *c, const TextCache *tc) {
    unsigned ans;
    if (c->ch_is_idx) {
        ans = tc_num_codepoints(tc, c->ch_or_idx);
        if (c->is_multicell) ans--;
    } else ans = c->ch_or_idx ? 1 : 0;
    return ans;
}
static inline unsigned mcd_x_limit(const CPUCell* mcd) { return mcd->scale * mcd->width; }

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
        c->ch_or_idx = tc_get_or_insert_chars(tc,  lc);
        c->ch_is_idx = true;
    }
}

static inline char_type
cell_first_char(const CPUCell *c, const TextCache *tc) {
    if (c->ch_is_idx) {
        if (c->is_multicell && (c->x || c->y)) return 0;
        return tc_first_char_at_index(tc, c->ch_or_idx);
    }
    return c->ch_or_idx;
}

static inline CellAttrs
cursor_to_attrs(const Cursor *c) {
    CellAttrs ans = {
        .decoration=c->decoration, .bold=c->bold, .italic=c->italic, .reverse=c->reverse,
        .strike=c->strikethrough, .dim=c->dim};
    return ans;
}

static inline void
attrs_to_cursor(const CellAttrs attrs, Cursor *c) {
    c->decoration = attrs.decoration; c->bold = attrs.bold;  c->italic = attrs.italic;
    c->reverse = attrs.reverse; c->strikethrough = attrs.strike; c->dim = attrs.dim;
}

#define cursor_as_gpu_cell(cursor) {.attrs=cursor_to_attrs(cursor), .fg=(cursor->fg & COL_MASK), .bg=(cursor->bg & COL_MASK), .decoration_fg=cursor->decoration_fg & COL_MASK}


