/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"

typedef struct {
    double visual_bell_duration;
    bool enable_audio_bell;
} Options;

typedef struct {
    ssize_t vao_idx;
    float xstart, ystart, dx, dy;
    Screen *screen;
} ScreenRenderData;

typedef struct {
    unsigned int id;
    bool visible;
    ScreenRenderData render_data;
} Window;

typedef struct {
    unsigned int id, active_window, num_windows;
    Window windows[MAX_CHILDREN];
} Tab;

typedef struct {
    Options opts;

    Tab tabs[MAX_CHILDREN];
    unsigned int active_tab, num_tabs;
    ScreenRenderData tab_bar_render_data;
    bool application_focused;
} GlobalState;

typedef void (*draw_borders_func)();
extern draw_borders_func draw_borders;
typedef void (*draw_cells_func)(ssize_t, float, float, float, float, Screen *);
extern draw_cells_func draw_cells;
