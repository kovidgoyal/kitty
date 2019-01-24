/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

#define REPORT_OOM global->oom = 1;

#define VECTOR_OF(TYPE, NAME) typedef struct { \
    TYPE *data; \
    size_t size; \
    size_t capacity; \
} NAME;

#define ALLOC_VEC(TYPE, vec, cap) \
    vec.size = 0; vec.capacity = cap; \
    vec.data = (TYPE*)malloc(vec.capacity * sizeof(TYPE)); \
    if (vec.data == NULL) { REPORT_OOM; }

#define FREE_VEC(vec) \
    if (vec.data) { free(vec.data); vec.data = NULL; } \
    vec.size = 0; vec.capacity = 0;

#define ENSURE_SPACE(TYPE, vec, amt) \
    if (vec.size + amt >= vec.capacity) { \
        vec.capacity = MAX(vec.capacity * 2, vec.size + amt); \
        vec.data = (TYPE*)realloc(vec.data, sizeof(TYPE) * vec.capacity); \
        if (vec.data == NULL) { REPORT_OOM; ret = 1; break; }  \
    }

#define NEXT(vec) (vec.data[vec.size])

#define INC(vec, amt) vec.size += amt;

#define SIZE(vec) (vec.size)

#define ITEM(vec, n) (vec.data[n])
