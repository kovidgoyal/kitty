/*
 * fixed_size_deque.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 *
 * A fixed size deque that does not allocate. To use define DEQUE_NAME, DEQUE_CAPACITY and
 * DEQUE_DATA_TYPE and include header. Use deque_push_back() to append. To
 * iterate in append order use deque_at(i) for 0 <= i < deque_size().
 */

#include <stdbool.h>
#include <string.h>

#ifndef DEQUE_NAME
#define DEQUE_NAME CircularDeque
#endif

#ifndef DEQUE_CAPACITY
#define DEQUE_CAPACITY 50
#endif

#ifndef DEQUE_DATA_TYPE
#define DEQUE_DATA_TYPE int
#endif

typedef struct {
    DEQUE_DATA_TYPE items[DEQUE_CAPACITY];
    unsigned head;  // Index of first element
    unsigned tail;  // Index one past last element
    unsigned count; // Number of elements
} DEQUE_NAME;

// Check if empty
static inline bool
deque_is_empty(const DEQUE_NAME* dq) { return dq->count == 0; }

// Check if full
static inline bool
deque_is_full(const DEQUE_NAME* dq) { return dq->count == DEQUE_CAPACITY; }

// Get current size
static inline unsigned
deque_size(const DEQUE_NAME* dq) { return dq->count; }

// Push to back auto-evicts from front if full.
// Returns true if an item was evicted, which will be copied to *evicted_item is not NULL.
static inline bool
deque_push_back(DEQUE_NAME* dq, DEQUE_DATA_TYPE item, DEQUE_DATA_TYPE *evicted_item) {
    bool evicted = false;
    if (deque_is_full(dq)) {
        // Evict front item
        if (evicted_item) *evicted_item = dq->items[dq->head];
        evicted = true;
        dq->head = (dq->head + 1) % DEQUE_CAPACITY;
        dq->count--;
    }
    dq->items[dq->tail] = item;
    dq->tail = (dq->tail + 1) % DEQUE_CAPACITY;
    dq->count++;
    return evicted;
}

// Push to front, auto-evicts from back if full.
// Returns true if an item was evicted, which will be copied to *evicted_item is not NULL.
static inline bool
deque_push_front(DEQUE_NAME* dq, DEQUE_DATA_TYPE item, DEQUE_DATA_TYPE *evicted_item) {
    bool evicted = false;

    if (deque_is_full(dq)) {
        // Evict oldest (back) item
        dq->tail = (dq->tail - 1 + DEQUE_CAPACITY) % DEQUE_CAPACITY;
        if (evicted_item) *evicted_item = dq->items[dq->tail];
        evicted = true;
        dq->count--;
    }

    dq->head = (dq->head - 1 + DEQUE_CAPACITY) % DEQUE_CAPACITY;
    dq->items[dq->head] = item;
    dq->count++;

    return evicted;
}

// Pop from front
static inline bool
deque_pop_front(DEQUE_NAME* dq, DEQUE_DATA_TYPE *ans) {
    if (deque_is_empty(dq)) return false;
    if (ans) *ans = dq->items[dq->head];
    dq->head = (dq->head + 1) % DEQUE_CAPACITY;
    dq->count--;
    return true;
}

// Pop from back
static inline bool
deque_pop_back(DEQUE_NAME* dq, DEQUE_DATA_TYPE *ans) {
    if (deque_is_empty(dq)) return false;
    dq->tail = (dq->tail - 1 + DEQUE_CAPACITY) % DEQUE_CAPACITY;
    if (ans) *ans = dq->items[dq->tail];
    dq->count--;
    return true;
}

// Peek at front without removing
static inline const DEQUE_DATA_TYPE*
deque_peek_front(const DEQUE_NAME* dq) {
    if (deque_is_empty(dq)) return NULL;
    return &dq->items[dq->head];
}

// Peek at back without removing
static inline const DEQUE_DATA_TYPE*
deque_peek_back(const DEQUE_NAME* dq) {
    if (deque_is_empty(dq)) return NULL;
    int idx = (dq->tail - 1 + DEQUE_CAPACITY) % DEQUE_CAPACITY;
    return &dq->items[idx];
}

// Access by index (0 = oldest, count-1 = newest)
static inline const DEQUE_DATA_TYPE*
deque_at(const DEQUE_NAME* dq, unsigned index) {
    if (index >= dq->count) return NULL;
    return &dq->items[(dq->head + index) % DEQUE_CAPACITY];
}

// Clear all items (doesn't free items)
static inline void
deque_clear(DEQUE_NAME* dq) {
    dq->head = 0;
    dq->tail = 0;
    dq->count = 0;
}

#undef DEQUE_CAPACITY
#undef DEQUE_DATA_TYPE
#undef DEQUE_NAME
