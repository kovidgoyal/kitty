/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "internal.h"

void free_all_csd_resources(_GLFWwindow *window);
void free_csd_surfaces(_GLFWwindow *window);
void resize_csd(_GLFWwindow *window);
void change_csd_title(_GLFWwindow *window);
bool ensure_csd_resources(_GLFWwindow *window);
