/*
 * arena.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

#ifndef MA_NAME
#error "Must define MA_NAME"
#endif

#ifndef MA_BLOCK_SIZE
#define MA_BLOCK_SIZE 1u
#endif

#define MA_CAT_( a, b ) a##b
#define MA_CAT( a, b ) MA_CAT_( a, b )

#ifndef MA_ARENA_NUM_BLOCKS
#define MA_ARENA_NUM_BLOCKS 4096u
#endif

#define MA_TYPE_NAME MA_CAT(MA_NAME, MonotonicArena)
#define MA_BLOCK_TYPE_NAME MA_CAT(MA_NAME, MonotonicArenaBlock)

typedef struct MA_BLOCK_TYPE_NAME {
    void *buf; size_t used, capacity;
} MA_BLOCK_TYPE_NAME;

typedef struct MA_TYPE_NAME {
    MA_BLOCK_TYPE_NAME *blocks;
    size_t count, capacity;
} MA_TYPE_NAME;

static inline void
MA_CAT(MA_NAME, _free_all)(MA_TYPE_NAME *self) {
    for (size_t i = 0; i < self->count; i++) free(self->blocks[i].buf);
    free(self->blocks);
    zero_at_ptr(self);
}

static inline void*
MA_CAT(MA_NAME, _get)(MA_TYPE_NAME *self, size_t sz) {
    size_t required_size = (sz / MA_BLOCK_SIZE) * MA_BLOCK_SIZE;
    if (required_size < sz) required_size += MA_BLOCK_SIZE;
    if (!self->count || (self->blocks[self->count-1].capacity - self->blocks[self->count-1].used) < required_size) {
        size_t count = self->count + 1;
        size_t block_sz = MAX(required_size, MA_ARENA_NUM_BLOCKS * MA_BLOCK_SIZE);
        void *chunk = NULL;
        if (MA_BLOCK_SIZE >= sizeof(void*) && MA_BLOCK_SIZE % sizeof(void*) == 0) {
            if (posix_memalign(&chunk, MA_BLOCK_SIZE, block_sz) != 0) chunk = NULL;
            memset(chunk, 0, block_sz);
        } else chunk = calloc(1, block_sz);
        if (!chunk) { return NULL; }
        if (count > self->capacity) {
            size_t capacity = MAX(8u, 2 * self->capacity);
            MA_BLOCK_TYPE_NAME *blocks = realloc(self->blocks, capacity * sizeof(MA_BLOCK_TYPE_NAME));
            if (!blocks) { free(chunk); return NULL; }
            self->capacity = capacity; self->blocks = blocks;
        }
        self->blocks[count - 1] = (MA_BLOCK_TYPE_NAME){.capacity=block_sz, .buf=chunk};
        self->count = count;
    }
    char *ans = (char*)self->blocks[self->count-1].buf + self->blocks[self->count-1].used;
    self->blocks[self->count-1].used += required_size;
    return ans;
}

#undef MA_NAME
#undef MA_BLOCK_SIZE
#undef MA_ARENA_NUM_BLOCKS
#undef MA_TYPE_NAME
#undef MA_BLOCK_TYPE_NAME
#undef MA_CAT
#undef MA_CAT_
