/*
 * text-cache.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "style-table.h"
#include "vector-glyph.h"
typedef struct Chars {
    const char_type *chars;
    size_t count;
} Chars;
static_assert(sizeof(Chars) == sizeof(void *) + sizeof(size_t), "reorder Chars");

// Entries bound to a glyph registered with the glyph protocol are rare, so
// they are kept out of the main map, to not slow down the common case. They
// are interned in a separate map, keyed by their text and glyph.
typedef struct BoundChars {
    Chars text;
    VGGlyph *glyph;
} BoundChars;

#define NAME chars_map
#define KEY_TY Chars
#define VAL_TY char_type
static uint64_t hash_chars(Chars k);
static bool cmpr_chars(Chars a, Chars b);
#define HASH_FN hash_chars
#define CMPR_FN cmpr_chars
#include "kitty-verstable.h"

#define NAME bound_chars_map
#define KEY_TY BoundChars
#define VAL_TY char_type
static uint64_t hash_bound_chars(BoundChars k);
static bool cmpr_bound_chars(BoundChars a, BoundChars b);
#define HASH_FN hash_bound_chars
#define CMPR_FN cmpr_bound_chars
#include "kitty-verstable.h"

#define MA_NAME Chars
#define MA_BLOCK_SIZE 16u
#define MA_ARENA_NUM_BLOCKS 128u
#include "arena.h"

typedef struct TextCache {
    struct {
        Chars *items;
        size_t capacity;
        char_type count;
    } array;
    chars_map map;
    unsigned refcnt;
    CharsMonotonicArena arena;
    unsigned adds_since_last_gc, adds_between_gcs;
    CellStyleTable *style_table;
    GlyphRegistry *glyph_registry;
    // Parallel to array.items, the glyph bound to each entry, NULL until the
    // first entry is bound. Entries own a reference to their glyph.
    struct {
        VGGlyph **items;
        size_t capacity;
    } glyphs;
    bound_chars_map bound_map;
    // The number of entries bound to glyphs and the memory of those glyphs
    size_t bound_count, bound_memory;
} TextCache;
static uint64_t
hash_chars(Chars k) {
    return vt_hash_bytes(k.chars, sizeof(k.chars[0]) * k.count);
}
static bool
cmpr_chars(Chars a, Chars b) {
    return a.count == b.count && memcmp(a.chars, b.chars, sizeof(a.chars[0]) * a.count) == 0;
}
static uint64_t
hash_bound_chars(BoundChars k) {
    return hash_chars(k.text) ^ ((uint64_t)(uintptr_t)k.glyph * 0x9E3779B97F4A7C15ull);
}
static bool
cmpr_bound_chars(BoundChars a, BoundChars b) {
    return a.glyph == b.glyph && cmpr_chars(a.text, b.text);
}

static void
release_glyphs(VGGlyph **items, size_t count) {
    if (items)
        for (size_t i = 0; i < count; i++) items[i] = vg_decref(items[i]);
}

#define TEXT_CACHE_IMPLEMENTATION
#include "text-cache.h"

TextCache *
tc_alloc(void) {
    TextCache *ans = calloc(1, sizeof(TextCache));
    if (!ans) return NULL;
    ans->array.capacity = 256;
    ans->array.items = malloc(ans->array.capacity * sizeof(ans->array.items[0]));
    if (!ans->array.items) {
        free(ans);
        ans = NULL;
        return ans;
    }
    ans->style_table = style_table_alloc();
    ans->glyph_registry = glyph_registry_alloc();
    if (!ans->style_table || !ans->glyph_registry) {
        style_table_free(ans->style_table);
        glyph_registry_free(ans->glyph_registry);
        free(ans->array.items);
        free(ans);
        return NULL;
    }
    vt_init(&ans->map);
    vt_init(&ans->bound_map);
    ans->refcnt = 1;
    return ans;
}

static void
free_text_cache(TextCache *self) {
    release_glyphs(self->glyphs.items, MIN(self->glyphs.capacity, self->array.count));
    free(self->glyphs.items);
    vt_cleanup(&self->bound_map);
    vt_cleanup(&self->map);
    Chars_free_all(&self->arena);
    free(self->array.items);
    style_table_free(self->style_table);
    glyph_registry_free(self->glyph_registry);
    free(self);
}

CellStyleTable *
tc_style_table(const TextCache *self) {
    return self->style_table;
}

GlyphRegistry *
tc_glyph_registry(const TextCache *self) {
    return self->glyph_registry;
}

TextCache *
tc_incref(TextCache *self) {
    if (self) { self->refcnt++; }
    return self;
}

TextCache *
tc_decref(TextCache *self) {
    if (self) {
        if (self->refcnt < 2) free_text_cache(self);
        else self->refcnt--;
    }
    return NULL;
}

char_type
tc_first_char_at_index(const TextCache *self, char_type idx) {
    if (self->array.count > idx) return self->array.items[idx].chars[0];
    return 0;
}

char_type
tc_last_char_at_index(const TextCache *self, char_type idx) {
    if (self->array.count > idx) return self->array.items[idx].chars[self->array.items[idx].count - 1];
    return 0;
}


void
tc_chars_at_index(const TextCache *self, char_type idx, ListOfChars *ans) {
    if (self->array.count > idx) {
        ensure_space_for_chars(ans, self->array.items[idx].count);
        ans->count = self->array.items[idx].count;
        memcpy(ans->chars, self->array.items[idx].chars, sizeof(ans->chars[0]) * ans->count);
    } else {
        ans->count = 0;
    }
}

bool
tc_chars_at_index_without_alloc(const TextCache *self, char_type idx, ListOfChars *ans) {
    if (self->array.count > idx) {
        ans->count = self->array.items[idx].count;
        if (ans->capacity < ans->count) return false;
        memcpy(ans->chars, self->array.items[idx].chars, sizeof(ans->chars[0]) * ans->count);
    } else {
        ans->count = 0;
    }
    return true;
}


unsigned
tc_num_codepoints(const TextCache *self, char_type idx) {
    return self->array.count > idx ? self->array.items[idx].count : 0;
}

unsigned
tc_chars_at_index_ansi(const TextCache *self, char_type idx, ANSIBuf *output) {
    unsigned count = 0;
    if (self->array.count > idx) {
        count = self->array.items[idx].count;
        // we ensure space for one extra byte for ANSI escape code trailer if multicell
        ensure_space_for(output, buf, output->buf[0], output->len + count + 1, capacity, 2048, false);
        memcpy(output->buf + output->len, self->array.items[idx].chars, sizeof(output->buf[0]) * count);
        output->len += count;
    }
    return count;
}

static char_type
copy_and_insert(TextCache *self, const Chars key, VGGlyph *glyph) {
    if (self->array.count > MAX_CHAR_TYPE_VALUE) fatal("Too many items in TextCache");
    ensure_space_for(&(self->array), items, Chars, self->array.count + 1, capacity, 256, false);
    char_type *copy = Chars_get(&self->arena, key.count * sizeof(key.chars[0]));
    if (!copy) fatal("Out of memory");
    memcpy(copy, key.chars, key.count * sizeof(key.chars[0]));
    char_type ans = self->array.count;
    Chars *k = self->array.items + self->array.count++;
    k->count = key.count;
    k->chars = copy;
    if (glyph) {
        if (self->glyphs.capacity <= ans) {
            const size_t cap = MAX(self->array.capacity, (size_t)ans + 1);
            VGGlyph **g = realloc(self->glyphs.items, cap * sizeof(g[0]));
            if (!g) fatal("Out of memory");
            memset(g + self->glyphs.capacity, 0, (cap - self->glyphs.capacity) * sizeof(g[0]));
            self->glyphs.items = g;
            self->glyphs.capacity = cap;
        }
        self->glyphs.items[ans] = vg_incref(glyph);
        self->bound_count++;
        self->bound_memory += glyph->memory_size;
        if (vt_is_end(vt_insert(&self->bound_map, ((BoundChars){.text = *k, .glyph = glyph}), ans))) fatal("Out of memory");
    } else if (vt_is_end(vt_insert(&self->map, *k, ans))) fatal("Out of memory");
    return ans;
}

VGGlyph *
tc_glyph_at_index(const TextCache *self, char_type idx) {
    return idx < self->glyphs.capacity ? self->glyphs.items[idx] : NULL;
}

static char_type
get_or_insert(TextCache *self, Chars key, VGGlyph *glyph, bool *added) {
    *added = false;
    if (glyph) {
        bound_chars_map_itr i = vt_get(&self->bound_map, ((BoundChars){.text = key, .glyph = glyph}));
        if (!vt_is_end(i)) return i.data->val;
    } else {
        chars_map_itr i = vt_get(&self->map, key);
        if (!vt_is_end(i)) return i.data->val;
    }
    *added = true;
    return copy_and_insert(self, key, glyph);
}

char_type
tc_get_or_insert_chars(TextCache *self, const ListOfChars *chars) {
    return tc_get_or_insert_chars_with_glyph(self, chars, NULL);
}

char_type
tc_get_or_insert_chars_with_glyph(TextCache *self, const ListOfChars *chars, VGGlyph *glyph) {
    bool added;
    const char_type ans = get_or_insert(self, (Chars){.count = chars->count, .chars = chars->chars}, glyph, &added);
    if (added) self->adds_since_last_gc++;
    return ans;
}

void
tc_bound_glyph_usage(const TextCache *self, size_t *count, size_t *memory) {
    *count = self->bound_count;
    *memory = self->bound_memory;
}

bool
tc_has_adds_since_last_gc(const TextCache *self) {
    return self->adds_since_last_gc > 0;
}

char_type
tc_num_entries(const TextCache *self) {
    return self->array.count;
}

// Interned cell texts are referenced from cells by index, so entries cannot
// be evicted individually. Instead, periodically garbage collect: the owner
// of all index-holding cells (Screen) calls tc_gc_begin(), remaps every live
// cell index via tc_gc_map_index() -- which re-interns just the entries that
// are still referenced -- and finishes with tc_gc_end(). Entries no longer
// referenced by any cell (typically unique texts that have scrolled out of
// the history buffer) are freed. Without this, a stream of unique
// multi-codepoint cells (for example random combining marks) grows the cache
// without bound for the lifetime of the window.
#define TEXT_CACHE_ADDS_BETWEEN_GCS 8192u

bool
tc_should_gc(const TextCache *self) {
    return self->adds_since_last_gc > MAX(TEXT_CACHE_ADDS_BETWEEN_GCS, self->adds_between_gcs);
}

struct TextCacheGCData {
    Chars *old_items;
    char_type old_count;
    VGGlyph **old_glyphs;
    size_t old_glyphs_capacity;
    CharsMonotonicArena old_arena;
    // old index -> new index + 1, 0 means not yet remapped
    char_type *map;
};

TextCacheGCData *
tc_gc_begin(TextCache *self) {
    TextCacheGCData *gc = calloc(1, sizeof(TextCacheGCData));
    if (!gc) return NULL;
    gc->map = calloc(MAX(1u, (size_t)self->array.count), sizeof(gc->map[0]));
    Chars *fresh = malloc(256 * sizeof(self->array.items[0]));
    if (!gc->map || !fresh) {
        free(gc->map);
        free(fresh);
        free(gc);
        return NULL;
    }
    gc->old_items = self->array.items;
    gc->old_count = self->array.count;
    gc->old_arena = self->arena;
    self->array.items = fresh;
    self->array.capacity = 256;
    self->array.count = 0;
    zero_at_ptr(&self->arena);
    gc->old_glyphs = self->glyphs.items;
    gc->old_glyphs_capacity = self->glyphs.capacity;
    zero_at_ptr(&self->glyphs);
    // Recomputed as the live entries are re-inserted
    self->bound_count = 0;
    self->bound_memory = 0;
    vt_cleanup(&self->bound_map);
    vt_init(&self->bound_map);
    vt_cleanup(&self->map);
    vt_init(&self->map);
    // Avoid rehashing repeatedly as the live entries are re-inserted, the live
    // set of the previous collection is the best estimate of their number.
    // Failing to do so is harmless, the map grows as needed.
    if (self->adds_between_gcs) (void)vt_reserve(&self->map, self->adds_between_gcs);
    return gc;
}

bool
tc_gc_map_index(TextCache *self, TextCacheGCData *gc, char_type old_idx, char_type *new_idx) {
    if (old_idx >= gc->old_count) return false;
    if (!gc->map[old_idx]) {
        VGGlyph *glyph = old_idx < gc->old_glyphs_capacity ? gc->old_glyphs[old_idx] : NULL;
        bool added;
        const char_type nidx = get_or_insert(self, gc->old_items[old_idx], glyph, &added);
        gc->map[old_idx] = nidx + 1;
    }
    *new_idx = gc->map[old_idx] - 1;
    return true;
}

void
tc_gc_end(TextCache *self, TextCacheGCData *gc) {
    self->adds_since_last_gc = 0;
    // scale with the live set so remapping cost stays amortized
    self->adds_between_gcs = self->array.count;
    // Size the map for the entries that will be added before the next
    // collection, to avoid rehashing repeatedly as it grows. Failing to do so
    // is harmless, the map grows as needed.
    (void)vt_reserve(&self->map, self->array.count + MAX(TEXT_CACHE_ADDS_BETWEEN_GCS, self->array.count));
    free(gc->map);
    // The entries that are still referenced hold their own reference to their glyph
    release_glyphs(gc->old_glyphs, MIN(gc->old_glyphs_capacity, gc->old_count));
    free(gc->old_glyphs);
    free(gc->old_items);
    Chars_free_all(&gc->old_arena);
    free(gc);
}
