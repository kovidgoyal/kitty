/*
 * text-cache.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
typedef struct Chars {
    const char_type *chars;
    size_t count;
} Chars;
static_assert(sizeof(Chars) == sizeof(void*) + sizeof(size_t), "reorder Chars");

#define NAME chars_map
#define KEY_TY Chars
#define VAL_TY char_type
static uint64_t hash_chars(Chars k);
static bool cmpr_chars(Chars a, Chars b);
#define HASH_FN hash_chars
#define CMPR_FN cmpr_chars
#include "kitty-verstable.h"

#define MA_NAME Chars
#define MA_BLOCK_SIZE 16u
#define MA_ARENA_NUM_BLOCKS 128u
#include "arena.h"

typedef struct TextCache {
    struct { Chars *items; size_t capacity; char_type count; } array;
    chars_map map;
    unsigned refcnt;
    CharsMonotonicArena arena;
    unsigned adds_since_last_gc;
} TextCache;
static uint64_t hash_chars(Chars k) { return vt_hash_bytes(k.chars, sizeof(k.chars[0]) * k.count); }
static bool cmpr_chars(Chars a, Chars b) { return a.count == b.count && memcmp(a.chars, b.chars, sizeof(a.chars[0]) * a.count) == 0; }

#define TEXT_CACHE_IMPLEMENTATION
#include "text-cache.h"

TextCache*
tc_alloc(void) {
    TextCache *ans = calloc(1, sizeof(TextCache));
    if (!ans) return NULL;
    ans->array.capacity = 256;
    ans->array.items = malloc(ans->array.capacity * sizeof(ans->array.items[0]));
    if (!ans->array.items) { free(ans); ans = NULL; return ans; }
    vt_init(&ans->map);
    ans->refcnt = 1;
    return ans;
}

static void
free_text_cache(TextCache *self) {
    vt_cleanup(&self->map);
    Chars_free_all(&self->arena);
    free(self->array.items);
    free(self);
}

TextCache*
tc_incref(TextCache *self) { if (self) { self->refcnt++; } return self; }

TextCache*
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
    if (self->array.count > idx) return self->array.items[idx].chars[self->array.items[idx].count-1];
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
copy_and_insert(TextCache *self, const Chars key) {
    if (self->array.count > MAX_CHAR_TYPE_VALUE) fatal("Too many items in TextCache");
    ensure_space_for(&(self->array), items, Chars, self->array.count + 1, capacity, 256, false);
    char_type *copy = Chars_get(&self->arena, key.count * sizeof(key.chars[0]));
    if (!copy) fatal("Out of memory");
    memcpy(copy, key.chars, key.count * sizeof(key.chars[0]));
    char_type ans = self->array.count;
    Chars *k = self->array.items + self->array.count++;
    k->count = key.count; k->chars = copy;
    chars_map_itr i = vt_insert(&self->map, *k, ans);
    if (vt_is_end(i)) fatal("Out of memory");
    return ans;
}

char_type
tc_get_or_insert_chars(TextCache *self, const ListOfChars *chars) {
    Chars key = {.count=chars->count, .chars=chars->chars};
    chars_map_itr i = vt_get(&self->map, key);
    if (vt_is_end(i)) { self->adds_since_last_gc++; return copy_and_insert(self, key); }
    return i.data->val;
}

char_type
tc_num_entries(const TextCache *self) { return self->array.count; }

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
tc_should_gc(const TextCache *self) { return self->adds_since_last_gc > TEXT_CACHE_ADDS_BETWEEN_GCS; }

struct TextCacheGCData {
    Chars *old_items; char_type old_count;
    CharsMonotonicArena old_arena;
    // old index -> new index + 1, 0 means not yet remapped
    char_type *map;
};

TextCacheGCData*
tc_gc_begin(TextCache *self) {
    TextCacheGCData *gc = calloc(1, sizeof(TextCacheGCData));
    if (!gc) return NULL;
    gc->map = calloc(MAX(1u, (size_t)self->array.count), sizeof(gc->map[0]));
    Chars *fresh = malloc(256 * sizeof(self->array.items[0]));
    if (!gc->map || !fresh) { free(gc->map); free(fresh); free(gc); return NULL; }
    gc->old_items = self->array.items; gc->old_count = self->array.count;
    gc->old_arena = self->arena;
    self->array.items = fresh; self->array.capacity = 256; self->array.count = 0;
    zero_at_ptr(&self->arena);
    vt_cleanup(&self->map); vt_init(&self->map);
    self->adds_since_last_gc = 0;
    return gc;
}

bool
tc_gc_map_index(TextCache *self, TextCacheGCData *gc, char_type old_idx, char_type *new_idx) {
    if (old_idx >= gc->old_count) return false;
    if (!gc->map[old_idx]) {
        Chars key = gc->old_items[old_idx];
        chars_map_itr i = vt_get(&self->map, key);
        char_type nidx = vt_is_end(i) ? copy_and_insert(self, key) : i.data->val;
        gc->map[old_idx] = nidx + 1;
    }
    *new_idx = gc->map[old_idx] - 1;
    return true;
}

void
tc_gc_end(TextCacheGCData *gc) {
    free(gc->map); free(gc->old_items);
    Chars_free_all(&gc->old_arena);
    free(gc);
}
