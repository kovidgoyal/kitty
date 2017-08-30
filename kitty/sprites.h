/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

typedef struct SpritePosition SpritePosition;
struct SpritePosition {
    SpritePosition *next;
    sprite_index x, y, z;
    char_type ch;
    combining_type cc;
    bool is_second;
    bool filled;
    bool rendered;
};


PyObject* sprite_map_set_limits(PyObject UNUSED *self, PyObject *args);
PyObject* sprite_map_set_layout(PyObject UNUSED *s, PyObject *args);
PyObject* sprite_map_current_layout(PyObject UNUSED *s);
PyObject* sprite_map_free();
PyObject* sprite_map_increment();
SpritePosition* sprite_map_position_for(char_type ch, combining_type cc, bool is_second, int *error);
PyObject* sprite_position_for(PyObject UNUSED *self, PyObject *args);
bool update_cell_range_data(ScreenModes *modes, Line *line, unsigned int xstart, unsigned int xmax, unsigned int *data);
PyObject* render_dirty_sprites(PyObject UNUSED *self, PyObject *args);

#define SPRITE_FUNC_WRAPPERS \
    {"sprite_map_set_limits", (PyCFunction)sprite_map_set_limits, METH_VARARGS, ""}, \
    {"sprite_map_set_layout", (PyCFunction)sprite_map_set_layout, METH_VARARGS, ""}, \
    {"sprite_map_current_layout", (PyCFunction)sprite_map_current_layout, METH_NOARGS, ""}, \
    {"sprite_map_free", (PyCFunction)sprite_map_free, METH_NOARGS, ""}, \
    {"sprite_map_increment", (PyCFunction)sprite_map_increment, METH_NOARGS, ""}, \
    {"sprite_position_for", (PyCFunction)sprite_position_for, METH_VARARGS, ""}, \
    {"render_dirty_sprites", (PyCFunction)render_dirty_sprites, METH_VARARGS, ""}, \

