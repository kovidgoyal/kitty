/*
 * shaped-run-cache.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "shaped-run-cache.h"

// Note that these limits apply to every Font, of which there are at least a
// dozen per FontGroup once fallback and symbol fonts are in use, so the total
// memory used by shaped run caches is a multiple of SHAPED_RUN_MAX_BYTES.
#define SHAPED_RUN_MAX_CELLS 32u
#define SHAPED_RUN_MAX_ENTRIES 2048u
#define SHAPED_RUN_MAX_BYTES (1024u * 1024u)
#define SHAPED_RUN_MA_BLOCK_SIZE 16u
#define SHAPED_RUN_SLAB 4096u

typedef struct ShapedRunKey {
    uint32_t keysz_in_bytes;
    uint8_t disable_ligature, force_ltr, scale, subscale;
    uint8_t data[];
} ShapedRunKey;
static_assert(sizeof(ShapedRunKey) == 8, "Fix the ordering of ShapedRunKey");

typedef struct ShapedRunValue {
    unsigned num_glyphs, num_groups;
} ShapedRunValue;

static inline hb_glyph_info_t *
val_info(ShapedRunValue *v) {
    return (hb_glyph_info_t *)(v + 1);
}

static inline hb_glyph_position_t *
val_positions(ShapedRunValue *v) {
    return (hb_glyph_position_t *)(val_info(v) + v->num_glyphs);
}

static inline ShapeGroup *
val_groups(ShapedRunValue *v) {
    return (ShapeGroup *)(val_positions(v) + v->num_glyphs);
}

static inline size_t
val_size(unsigned num_glyphs, unsigned num_groups) {
    return sizeof(ShapedRunValue) + num_glyphs * (sizeof(hb_glyph_info_t) + sizeof(hb_glyph_position_t)) + num_groups * sizeof(ShapeGroup);
}

#define NAME shaped_run_map
#define KEY_TY const ShapedRunKey *
#define VAL_TY ShapedRunValue *
static uint64_t shaped_run_map_hash(KEY_TY key);
#define HASH_FN shaped_run_map_hash
static bool shaped_run_map_cmpr(KEY_TY a, KEY_TY b);
#define CMPR_FN shaped_run_map_cmpr
#define MA_NAME Key
#define MA_BLOCK_SIZE SHAPED_RUN_MA_BLOCK_SIZE
static_assert(MA_BLOCK_SIZE > sizeof(ShapedRunKey), "increase arena block size");
static_assert(SHAPED_RUN_SLAB % MA_BLOCK_SIZE == 0, "slab must be a multiple of the block size");
#define MA_ARENA_NUM_BLOCKS (SHAPED_RUN_SLAB / MA_BLOCK_SIZE)
#include "arena.h"
#define MA_NAME Val
#define MA_BLOCK_SIZE SHAPED_RUN_MA_BLOCK_SIZE
#define MA_ARENA_NUM_BLOCKS (SHAPED_RUN_SLAB / MA_BLOCK_SIZE)
#include "arena.h"

#include "kitty-verstable.h"

static uint64_t
shaped_run_map_hash(const ShapedRunKey *key) {
    return vt_hash_bytes(key, sizeof(ShapedRunKey) + key->keysz_in_bytes);
}

static bool
shaped_run_map_cmpr(const ShapedRunKey *a, const ShapedRunKey *b) {
    return a->keysz_in_bytes == b->keysz_in_bytes && memcmp(a, b, sizeof(ShapedRunKey) + a->keysz_in_bytes) == 0;
}

typedef struct HashTable {
    shaped_run_map table;
    KeyMonotonicArena keys;
    ValMonotonicArena vals;
    struct {
        ShapedRunKey *key;
        size_t capacity;
        bool key_is_valid; // true when key describes the run from the last shaped_run_get()
    } scratch;
} HashTable;

SHAPED_RUN_MAP_HANDLE
create_shaped_run_hash_table(void) {
    HashTable *ans = calloc(1, sizeof(HashTable));
    if (ans) vt_init(&ans->table);
    return (SHAPED_RUN_MAP_HANDLE)ans;
}

void
free_shaped_run_hash_table(SHAPED_RUN_MAP_HANDLE *map) {
    HashTable **mapref = (HashTable **)map;
    if (*mapref) {
        vt_cleanup(&mapref[0]->table);
        Key_free_all(&mapref[0]->keys);
        Val_free_all(&mapref[0]->vals);
        free(mapref[0]->scratch.key);
        free(mapref[0]);
        mapref[0] = NULL;
    }
}

static bool
shaped_run_too_long(index_type num_cells) {
    return num_cells > SHAPED_RUN_MAX_CELLS;
}

static bool
fill_key(
    HashTable *ht, const CPUCell *cells, index_type num_cells, const TextCache *tc, bool disable_ligature, bool force_ltr, uint8_t scale, uint8_t subscale) {
    const size_t keysz_in_bytes = (size_t)num_cells * (sizeof(uint32_t) + MAX_NUM_CODEPOINTS_PER_CELL * sizeof(char_type));
    if (!ht->scratch.key || keysz_in_bytes > ht->scratch.capacity) {
        const size_t newsz = sizeof(ht->scratch.key[0]) + keysz_in_bytes + 64;
        ht->scratch.key = realloc(ht->scratch.key, newsz);
        if (!ht->scratch.key) {
            ht->scratch.capacity = 0;
            return false;
        }
        ht->scratch.capacity = newsz - sizeof(ht->scratch.key[0]);
        memset(ht->scratch.key, 0, newsz);
    }
#define scratch ht->scratch.key
    RAII_ListOfChars(lc);
    size_t used = 0;
    scratch->disable_ligature = disable_ligature;
    scratch->force_ltr = force_ltr;
    scratch->scale = scale;
    scratch->subscale = subscale;
    for (; num_cells; cells++, num_cells--) {
        if (cells->is_multicell && cells->x) continue;
        text_in_cell(cells, tc, &lc);
        // the scratch buffer is sized assuming this limit, cells that exceed it
        // (only possible via the Python API) are simply not cached
        if (lc.count > MAX_NUM_CODEPOINTS_PER_CELL) return false;
        uint16_t advance = 1;
        if (cells->is_multicell) advance = (uint16_t)(cells->width * cells->scale);
        uint32_t hdr = ((uint32_t)advance << 16) | (uint32_t)lc.count;
        memcpy(scratch->data + used, &hdr, sizeof(hdr));
        used += sizeof(hdr);
        if (lc.count) {
            memcpy(scratch->data + used, lc.chars, lc.count * sizeof(char_type));
            used += lc.count * sizeof(char_type);
        }
    }
    scratch->keysz_in_bytes = (uint32_t)used;
    return true;
#undef scratch
}

bool
shaped_run_get(
    SHAPED_RUN_MAP_HANDLE map,
    const CPUCell *cells,
    index_type num_cells,
    const TextCache *tc,
    bool disable_ligature,
    bool force_ltr,
    uint8_t scale,
    uint8_t subscale,
    ShapedRun *result) {
    HashTable *ht = (HashTable *)map;
    if (!ht) return false;
    ht->scratch.key_is_valid = false;
    if (shaped_run_too_long(num_cells)) return false;
    if (!fill_key(ht, cells, num_cells, tc, disable_ligature, force_ltr, scale, subscale)) return false;
    shaped_run_map_itr n = vt_get(&ht->table, ht->scratch.key);
    if (vt_is_end(n)) {
        ht->scratch.key_is_valid = true; // so that shaped_run_put() can re-use it
        return false;
    }
    ShapedRunValue *v = n.data->val;
    result->num_glyphs = v->num_glyphs;
    result->num_groups = v->num_groups;
    result->info = v->num_glyphs ? val_info(v) : NULL;
    result->positions = v->num_glyphs ? val_positions(v) : NULL;
    result->groups = v->num_groups ? val_groups(v) : NULL;
    return true;
}

// Must count bytes actually malloced, not the sum of the requested sizes. The
// arenas hand out space from fixed size blocks and strand the tail of a block
// whenever the next allocation does not fit in it, which for run lengths that
// happen to produce a value just over half a block wastes almost half of every
// block. Counting requested sizes instead understates real usage by up to ~2x.
static size_t
shaped_run_live_bytes(const HashTable *ht) {
    const size_t buckets = vt_bucket_count(&ht->table);
    const size_t scratch = ht->scratch.key ? sizeof(ShapedRunKey) + ht->scratch.capacity : 0;
    return sizeof(HashTable) + scratch + ht->keys.allocated + ht->vals.allocated + buckets * (sizeof(shaped_run_map_bucket) + sizeof(uint16_t));
}

static bool
shaped_run_at_cap(const HashTable *ht) {
    return vt_size(&ht->table) >= SHAPED_RUN_MAX_ENTRIES || shaped_run_live_bytes(ht) >= SHAPED_RUN_MAX_BYTES;
}

static void
shaped_run_drop(HashTable *ht) {
    vt_cleanup(&ht->table);
    Key_free_all(&ht->keys);
    Val_free_all(&ht->vals);
    vt_init(&ht->table);
}

void
shaped_run_put(
    SHAPED_RUN_MAP_HANDLE map,
    const hb_glyph_info_t *info,
    const hb_glyph_position_t *positions,
    unsigned num_glyphs,
    const ShapeGroup *groups,
    unsigned num_groups) {
    HashTable *ht = (HashTable *)map;
    // the key for this run was built by the shaped_run_get() call that missed,
    // without it we have no way of knowing what run these glyphs belong to
    if (!ht || !ht->scratch.key_is_valid) return;
    ht->scratch.key_is_valid = false;
    if ((num_glyphs && (!info || !positions)) || (num_groups && !groups)) return;
#define scratch ht->scratch.key
    if (shaped_run_at_cap(ht)) shaped_run_drop(ht);
    ShapedRunKey *key = Key_get(&ht->keys, sizeof(ShapedRunKey) + scratch->keysz_in_bytes);
    ShapedRunValue *val = key ? Val_get(&ht->vals, val_size(num_glyphs, num_groups)) : NULL;
    // the arenas cannot free individual allocations, so on failure drop the
    // whole cache rather than leaking what was allocated for this entry
    if (!val) {
        shaped_run_drop(ht);
        return;
    }
    memcpy(key, scratch, sizeof(scratch[0]) + scratch->keysz_in_bytes);
    val->num_glyphs = num_glyphs;
    val->num_groups = num_groups;
    if (num_glyphs) {
        memcpy(val_info(val), info, num_glyphs * sizeof(info[0]));
        memcpy(val_positions(val), positions, num_glyphs * sizeof(positions[0]));
    }
    if (num_groups) memcpy(val_groups(val), groups, num_groups * sizeof(groups[0]));
    if (vt_is_end(vt_insert(&ht->table, key, val))) shaped_run_drop(ht);
#undef scratch
}
