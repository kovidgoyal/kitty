/*
 * tracker.h
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

static inline void tracker_cursor_changed(ChangeTracker *self) {
    self->cursor_changed = true;
    self->dirty = true;
}

static inline void tracker_line_added_to_history(ChangeTracker *self) {
    self->history_line_added_count++;
    self->dirty = true;
}

static inline void tracker_update_screen(ChangeTracker *self) {
    self->screen_changed = true;
    self->dirty = true;
}

static inline void tracker_update_line_range(ChangeTracker *self, unsigned int first_line, unsigned int last_line) {
    if (!self->screen_changed) {
        for (unsigned int i = first_line; i <= MIN(self->ynum - 1, last_line); i++) self->changed_lines[i] = true;
        self->dirty = true;
    }
}

static inline void tracker_update_cell_range(ChangeTracker *self, unsigned int line, unsigned int first_cell, unsigned int last_cell) {
    if (!self->screen_changed && line < self->ynum && !self->changed_lines[line]) {
        self->lines_with_changed_cells[line] = true;
        unsigned int base = line * self->xnum;
        for (unsigned int i = first_cell; i <= MIN(self->xnum - 1, last_cell); i++) self->changed_cells[base + i] = true;
        self->dirty = true;
    }
}

#define RESET_STATE_VARS(self) \
    self->screen_changed = false; self->cursor_changed = false; self->dirty = false; self->history_line_added_count = 0; 

static inline void tracker_reset(ChangeTracker *self) {
    self->screen_changed = false; self->cursor_changed = false; self->dirty = false;
    self->history_line_added_count = 0;
    memset(self->changed_lines, 0, self->ynum * sizeof(bool));
    memset(self->changed_cells, 0, self->ynum * self->xnum * sizeof(bool));
    memset(self->lines_with_changed_cells, 0, self->ynum * sizeof(bool));
    RESET_STATE_VARS(self);
}

PyObject* tracker_consolidate_changes(ChangeTracker *self);
bool tracker_resize(ChangeTracker *self, unsigned int ynum, unsigned int xnum);
bool tracker_update_cell_data(ScreenModes*, ChangeTracker *, LineBuf *, SpriteMap *, ColorProfile *, unsigned int *, unsigned long, unsigned long, bool);
