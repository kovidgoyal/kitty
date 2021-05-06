/*
 * glyph-cache.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "glyph-cache.h"
#include "kitty-uthash.h"


typedef struct SpritePosItem {
    SpritePositionHead
    UT_hash_handle hh;
    glyph_index key[];
} SpritePosItem;

static glyph_index *scratch = NULL;
static unsigned scratch_sz = 0;


void
free_glyph_cache_global_resources(void) {
    free(scratch);
    scratch = NULL; scratch_sz = 0;
}


static inline unsigned
key_size_for_glyph_count(unsigned count) { return count + 2; }


SpritePosition*
find_or_create_sprite_position(SpritePosition **head_, glyph_index *glyphs, glyph_index count, glyph_index ligature_index, bool *created) {
    SpritePosItem **head = (SpritePosItem**)head_, *p;
    const unsigned key_sz = key_size_for_glyph_count(count);
    if (key_sz > scratch_sz) {
        scratch = realloc(scratch, sizeof(glyph_index) * (key_sz + 16));
        if (!scratch) return NULL;
        scratch_sz = key_sz + 16;
    }
    const unsigned key_sz_bytes = key_sz * sizeof(glyph_index);
    scratch[0] = count; scratch[1] = ligature_index;
    memcpy(scratch + 2, glyphs, count * sizeof(glyph_index));
    HASH_FIND(hh, *head, scratch, key_sz_bytes, p);
    if (p) { *created = false; return (SpritePosition*)p; }

    p = calloc(1, sizeof(SpritePosItem) + key_sz_bytes);
    if (!p) return NULL;
    memcpy(p->key, scratch, key_sz_bytes);
    HASH_ADD(hh, *head, key, key_sz_bytes, p);
    *created = true;
    return (SpritePosition*)p;
}

void
free_sprite_position_hash_table(SpritePosition **head_) {
    SpritePosItem **head = (SpritePosItem**)head_, *s, *tmp;
    HASH_ITER(hh, *head, s, tmp) {
        HASH_DEL(*head, s);
        free(s);
    }
}

typedef struct GlyphPropertiesItem {
    GlyphPropertiesHead
    UT_hash_handle hh;
    unsigned key;
} GlyphPropertiesItem;


GlyphProperties*
find_or_create_glyph_properties(GlyphProperties **head_, unsigned glyph) {
    GlyphPropertiesItem **head = (GlyphPropertiesItem**)head_, *p;
    HASH_FIND_INT(*head, &glyph, p);
    if (p) return (GlyphProperties*)p;
    p = calloc(1, sizeof(GlyphPropertiesItem));
    if (!p) return NULL;
    p->key = glyph;
    HASH_ADD_INT(*head, key, p);
    return (GlyphProperties*)p;
}

void
free_glyph_properties_hash_table(GlyphProperties **head_) {
    GlyphPropertiesItem **head = (GlyphPropertiesItem**)head_, *s, *tmp;
    HASH_ITER(hh, *head, s, tmp) {
        HASH_DEL(*head, s);
        free(s);
    }
}
