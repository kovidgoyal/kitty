/*
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "line.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <hb.h>
#pragma GCC diagnostic pop

typedef struct ShapeGroup {
    unsigned int first_glyph_idx, first_cell_idx, num_glyphs, num_cells;
    bool has_special_glyph, started_with_infinite_ligature;
} ShapeGroup;

typedef struct ShapedRun {
    const hb_glyph_info_t *info;
    const hb_glyph_position_t *positions;
    const ShapeGroup *groups;
    unsigned num_glyphs, num_groups;
} ShapedRun;

typedef struct {
    int x;
} *SHAPED_RUN_MAP_HANDLE;

SHAPED_RUN_MAP_HANDLE
create_shaped_run_hash_table(void);
void free_shaped_run_hash_table(SHAPED_RUN_MAP_HANDLE *handle);
bool shaped_run_get(
    SHAPED_RUN_MAP_HANDLE map,
    const CPUCell *cells,
    index_type num_cells,
    const TextCache *tc,
    bool disable_ligature,
    bool force_ltr,
    uint8_t scale,
    uint8_t subscale,
    ShapedRun *result);
// Store the results of shaping the run that the immediately preceding
// shaped_run_get() call looked up and did not find. Building the key is not
// cheap, so it is re-used rather than computed a second time. Does nothing if
// there was no such call, i.e. if the run was found in the cache or is not
// cacheable at all.
void shaped_run_put(
    SHAPED_RUN_MAP_HANDLE map,
    const hb_glyph_info_t *info,
    const hb_glyph_position_t *positions,
    unsigned num_glyphs,
    const ShapeGroup *groups,
    unsigned num_groups);
