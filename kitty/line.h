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
    };
    uint16_t val;
} CellAttrs;

#define WIDTH_MASK (3u)
#define DECORATION_MASK (7u)
#define NUM_UNDERLINE_STYLES (5u)
#define SGR_MASK (~(((CellAttrs){.width=WIDTH_MASK, .mark=MARK_MASK, .next_char_was_wrapped=1}).val))

typedef struct {
    color_type fg, bg, decoration_fg;
    sprite_index sprite_x, sprite_y, sprite_z;
    CellAttrs attrs;
} GPUCell;
static_assert(sizeof(GPUCell) == 20, "Fix the ordering of GPUCell");

typedef struct {
    char_type ch;
    hyperlink_id_type hyperlink_id;
    combining_type cc_idx[3];
} CPUCell;
static_assert(sizeof(CPUCell) == 12, "Fix the ordering of CPUCell");


typedef union LineAttrs {
    struct {
        uint8_t is_continued : 1;
        uint8_t has_dirty_text : 1;
        uint8_t has_image_placeholders : 1;
        PromptKind prompt_kind : 2;
    };
    uint8_t val;
} LineAttrs ;


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


