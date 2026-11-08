/*
 * style-table.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

// The formatting (CellStyle) of cells is interned per screen in a CellStyleTable and
// cells store only the index of their style. Index zero is always the default
// (all zero) style, so zeroed cells have the default style.
#define STYLE_IDX_BITS 18u
#define MAX_NUM_OF_STYLES (1u << STYLE_IDX_BITS)

typedef struct CellStyleTable {
    CellStyle *styles;
    uint32_t count;
    // Incremented whenever existing indices are invalidated, never zero
    uint32_t generation;
} CellStyleTable;

CellStyleTable *style_table_alloc(void);
void style_table_free(CellStyleTable *self);
uint32_t style_table_intern(CellStyleTable *self, const CellStyle *style);
// Remove all styles except the default style, invalidating all indices and freeing memory.
// Must only be called when no cells use a style other than the default style.
void style_table_reset(CellStyleTable *self);
// For testing
void style_table_set_max_count(CellStyleTable *self, uint32_t max_count);
uint32_t style_table_max_count(const CellStyleTable *self);
uint64_t style_table_gc_count(const CellStyleTable *self);
bool style_table_is_degraded(const CellStyleTable *self);

// Reduce the precision of RGB colors in style to bits per channel
CellStyle style_quantize(const CellStyle *style, unsigned bits);

// Garbage collection. When the table is full, style_table_intern() returns
// the index of an existing style close to the requested one. The owner of the
// table must then, at a time when no style indices are held outside of cells,
// call style_table_gc_begin(), style_table_gc_map() with the style index of
// every live cell, replacing it with the returned index, and
// style_table_gc_end(). With quantize_bits, cells for which quantize is true
// get styles with colors of reduced precision, to free up space.
bool style_table_needs_gc(const CellStyleTable *self);
unsigned style_table_last_gc_quantize_bits(const CellStyleTable *self);
typedef struct StyleTableGC StyleTableGC;
StyleTableGC *style_table_gc_begin(CellStyleTable *self, unsigned quantize_bits);
uint32_t style_table_gc_map(CellStyleTable *self, StyleTableGC *gc, uint32_t old_idx, bool quantize);
void style_table_gc_end(CellStyleTable *self, StyleTableGC *gc, bool degraded);

static inline const CellStyle *
style_table_get(const CellStyleTable *self, uint32_t idx) {
    return self->styles + (idx < self->count ? idx : 0);
}

static inline bool
style_eq(const CellStyle *a, const CellStyle *b) {
    return a->fg == b->fg && a->bg == b->bg && a->decoration_fg == b->decoration_fg && a->attrs.val == b->attrs.val;
}

// Intern style, using *idx as a cache of the index of the last style interned
// with it, to avoid hash lookups when the style is unchanged. The cache needs
// no invalidation: if the style at *idx equals style, *idx is a valid index
// for style, even after the table is compacted.
static inline uint32_t
style_table_intern_cached(CellStyleTable *self, const CellStyle *style, uint32_t *idx) {
    if (*idx >= self->count || !style_eq(style, self->styles + *idx)) *idx = style_table_intern(self, style);
    return *idx;
}
