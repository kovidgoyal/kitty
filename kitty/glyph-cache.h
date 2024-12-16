/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef union SpritePosition {
    struct {
        sprite_index idx : sizeof(sprite_index) * 8;
        bool rendered : 1;
        bool colored : 1;
        uint32_t : 30;
    };
    uint64_t val;
} SpritePosition;
static_assert(sizeof(SpritePosition) == sizeof(uint64_t), "Fix ordering of SpritePosition");

typedef struct {int x;} *SPRITE_POSITION_MAP_HANDLE;

SPRITE_POSITION_MAP_HANDLE
create_sprite_position_hash_table(void);
void
free_sprite_position_hash_table(SPRITE_POSITION_MAP_HANDLE *handle);
SpritePosition*
find_or_create_sprite_position(SPRITE_POSITION_MAP_HANDLE map, glyph_index *glyphs, glyph_index count, glyph_index ligature_index, glyph_index cell_count, uint8_t scale, uint8_t subscale, uint8_t multicell_y, uint8_t vertical_align, bool *created);


typedef union GlyphProperties {
    struct {
        uint8_t special_set : 1;
        uint8_t special_val : 1;
        uint8_t empty_set : 1;
        uint8_t empty_val : 1;
    };
    uint8_t val;
} GlyphProperties;

typedef struct {int x;} *GLYPH_PROPERTIES_MAP_HANDLE;

GLYPH_PROPERTIES_MAP_HANDLE
create_glyph_properties_hash_table(void);

void free_glyph_properties_hash_table(GLYPH_PROPERTIES_MAP_HANDLE *handle);
GlyphProperties
find_glyph_properties(GLYPH_PROPERTIES_MAP_HANDLE map, glyph_index glyph);
bool
set_glyph_properties(GLYPH_PROPERTIES_MAP_HANDLE map, glyph_index glyph, GlyphProperties val);
