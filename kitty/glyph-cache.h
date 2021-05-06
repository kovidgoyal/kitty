/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

void free_glyph_cache_global_resources(void);

#define SpritePositionHead \
    bool rendered, colored; \
    sprite_index x, y, z; \

typedef struct SpritePosition {
    SpritePositionHead
} SpritePosition;


void free_sprite_position_hash_table(SpritePosition **head);
SpritePosition*
find_or_create_sprite_position(SpritePosition **head, glyph_index *glyphs, glyph_index count, glyph_index ligature_index, bool *created);

#define GlyphPropertiesHead \
    uint8_t data;

typedef struct GlyphProperties {
    GlyphPropertiesHead
} GlyphProperties;

void free_glyph_properties_hash_table(GlyphProperties **head);
GlyphProperties*
find_or_create_glyph_properties(GlyphProperties **head, unsigned glyph);
