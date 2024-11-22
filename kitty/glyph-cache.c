/*
 * glyph-cache.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "glyph-cache.h"

typedef struct SpritePosKey {
    glyph_index ligature_index, count, cell_count, keysz_in_bytes;
    uint8_t scale, subscale, multicell_y, vertical_align;
    glyph_index key[];
} SpritePosKey;
static_assert(sizeof(SpritePosKey) == sizeof(glyph_index) * 4 + sizeof(uint8_t) * 4, "Fix the ordering of SpritePosKey");

#define NAME sprite_pos_map
#define KEY_TY const SpritePosKey*
#define VAL_TY SpritePosition*
static uint64_t sprite_pos_map_hash(KEY_TY key);
#define HASH_FN sprite_pos_map_hash
static bool sprite_pos_map_cmpr(KEY_TY a, KEY_TY b);
#define CMPR_FN sprite_pos_map_cmpr
static void free_const(const void* x) { free((void*)x); }
#define KEY_DTOR_FN free_const
#define VAL_DTOR_FN free_const

#include "kitty-verstable.h"

static uint64_t
sprite_pos_map_hash(const SpritePosKey *key) {
    return vt_hash_bytes(key, key->keysz_in_bytes + sizeof(SpritePosKey));
}

static bool
sprite_pos_map_cmpr(const SpritePosKey *a, const SpritePosKey *b) {
    return a->keysz_in_bytes == b->keysz_in_bytes && memcmp(a, b, a->keysz_in_bytes + sizeof(SpritePosKey)) == 0;
}


static SpritePosKey *scratch = NULL;
static size_t scratch_key_capacity = 0;


void
free_glyph_cache_global_resources(void) {
    free(scratch); scratch = NULL; scratch_key_capacity = 0;
}


SPRITE_POSITION_MAP_HANDLE
create_sprite_position_hash_table(void) {
    sprite_pos_map *ans = calloc(1, sizeof(sprite_pos_map));
    if (ans) vt_init(ans);
    return (SPRITE_POSITION_MAP_HANDLE)ans;
}

SpritePosition*
find_or_create_sprite_position(
    SPRITE_POSITION_MAP_HANDLE map_, glyph_index *glyphs, glyph_index count, glyph_index ligature_index, glyph_index cell_count,
    uint8_t scale, uint8_t subscale, uint8_t multicell_y, uint8_t vertical_align, bool *created
) {
    sprite_pos_map *map = (sprite_pos_map*)map_;
    const size_t keysz_in_bytes = count * sizeof(glyph_index);
    if (!scratch || keysz_in_bytes > scratch_key_capacity) {
        const size_t newsz = sizeof(scratch[0]) + keysz_in_bytes + 64;
        scratch = realloc(scratch, newsz);
        if (!scratch) { scratch_key_capacity = 0; return NULL; }
        scratch_key_capacity = newsz - sizeof(scratch[0]);
        memset(scratch, 0, newsz);
    }
    scratch->keysz_in_bytes = keysz_in_bytes;
    scratch->count = count; scratch->ligature_index = ligature_index; scratch->cell_count = cell_count;
    scratch->scale = scale; scratch->subscale = subscale; scratch->multicell_y = multicell_y; scratch->vertical_align = vertical_align;
    memcpy(scratch->key, glyphs, keysz_in_bytes);
    sprite_pos_map_itr n = vt_get(map, scratch);
    if (!vt_is_end(n)) { *created = false; return n.data->val; }

    SpritePosition *val = calloc(1, sizeof(SpritePosition));
    SpritePosKey *key = malloc(sizeof(SpritePosKey) + scratch->keysz_in_bytes);
    if (!val || !key) return NULL;
    memcpy(key, scratch, sizeof(scratch[0]) + scratch->keysz_in_bytes);
    if (vt_is_end(vt_insert(map, key, val))) return NULL;
    *created = true;
    return val;
}

void
free_sprite_position_hash_table(SPRITE_POSITION_MAP_HANDLE *map) {
    sprite_pos_map **mapref = (sprite_pos_map**)map;
    if (*mapref) {
        vt_cleanup(*mapref); free(*mapref); *mapref = NULL;
    }
}


#define NAME glyph_props_map
#define KEY_TY glyph_index
#define VAL_TY GlyphProperties
#include "kitty-verstable.h"

GLYPH_PROPERTIES_MAP_HANDLE
create_glyph_properties_hash_table(void) {
    glyph_props_map *ans = calloc(1, sizeof(glyph_props_map));
    if (ans) vt_init(ans);
    return (GLYPH_PROPERTIES_MAP_HANDLE)ans;
}

GlyphProperties
find_glyph_properties(GLYPH_PROPERTIES_MAP_HANDLE map_, glyph_index glyph) {
    glyph_props_map *map = (glyph_props_map*)map_;
    glyph_props_map_itr n = vt_get(map, glyph);
    if (vt_is_end(n)) return (GlyphProperties){0};
    return n.data->val;
}

bool
set_glyph_properties(GLYPH_PROPERTIES_MAP_HANDLE map_, glyph_index glyph, GlyphProperties val) {
    glyph_props_map *map = (glyph_props_map*)map_;
    return !vt_is_end(vt_insert(map, glyph, val));
}


void
free_glyph_properties_hash_table(GLYPH_PROPERTIES_MAP_HANDLE *map_) {
    glyph_props_map **mapref = (glyph_props_map**)map_;
    if (*mapref) {
        vt_cleanup(*mapref); free(*mapref); *mapref = NULL;
    }
}
