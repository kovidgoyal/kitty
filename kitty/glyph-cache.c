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
#define MA_NAME Key
#define MA_BLOCK_SIZE 16u
static_assert(MA_BLOCK_SIZE > sizeof(SpritePosKey) + 2, "increase arena block size");
#define MA_ARENA_NUM_BLOCKS (2048u / MA_BLOCK_SIZE)
#include "arena.h"
#define MA_NAME Val
#define MA_BLOCK_SIZE sizeof(VAL_TY)
#define MA_ARENA_NUM_BLOCKS (2048u / MA_BLOCK_SIZE)
#include "arena.h"


#include "kitty-verstable.h"

static uint64_t
sprite_pos_map_hash(const SpritePosKey *key) {
    return vt_hash_bytes(key, key->keysz_in_bytes + sizeof(SpritePosKey));
}

static bool
sprite_pos_map_cmpr(const SpritePosKey *a, const SpritePosKey *b) {
    return a->keysz_in_bytes == b->keysz_in_bytes && memcmp(a, b, a->keysz_in_bytes + sizeof(SpritePosKey)) == 0;
}


typedef struct HashTable {
    sprite_pos_map table;
    KeyMonotonicArena keys;
    ValMonotonicArena vals;
    struct { SpritePosKey *key; size_t capacity; } scratch;
} HashTable;

SPRITE_POSITION_MAP_HANDLE
create_sprite_position_hash_table(void) {
    HashTable *ans = calloc(1, sizeof(HashTable));
    if (ans) vt_init(&ans->table);
    return (SPRITE_POSITION_MAP_HANDLE)ans;
}

SpritePosition*
find_or_create_sprite_position(
    SPRITE_POSITION_MAP_HANDLE map_, glyph_index *glyphs, glyph_index count, glyph_index ligature_index, glyph_index cell_count,
    uint8_t scale, uint8_t subscale, uint8_t multicell_y, uint8_t vertical_align, bool *created
) {
    HashTable *ht = (HashTable*)map_;
    sprite_pos_map *map = &ht->table;
    const size_t keysz_in_bytes = count * sizeof(glyph_index);
    if (!ht->scratch.key || keysz_in_bytes > ht->scratch.capacity) {
        const size_t newsz = sizeof(ht->scratch.key[0]) + keysz_in_bytes + 64;
        ht->scratch.key = realloc(ht->scratch.key, newsz);
        if (!ht->scratch.key) { ht->scratch.capacity = 0; return NULL; }
        ht->scratch.capacity = newsz - sizeof(ht->scratch.key[0]);
        memset(ht->scratch.key, 0, newsz);
    }
#define scratch ht->scratch.key
    scratch->keysz_in_bytes = keysz_in_bytes;
    scratch->count = count; scratch->ligature_index = ligature_index; scratch->cell_count = cell_count;
    scratch->scale = scale; scratch->subscale = subscale; scratch->multicell_y = multicell_y; scratch->vertical_align = vertical_align;
    memcpy(scratch->key, glyphs, keysz_in_bytes);
    sprite_pos_map_itr n = vt_get(map, scratch);
    if (!vt_is_end(n)) { *created = false; return n.data->val; }

    SpritePosKey *key = Key_get(&ht->keys, sizeof(SpritePosKey) + scratch->keysz_in_bytes);
    if (!key) return NULL;
    SpritePosition *val = Val_get(&ht->vals, sizeof(SpritePosition));
    if (!val) return NULL;
    memcpy(key, scratch, sizeof(scratch[0]) + scratch->keysz_in_bytes);
    if (vt_is_end(vt_insert(map, key, val))) return NULL;
    *created = true;
    return val;
#undef scratch
}

void
free_sprite_position_hash_table(SPRITE_POSITION_MAP_HANDLE *map) {
    HashTable **mapref = (HashTable**)map;
    if (*mapref) {
        vt_cleanup(&mapref[0]->table);
        Key_free_all(&mapref[0]->keys);
        Val_free_all(&mapref[0]->vals);
        free(mapref[0]->scratch.key);
        free(mapref[0]); mapref[0] = NULL;
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
