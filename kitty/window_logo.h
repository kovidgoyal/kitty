/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>

typedef unsigned int window_logo_id_t;

typedef struct WindowLogo {
    unsigned int height, width;
    bool load_from_disk_ok;
    uint32_t texture_id;
    uint8_t* bitmap;
    size_t mmap_size;
} WindowLogo;

typedef struct WindowLogoTable WindowLogoTable;

window_logo_id_t
find_or_create_window_logo(WindowLogoTable *table, const char *path, void *png_data, size_t png_data_size);

WindowLogo*
find_window_logo(WindowLogoTable *table, window_logo_id_t id);

void
decref_window_logo(WindowLogoTable *table, window_logo_id_t id);

void
set_on_gpu_state(WindowLogo *logo, bool on_gpu);

WindowLogoTable*
alloc_window_logo_table(void);

void
free_window_logo_table(WindowLogoTable **table);
