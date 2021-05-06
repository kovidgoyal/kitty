/*
 * hyperlink.c
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "hyperlink.h"
#include "kitty-uthash.h"
#include <string.h>

#define MAX_KEY_LEN 2048
#define MAX_ID_LEN 256
#define MAX_ADDS_BEFORE_GC 256

typedef struct {
    const char *key;
    hyperlink_id_type id;
    UT_hash_handle hh;
} HyperLinkEntry;


typedef struct {
    HyperLinkEntry *hyperlinks;
    unsigned int max_link_id, num_of_adds_since_garbage_collection;
} HyperLinkPool;


static void
free_hyperlink_entry(HyperLinkEntry *s) {
    free((void*)s->key);
    free(s);
}

static void
clear_pool(HyperLinkPool *pool) {
    if (pool->hyperlinks) {
        HyperLinkEntry *tmp, *s;
        HASH_ITER(hh, pool->hyperlinks, s, tmp) {
            HASH_DEL(pool->hyperlinks, s);
            free_hyperlink_entry(s); s = NULL;
        }
        pool->max_link_id = 0;
    }
}

HYPERLINK_POOL_HANDLE
alloc_hyperlink_pool(void) {
    return calloc(1, sizeof(HyperLinkPool));
}


void
clear_hyperlink_pool(HYPERLINK_POOL_HANDLE h) {
    if (h) {
        HyperLinkPool *pool = (HyperLinkPool*)h;
        clear_pool(pool);
    }
}


void
free_hyperlink_pool(HYPERLINK_POOL_HANDLE h) {
    if (h) {
        HyperLinkPool *pool = (HyperLinkPool*)h;
        clear_pool(pool);
        free(pool);
    }
}


void
screen_garbage_collect_hyperlink_pool(Screen *screen) {
    HyperLinkPool *pool = (HyperLinkPool*)screen->hyperlink_pool;
    pool->num_of_adds_since_garbage_collection = 0;
    if (!pool->max_link_id) return;
    hyperlink_id_type *map = calloc(HYPERLINK_MAX_NUMBER + 4, sizeof(hyperlink_id_type));
    if (!map) fatal("Out of memory");
    hyperlink_id_type num = remap_hyperlink_ids(screen, map);
    if (num) {
        HyperLinkEntry *s, *tmp;
        pool->max_link_id = 0;
        HASH_ITER(hh, pool->hyperlinks, s, tmp) {
            if (map[s->id]) {
                s->id = map[s->id];
                pool->max_link_id = MAX(pool->max_link_id, s->id);
            } else {
                HASH_DEL(pool->hyperlinks, s);
                free_hyperlink_entry(s); s = NULL;
            }
        }
    } else clear_pool(pool);
    free(map);
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
    HyperLinkEntry *s = NULL;
    if (pool->hyperlinks) {
        HASH_FIND_STR(pool->hyperlinks, key, s);
        if (s) {
            // Remove and re-add s so that it is the last entry in the hash table and
            // The first entry is discarded when hash table is full.
            HASH_DEL(pool->hyperlinks, s);
            HASH_ADD_KEYPTR(hh, pool->hyperlinks, s->key, strlen(s->key), s);
            return s->id;
        }
    }
    hyperlink_id_type new_id = 0;
    if (pool->num_of_adds_since_garbage_collection >= MAX_ADDS_BEFORE_GC) screen_garbage_collect_hyperlink_pool(screen);
    if (pool->max_link_id >= HYPERLINK_MAX_NUMBER && pool->hyperlinks) {
        log_error("Too many hyperlinks, discarding oldest, this means some hyperlinks might be incorrect");
        new_id = pool->hyperlinks->id;
        HyperLinkEntry *s = pool->hyperlinks;
        HASH_DEL(pool->hyperlinks, s);
        free_hyperlink_entry(s); s = NULL;
    }
    s = malloc(sizeof(HyperLinkEntry));
    if (!s) fatal("Out of memory");
    s->key = malloc(keylen + 1);
    if (!s->key) fatal("Out of memory");
    memcpy((void*)s->key, key, keylen + 1);
    s->id = new_id ? new_id : ++pool->max_link_id;
    HASH_ADD_KEYPTR(hh, pool->hyperlinks, s->key, keylen, s);
    pool->num_of_adds_since_garbage_collection++;
    return s->id;
}

const char*
get_hyperlink_for_id(const HYPERLINK_POOL_HANDLE handle, hyperlink_id_type id, bool only_url) {
    const HyperLinkPool *pool = (HyperLinkPool*)handle;
    HyperLinkEntry *s, *tmp;
    HASH_ITER(hh, pool->hyperlinks, s, tmp) {
        if (s->id == id) return only_url ? strstr(s->key, ":") + 1 : s->key;
    }
    return NULL;
}


PyObject*
screen_hyperlinks_as_list(Screen *screen) {
    HyperLinkPool *pool = (HyperLinkPool*)screen->hyperlink_pool;
    PyObject *ans = PyList_New(0);
    HyperLinkEntry *s, *tmp;
    HASH_ITER(hh, pool->hyperlinks, s, tmp) {
        PyObject *e = Py_BuildValue("sH", s->key, s->id);
        PyList_Append(ans, e);
        Py_DECREF(e);
    }
    return ans;
}
