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

#ifndef TEXT_CACHE_IMPLEMENTATION
typedef struct {int x; } *TextCache;
#endif

TextCache* tc_alloc(void);
TextCache* tc_incref(TextCache *self);
TextCache* tc_decref(TextCache *self);
void tc_clear(TextCache *ans);
void tc_chars_at_index(const TextCache *self, CharOrIndex idx, ListOfChars *ans);
CharOrIndex tc_get_or_insert_chars(TextCache *self, const ListOfChars *chars);
