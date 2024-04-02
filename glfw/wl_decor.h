/*
 * wl_decor.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <wayland-client.h>

typedef struct {int x;} *DECOR_LIB_HANDLE;
DECOR_LIB_HANDLE glfw_wl_load_decorations_library(struct wl_display*);
void glfw_wl_unload_decorations_library(DECOR_LIB_HANDLE);
int glfw_wl_dispatch_decor_events(void);
