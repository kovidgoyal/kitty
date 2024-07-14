/*
 * text-cache.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
typedef struct Chars {
    size_t count;
    const char_type *chars;
} Chars;

#define NAME chars_map
#define KEY_TY Chars
#define VAL_TY CharOrIndex
static uint64_t hash_chars(Chars k);
static bool cmpr_chars(Chars a, Chars b);
#define HASH_FN hash_chars
#define CMPR_FN cmpr_chars
#include "kitty-verstable.h"

typedef struct TextCache {
    struct { Chars *items; size_t count, capacity; } array;
    chars_map map;
    unsigned refcnt;
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

void
tc_clear(TextCache *ans) {
    ans->array.count = 0;
    vt_cleanup(&ans->map);
}

static void
free_text_cache(TextCache *self) {
    vt_cleanup(&self->map);
    for (size_t i = 0; i < self->array.count; i++) free((char_type*)self->array.items[i].chars);
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

void
tc_chars_at_index(const TextCache *self, CharOrIndex idx, ListOfChars *ans) {
    if (idx.ch_is_index) {
        if (self->array.count > idx.ch) {
            ans->count = self->array.items[idx.ch].count;
            ensure_space_for(ans, chars, char_type, ans->count, capacity, 8, false);
            memcpy(ans->chars, self->array.items[idx.ch].chars, sizeof(ans->chars[0]) * ans->count);
        } else {
            ans->count = 0;
        }
    } else {
        ans->count = 1;
        ensure_space_for(ans, chars, char_type, 1, capacity, 8, false);
        ans->chars[0] = idx.ch;
    }
}

static CharOrIndex
copy_and_insert(TextCache *self, const Chars key) {
    if (self->array.count >= (1llu << (8*sizeof(char_type) - 1)) - 1) fatal("Too many items in TextCache");
    ensure_space_for(&(self->array), items, Chars, self->array.count + 1, capacity, 256, false);
    char_type *copy = malloc(key.count * sizeof(key.chars[0]));
    if (!copy) fatal("Out of memory");
    memcpy(copy, key.chars, key.count * sizeof(key.chars[0]));
    CharOrIndex ans;
    ans.ch_is_index = 1; ans.ch = self->array.count;
    Chars *k = self->array.items + self->array.count++;
    k->count = key.count; k->chars = copy;
    chars_map_itr i = vt_insert(&self->map, *k, ans);
    if (vt_is_end(i)) fatal("Out of memory");
    return ans;
}

CharOrIndex
tc_get_or_insert_chars(TextCache *self, const ListOfChars *chars) {
    if (chars->count == 1) {
        CharOrIndex ans = {0};
        ans.ch = chars->chars[0];
        return ans;
    }
    Chars key = {.count=chars->count, .chars=chars->chars};
    chars_map_itr i = vt_get(&self->map, key);
    if (vt_is_end(i)) return copy_and_insert(self, key);
    return i.data->val;
}
