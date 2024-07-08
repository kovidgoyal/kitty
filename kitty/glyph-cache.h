/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

void free_glyph_cache_global_resources(void);

typedef struct SpritePosition {
    bool rendered, colored;
    sprite_index x, y, z;
} SpritePosition;

typedef struct {int x;} *SPRITE_POSITION_MAP_HANDLE;

SPRITE_POSITION_MAP_HANDLE
create_sprite_position_hash_table(void);
void
free_sprite_position_hash_table(SPRITE_POSITION_MAP_HANDLE *handle);
SpritePosition*
find_or_create_sprite_position(SPRITE_POSITION_MAP_HANDLE map, glyph_index *glyphs, glyph_index count, glyph_index ligature_index, glyph_index cell_count, bool *created);

#define GlyphPropertiesHead \
    uint8_t data;

typedef struct GlyphProperties {
    GlyphPropertiesHead
} GlyphProperties;

void free_glyph_properties_hash_table(GlyphProperties **head);
GlyphProperties*
find_or_create_glyph_properties(GlyphProperties **head, unsigned glyph);
