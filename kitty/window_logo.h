/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "kitty-uthash.h"

#define WindowLogoHead \
    unsigned int height, width; \
    bool load_from_disk_ok; \
    uint32_t texture_id; \
    uint8_t* bitmap;


typedef struct WindowLogo {
    WindowLogoHead
} WindowLogo;

WindowLogo*
find_or_create_window_logo(WindowLogo **head, const char *path);

void
decref_window_logo(WindowLogo **head, WindowLogo** logo);

void
set_on_gpu_state(WindowLogo *logo, bool on_gpu);
