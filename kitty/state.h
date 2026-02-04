/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once
#include "data-types.h"
#include "animation.h"
#include "screen.h"
#include "monotonic.h"
#include "window_logo.h"
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#include <hb.h>
#pragma GCC diagnostic pop

#define OPT(name) global_state.opts.name
#define debug_rendering(...) if (global_state.debug_rendering) { timed_debug_print(__VA_ARGS__); }
#define debug_input(...) if (OPT(debug_keyboard)) { timed_debug_print(__VA_ARGS__); }
#define debug_fonts(...) if (global_state.debug_font_fallback) { timed_debug_print(__VA_ARGS__); }

typedef enum { LEFT_EDGE = 1, TOP_EDGE = 2, RIGHT_EDGE = 4, BOTTOM_EDGE = 8 } Edge;
typedef enum { REPEAT_MIRROR, REPEAT_CLAMP, REPEAT_DEFAULT } RepeatStrategy;
typedef enum { WINDOW_NORMAL, WINDOW_FULLSCREEN, WINDOW_MAXIMIZED, WINDOW_MINIMIZED, WINDOW_HIDDEN } WindowState;

typedef struct UrlPrefix {
    char_type string[16];
    size_t len;
} UrlPrefix;

typedef enum AdjustmentUnit { POINT = 0, PERCENT = 1, PIXEL = 2 } AdjustmentUnit;
typedef enum UnderlineHyperlinks { UNDERLINE_ON_HOVER = 0, UNDERLINE_ALWAYS = 1, UNDERLINE_NEVER = 2 } UnderlineHyperlinks;

struct MenuItem {
    const char* *location;
    size_t location_count;
    const char *definition;
};

typedef struct Options {
    monotonic_t visual_bell_duration, cursor_blink_interval, cursor_stop_blinking_after, click_interval;
    struct {
        monotonic_t hide_wait, unhide_wait;
        int unhide_threshold;
        bool scroll_unhide;
    } mouse_hide;
    double wheel_scroll_multiplier, touch_scroll_multiplier;
    int wheel_scroll_min_lines;
    bool pixel_scroll;
    bool enable_audio_bell;
    CursorShape cursor_shape, cursor_shape_unfocused;
    float cursor_beam_thickness;
    float cursor_underline_thickness;
    monotonic_t cursor_trail;
    float cursor_trail_decay_fast;
    float cursor_trail_decay_slow;
    color_type cursor_trail_color;
    float cursor_trail_start_threshold;
    unsigned int url_style;
    unsigned int scrollback_pager_history_size;
    bool scrollback_fill_enlarged_window;
    char_type *select_by_word_characters;
    char_type *select_by_word_characters_forward;
    color_type url_color, background, foreground, active_border_color, inactive_border_color, bell_border_color, tab_bar_background, tab_bar_margin_color;
    monotonic_t repaint_delay, input_delay;
    bool focus_follows_mouse;
    unsigned int hide_window_decorations;
    bool macos_hide_from_tasks, macos_quit_when_last_window_closed, macos_window_resizable, macos_traditional_fullscreen;
    unsigned int macos_option_as_alt;
    float macos_thicken_font;
    WindowTitleIn macos_show_window_title_in;
    char *bell_path, *bell_theme;
    float background_opacity, dim_opacity;

    ScrollbarVisibilityPolicy scrollbar;
    bool scrollbar_interactive, scrollbar_jump_on_click;
    float scrollbar_width, scrollbar_radius, scrollbar_gap, scrollbar_min_handle_height, scrollbar_hitbox_expansion;
    float scrollbar_hover_width, scrollbar_handle_opacity, scrollbar_track_opacity, scrollbar_track_hover_opacity;
    color_type scrollbar_handle_color, scrollbar_track_color;

    float text_contrast, text_gamma_adjustment;
    bool text_old_gamma;

    char *background_image, *default_window_logo;
    BackgroundImageLayout background_image_layout;
    ImageAnchorPosition window_logo_position;
    bool background_image_linear;
    float background_tint, background_tint_gaps, window_logo_alpha;
    struct { float width, height; } window_logo_scale;

    bool dynamic_background_opacity;
    float inactive_text_alpha;
    Edge tab_bar_edge;
    DisableLigature disable_ligatures;
    bool force_ltr;
    bool resize_in_steps;
    bool sync_to_monitor;
    bool close_on_child_death;
    bool window_alert_on_bell;
    bool debug_keyboard;
    bool allow_hyperlinks;
    struct { monotonic_t on_end, on_pause; } resize_debounce_time;
    MouseShape pointer_shape_when_grabbed;
    MouseShape default_pointer_shape;
    MouseShape pointer_shape_when_dragging, pointer_shape_when_dragging_rectangle;
    struct {
        UrlPrefix *values;
        size_t num, max_prefix_len;
    } url_prefixes;
    char_type *url_excluded_characters;
    bool detect_urls;
    bool tab_bar_hidden;
    double font_size;
    struct {
        double outer, inner;
    } tab_bar_margin_height;
    long macos_menubar_title_max_length;
    int macos_colorspace;
    struct {
        float val; AdjustmentUnit unit;
    } underline_position, underline_thickness, strikethrough_position, strikethrough_thickness, cell_width, cell_height, baseline;
    bool show_hyperlink_targets;
    UnderlineHyperlinks underline_hyperlinks;
    int background_blur;
    long macos_titlebar_color;
    unsigned long wayland_titlebar_color;
    struct { struct MenuItem *entries; size_t count; } global_menu;
    bool wayland_enable_ime;
    struct {
        size_t num;
        struct {
            const char *psname;
            size_t num;
            hb_feature_t *features;
        } *entries;
    } font_features;
    struct { Animation *cursor, *visual_bell; } animation;
    unsigned undercurl_style;
    struct { float thickness; int unit; } underline_exclusion;
    float box_drawing_scale[4];
    double momentum_scroll;
} Options;

typedef struct WindowLogoRenderData {
    window_logo_id_t id;
    WindowLogo *instance;
    ImageAnchorPosition position;
    float alpha;
    bool using_default;
} WindowLogoRenderData;

typedef struct {
    unsigned int left, top, right, bottom;
    struct {
        unsigned int left, top, right, bottom;
    } spaces;
} WindowGeometry;

typedef struct WindowRenderData {
    ssize_t vao_idx;
    WindowGeometry geometry;
    Screen *screen;
} WindowRenderData;

typedef struct Click {
    monotonic_t at;
    int button, modifiers;
    double x, y;
    unsigned long num;
} Click;

#define CLICK_QUEUE_SZ 3
typedef struct ClickQueue {
    Click clicks[CLICK_QUEUE_SZ];
    unsigned int length;
} ClickQueue;

typedef struct MousePosition {
    unsigned int cell_x, cell_y;
    double global_x, global_y;
    bool in_left_half_of_cell;
} MousePosition;

typedef struct PendingClick {
    id_type window_id;
    int button, count, modifiers;
    bool grabbed;
    monotonic_t at;
    MousePosition mouse_pos;
    unsigned long press_num;
    double radius_for_multiclick;
} PendingClick;


typedef struct WindowBarData {
    unsigned width, height;
    uint8_t *buf;
    PyObject *last_drawn_title_object_id;
    hyperlink_id_type hyperlink_id_for_title_object;
    bool needs_render;
} WindowBarData;

typedef struct Window {
    id_type id;
    bool visible;
    PyObject *title;
    WindowRenderData render_data;
    WindowLogoRenderData window_logo;
    MousePosition mouse_pos;
    struct {
        unsigned int left, top, right, bottom;
    } padding;
    ClickQueue click_queues[8];
    monotonic_t last_drag_scroll_at;
    uint32_t last_special_key_pressed;
    WindowBarData title_bar_data, url_target_bar_data;
    id_type redirect_keys_to_overlay;
    struct {
        bool enabled;
        void *key_data;
        size_t count, capacity;
    } buffered_keys;
    struct {
        PendingClick *clicks;
        size_t num, capacity;
    } pending_clicks;
    struct {
        double thumb_top, thumb_bottom;
        bool is_dragging;
        double drag_start_y;
        double drag_start_scrolled_by;
        bool is_hovering;
    } scrollbar;
} Window;

typedef struct BorderRect {
    float left, top, right, bottom;
    uint32_t color;
} BorderRect;

typedef struct BorderRects {
    BorderRect *rect_buf;
    unsigned int num_border_rects, capacity;
    bool is_dirty;
    ssize_t vao_idx;
} BorderRects;

typedef struct CursorTrail {
    bool needs_render;
    monotonic_t updated_at;
    float opacity;
    float corner_x[4];
    float corner_y[4];
    float cursor_edge_x[2];
    float cursor_edge_y[2];
} CursorTrail;

typedef struct Tab {
    id_type id;
    unsigned int active_window, num_windows, capacity;
    Window *windows;
    BorderRects border_rects;
    CursorTrail cursor_trail;
} Tab;

enum RENDER_STATE { RENDER_FRAME_NOT_REQUESTED, RENDER_FRAME_REQUESTED, RENDER_FRAME_READY };
typedef enum { NO_CLOSE_REQUESTED, CONFIRMABLE_CLOSE_REQUESTED, CLOSE_BEING_CONFIRMED, IMPERATIVE_CLOSE_REQUESTED } CloseRequest;

typedef struct LiveResizeInfo {
    monotonic_t last_resize_event_at;
    bool in_progress;
    bool from_os_notification;
    bool os_says_resize_complete;
    unsigned int width, height, num_of_resize_events;
} LiveResizeInfo;

typedef struct WindowChromeState {
    color_type color;
    bool use_system_color;
    unsigned system_color;
    int background_blur;
    unsigned hide_window_decorations;
    bool show_title_in_titlebar;
    bool resizable;
    int macos_colorspace;
    float background_opacity;
} WindowChromeState;

typedef struct BackgroundImageRenderSettings {
    struct { unsigned width, height; } os_window;
    unsigned instance_id;
    BackgroundImageLayout layout;
    bool linear; uint32_t bgcolor; float opacity;
} BackgroundImageRenderSettings;

typedef struct OSWindow {
    void *handle;
    id_type id;
    monotonic_t created_at;
    struct {
        int x, y, w, h;
        bool is_set, was_maximized;
    } before_fullscreen;
    int viewport_width, viewport_height, window_width, window_height;
    double viewport_x_ratio, viewport_y_ratio;
    Tab *tabs;
    BackgroundImage *bgimage;
    struct {
        uint32_t texture_id, framebuffer_id;
        int width, height;
    } indirect_output;
    unsigned int active_tab, num_tabs, capacity, last_active_tab, last_num_tabs, last_active_window_id;
    bool focused_at_last_render, needs_render, needs_layers;
    unsigned keep_rendering_till_swap;
    WindowRenderData tab_bar_render_data;
    struct {
        color_type left, right;
    } tab_bar_edge_color;
    bool tab_bar_data_updated;
    bool is_focused;
    monotonic_t cursor_blink_zero_time, last_mouse_activity_at, mouse_activate_deadline;
    int mouse_show_threshold;
    bool has_received_cursor_pos_event;
    double mouse_x, mouse_y;
    bool mouse_button_pressed[32];
    bool has_too_few_tabs;
    PyObject *window_title;
    bool disallow_title_changes, title_is_overriden;
    bool viewport_size_dirty, viewport_updated_at_least_once;
    monotonic_t viewport_resized_at;
    LiveResizeInfo live_resize;
    bool has_pending_resizes, shown_once, ignore_resize_events;
    unsigned int redraw_count;
    WindowChromeState last_window_chrome;
    struct { float alpha; bool os_forces_opaque, supports_transparency; } background_opacity;
    FONTS_DATA_HANDLE fonts_data;
    id_type temp_font_group_id;
    enum RENDER_STATE render_state;
    monotonic_t last_render_frame_received_at;
    uint64_t render_calls;
    id_type last_focused_counter;
    CloseRequest close_request;
    bool is_layer_shell, hide_on_focus_loss;
    struct { int x, y; } last_drag_event;
} OSWindow;

static inline float
effective_os_window_alpha(OSWindow *w) {
    return (!w->background_opacity.supports_transparency || w->background_opacity.os_forces_opaque) ?
        1.f : w->background_opacity.alpha;
}

typedef struct GlobalState {
    Options opts;

    id_type os_window_id_counter, tab_id_counter, window_id_counter;
    PyObject *boss;
    BackgroundImage *bgimage;
    OSWindow *os_windows;
    size_t num_os_windows, capacity;
    OSWindow *callback_os_window;
    bool is_wayland, is_apple;
    bool has_render_frames;
    bool debug_rendering, debug_font_fallback;
    bool has_pending_resizes, has_pending_closes;
    bool check_for_active_animated_images;
    struct { double x, y; } default_dpi;
    id_type active_drag_in_window, tracked_drag_in_window, mouse_hover_in_window;
    int active_drag_button, tracked_drag_button;
    CloseRequest quit_request;
    bool redirect_mouse_handling;
    WindowLogoTable *all_window_logos;
    int gl_version;
    bool supports_framebuffer_srgb;
    PyObject *options_object;
} GlobalState;

extern GlobalState global_state;

#define call_boss(name, ...) if (global_state.boss) { \
    PyObject *cret_ = PyObject_CallMethod(global_state.boss, #name, __VA_ARGS__); \
    if (cret_ == NULL) { PyErr_Print(); } \
    else Py_DECREF(cret_); \
}

static inline void
sprite_index_to_pos(unsigned idx, unsigned xnum, unsigned ynum, unsigned *x, unsigned *y, unsigned *z) {
    div_t r = div(idx & 0x7fffffff, ynum * xnum), r2 = div(r.rem, xnum);
    *z = r.quot; *y = r2.quot; *x = r2.rem;
}


void gl_init(void);
void remove_vao(ssize_t vao_idx);
bool remove_os_window(id_type os_window_id);
void* make_os_window_context_current(OSWindow *w);
void set_os_window_size(OSWindow *os_window, int x, int y);
void get_os_window_size(OSWindow *os_window, int *w, int *h, int *fw, int *fh);
void get_os_window_pos(OSWindow *os_window, int *x, int *y);
void set_os_window_pos(OSWindow *os_window, int x, int y);
void get_os_window_content_scale(OSWindow *os_window, double *xdpi, double *ydpi, float *xscale, float *yscale);
void update_os_window_references(void);
void mark_os_window_for_close(OSWindow* w, CloseRequest cr);
void update_os_window_viewport(OSWindow *window, bool notify_boss);
bool should_os_window_be_rendered(OSWindow* w);
void wakeup_main_loop(void);
bool make_window_context_current(id_type);
void hide_mouse(OSWindow *w);
bool is_mouse_hidden(OSWindow *w);
void destroy_os_window(OSWindow *w);
void focus_os_window(OSWindow *w, bool also_raise, const char *activation_token);
void run_with_activation_token_in_os_window(OSWindow *w, PyObject *callback);
void set_os_window_title(OSWindow *w, const char *title);
OSWindow* os_window_for_kitty_window(id_type);
OSWindow* os_window_for_id(id_type);
OSWindow* add_os_window(void);
OSWindow* current_os_window(void);
void os_window_regions(OSWindow*, Region *main, Region *tab_bar);
bool drag_scroll(Window *, OSWindow*);
void draw_borders(ssize_t vao_idx, unsigned int num_border_rects, BorderRect *rect_buf, bool rect_data_is_dirty, color_type, unsigned int, bool, OSWindow *w);
ssize_t create_cell_vao(void);
ssize_t create_graphics_vao(void);
ssize_t create_border_vao(void);
bool send_cell_data_to_gpu(ssize_t, Screen *, OSWindow *);
void draw_cells(const WindowRenderData*, OSWindow *, bool, bool, bool, Window*);
bool update_cursor_trail(CursorTrail *ct, Window *w, monotonic_t now, OSWindow *os_window);
void set_gpu_viewport(unsigned w, unsigned h);
void free_texture(uint32_t*);
void free_framebuffer(uint32_t*);
void send_image_to_gpu(uint32_t*, const void*, int32_t, int32_t, bool, bool, bool, RepeatStrategy);
void send_sprite_to_gpu(FONTS_DATA_HANDLE fg, sprite_index, pixel*, sprite_index);
void blank_canvas(float, color_type, bool);
void blank_os_window(OSWindow *);
void set_os_window_chrome(OSWindow *w);
FONTS_DATA_HANDLE load_fonts_data(double, double, double);
void send_prerendered_sprites_for_window(OSWindow *w);
#ifdef __APPLE__
#include "cocoa_window.h"
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
void on_os_window_font_size_change(OSWindow *window, double new_sz);
void set_os_window_title_from_window(Window *w, OSWindow *os_window);
void update_os_window_title(OSWindow *os_window);
void fake_scroll(Window *w, int amount, bool upwards);
Window* window_for_window_id(id_type kitty_window_id);
bool mouse_open_url(Window *w);
bool mouse_set_last_visited_cmd_output(Window *w);
bool mouse_select_cmd_output(Window *w);
bool move_cursor_to_mouse_if_at_shell_prompt(Window *w);
void mouse_selection(Window *w, int code, int button);
const char* format_mods(unsigned mods);
void dispatch_pending_clicks(id_type, void*);
void send_pending_click_to_window(Window*, int);
void get_platform_dependent_config_values(void *glfw_window);
bool draw_window_title(double, double, const char *text, color_type fg, color_type bg, uint8_t *output_buf, size_t width, size_t height);
uint8_t* draw_single_ascii_char(const char ch, size_t *result_width, size_t *result_height);
bool is_os_window_fullscreen(OSWindow *);
void update_ime_focus(OSWindow* osw, bool focused);
void update_ime_position(Window* w, Screen *screen);
bool update_ime_position_for_window(id_type window_id, bool force, int update_focus);
void set_ignore_os_keyboard_processing(bool enabled);
void update_menu_bar_title(PyObject *title UNUSED);
void change_live_resize_state(OSWindow*, bool);
bool render_os_window(OSWindow *w, monotonic_t now, bool scan_for_animated_images);
void update_mouse_pointer_shape(void);
void adjust_window_size_for_csd(OSWindow *w, int width, int height, int *adjusted_width, int *adjusted_height);
void dispatch_buffered_keys(Window *w);
bool screen_needs_rendering_in_layers(OSWindow *os_window, Window *w, Screen *screen);
void setup_os_window_for_rendering(OSWindow*, Tab*, Window*, bool);
void swap_window_buffers(OSWindow *w);
