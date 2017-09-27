/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"

#define OPT(name) global_state.opts.name

typedef struct {
    double visual_bell_duration, cursor_blink_interval, cursor_stop_blinking_after, mouse_hide_wait, click_interval, wheel_scroll_multiplier;
    bool enable_audio_bell;
    CursorShape cursor_shape;
    unsigned int open_url_modifiers;
    char_type select_by_word_characters[256]; size_t select_by_word_characters_count;
    color_type url_color;
    double repaint_delay, input_delay;
} Options;

typedef struct {
    ssize_t vao_idx;
    float xstart, ystart, dx, dy;
    Screen *screen;
} ScreenRenderData;

typedef struct {
    unsigned int left, top, right, bottom;
} WindowGeometry;

typedef struct {
    double at;
    int button, modifiers;
} Click;

#define CLICK_QUEUE_SZ 3
typedef struct {
    Click clicks[CLICK_QUEUE_SZ];
    unsigned int length;
} ClickQueue;

typedef struct {
    unsigned int id;
    bool visible;
    PyObject *title;
    ScreenRenderData render_data;
    unsigned int mouse_cell_x, mouse_cell_y;
    WindowGeometry geometry;
    ClickQueue click_queue;
    double last_drag_scroll_at;
} Window;

typedef struct {
    unsigned int id, active_window, num_windows;
    Window windows[MAX_CHILDREN];
} Tab;

#define MAX_KEY_COUNT 512

typedef struct {
    Options opts;

    Tab tabs[MAX_CHILDREN];
    unsigned int active_tab, num_tabs;
    ScreenRenderData tab_bar_render_data;
    bool application_focused;
    double cursor_blink_zero_time, last_mouse_activity_at;
    double logical_dpi_x, logical_dpi_y;
    double mouse_x, mouse_y;
    bool mouse_button_pressed[20];
    int viewport_width, viewport_height;
    double viewport_x_ratio, viewport_y_ratio;
    unsigned int cell_width, cell_height;
    PyObject *application_title;
    PyObject *boss;
    bool is_key_pressed[MAX_KEY_COUNT];
} GlobalState;

extern GlobalState global_state;

typedef struct {
    bool is_visible;
    CursorShape shape;
    double left, right, top, bottom;
    color_type color;
} CursorRenderInfo;

bool drag_scroll(Window *);

#define call_boss(name, ...) { \
    PyObject *cret_ = PyObject_CallMethod(global_state.boss, #name, __VA_ARGS__); \
    if (cret_ == NULL) { PyErr_Print(); } \
    else Py_DECREF(cret_); \
}

#define EXTERNAL_FUNC(name, ret, ...) typedef ret (*name##_func)(__VA_ARGS__); extern name##_func name
#define EXTERNAL_FUNC0(name, ret) typedef ret (*name##_func)(); extern name##_func name
EXTERNAL_FUNC0(draw_borders, void);
EXTERNAL_FUNC(draw_cells, void, ssize_t, float, float, float, float, Screen *, CursorRenderInfo *);
EXTERNAL_FUNC(draw_cursor, void, CursorRenderInfo *);
EXTERNAL_FUNC(update_viewport_size, void, int, int);
