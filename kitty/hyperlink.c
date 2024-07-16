/*
 * hyperlink.c
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "hyperlink.h"
#include "lineops.h"
#include <string.h>

#define MAX_KEY_LEN 2048
#define MAX_ID_LEN 256

#define NAME hyperlink_map
#define KEY_TY const char*
#define VAL_TY hyperlink_id_type
#include "kitty-verstable.h"
#define hyperlink_for_loop vt_create_for_loop(hyperlink_map_itr, itr, &pool->map)

typedef const char* hyperlink;
typedef struct HyperLinks {
    hyperlink *items;
    size_t count, capacity;
} HyperLinks;

typedef struct {
    HyperLinks array;
    hyperlink_map map;
    hyperlink_id_type adds_since_last_gc;
} HyperLinkPool;

static void
free_hyperlink_items(HyperLinks array) { for (size_t i = 1; i < array.count; i++) free((void*)array.items[i]); }

static void
clear_pool(HyperLinkPool *pool) {
    if (pool->array.items) {
        free_hyperlink_items(pool->array);
        free(pool->array.items);
    }
    vt_cleanup(&pool->map);
    zero_at_ptr(&(pool->array));
    pool->adds_since_last_gc = 0;
}

HYPERLINK_POOL_HANDLE
alloc_hyperlink_pool(void) {
    HyperLinkPool *ans = calloc(1, sizeof(HyperLinkPool));
    if (ans) vt_init(&ans->map);
    return (HYPERLINK_POOL_HANDLE)ans;
}


void
clear_hyperlink_pool(HYPERLINK_POOL_HANDLE h) {
    if (h) clear_pool((HyperLinkPool*)h);
}


void
free_hyperlink_pool(HYPERLINK_POOL_HANDLE h) {
    if (h) {
        HyperLinkPool *pool = (HyperLinkPool*)h;
        clear_pool(pool);
        free(pool);
    }
}

static const char*
dupstr(const char *src, size_t len) {
    char *ans = malloc(len+1);
    if (!ans) fatal("Out of memory");
    memcpy(ans, src, len); ans[len] = 0;
    return ans;
}

static void
process_cell(HyperLinkPool *pool, hyperlink_id_type *map, HyperLinks clone, CPUCell *c) {
    if (!c->hyperlink_id) return;
    if (c->hyperlink_id >= clone.count) { c->hyperlink_id = 0; return; }
    hyperlink_id_type new_id = map[c->hyperlink_id];
    if (!new_id) {
        new_id = pool->array.count++;
        map[c->hyperlink_id] = new_id;
        pool->array.items[new_id] = clone.items[c->hyperlink_id]; clone.items[c->hyperlink_id] = NULL;
        if (vt_is_end(vt_insert(&pool->map, pool->array.items[new_id], new_id))) fatal("Out of memory");
    }
    c->hyperlink_id = new_id;
}

static void
remap_hyperlink_ids(Screen *self, bool preserve_hyperlinks_in_history, hyperlink_id_type *map, HyperLinks clone) {
    HyperLinkPool *pool = (HyperLinkPool*)self->hyperlink_pool;
    if (self->historybuf->count && preserve_hyperlinks_in_history) {
        for (index_type y = self->historybuf->count; y-- > 0;) {
            CPUCell *cells = historybuf_cpu_cells(self->historybuf, y);
            for (index_type x = 0; x < self->historybuf->xnum; x++) process_cell(pool, map, clone, cells + x);
        }
    }
    LineBuf *second = self->linebuf, *first = second == self->main_linebuf ? self->alt_linebuf : self->main_linebuf;
    for (index_type i = 0; i < self->lines * self->columns; i++) process_cell(pool, map, clone, first->cpu_cell_buf + i);
    for (index_type i = 0; i < self->lines * self->columns; i++) process_cell(pool, map, clone, second->cpu_cell_buf + i);
}

static void
_screen_garbage_collect_hyperlink_pool(Screen *screen, bool preserve_hyperlinks_in_history) {
    HyperLinkPool *pool = (HyperLinkPool*)screen->hyperlink_pool;
    if (!pool->array.count) return;
    pool->adds_since_last_gc = 0;
    RAII_ALLOC(hyperlink_id_type, map, calloc(pool->array.count, sizeof(hyperlink_id_type)));
    RAII_ALLOC(void, buf, malloc(pool->array.count * sizeof(pool->array.items[0])));
    if (!map || !buf) fatal("Out of memory");
    HyperLinks clone = {.capacity=pool->array.count, .count=pool->array.count, .items=buf};
    memcpy(buf, pool->array.items, pool->array.count * sizeof(pool->array.items[0]));
    vt_cleanup(&pool->map);
    pool->array.count = 1;  // First id must be 1
    remap_hyperlink_ids(screen, preserve_hyperlinks_in_history, map, clone);
    free_hyperlink_items(clone);
}

void
screen_garbage_collect_hyperlink_pool(Screen *screen) { _screen_garbage_collect_hyperlink_pool(screen, true); }


hyperlink_id_type
get_id_for_hyperlink(Screen *screen, const char *id, const char *url) {
    if (!url) return 0;
    HyperLinkPool *pool = (HyperLinkPool*)screen->hyperlink_pool;
    static char key[MAX_KEY_LEN] = {0};
    int keylen = snprintf(key, MAX_KEY_LEN-1, "%.*s:%s", MAX_ID_LEN, id ? id : "", url);
    if (keylen < 0) keylen = strlen(key);
    else keylen = MIN(keylen, MAX_KEY_LEN - 2);  // snprintf returns how many chars it would have written in case of truncation
    key[keylen] = 0;
    hyperlink_map_itr itr = vt_get(&pool->map, key);
    if (!vt_is_end(itr)) return itr.data->val;
    if (pool->array.count >= HYPERLINK_MAX_NUMBER-1) {
        screen_garbage_collect_hyperlink_pool(screen);
        if (pool->array.count >= HYPERLINK_MAX_NUMBER - 128) {
            log_error("Too many hyperlinks, discarding hyperlinks in scrollback");
            _screen_garbage_collect_hyperlink_pool(screen, false);
            if (pool->array.count >= HYPERLINK_MAX_NUMBER) {
                log_error("Too many hyperlinks, discarding hyperlink: %s", key);
                return 0;
            }
        }
    }
    if (!pool->array.count) pool->array.count = 1;  // First id must be 1
    ensure_space_for(&(pool->array), items, hyperlink, pool->array.count + 1, capacity, 256, false);
    hyperlink_id_type new_id = pool->array.count++;
    pool->array.items[new_id] = dupstr(key, keylen);
    if (vt_is_end(vt_insert(&pool->map, pool->array.items[new_id], new_id))) fatal("Out of memory");
    // If there have been a lot of hyperlink adds do a garbage collect so as
    // not to leak too much memory over unused hyperlinks
    if (++pool->adds_since_last_gc > 8192) screen_garbage_collect_hyperlink_pool(screen);
    return new_id;
}

const char*
get_hyperlink_for_id(const HYPERLINK_POOL_HANDLE handle, hyperlink_id_type id, bool only_url) {
    HyperLinkPool *pool = (HyperLinkPool*)handle;
    if (id >= pool->array.count) return NULL;
    return only_url ? strstr(pool->array.items[id], ":") + 1 : pool->array.items[id];
}

PyObject*
screen_hyperlinks_as_set(Screen *screen) {
    HyperLinkPool *pool = (HyperLinkPool*)screen->hyperlink_pool;
    RAII_PyObject(ans, PySet_New(0));
    if (ans) {
        hyperlink_for_loop {
            RAII_PyObject(e, Py_BuildValue("sH", itr.data->key, itr.data->val));
            if (!e || PySet_Add(ans, e) != 0) return NULL;
        }
    }
    Py_XINCREF(ans); return ans;
}
