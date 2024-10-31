/*
 * line.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "text-cache.h"

typedef union CellAttrs {
    struct {
        uint16_t width : 2;
        uint16_t decoration : 3;
        uint16_t bold : 1;
        uint16_t italic : 1;
        uint16_t reverse : 1;
        uint16_t strike : 1;
        uint16_t dim : 1;
        uint16_t mark : 2;
        uint16_t next_char_was_wrapped : 1;
        uint16_t : 3;
    };
    uint16_t val;
} CellAttrs;
static_assert(sizeof(CellAttrs) == sizeof(uint16_t), "Fix the ordering of CellAttrs");

#define WIDTH_MASK (3u)
#define DECORATION_MASK (7u)
#define NUM_UNDERLINE_STYLES (5u)
#define SGR_MASK (~(((CellAttrs){.width=WIDTH_MASK, .mark=MARK_MASK, .next_char_was_wrapped=1}).val))
// Text presentation selector
#define VS15 0xfe0e
// Emoji presentation selector
#define VS16 0xfe0f

typedef struct {
    color_type fg, bg, decoration_fg;
    sprite_index sprite_x, sprite_y, sprite_z;
    CellAttrs attrs;
} GPUCell;
static_assert(sizeof(GPUCell) == 20, "Fix the ordering of GPUCell");

typedef union CPUCell {
    struct {
        bool ch_is_idx: 1;
        char_type ch_or_idx: sizeof(char_type) * 8 - 1;
        hyperlink_id_type hyperlink_id: sizeof(hyperlink_id_type) * 8;
        uint16_t : 16;
    };
    uint64_t val;
} CPUCell;
static_assert(sizeof(CPUCell) == sizeof(uint64_t), "Fix the ordering of CPUCell");

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

Line* alloc_line(TextCache *text_cache);
void apply_sgr_to_cells(GPUCell *first_cell, unsigned int cell_count, int *params, unsigned int count, bool is_group);
const char* cell_as_sgr(const GPUCell *, const GPUCell *);
static inline bool cell_has_text(const CPUCell *c) { return c->ch_is_idx || c->ch_or_idx; }
static inline void cell_set_char(CPUCell *c, char_type ch) { c->ch_is_idx = false; c->ch_or_idx = ch; }
static inline bool cell_is_char(const CPUCell *c, char_type ch) { return !c->ch_is_idx && c->ch_or_idx == ch; }
static inline unsigned num_codepoints_in_cell(const CPUCell *c, const TextCache *tc) {
    return c->ch_is_idx ? tc_num_codepoints(tc, c->ch_or_idx) : (c->ch_or_idx ? 1 : 0);
}

static inline void
text_in_cell(const CPUCell *c, const TextCache *tc, ListOfChars *ans) {
    if (c->ch_is_idx) tc_chars_at_index(tc, c->ch_or_idx, ans);
    else {
        ans->count = 1;
        ans->chars[0] = c->ch_or_idx;
    }
}

static inline bool
text_in_cell_without_alloc(const CPUCell *c, const TextCache *tc, ListOfChars *ans) {
    if (c->ch_is_idx) return tc_chars_at_index_without_alloc(tc, c->ch_or_idx, ans);
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
    if (c->ch_is_idx) return tc_first_char_at_index(tc, c->ch_or_idx);
    return c->ch_or_idx;
}


static inline CellAttrs
cursor_to_attrs(const Cursor *c, const uint16_t width) {
    CellAttrs ans = {
        .width=width, .decoration=c->decoration, .bold=c->bold, .italic=c->italic, .reverse=c->reverse,
        .strike=c->strikethrough, .dim=c->dim};
    return ans;
}

static inline void
attrs_to_cursor(const CellAttrs attrs, Cursor *c) {
    c->decoration = attrs.decoration; c->bold = attrs.bold;  c->italic = attrs.italic;
    c->reverse = attrs.reverse; c->strikethrough = attrs.strike; c->dim = attrs.dim;
}

#define cursor_as_gpu_cell(cursor) {.attrs=cursor_to_attrs(cursor, 0), .fg=(cursor->fg & COL_MASK), .bg=(cursor->bg & COL_MASK), .decoration_fg=cursor->decoration_fg & COL_MASK}


