/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"
#include "screen.h"

#define OPT(name) global_state.opts.name

typedef struct {
    double visual_bell_duration, cursor_blink_interval, cursor_stop_blinking_after, mouse_hide_wait, click_interval, wheel_scroll_multiplier;
    bool enable_audio_bell;
    CursorShape cursor_shape;
    unsigned int open_url_modifiers;
    unsigned int url_style;
    char_type select_by_word_characters[256]; size_t select_by_word_characters_count;
    color_type url_color, background;
    double repaint_delay, input_delay;
    bool focus_follows_mouse;
    bool macos_option_as_alt, macos_hide_titlebar;
    int adjust_line_height_px;
    int x11_bell_volume;
    float adjust_line_height_frac;
    float background_opacity;
} Options;

typedef struct {
    ssize_t vao_idx, gvao_idx;
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
    id_type id;
    bool visible;
    PyObject *title;
    ScreenRenderData render_data;
    unsigned int mouse_cell_x, mouse_cell_y;
    WindowGeometry geometry;
    ClickQueue click_queue;
    double last_drag_scroll_at;
} Window;

typedef struct {
    uint32_t left, top, right, bottom, color;
} BorderRect;

typedef struct {
    BorderRect *rect_buf;
    unsigned int num_border_rects, capacity;
    bool is_dirty;
    ssize_t vao_idx;
} BorderRects;

typedef struct {
    id_type id;
    unsigned int active_window, num_windows, capacity;
    Window *windows;
    BorderRects border_rects;
} Tab;

#define MAX_KEY_COUNT 512

typedef struct {
    int x, y, w, h;
    bool is_set;
} OSWindowGeometry;


typedef struct {
    void *handle;
    id_type id;
    OSWindowGeometry before_fullscreen;
    int viewport_width, viewport_height;
    double viewport_x_ratio, viewport_y_ratio;
    Tab *tabs;
    unsigned int active_tab, num_tabs, capacity, last_active_tab, last_num_tabs, last_active_window_id;
    ScreenRenderData tab_bar_render_data;
    bool is_focused;
    double cursor_blink_zero_time, last_mouse_activity_at;
    double mouse_x, mouse_y;
    bool mouse_button_pressed[20];
    PyObject *window_title;
    bool is_key_pressed[MAX_KEY_COUNT];
    bool viewport_size_dirty;
    double last_resize_at;
    bool has_pending_resizes;
    bool is_semi_transparent;
    uint32_t offscreen_texture_id;
    unsigned int clear_count;
} OSWindow;


typedef struct {
    Options opts;

    double logical_dpi_x, logical_dpi_y;
    id_type os_window_id_counter, tab_id_counter, window_id_counter;
    float font_sz_in_pts;
    unsigned int cell_width, cell_height;
    PyObject *boss;
    OSWindow *os_windows;
    size_t num_os_windows, capacity;
    OSWindow *callback_os_window;
    bool close_all_windows;
    bool is_wayland;
    bool debug_gl;
    bool has_pending_resizes;
} GlobalState;

extern GlobalState global_state;

#define call_boss(name, ...) { \
    PyObject *cret_ = PyObject_CallMethod(global_state.boss, #name, __VA_ARGS__); \
    if (cret_ == NULL) { PyErr_Print(); } \
    else Py_DECREF(cret_); \
}

#define RESIZE_DEBOUNCE_TIME 0.2

void gl_init();
void remove_vao(ssize_t vao_idx);
bool remove_os_window(id_type os_window_id);
void make_os_window_context_current(OSWindow *w);
void update_os_window_references();
void mark_os_window_for_close(OSWindow* w, bool yes);
void update_os_window_viewport(OSWindow *window, bool);
bool should_os_window_close(OSWindow* w);
bool should_os_window_be_rendered(OSWindow* w);
void wakeup_main_loop();
void event_loop_wait(double timeout);
void swap_window_buffers(OSWindow *w);
void make_window_context_current(OSWindow *w);
void hide_mouse(OSWindow *w);
void destroy_os_window(OSWindow *w);
void set_os_window_title(OSWindow *w, const char *title);
OSWindow* os_window_for_kitty_window(id_type);
OSWindow* add_os_window();
OSWindow* current_os_window();
bool drag_scroll(Window *, OSWindow*);
void draw_borders(ssize_t vao_idx, unsigned int num_border_rects, BorderRect *rect_buf, bool rect_data_is_dirty, uint32_t viewport_width, uint32_t viewport_height);
ssize_t create_cell_vao();
ssize_t create_graphics_vao();
ssize_t create_border_vao();
void draw_cells(ssize_t, ssize_t, float, float, float, float, Screen *, OSWindow *);
void draw_cursor(CursorRenderInfo *, bool);
void update_surface_size(int, int, uint32_t);
void free_texture(uint32_t*);
void send_image_to_gpu(uint32_t*, const void*, int32_t, int32_t, bool, bool);
void send_sprite_to_gpu(unsigned int, unsigned int, unsigned int, pixel*);
