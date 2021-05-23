/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"
#include "screen.h"
#include "monotonic.h"

#define OPT(name) global_state.opts.name

typedef enum { LEFT_EDGE, TOP_EDGE, RIGHT_EDGE, BOTTOM_EDGE } Edge;
typedef enum { RESIZE_DRAW_STATIC, RESIZE_DRAW_SCALED, RESIZE_DRAW_BLANK, RESIZE_DRAW_SIZE } ResizeDrawStrategy;
typedef enum { REPEAT_MIRROR, REPEAT_CLAMP, REPEAT_DEFAULT } RepeatStrategy;

typedef struct {
    char_type string[16];
    size_t len;
} UrlPrefix;

typedef struct {
    monotonic_t visual_bell_duration, cursor_blink_interval, cursor_stop_blinking_after, mouse_hide_wait, click_interval;
    double wheel_scroll_multiplier, touch_scroll_multiplier;
    bool enable_audio_bell;
    CursorShape cursor_shape;
    float cursor_beam_thickness;
    float cursor_underline_thickness;
    unsigned int url_style;
    unsigned int scrollback_pager_history_size;
    bool scrollback_fill_enlarged_window;
    char_type select_by_word_characters[256]; size_t select_by_word_characters_count;
    color_type url_color, background, foreground, active_border_color, inactive_border_color, bell_border_color;
    color_type mark1_foreground, mark1_background, mark2_foreground, mark2_background, mark3_foreground, mark3_background;
    monotonic_t repaint_delay, input_delay;
    bool focus_follows_mouse;
    unsigned int hide_window_decorations;
    bool macos_hide_from_tasks, macos_quit_when_last_window_closed, macos_window_resizable, macos_traditional_fullscreen;
    unsigned int macos_option_as_alt;
    float macos_thicken_font;
    WindowTitleIn macos_show_window_title_in;
    int adjust_line_height_px, adjust_column_width_px;
    float adjust_line_height_frac, adjust_column_width_frac;
    float background_opacity, dim_opacity;

    char* background_image;
    BackgroundImageLayout background_image_layout;
    bool background_image_linear;
    float background_tint;

    bool dynamic_background_opacity;
    float inactive_text_alpha;
    Edge tab_bar_edge;
    unsigned long tab_bar_min_tabs;
    DisableLigature disable_ligatures;
    bool force_ltr;
    ResizeDrawStrategy resize_draw_strategy;
    bool resize_in_steps;
    bool sync_to_monitor;
    bool close_on_child_death;
    bool window_alert_on_bell;
    bool debug_keyboard;
    bool allow_hyperlinks;
    monotonic_t resize_debounce_time;
    MouseShape pointer_shape_when_grabbed;
    MouseShape default_pointer_shape;
    MouseShape pointer_shape_when_dragging;
    struct {
        UrlPrefix *values;
        size_t num, max_prefix_len;
    } url_prefixes;
    bool detect_urls;
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
    monotonic_t at;
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
        bool in_left_half_of_cell;
    } mouse_pos;
    struct {
        unsigned int left, top, right, bottom;
    } padding;
    WindowGeometry geometry;
    ClickQueue click_queues[8];
    monotonic_t last_drag_scroll_at;
    uint32_t last_special_key_pressed;
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

typedef struct {
    int x, y, w, h;
    bool is_set;
} OSWindowGeometry;

enum RENDER_STATE { RENDER_FRAME_NOT_REQUESTED, RENDER_FRAME_REQUESTED, RENDER_FRAME_READY };
typedef enum { NO_CLOSE_REQUESTED, CONFIRMABLE_CLOSE_REQUESTED, CLOSE_BEING_CONFIRMED, IMPERATIVE_CLOSE_REQUESTED } CloseRequest;

typedef struct {
    monotonic_t last_resize_event_at;
    bool in_progress;
    bool from_os_notification;
    bool os_says_resize_complete;
    unsigned int width, height, num_of_resize_events;
} LiveResizeInfo;


typedef struct {
    void *handle;
    id_type id;
    uint32_t offscreen_framebuffer;
    OSWindowGeometry before_fullscreen;
    int viewport_width, viewport_height, window_width, window_height;
    double viewport_x_ratio, viewport_y_ratio;
    Tab *tabs;
    BackgroundImage *bgimage;
    unsigned int active_tab, num_tabs, capacity, last_active_tab, last_num_tabs, last_active_window_id;
    bool focused_at_last_render, needs_render;
    ScreenRenderData tab_bar_render_data;
    bool tab_bar_data_updated;
    bool is_focused;
    monotonic_t cursor_blink_zero_time, last_mouse_activity_at;
    double mouse_x, mouse_y;
    double logical_dpi_x, logical_dpi_y, font_sz_in_pts;
    bool mouse_button_pressed[32];
    PyObject *window_title;
    bool viewport_size_dirty, viewport_updated_at_least_once;
    LiveResizeInfo live_resize;
    bool has_pending_resizes, is_semi_transparent, shown_once, is_damaged;
    uint32_t offscreen_texture_id;
    unsigned int clear_count;
    color_type last_titlebar_color;
    float background_opacity;
    FONTS_DATA_HANDLE fonts_data;
    id_type temp_font_group_id;
    enum RENDER_STATE render_state;
    monotonic_t last_render_frame_received_at;
    uint64_t render_calls;
    id_type last_focused_counter;
    ssize_t gvao_idx;
    CloseRequest close_request;
} OSWindow;


typedef struct {
    Options opts;

    id_type os_window_id_counter, tab_id_counter, window_id_counter;
    PyObject *boss;
    BackgroundImage *bgimage;
    OSWindow *os_windows;
    size_t num_os_windows, capacity;
    OSWindow *callback_os_window;
    bool is_wayland;
    bool has_render_frames;
    bool debug_rendering, debug_font_fallback;
    bool has_pending_resizes, has_pending_closes;
    bool in_sequence_mode;
    bool tab_bar_hidden;
    bool check_for_active_animated_images;
    double font_sz_in_pts;
    struct { double x, y; } default_dpi;
    id_type active_drag_in_window;
    int active_drag_button;
    CloseRequest quit_request;
} GlobalState;

extern GlobalState global_state;

#define call_boss(name, ...) if (global_state.boss) { \
    PyObject *cret_ = PyObject_CallMethod(global_state.boss, #name, __VA_ARGS__); \
    if (cret_ == NULL) { PyErr_Print(); } \
    else Py_DECREF(cret_); \
}

void gl_init(void);
void remove_vao(ssize_t vao_idx);
bool remove_os_window(id_type os_window_id);
void make_os_window_context_current(OSWindow *w);
void update_os_window_references(void);
void mark_os_window_for_close(OSWindow* w, CloseRequest cr);
void update_os_window_viewport(OSWindow *window, bool);
bool should_os_window_be_rendered(OSWindow* w);
void wakeup_main_loop(void);
void swap_window_buffers(OSWindow *w);
bool make_window_context_current(id_type);
void hide_mouse(OSWindow *w);
bool is_mouse_hidden(OSWindow *w);
void destroy_os_window(OSWindow *w);
void focus_os_window(OSWindow *w, bool also_raise);
void set_os_window_title(OSWindow *w, const char *title);
OSWindow* os_window_for_kitty_window(id_type);
OSWindow* add_os_window(void);
OSWindow* current_os_window(void);
void os_window_regions(OSWindow*, Region *main, Region *tab_bar);
bool drag_scroll(Window *, OSWindow*);
void draw_borders(ssize_t vao_idx, unsigned int num_border_rects, BorderRect *rect_buf, bool rect_data_is_dirty, uint32_t viewport_width, uint32_t viewport_height, color_type, unsigned int, bool, OSWindow *w);
ssize_t create_cell_vao(void);
ssize_t create_graphics_vao(void);
ssize_t create_border_vao(void);
bool send_cell_data_to_gpu(ssize_t, ssize_t, float, float, float, float, Screen *, OSWindow *);
void draw_cells(ssize_t, ssize_t, float, float, float, float, Screen *, OSWindow *, bool, bool);
void draw_centered_alpha_mask(OSWindow *w, size_t screen_width, size_t screen_height, size_t width, size_t height, uint8_t *canvas);
void update_surface_size(int, int, uint32_t);
void free_texture(uint32_t*);
void free_framebuffer(uint32_t*);
void send_image_to_gpu(uint32_t*, const void*, int32_t, int32_t, bool, bool, bool, RepeatStrategy);
void send_sprite_to_gpu(FONTS_DATA_HANDLE fg, unsigned int, unsigned int, unsigned int, pixel*);
void blank_canvas(float, color_type);
void blank_os_window(OSWindow *);
void set_titlebar_color(OSWindow *w, color_type color, bool use_system_color);
FONTS_DATA_HANDLE load_fonts_data(double, double, double);
void send_prerendered_sprites_for_window(OSWindow *w);
#ifdef __APPLE__
void get_cocoa_key_equivalent(uint32_t, int, char *key, size_t key_sz, int*);
typedef enum {
    NO_COCOA_PENDING_ACTION = 0,
    PREFERENCES_WINDOW = 1,
    NEW_OS_WINDOW = 2,
    NEW_OS_WINDOW_WITH_WD = 4,
    NEW_TAB_WITH_WD = 8,
    CLOSE_OS_WINDOW = 16,
    CLOSE_TAB = 32,
    NEW_TAB = 64,
    NEXT_TAB = 128,
    PREVIOUS_TAB = 256,
    DETACH_TAB = 512,
    OPEN_FILE = 1024,
    NEW_WINDOW = 2048,
    CLOSE_WINDOW = 4096,
} CocoaPendingAction;
void set_cocoa_pending_action(CocoaPendingAction action, const char*);
#endif
void request_frame_render(OSWindow *w);
void request_tick_callback(void);
typedef void (* timer_callback_fun)(id_type, void*);
typedef void (* tick_callback_fun)(void*);
id_type add_main_loop_timer(monotonic_t interval, bool repeats, timer_callback_fun callback, void *callback_data, timer_callback_fun free_callback);
void remove_main_loop_timer(id_type timer_id);
void update_main_loop_timer(id_type timer_id, monotonic_t interval, bool enabled);
void run_main_loop(tick_callback_fun, void*);
void stop_main_loop(void);
void os_window_update_size_increments(OSWindow *window);
void set_os_window_title_from_window(Window *w, OSWindow *os_window);
void update_os_window_title(OSWindow *os_window);
void fake_scroll(Window *w, int amount, bool upwards);
Window* window_for_window_id(id_type kitty_window_id);
void mouse_open_url(Window *w);
void mouse_selection(Window *w, int code, int button);
const char* format_mods(unsigned mods);
void send_pending_click_to_window_id(id_type, void*);
void send_pending_click_to_window(Window*, void*);
