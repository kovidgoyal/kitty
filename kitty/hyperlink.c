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

#define NAME hyperlink_id_map
#define KEY_TY hyperlink_id_type
#define VAL_TY const char*
#include "kitty-verstable.h"


typedef struct {
    hyperlink_map map;
    hyperlink_id_map idmap;
    hyperlink_id_type max_link_id, num_of_adds_since_garbage_collection;
} HyperLinkPool;

static void
clear_pool(HyperLinkPool *pool) {
    for (hyperlink_map_itr i = vt_first(&pool->map); !vt_is_end(i); i = vt_next(i)) free((char*)i.data->key);
    vt_cleanup(&pool->map); vt_cleanup(&pool->idmap);
    pool->max_link_id = 0; pool->num_of_adds_since_garbage_collection = 0;
}

HYPERLINK_POOL_HANDLE
alloc_hyperlink_pool(void) {
    HyperLinkPool *ans = calloc(1, sizeof(HyperLinkPool));
    if (ans) { vt_init(&ans->map); vt_init(&ans->idmap); }
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

#define NAME id_id_map
#define KEY_TY hyperlink_id_type
#define VAL_TY hyperlink_id_type
#include "kitty-verstable.h"


static const char*
dupstr(const char *src, size_t len) {
    char *ans = malloc(len+1);
    if (!ans) fatal("Out of memory");
    memcpy(ans, src, len); ans[len] = 0;
    return ans;
}

static void
process_cell(HyperLinkPool *pool, id_id_map *map, hyperlink_id_map *clone, CPUCell *c) {
    if (!c->hyperlink_id) return;
    id_id_map_itr n = vt_get(map, c->hyperlink_id);
    hyperlink_id_type new_id;
    if (vt_is_end(n)) {
        hyperlink_id_map_itr i = vt_get(clone, c->hyperlink_id);
        if (vt_is_end(i)) new_id = 0;
        else {
            new_id = ++pool->max_link_id;
            if (vt_is_end(vt_insert(map, c->hyperlink_id, new_id))) fatal("Out of memory");
            const char *key = i.data->val;
            if (vt_is_end(vt_insert(&pool->map, key, new_id))) fatal("Out of memory");
            if (vt_is_end(vt_insert(&pool->idmap, new_id, key))) fatal("Out of memory");
            vt_erase_itr(clone, i);
        }
    } else new_id = n.data->val;
    c->hyperlink_id = new_id;
}

static void
remap_hyperlink_ids(Screen *self, id_id_map *map, hyperlink_id_map *clone) {
    HyperLinkPool *pool = (HyperLinkPool*)self->hyperlink_pool;
    if (self->historybuf->count) {
        for (index_type y = self->historybuf->count; y-- > 0;) {
            CPUCell *cells = historybuf_cpu_cells(self->historybuf, y);
            for (index_type x = 0; x < self->historybuf->xnum; x++) process_cell(pool, map, clone, cells + x);
        }
    }
    LineBuf *second = self->linebuf, *first = second == self->main_linebuf ? self->alt_linebuf : self->main_linebuf;
    for (index_type i = 0; i < self->lines * self->columns; i++) process_cell(pool, map, clone, first->cpu_cell_buf + i);
    for (index_type i = 0; i < self->lines * self->columns; i++) process_cell(pool, map, clone, second->cpu_cell_buf + i);
}

void
screen_garbage_collect_hyperlink_pool(Screen *screen) {
    HyperLinkPool *pool = (HyperLinkPool*)screen->hyperlink_pool;
    pool->num_of_adds_since_garbage_collection = 0;
    if (!pool->max_link_id) return;
    pool->max_link_id = 0;
    id_id_map map = {0};
    vt_init(&map);
    hyperlink_id_map clone = {0};
    if (!vt_init_clone(&clone, &pool->idmap)) fatal("Out of memory");
    vt_cleanup(&pool->map); vt_cleanup(&pool->idmap);
    remap_hyperlink_ids(screen, &map, &clone);
    for (hyperlink_id_map_itr i = vt_first(&clone); !vt_is_end(i); i = vt_next(i)) free((char*)i.data->val);
    vt_clear(&map); vt_clear(&clone);
}


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
    if (pool->max_link_id >= HYPERLINK_MAX_NUMBER) {
        if (pool->num_of_adds_since_garbage_collection > 128) screen_garbage_collect_hyperlink_pool(screen);
        if (pool->max_link_id >= HYPERLINK_MAX_NUMBER) {
            log_error("Too many hyperlinks, discarding hyperlink: %s", key);
            return 0;
        }
    }
    hyperlink_id_type new_id = ++pool->max_link_id;
    const char *skey = dupstr(key, keylen);
    if (vt_is_end(vt_insert(&pool->map, skey, new_id))) fatal("Out of memory");
    if (vt_is_end(vt_insert(&pool->idmap, new_id, skey))) fatal("Out of memory");
    pool->num_of_adds_since_garbage_collection++;
    return new_id;
}

const char*
get_hyperlink_for_id(const HYPERLINK_POOL_HANDLE handle, hyperlink_id_type id, bool only_url) {
    HyperLinkPool *pool = (HyperLinkPool*)handle;
    hyperlink_id_map_itr itr = vt_get(&pool->idmap, id);
    if (vt_is_end(itr)) return NULL;
    return only_url ? strstr(itr.data->val, ":") + 1 : itr.data->val;
}

PyObject*
screen_hyperlinks_as_set(Screen *screen) {
    HyperLinkPool *pool = (HyperLinkPool*)screen->hyperlink_pool;
    RAII_PyObject(ans, PySet_New(0));
    if (ans) {
        for (hyperlink_map_itr itr = vt_first(&pool->map); !vt_is_end(itr); itr = vt_next(itr)) {
            RAII_PyObject(e, Py_BuildValue("sH", itr.data->key, itr.data->val));
            if (!e || PySet_Add(ans, e) != 0) return NULL;
        }
    }
    Py_XINCREF(ans); return ans;
}
