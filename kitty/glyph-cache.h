/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

#define SpritePositionHead \
    bool rendered, colored; \
    sprite_index x, y, z; \

typedef struct SpritePosition {
    SpritePositionHead
} SpritePosition;


void free_glyph_cache_global_resources(void);
void free_sprite_position_hash_table(SpritePosition **head);
SpritePosition*
find_or_create_sprite_position(SpritePosition **head, glyph_index *glyphs, glyph_index count, glyph_index ligature_index, bool *created);
