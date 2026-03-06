/*
 * dnd.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */
#pragma once

#include "state.h"

void drop_move_on_child(Window *w, const char **mimes, size_t num_mimes);
void drop_left_child(Window *w);
void drop_free_data(Window *w);
