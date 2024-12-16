/*
 * text-cache.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef struct ListOfChars {
    char_type *chars;
    size_t count, capacity;
} ListOfChars;

#define LIST_OF_CHARS_STACK_SIZE 4
static inline void cleanup_list_of_chars(ListOfChars *lc) { if (lc->capacity > LIST_OF_CHARS_STACK_SIZE) free(lc->chars); }
#define RAII_ListOfChars(name) char_type name##lcbuf[LIST_OF_CHARS_STACK_SIZE]; __attribute__((cleanup(cleanup_list_of_chars))) ListOfChars name = {.chars=name##lcbuf, .capacity = LIST_OF_CHARS_STACK_SIZE};
static inline ListOfChars* alloc_list_of_chars(void) {
    ListOfChars *ans = calloc(1, sizeof(ListOfChars));
    if (ans) {
        ans->capacity = LIST_OF_CHARS_STACK_SIZE * 2;
        ans->chars = malloc(ans->capacity * sizeof(ans->chars[0]));
        if (!ans->chars) { free(ans); ans = NULL; }
    }
    return ans;
}

static inline void
ensure_space_for_chars(ListOfChars *lc, size_t count) {
    if (lc->capacity >= count) return;
    if (lc->capacity > LIST_OF_CHARS_STACK_SIZE) {
        ensure_space_for(lc, chars, char_type, count, capacity, count, false);
    } else {
        lc->capacity = count + LIST_OF_CHARS_STACK_SIZE;
        void *chars = malloc(lc->capacity * sizeof(lc->chars[0]));
        if (!chars) fatal("Out of memory allocating LCChars char space");
        memcpy(chars, lc->chars, LIST_OF_CHARS_STACK_SIZE * sizeof(lc->chars[0]));
        lc->chars = chars;
    }
}

#ifndef TEXT_CACHE_IMPLEMENTATION
typedef struct {int x; } *TextCache;
#endif

TextCache* tc_alloc(void);
TextCache* tc_incref(TextCache *self);
TextCache* tc_decref(TextCache *self);
void tc_chars_at_index(const TextCache *self, char_type idx, ListOfChars *ans);
unsigned tc_chars_at_index_ansi(const TextCache *self, char_type idx, ANSIBuf *output);
char_type tc_get_or_insert_chars(TextCache *self, const ListOfChars *chars);
char_type tc_first_char_at_index(const TextCache *self, char_type idx);
char_type tc_last_char_at_index(const TextCache *self, char_type idx);
bool tc_chars_at_index_without_alloc(const TextCache *self, char_type idx, ListOfChars *ans);
unsigned tc_num_codepoints(const TextCache *self, char_type idx);
