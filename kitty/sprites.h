/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once


void sprite_map_current_layout(unsigned int *x, unsigned int *y, unsigned int*);
void sprite_map_set_layout(unsigned int cell_width, unsigned int cell_height);
void sprite_map_set_limits(size_t max_texture_size, size_t max_array_len);
void sprite_map_free();
int sprite_map_increment(sprite_index *x, sprite_index *y, sprite_index *z);
void render_dirty_sprites(void (*render)(PyObject*, bool, bool, bool, sprite_index, sprite_index, sprite_index));
