/*
 * window_logo.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "window_logo.h"
#include "state.h"


typedef struct WindowLogoItem {
    WindowLogo wl;
    unsigned int refcnt;
    char *path;
    window_logo_id_t id;
    UT_hash_handle hh_id;
    UT_hash_handle hh_path;
} WindowLogoItem;

struct WindowLogoTable {
    WindowLogoItem *by_id, *by_path;
};

static void
free_window_logo(WindowLogoTable *table, WindowLogoItem **itemref) {
    WindowLogoItem *item = *itemref;
    free(item->path);
    free(item->wl.bitmap);
    if (item->wl.texture_id) free_texture(&item->wl.texture_id);
    HASH_DELETE(hh_id, table->by_id, item);
    HASH_DELETE(hh_path, table->by_path, item);
    free(item); itemref = NULL;
}

static void
send_logo_to_gpu(WindowLogo *s) {
    send_image_to_gpu(&s->texture_id, s->bitmap, s->width, s->height, false, true, true, REPEAT_CLAMP);
    free(s->bitmap); s->bitmap = NULL;
}


void
set_on_gpu_state(WindowLogo *s, bool on_gpu) {
    if (s->load_from_disk_ok) {
        if (on_gpu) { if (!s->texture_id) send_logo_to_gpu(s); }
        else if (s->texture_id) free_texture(&s->texture_id);
    }
}

window_logo_id_t
find_or_create_window_logo(WindowLogoTable *head, const char *path, void *png_data, size_t png_data_size) {
    WindowLogoItem *s = NULL;
    unsigned _uthash_hfstr_keylen = (unsigned)uthash_strlen(path);
    HASH_FIND(hh_path, head->by_path, path, _uthash_hfstr_keylen, s);
    if (s) {
        s->refcnt++;
        return s->id;
    }
    s = calloc(1, sizeof *s);
    size_t size;
    if (!s) { PyErr_NoMemory(); return 0; }
    s->path = strdup(path);
    if (!s->path) { free(s); PyErr_NoMemory(); return 0; }
    bool ok = false;
    if (png_data == NULL || !png_data_size) {
        ok = png_path_to_bitmap(path, &s->wl.bitmap, &s->wl.width, &s->wl.height, &size);
    } else {
        ok = png_from_data(png_data, png_data_size, path, &s->wl.bitmap, &s->wl.width, &s->wl.height, &size);
    }
    if (ok) s->wl.load_from_disk_ok = true;
    s->refcnt++;
    static window_logo_id_t idc = 0;
    s->id = ++idc;
    HASH_ADD(hh_id, head->by_id, id, sizeof(window_logo_id_t), s);
    HASH_ADD_KEYPTR(hh_path, head->by_path, s->path, strlen(s->path), s);
    return s->id;
}

WindowLogo*
find_window_logo(WindowLogoTable *table, window_logo_id_t id) {
    WindowLogoItem *s = NULL;
    HASH_FIND(hh_id, table->by_id, &id, sizeof(window_logo_id_t), s);
    return s ? &s->wl : NULL;
}

void
decref_window_logo(WindowLogoTable *table, window_logo_id_t id) {
    WindowLogoItem *s = NULL;
    HASH_FIND(hh_id, table->by_id, &id, sizeof(window_logo_id_t), s);
    if (s) {
        if (s->refcnt < 2) free_window_logo(table, &s);
        else s->refcnt--;
    }
}

WindowLogoTable*
alloc_window_logo_table(void) {
    return calloc(1, sizeof(WindowLogoTable));
}

void
free_window_logo_table(WindowLogoTable **table) {
    WindowLogoItem *current, *tmp;
    HASH_ITER(hh_id, (*table)->by_id, current, tmp) {
        free_window_logo(*table, &current);
    }
    HASH_CLEAR(hh_path, (*table)->by_path);
    HASH_CLEAR(hh_id, (*table)->by_id);
    free(*table); *table = NULL;
}
