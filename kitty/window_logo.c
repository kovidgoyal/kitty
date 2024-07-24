/*
 * window_logo.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */


#include "state.h"
#include "window_logo.h"
#include <sys/mman.h>

typedef struct WindowLogoItem {
    WindowLogo wl;
    unsigned int refcnt;
    char *path;
    window_logo_id_t id;
} WindowLogoItem;

#define NAME hash_by_id
#define KEY_TY window_logo_id_t
#define VAL_TY WindowLogoItem*
#include "kitty-verstable.h"
#define id_for_loop(table) vt_create_for_loop(hash_by_id_itr, itr, &(table)->by_id)

#define NAME hash_by_path
#define KEY_TY const char*
#define VAL_TY WindowLogoItem*
#include "kitty-verstable.h"


struct WindowLogoTable {
    hash_by_id by_id;
    hash_by_path by_path;
};

static void
free_window_logo_bitmap(WindowLogo *wl) {
    if (!wl->bitmap) return;
    if (wl->mmap_size) {
        if (munmap(wl->bitmap, wl->mmap_size) != 0) log_error("Failed to unmap window logo bitmap with error: %s", strerror(errno));
    } else free(wl->bitmap);
    wl->bitmap = NULL; wl->mmap_size = 0;
}

static void
free_window_logo(WindowLogoItem **itemref) {
    WindowLogoItem *item = *itemref;
    free(item->path);
    free_window_logo_bitmap(&item->wl);
    if (item->wl.texture_id) free_texture(&item->wl.texture_id);
    free(item); itemref = NULL;
}

static void
send_logo_to_gpu(WindowLogo *s) {
    size_t off = s->mmap_size ? s->mmap_size - ((size_t)4) * s->width * s->height : 0;
    send_image_to_gpu(&s->texture_id, s->bitmap + off, s->width, s->height, false, true, true, REPEAT_CLAMP);
    free_window_logo_bitmap(s);
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
    hash_by_path_itr n = vt_get(&head->by_path, path);
    if (!vt_is_end(n)) { n.data->val->refcnt++; return n.data->val->id; }
    WindowLogoItem *s = calloc(1, sizeof *s);
    if (!s) { PyErr_NoMemory(); return 0; }
    s->path = strdup(path);
    if (!s->path) { free(s); PyErr_NoMemory(); return 0; }
    size_t size;
    bool ok = false;
    if (png_data == NULL || !png_data_size) {
        ok = image_path_to_bitmap(path, &s->wl.bitmap, &s->wl.width, &s->wl.height, &s->wl.mmap_size);
    } else {
        ok = png_from_data(png_data, png_data_size, path, &s->wl.bitmap, &s->wl.width, &s->wl.height, &size);
    }
    if (ok) s->wl.load_from_disk_ok = true;
    s->refcnt++;
    static window_logo_id_t idc = 0;
    s->id = ++idc;
    if (vt_is_end(vt_insert(&head->by_path, s->path, s))) { free_window_logo(&s); PyErr_NoMemory(); return 0; }
    if (vt_is_end(vt_insert(&head->by_id, s->id, s))) { vt_erase(&head->by_path, s->path); free_window_logo(&s); PyErr_NoMemory(); return 0; }
    return s->id;
}

WindowLogo*
find_window_logo(WindowLogoTable *table, window_logo_id_t id) {
    hash_by_id_itr n = vt_get(&table->by_id, id);
    if (vt_is_end(n)) return NULL;
    return &n.data->val->wl;
}

void
decref_window_logo(WindowLogoTable *table, window_logo_id_t id) {
    hash_by_id_itr n = vt_get(&table->by_id, id);
    if (!vt_is_end(n)) {
        WindowLogoItem *s = n.data->val;
        if (s->refcnt < 2) {
            vt_erase(&table->by_id, s->id); vt_erase(&table->by_path, s->path);
            free_window_logo(&s);
        }
        else s->refcnt--;
    }
}

WindowLogoTable*
alloc_window_logo_table(void) {
    WindowLogoTable *ans = calloc(1, sizeof(WindowLogoTable));
    if (ans) { vt_init(&ans->by_path); vt_init(&ans->by_id); }
    return ans;
}

void
free_window_logo_table(WindowLogoTable **table) {
    id_for_loop(*table) free_window_logo(&itr.data->val);
    vt_cleanup(&(*table)->by_id); vt_cleanup(&(*table)->by_path);
    free(*table); *table = NULL;
}
