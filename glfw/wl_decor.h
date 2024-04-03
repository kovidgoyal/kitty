/*
 * wl_decor.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <wayland-client.h>
#include <stdbool.h>
#include "internal.h"

DECOR_LIB_HANDLE glfw_wl_load_decorations_library(struct wl_display*);
void glfw_wl_unload_decorations_library(DECOR_LIB_HANDLE);
int glfw_wl_dispatch_decor_events(void);
void glfw_wl_set_fullscreen(_GLFWwindow *w, bool on, struct wl_output *monitor);
void glfw_wl_set_maximized(_GLFWwindow *w, bool on);
void glfw_wl_set_minimized(_GLFWwindow *w);
void glfw_wl_set_title(_GLFWwindow *w, const char *title);
void glfw_wl_set_app_id(_GLFWwindow *w, const char *appid);
void glfw_wl_set_size_limits(_GLFWwindow *w, int minwidth, int minheight, int maxwidth, int maxheight);
