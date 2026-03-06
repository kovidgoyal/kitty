/*
 * dnd.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */
#pragma once

#include "state.h"

void drop_move_on_child(Window *w, const char **mimes, size_t num_mimes, bool is_drop);
void drop_left_child(Window *w);
void drop_free_data(Window *w);
void drop_set_status(Window *w, int operation, const char *payload, size_t payload_sz, bool more);
size_t drop_update_mimes(Window *w, const char **allowed_mimes, size_t allowed_mimes_count);
