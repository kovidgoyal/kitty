/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include <wayland-client.h>

void _glfwWaylandBindTextInput(struct wl_registry* registry, uint32_t name);
void _glfwWaylandInitTextInput(void);
void _glfwWaylandDestroyTextInput(void);
