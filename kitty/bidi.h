/*
 * bidi.h
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#include "line.h"
#include <fribidi.h>

typedef struct BidiScratch {
    FriBidiChar *text;
    FriBidiCharType *types;
    FriBidiBracketType *brackets;
    FriBidiLevel *levels;
    uint32_t *cell_of_char;
    size_t text_cap, types_cap, brackets_cap, levels_cap, cell_of_char_cap;
    uint32_t *row_start;
    size_t row_start_cap;
    uint8_t *row_bytes;
    size_t row_bytes_cap;
    size_t peak; // the most chars a paragraph fed FriBidi since the last trim
} BidiScratch;

void bidi_scratch_free(BidiScratch *s);
// Frees the buffers when far larger than the paragraphs resolved since the last call needed
void bidi_scratch_trim(BidiScratch *s);
// Whether the base codepoint of some cell may be right-to-left
bool bidi_cells_may_reorder(const CPUCell *cells, index_type num, const TextCache *tc);
// Resolves the paragraph rows[0..num_rows) from base into levels[r * cols + x], after UAX #9 L1 per row. Returns false, leaving
// levels unwritten, when every level is 0 or a cell spans several rows, which is never reordered.
bool bidi_resolve_paragraph(
    BidiScratch *s, const CPUCell *const *rows, unsigned num_rows, index_type cols, const TextCache *tc, FriBidiParType base, uint8_t *levels);
// Puts in v2l[v] the logical cell shown at visual column v of a row with these levels (UAX #9 L2). Returns false for the identity.
bool bidi_visual_order(const uint8_t *levels, index_type cols, uint16_t *v2l);
// row has cols cells of stride bytes each, in logical order: puts them in the visual order v2l
void bidi_permute_row_bytes(BidiScratch *s, const uint16_t *v2l, index_type cols, uint8_t *row, size_t stride);
