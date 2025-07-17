/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "internal.h"

void csd_initialize_metrics(_GLFWwindow *window);
void csd_free_all_resources(_GLFWwindow *window);
bool csd_change_title(_GLFWwindow *window);
void csd_set_window_geometry(_GLFWwindow *window, int32_t *width, int32_t *height);
bool csd_set_titlebar_color(_GLFWwindow *window, uint32_t color, bool use_system_color);
bool csd_should_window_be_decorated(_GLFWwindow *window);
void csd_set_visible(_GLFWwindow *window, bool visible);
void csd_handle_pointer_event(_GLFWwindow *window, int button, int state, struct wl_surface* surface);
