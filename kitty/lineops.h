/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

static inline void
set_attribute_on_line(Cell *cells, uint32_t shift, uint32_t val, index_type xnum) {
    uint32_t mask = shift == DECORATION_SHIFT ? 3 : 1;
    uint32_t aval = (val & mask) << (ATTRS_SHIFT + shift); 
    mask = ~(mask << (ATTRS_SHIFT + shift));
    for (index_type i = 0; i < xnum; i++) cells[i].ch = (cells[i].ch & mask) | aval;
}

static inline void
copy_cells(const Cell *src, Cell *dest, index_type xnum) {
    memcpy(dest, src, sizeof(Cell) * xnum);
}

static inline void
copy_line(const Line *src, Line *dest) {
    copy_cells(src->cells, dest->cells, MIN(src->xnum, dest->xnum));
}

static inline void
clear_chars_in_line(Cell *cells, index_type xnum, char_type ch) {
    char_type c = (1 << ATTRS_SHIFT) | ch;
    for (index_type i = 0; i < xnum; i++) cells[i].ch = c;
}
