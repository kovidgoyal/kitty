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
copy_line(Line *src, Line *dest) {
    memcpy(dest->cells, src->cells, sizeof(Cell) * (MIN(src->xnum, dest->xnum)));
}
