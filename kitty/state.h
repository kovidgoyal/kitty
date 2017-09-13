/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"

#define OPT(name) global_state.opts.name

typedef struct {
    double visual_bell_duration, cursor_blink_interval, cursor_stop_blinking_after, mouse_hide_wait;
    bool enable_audio_bell;
    CursorShape cursor_shape;
    double cursor_opacity;
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
    bool application_focused, mouse_visible;
    double cursor_blink_zero_time, last_mouse_activity_at;
    double logical_dpi_x, logical_dpi_y;
    int viewport_width, viewport_height;
} GlobalState;

#define EXTERNAL_FUNC(name, ret, ...) typedef ret (*name##_func)(__VA_ARGS__); extern name##_func name
#define EXTERNAL_FUNC0(name, ret) typedef ret (*name##_func)(); extern name##_func name
EXTERNAL_FUNC0(draw_borders, void);
EXTERNAL_FUNC(draw_cells, void, ssize_t, float, float, float, float, Screen *);
EXTERNAL_FUNC(draw_cursor, void, bool, bool, color_type, float, float, float, float, float);
EXTERNAL_FUNC(update_viewport_size, void, int, int);
