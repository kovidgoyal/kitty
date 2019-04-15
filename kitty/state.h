/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"
#include "screen.h"

#define OPT(name) global_state.opts.name

typedef enum { LEFT_EDGE, TOP_EDGE, RIGHT_EDGE, BOTTOM_EDGE } Edge;

typedef struct {
    double visual_bell_duration, cursor_blink_interval, cursor_stop_blinking_after, mouse_hide_wait, click_interval, wheel_scroll_multiplier, touch_scroll_multiplier;
    bool enable_audio_bell;
    CursorShape cursor_shape;
    unsigned int open_url_modifiers;
    unsigned int rectangle_select_modifiers;
    unsigned int url_style;
    unsigned int scrollback_pager_history_size;
    char_type select_by_word_characters[256]; size_t select_by_word_characters_count;
    color_type url_color, background, foreground, active_border_color, inactive_border_color, bell_border_color;
    double repaint_delay, input_delay;
    bool focus_follows_mouse, hide_window_decorations;
    bool macos_hide_from_tasks, macos_quit_when_last_window_closed, macos_window_resizable, macos_traditional_fullscreen, macos_show_window_title_in_menubar;
    unsigned int macos_option_as_alt;
    float macos_thicken_font;
    int adjust_line_height_px, adjust_column_width_px;
    float adjust_line_height_frac, adjust_column_width_frac;
    float background_opacity, dim_opacity;
    bool dynamic_background_opacity;
    float inactive_text_alpha;
    float window_padding_width;
    Edge tab_bar_edge;
    unsigned long tab_bar_min_tabs;
    bool disable_ligatures_under_cursor;
    bool sync_to_monitor;
    bool close_on_child_death;
    bool window_alert_on_bell;
    bool debug_keyboard;
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
    double x, y;
} Click;

#define CLICK_QUEUE_SZ 3
typedef struct {
    Click clicks[CLICK_QUEUE_SZ];
    unsigned int length;
} ClickQueue;

typedef struct {
    id_type id;
    bool visible, cursor_visible_at_last_render;
    unsigned int last_cursor_x, last_cursor_y;
    CursorShape last_cursor_shape;
    PyObject *title;
    ScreenRenderData render_data;
    struct {
        unsigned int cell_x, cell_y;
        double x, y;
    } mouse_pos;
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

enum RENDER_STATE { RENDER_FRAME_NOT_REQUESTED, RENDER_FRAME_REQUESTED, RENDER_FRAME_READY };

typedef struct {
    double last_resize_event_at;
    bool in_progress;
    bool from_os_notification;
    bool os_says_resize_complete;
    unsigned int width, height;
} LiveResizeInfo;


typedef struct {
    void *handle;
    id_type id;
    OSWindowGeometry before_fullscreen;
    int viewport_width, viewport_height, window_width, window_height;
    double viewport_x_ratio, viewport_y_ratio;
    Tab *tabs;
    unsigned int active_tab, num_tabs, capacity, last_active_tab, last_num_tabs, last_active_window_id;
    bool focused_at_last_render, needs_render;
    ScreenRenderData tab_bar_render_data;
    bool tab_bar_data_updated;
    bool is_focused;
    double cursor_blink_zero_time, last_mouse_activity_at;
    double mouse_x, mouse_y;
    double logical_dpi_x, logical_dpi_y, font_sz_in_pts;
    bool mouse_button_pressed[20];
    PyObject *window_title;
    bool is_key_pressed[MAX_KEY_COUNT];
    bool viewport_size_dirty;
    LiveResizeInfo live_resize;
    bool has_pending_resizes, is_semi_transparent, shown_once, is_damaged;
    uint32_t offscreen_texture_id;
    unsigned int clear_count;
    color_type last_titlebar_color;
    float background_opacity;
    FONTS_DATA_HANDLE fonts_data;
    id_type temp_font_group_id;
    double pending_scroll_pixels;
    enum RENDER_STATE render_state;
    id_type last_focused_counter;
    ssize_t gvao_idx;
} OSWindow;


typedef struct {
    Options opts;

    id_type os_window_id_counter, tab_id_counter, window_id_counter;
    PyObject *boss;
    OSWindow *os_windows;
    size_t num_os_windows, capacity;
    OSWindow *callback_os_window;
    bool terminate;
    bool is_wayland;
    bool has_render_frames;
    bool debug_gl, debug_font_fallback;
    bool has_pending_resizes, has_pending_closes;
    bool in_sequence_mode;
    bool tab_bar_hidden;
    double font_sz_in_pts;
    struct { double x, y; } default_dpi;
    id_type active_drag_in_window;
} GlobalState;

extern GlobalState global_state;

#define call_boss(name, ...) if (global_state.boss) { \
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
void swap_window_buffers(OSWindow *w);
void make_window_context_current(OSWindow *w);
void hide_mouse(OSWindow *w);
bool is_mouse_hidden(OSWindow *w);
void destroy_os_window(OSWindow *w);
void focus_os_window(OSWindow *w, bool also_raise);
void set_os_window_title(OSWindow *w, const char *title);
OSWindow* os_window_for_kitty_window(id_type);
OSWindow* add_os_window();
OSWindow* current_os_window();
void os_window_regions(OSWindow*, Region *main, Region *tab_bar);
bool drag_scroll(Window *, OSWindow*);
void draw_borders(ssize_t vao_idx, unsigned int num_border_rects, BorderRect *rect_buf, bool rect_data_is_dirty, uint32_t viewport_width, uint32_t viewport_height, color_type, unsigned int, OSWindow *w);
ssize_t create_cell_vao();
ssize_t create_graphics_vao();
ssize_t create_border_vao();
bool send_cell_data_to_gpu(ssize_t, ssize_t, float, float, float, float, Screen *, OSWindow *);
void draw_cells(ssize_t, ssize_t, float, float, float, float, Screen *, OSWindow *, bool, bool);
void draw_centered_alpha_mask(ssize_t gvao_idx, size_t screen_width, size_t screen_height, size_t width, size_t height, uint8_t *canvas);
void update_surface_size(int, int, uint32_t);
void free_texture(uint32_t*);
void send_image_to_gpu(uint32_t*, const void*, int32_t, int32_t, bool, bool);
void send_sprite_to_gpu(FONTS_DATA_HANDLE fg, unsigned int, unsigned int, unsigned int, pixel*);
void blank_canvas(float);
void blank_os_window(OSWindow *);
void set_titlebar_color(OSWindow *w, color_type color);
FONTS_DATA_HANDLE load_fonts_data(double, double, double);
void send_prerendered_sprites_for_window(OSWindow *w);
#ifdef __APPLE__
void get_cocoa_key_equivalent(int, int, unsigned short*, int*);
typedef enum {
    PREFERENCES_WINDOW = 1,
    NEW_OS_WINDOW = 2,
    NEW_OS_WINDOW_WITH_WD = 4,
    NEW_TAB_WITH_WD = 8
} CocoaPendingAction;
void set_cocoa_pending_action(CocoaPendingAction action, const char*);
bool application_quit_requested();
void request_application_quit();
#endif
void request_frame_render(OSWindow *w);
typedef void (* timer_callback_fun)(id_type, void*);
typedef void (* tick_callback_fun)(void*);
id_type add_main_loop_timer(double interval, bool repeats, timer_callback_fun callback, void *callback_data, timer_callback_fun free_callback);
void remove_main_loop_timer(id_type timer_id);
void update_main_loop_timer(id_type timer_id, double interval, bool enabled);
void run_main_loop(tick_callback_fun, void*);
void request_tick_callback(void);
void stop_main_loop(void);
