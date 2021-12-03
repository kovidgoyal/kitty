/*
 * window_logo.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "window_logo.h"
#include "state.h"


typedef struct WindowLogoItem {
    WindowLogoHead
    unsigned int refcnt;
    char *path;
    UT_hash_handle hh;
} WindowLogoItem;


static void
free_window_logo(WindowLogoItem **head, WindowLogoItem **itemref) {
    WindowLogoItem *item = *itemref;
    free(item->path);
    free(item->bitmap);
    if (item->texture_id) free_texture(&item->texture_id);
    HASH_DEL(*head, item);
    free(item); itemref = NULL;
}

static void
send_logo_to_gpu(WindowLogoItem *s) {
    send_image_to_gpu(&s->texture_id, s->bitmap, s->width, s->height, false, true, true, REPEAT_CLAMP);
}


void
set_on_gpu_state(WindowLogo *x, bool on_gpu) {
    WindowLogoItem *s = (WindowLogoItem*)x;
    if (s->load_from_disk_ok) {
        if (on_gpu) { if (!s->texture_id) send_logo_to_gpu(s); }
        else if (s->texture_id) free_texture(&s->texture_id);
    }
}

WindowLogo*
find_or_create_window_logo(WindowLogo **head_, const char *path) {
    WindowLogoItem **head = (WindowLogoItem**)head_;
    WindowLogoItem *s = NULL;
    HASH_FIND_STR(*head, path, s);
    if (s) return (WindowLogo*)s;
    s = calloc(1, sizeof *s);
    size_t size;
    if (!s) { PyErr_NoMemory(); return NULL; }
    s->path = strdup(path);
    if (!s->path) { free(s->bitmap); free(s); PyErr_NoMemory(); return NULL; }
    if (png_path_to_bitmap(path, &s->bitmap, &s->width, &s->height, &size)) s->load_from_disk_ok = true;
    s->refcnt++;
    HASH_ADD_KEYPTR(hh, *head, s->path, strlen(s->path), s);
    return (WindowLogo*)s;
}

void
decref_window_logo(WindowLogo **head_, WindowLogo** logo) {
    WindowLogoItem **head = (WindowLogoItem**)head_;
    WindowLogoItem **s = (WindowLogoItem**)logo;
    if (*s) { if ((*s)->refcnt < 2) free_window_logo(head, s); else (*s)->refcnt--; }
}
