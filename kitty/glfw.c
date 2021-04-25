/*
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "cleanup.h"
#include "fonts.h"
#include "monotonic.h"
#include "charsets.h"
#include <structmember.h>
#include "glfw-wrapper.h"
#ifndef __APPLE__
#include "freetype_render_ui_text.h"
#endif
extern bool cocoa_make_window_resizable(void *w, bool);
extern void cocoa_focus_window(void *w);
extern long cocoa_window_number(void *w);
extern void cocoa_create_global_menu(void);
extern void cocoa_hide_window_title(void *w);
extern void cocoa_system_beep(void);
extern void cocoa_set_activation_policy(bool);
extern void cocoa_set_titlebar_color(void *w, color_type color);
extern bool cocoa_alt_option_key_pressed(unsigned long);
extern size_t cocoa_get_workspace_ids(void *w, size_t *workspace_ids, size_t array_sz);
extern monotonic_t cocoa_cursor_blink_interval(void);


static GLFWcursor *standard_cursor = NULL, *click_cursor = NULL, *arrow_cursor = NULL;

static void set_os_window_dpi(OSWindow *w);


void
request_tick_callback(void) {
    glfwPostEmptyEvent();
}

static inline void
min_size_for_os_window(OSWindow *window, int *min_width, int *min_height) {
    *min_width = MAX(8u, window->fonts_data->cell_width + 1);
    *min_height = MAX(8u, window->fonts_data->cell_height + 1);
}


void
update_os_window_viewport(OSWindow *window, bool notify_boss) {
    int w, h, fw, fh;
    glfwGetFramebufferSize(window->handle, &fw, &fh);
    glfwGetWindowSize(window->handle, &w, &h);
    double xdpi = window->logical_dpi_x, ydpi = window->logical_dpi_y;
    set_os_window_dpi(window);

    if (fw == window->viewport_width && fh == window->viewport_height && w == window->window_width && h == window->window_height && xdpi == window->logical_dpi_x && ydpi == window->logical_dpi_y) {
        return; // no change, ignore
    }
    int min_width, min_height; min_size_for_os_window(window, &min_width, &min_height);
    if (w <= 0 || h <= 0 || fw < min_width || fh < min_height || fw < w || fh < h) {
        log_error("Invalid geometry ignored: framebuffer: %dx%d window: %dx%d\n", fw, fh, w, h);
        if (!window->viewport_updated_at_least_once) {
            window->viewport_width = min_width; window->viewport_height = min_height;
            window->window_width = min_width; window->window_height = min_height;
            window->viewport_x_ratio = 1; window->viewport_y_ratio = 1;
            window->viewport_size_dirty = true;
            if (notify_boss) {
                call_boss(on_window_resize, "KiiO", window->id, window->viewport_width, window->viewport_height, Py_False);
            }
        }
        return;
    }
    window->viewport_updated_at_least_once = true;
    window->viewport_width = fw; window->viewport_height = fh;
    double xr = window->viewport_x_ratio, yr = window->viewport_y_ratio;
    window->viewport_x_ratio = w > 0 ? (double)window->viewport_width / (double)w : xr;
    window->viewport_y_ratio = h > 0 ? (double)window->viewport_height / (double)h : yr;
    bool dpi_changed = (xr != 0.0 && xr != window->viewport_x_ratio) || (yr != 0.0 && yr != window->viewport_y_ratio) || (xdpi != window->logical_dpi_x) || (ydpi != window->logical_dpi_y);

    window->viewport_size_dirty = true;
    window->viewport_width = MAX(window->viewport_width, min_width);
    window->viewport_height = MAX(window->viewport_height, min_height);
    window->window_width = MAX(w, min_width);
    window->window_height = MAX(h, min_height);
    if (notify_boss) {
        call_boss(on_window_resize, "KiiO", window->id, window->viewport_width, window->viewport_height, dpi_changed ? Py_True : Py_False);
    }
}

void
log_event(const char *format, ...) {
    if (format)
    {
        va_list vl;

        fprintf(stderr, "[%.4f] ", monotonic_t_to_s_double(glfwGetTime()));
        va_start(vl, format);
        vfprintf(stderr, format, vl);
        va_end(vl);
        fprintf(stderr, "\n");
    }

}


// callbacks {{{

void
update_os_window_references() {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (w->handle) glfwSetWindowUserPointer(w->handle, w);
    }
}

static inline bool
set_callback_window(GLFWwindow *w) {
    global_state.callback_os_window = glfwGetWindowUserPointer(w);
    if (global_state.callback_os_window) return true;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        if ((GLFWwindow*)(global_state.os_windows[i].handle) == w) {
            global_state.callback_os_window = global_state.os_windows + i;
            return true;
        }
    }
    return false;
}

static inline bool
is_window_ready_for_callbacks(void) {
    OSWindow *w = global_state.callback_os_window;
    if (w->num_tabs == 0) return false;
    Tab *t = w->tabs + w->active_tab;
    if (t->num_windows == 0) return false;
    return true;
}

#define WINDOW_CALLBACK(name, fmt, ...) call_boss(name, "K" fmt, global_state.callback_os_window->id, __VA_ARGS__)

static inline void
show_mouse_cursor(GLFWwindow *w) {
    glfwSetInputMode(w, GLFW_CURSOR, GLFW_CURSOR_NORMAL);
}

void
blank_os_window(OSWindow *w) {
    color_type color = OPT(background);
    if (w->num_tabs > 0) {
        Tab *t = w->tabs + w->active_tab;
        if (t->num_windows == 1) {
            Window *w = t->windows + t->active_window;
            Screen *s = w->render_data.screen;
            if (s) {
                color = colorprofile_to_color(s->color_profile, s->color_profile->overridden.default_bg, s->color_profile->configured.default_bg);
            }
        }
    }
    blank_canvas(w->is_semi_transparent ? w->background_opacity : 1.0f, color);
}

static void
window_close_callback(GLFWwindow* window) {
    if (!set_callback_window(window)) return;
    if (global_state.callback_os_window->close_request == NO_CLOSE_REQUESTED) {
        global_state.callback_os_window->close_request = CONFIRMABLE_CLOSE_REQUESTED;
        global_state.has_pending_closes = true;
        request_tick_callback();
    }
    glfwSetWindowShouldClose(window, false);
    global_state.callback_os_window = NULL;
}

static void
window_occlusion_callback(GLFWwindow *window, bool occluded) {
    if (!set_callback_window(window)) return;
    if (!occluded) global_state.check_for_active_animated_images = true;
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static void
window_iconify_callback(GLFWwindow *window, int iconified) {
    if (!set_callback_window(window)) return;
    if (!iconified) global_state.check_for_active_animated_images = true;
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static void
live_resize_callback(GLFWwindow *w, bool started) {
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->live_resize.from_os_notification = true;
    global_state.callback_os_window->live_resize.in_progress = true;
    global_state.has_pending_resizes = true;
    if (!started) {
        global_state.callback_os_window->live_resize.os_says_resize_complete = true;
        request_tick_callback();
    }
    global_state.callback_os_window = NULL;
}

static void
framebuffer_size_callback(GLFWwindow *w, int width, int height) {
    if (!set_callback_window(w)) return;
    int min_width, min_height; min_size_for_os_window(global_state.callback_os_window, &min_width, &min_height);
    if (width >= min_width && height >= min_height) {
        OSWindow *window = global_state.callback_os_window;
        global_state.has_pending_resizes = true;
        window->live_resize.in_progress = true;
        window->live_resize.last_resize_event_at = monotonic();
        window->live_resize.width = MAX(0, width); window->live_resize.height = MAX(0, height);
        window->live_resize.num_of_resize_events++;
        make_os_window_context_current(window);
        update_surface_size(width, height, window->offscreen_texture_id);
        request_tick_callback();
    } else log_error("Ignoring resize request for tiny size: %dx%d", width, height);
    global_state.callback_os_window = NULL;
}

static void
dpi_change_callback(GLFWwindow *w, float x_scale UNUSED, float y_scale UNUSED) {
    if (!set_callback_window(w)) return;
    // Ensure update_os_window_viewport() is called in the near future, it will
    // take care of DPI changes.
    OSWindow *window = global_state.callback_os_window;
    window->live_resize.in_progress = true; global_state.has_pending_resizes = true;
    window->live_resize.last_resize_event_at = monotonic();
    global_state.callback_os_window = NULL;
    request_tick_callback();
}

static void
refresh_callback(GLFWwindow *w) {
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->is_damaged = true;
    global_state.callback_os_window = NULL;
    request_tick_callback();
}

static int mods_at_last_key_or_button_event = 0;

static inline int
key_to_modifier(uint32_t key) {
    switch(key) {
        case GLFW_FKEY_LEFT_SHIFT:
        case GLFW_FKEY_RIGHT_SHIFT:
            return GLFW_MOD_SHIFT;
        case GLFW_FKEY_LEFT_CONTROL:
        case GLFW_FKEY_RIGHT_CONTROL:
            return GLFW_MOD_CONTROL;
        case GLFW_FKEY_LEFT_ALT:
        case GLFW_FKEY_RIGHT_ALT:
            return GLFW_MOD_ALT;
        case GLFW_FKEY_LEFT_SUPER:
        case GLFW_FKEY_RIGHT_SUPER:
            return GLFW_MOD_SUPER;
        case GLFW_FKEY_LEFT_HYPER:
        case GLFW_FKEY_RIGHT_HYPER:
            return GLFW_MOD_HYPER;
        case GLFW_FKEY_LEFT_META:
        case GLFW_FKEY_RIGHT_META:
            return GLFW_MOD_META;
        default:
            return -1;
    }
}

static void
key_callback(GLFWwindow *w, GLFWkeyevent *ev) {
    if (!set_callback_window(w)) return;
    mods_at_last_key_or_button_event = ev->mods;
    int key_modifier = key_to_modifier(ev->key);
    if (key_modifier != -1) {
        if (ev->action == GLFW_RELEASE) {
            mods_at_last_key_or_button_event &= ~key_modifier;
        } else {
            mods_at_last_key_or_button_event |= key_modifier;
        }
    }
    global_state.callback_os_window->cursor_blink_zero_time = monotonic();
    if (is_window_ready_for_callbacks()) on_key_input(ev);
    global_state.callback_os_window = NULL;
    request_tick_callback();
}

static void
cursor_enter_callback(GLFWwindow *w, int entered) {
    if (!set_callback_window(w)) return;
    if (entered) {
        show_mouse_cursor(w);
        monotonic_t now = monotonic();
        global_state.callback_os_window->last_mouse_activity_at = now;
        if (is_window_ready_for_callbacks()) enter_event();
        request_tick_callback();
    }
    global_state.callback_os_window = NULL;
}

static void
mouse_button_callback(GLFWwindow *w, int button, int action, int mods) {
    if (!set_callback_window(w)) return;
    show_mouse_cursor(w);
    mods_at_last_key_or_button_event = mods;
    monotonic_t now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    if (button >= 0 && (unsigned int)button < arraysz(global_state.callback_os_window->mouse_button_pressed)) {
        global_state.callback_os_window->mouse_button_pressed[button] = action == GLFW_PRESS ? true : false;
        if (is_window_ready_for_callbacks()) mouse_event(button, mods, action);
    }
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static void
cursor_pos_callback(GLFWwindow *w, double x, double y) {
    if (!set_callback_window(w)) return;
    show_mouse_cursor(w);
    monotonic_t now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    global_state.callback_os_window->cursor_blink_zero_time = now;
    global_state.callback_os_window->mouse_x = x * global_state.callback_os_window->viewport_x_ratio;
    global_state.callback_os_window->mouse_y = y * global_state.callback_os_window->viewport_y_ratio;
    if (is_window_ready_for_callbacks()) mouse_event(-1, mods_at_last_key_or_button_event, -1);
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static void
scroll_callback(GLFWwindow *w, double xoffset, double yoffset, int flags, int mods) {
    if (!set_callback_window(w)) return;
    show_mouse_cursor(w);
    monotonic_t now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    if (is_window_ready_for_callbacks()) scroll_event(xoffset, yoffset, flags, mods);
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static id_type focus_counter = 0;

static void
window_focus_callback(GLFWwindow *w, int focused) {
    global_state.active_drag_in_window = 0;
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->is_focused = focused ? true : false;
    if (focused) {
        show_mouse_cursor(w);
        focus_in_event();
        global_state.callback_os_window->last_focused_counter = ++focus_counter;
        global_state.check_for_active_animated_images = true;
    }
    monotonic_t now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    global_state.callback_os_window->cursor_blink_zero_time = now;
    if (is_window_ready_for_callbacks()) {
        WINDOW_CALLBACK(on_focus, "O", focused ? Py_True : Py_False);
        GLFWIMEUpdateEvent ev = { .type = GLFW_IME_UPDATE_FOCUS, .focused = focused };
        glfwUpdateIMEState(global_state.callback_os_window->handle, &ev);
    }
    request_tick_callback();
    global_state.callback_os_window = NULL;
}

static int
drop_callback(GLFWwindow *w, const char *mime, const char *data, size_t sz) {
    if (!set_callback_window(w)) return 0;
#define RETURN(x) { global_state.callback_os_window = NULL; return x; }
    if (!data) {
        if (strcmp(mime, "text/uri-list") == 0) RETURN(3);
        if (strcmp(mime, "text/plain;charset=utf-8") == 0) RETURN(2);
        if (strcmp(mime, "text/plain") == 0) RETURN(1);
        RETURN(0);
    }
    WINDOW_CALLBACK(on_drop, "sy#", mime, data, (Py_ssize_t)sz);
    request_tick_callback();
    RETURN(0);
#undef RETURN
}

static void
application_close_requested_callback(int flags) {
    if (flags) {
        global_state.quit_request = IMPERATIVE_CLOSE_REQUESTED;
        global_state.has_pending_closes = true;
        request_tick_callback();
    } else {
        if (global_state.quit_request == NO_CLOSE_REQUESTED) {
            global_state.has_pending_closes = true;
            global_state.quit_request = CONFIRMABLE_CLOSE_REQUESTED;
            request_tick_callback();
        }
    }
}

static inline void get_window_dpi(GLFWwindow *w, double *x, double *y);

#ifdef __APPLE__
static bool
apple_file_open_callback(const char* filepath) {
    set_cocoa_pending_action(OPEN_FILE, filepath);
    return true;
}
#else

static FreeTypeRenderCtx csd_title_render_ctx = NULL;

static bool
draw_text_callback(GLFWwindow *window, const char *text, uint32_t fg, uint32_t bg, uint8_t *output_buf, size_t width, size_t height, float x_offset, float y_offset, size_t right_margin) {
    if (!set_callback_window(window)) return false;
    if (!csd_title_render_ctx) {
        csd_title_render_ctx = create_freetype_render_context(NULL, true, false);
        if (!csd_title_render_ctx) {
            if (PyErr_Occurred()) PyErr_Print();
            return false;
        }
    }
    double xdpi, ydpi;
    get_window_dpi(window, &xdpi, &ydpi);
    unsigned px_sz = (unsigned)(global_state.callback_os_window->font_sz_in_pts * ydpi / 72.);
    px_sz = MIN(px_sz, 3 * height / 4);
    static char title[2048];
    snprintf(title, sizeof(title), "🐱 %s", text);
    bool ok = render_single_line(csd_title_render_ctx, title, px_sz, fg, bg, output_buf, width, height, x_offset, y_offset, right_margin);
    if (!ok && PyErr_Occurred()) PyErr_Print();
    return ok;
}
#endif
// }}}

void
set_mouse_cursor(MouseShape type) {
    if (global_state.callback_os_window) {
        GLFWwindow *w = (GLFWwindow*)global_state.callback_os_window->handle;
        switch(type) {
            case HAND:
                glfwSetCursor(w, click_cursor);
                break;
            case ARROW:
                glfwSetCursor(w, arrow_cursor);
                break;
            default:
                glfwSetCursor(w, standard_cursor);
                break;
        }
    }
}

static GLFWimage logo = {0};

static PyObject*
set_default_window_icon(PyObject UNUSED *self, PyObject *args) {
    size_t sz;
    unsigned int width, height;
    const char *path;
    uint8_t *data;
    if(!PyArg_ParseTuple(args, "s", &path)) return NULL;
    if (png_path_to_bitmap(path, &data, &width, &height, &sz)) {
        logo.width = width; logo.height = height;
        logo.pixels = data;
    }
    Py_RETURN_NONE;
}


void
make_os_window_context_current(OSWindow *w) {
    GLFWwindow *current_context = glfwGetCurrentContext();
    if (w->handle != current_context) {
        glfwMakeContextCurrent(w->handle);
    }
}


static inline void
get_window_content_scale(GLFWwindow *w, float *xscale, float *yscale, double *xdpi, double *ydpi) {
    *xscale = 1; *yscale = 1;
    if (w) glfwGetWindowContentScale(w, xscale, yscale);
    else {
        GLFWmonitor *monitor = glfwGetPrimaryMonitor();
        if (monitor) glfwGetMonitorContentScale(monitor, xscale, yscale);
    }
    // check for zero, negative, NaN or excessive values of xscale/yscale
    if (*xscale <= 0.0001 || *xscale != *xscale || *xscale >= 24) *xscale = 1.0;
    if (*yscale <= 0.0001 || *yscale != *yscale || *yscale >= 24) *yscale = 1.0;
#ifdef __APPLE__
    const double factor = 72.0;
#else
    const double factor = 96.0;
#endif
    *xdpi = *xscale * factor;
    *ydpi = *yscale * factor;
}

static inline void
get_window_dpi(GLFWwindow *w, double *x, double *y) {
    float xscale, yscale;
    get_window_content_scale(w, &xscale, &yscale, x, y);
}

static void
set_os_window_dpi(OSWindow *w) {
    get_window_dpi(w->handle, &w->logical_dpi_x, &w->logical_dpi_y);
}

static inline bool
do_toggle_fullscreen(OSWindow *w) {
    int width, height, x, y;
    glfwGetWindowSize(w->handle, &width, &height);
    glfwGetWindowPos(w->handle, &x, &y);
    if (glfwToggleFullscreen(w->handle, 0)) {
        w->before_fullscreen.is_set = true;
        w->before_fullscreen.w = width; w->before_fullscreen.h = height; w->before_fullscreen.x = x; w->before_fullscreen.y = y;
        return true;
    }
    if (w->before_fullscreen.is_set) {
        glfwSetWindowSize(w->handle, w->before_fullscreen.w, w->before_fullscreen.h);
        glfwSetWindowPos(w->handle, w->before_fullscreen.x, w->before_fullscreen.y);
    }
    return false;
}

static bool
toggle_fullscreen_for_os_window(OSWindow *w) {
    if (w && w->handle) {
#ifdef __APPLE__
    if (!OPT(macos_traditional_fullscreen)) return glfwToggleFullscreen(w->handle, 1);
#endif
    return do_toggle_fullscreen(w);
    }
    return false;
}

static bool
toggle_maximized_for_os_window(OSWindow *w) {
    bool maximized = false;
    if (w && w->handle) {
        if (glfwGetWindowAttrib(w->handle, GLFW_MAXIMIZED)) {
            glfwRestoreWindow(w->handle);
        } else {
            glfwMaximizeWindow(w->handle);
            maximized = true;
        }
    }
    return maximized;
}


#ifdef __APPLE__
static GLFWwindow *apple_preserve_common_context = NULL;

static int
filter_option(int key UNUSED, int mods, unsigned int native_key UNUSED, unsigned long flags) {
    if ((mods == GLFW_MOD_ALT) || (mods == (GLFW_MOD_ALT | GLFW_MOD_SHIFT))) {
        if (OPT(macos_option_as_alt) == 3) return 1;
        if (cocoa_alt_option_key_pressed(flags)) return 1;
    }
    return 0;
}

static bool
on_application_reopen(int has_visible_windows) {
    if (has_visible_windows) return true;
    set_cocoa_pending_action(NEW_OS_WINDOW, NULL);
    return false;
}

static bool
intercept_cocoa_fullscreen(GLFWwindow *w) {
    if (!OPT(macos_traditional_fullscreen) || !set_callback_window(w)) return false;
    toggle_fullscreen_for_os_window(global_state.callback_os_window);
    global_state.callback_os_window = NULL;
    return true;
}
#endif

void
set_titlebar_color(OSWindow *w, color_type color, bool use_system_color) {
    if (w->handle && (!w->last_titlebar_color || (w->last_titlebar_color & 0xffffff) != (color & 0xffffff))) {
        w->last_titlebar_color = (1 << 24) | (color & 0xffffff);
#ifdef __APPLE__
        if (!use_system_color) cocoa_set_titlebar_color(glfwGetCocoaWindow(w->handle), color);
#else
        if (global_state.is_wayland && glfwWaylandSetTitlebarColor) glfwWaylandSetTitlebarColor(w->handle, color, use_system_color);
#endif
    }
}

static inline PyObject*
native_window_handle(GLFWwindow *w) {
#ifdef __APPLE__
    void *ans = glfwGetCocoaWindow(w);
    return PyLong_FromVoidPtr(ans);
#endif
    if (glfwGetX11Window) return PyLong_FromLong((long)glfwGetX11Window(w));
    return Py_None;
}

static PyObject*
create_os_window(PyObject UNUSED *self, PyObject *args) {
    int x = -1, y = -1;
    char *title, *wm_class_class, *wm_class_name;
    PyObject *load_programs = NULL, *get_window_size, *pre_show_callback;
    if (!PyArg_ParseTuple(args, "OOsss|Oii", &get_window_size, &pre_show_callback, &title, &wm_class_name, &wm_class_class, &load_programs, &x, &y)) return NULL;

    static bool is_first_window = true;
    if (is_first_window) {
        glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, OPENGL_REQUIRED_VERSION_MAJOR);
        glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, OPENGL_REQUIRED_VERSION_MINOR);
        glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
        glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, true);
        // We don't use depth and stencil buffers
        glfwWindowHint(GLFW_DEPTH_BITS, 0);
        glfwWindowHint(GLFW_STENCIL_BITS, 0);
        if (OPT(hide_window_decorations) & 1) glfwWindowHint(GLFW_DECORATED, false);
        glfwSetApplicationCloseCallback(application_close_requested_callback);
#ifdef __APPLE__
        cocoa_set_activation_policy(OPT(macos_hide_from_tasks));
        glfwWindowHint(GLFW_COCOA_GRAPHICS_SWITCHING, true);
        glfwSetApplicationShouldHandleReopen(on_application_reopen);
        glfwSetApplicationWillFinishLaunching(cocoa_create_global_menu);
#endif
    }

#ifndef __APPLE__
    glfwWindowHintString(GLFW_X11_INSTANCE_NAME, wm_class_name);
    glfwWindowHintString(GLFW_X11_CLASS_NAME, wm_class_class);
    glfwWindowHintString(GLFW_WAYLAND_APP_ID, wm_class_class);
#endif

    if (global_state.num_os_windows >= MAX_CHILDREN) {
        PyErr_SetString(PyExc_ValueError, "Too many windows");
        return NULL;
    }
    bool want_semi_transparent = (1.0 - OPT(background_opacity) >= 0.01) || OPT(dynamic_background_opacity);
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER, want_semi_transparent);
    // We use a temp window to avoid the need to set the window size after
    // creation, which causes a resize event and all the associated processing.
    // The temp window is used to get the DPI.
    glfwWindowHint(GLFW_VISIBLE, false);
    GLFWwindow *common_context = global_state.num_os_windows ? global_state.os_windows[0].handle : NULL;
    GLFWwindow *temp_window = NULL;
#ifdef __APPLE__
    if (!apple_preserve_common_context) {
        apple_preserve_common_context = glfwCreateWindow(640, 480, "kitty", NULL, common_context);
    }
    if (!common_context) common_context = apple_preserve_common_context;
#endif
    if (!global_state.is_wayland) {
        // On Wayland windows dont get a content scale until they receive an enterEvent anyway
        // which won't happen until the event loop ticks, so using a temp window is useless.
        temp_window = glfwCreateWindow(640, 480, "temp", NULL, common_context);
        if (temp_window == NULL) { fatal("Failed to create GLFW temp window! This usually happens because of old/broken OpenGL drivers. kitty requires working OpenGL 3.3 drivers."); }
    }
    float xscale, yscale;
    double xdpi, ydpi;
    get_window_content_scale(temp_window, &xscale, &yscale, &xdpi, &ydpi);
    FONTS_DATA_HANDLE fonts_data = load_fonts_data(global_state.font_sz_in_pts, xdpi, ydpi);
    PyObject *ret = PyObject_CallFunction(get_window_size, "IIddff", fonts_data->cell_width, fonts_data->cell_height, fonts_data->logical_dpi_x, fonts_data->logical_dpi_y, xscale, yscale);
    if (ret == NULL) return NULL;
    int width = PyLong_AsLong(PyTuple_GET_ITEM(ret, 0)), height = PyLong_AsLong(PyTuple_GET_ITEM(ret, 1));
    Py_CLEAR(ret);
    // The GLFW Wayland backend cannot create and show windows separately so we
    // cannot call the pre_show_callback. See
    // https://github.com/glfw/glfw/issues/1268 It doesn't matter since there
    // is no startup notification in Wayland anyway. It amazes me that anyone
    // uses Wayland as anything other than a butt for jokes.
    if (global_state.is_wayland) glfwWindowHint(GLFW_VISIBLE, true);
    GLFWwindow *glfw_window = glfwCreateWindow(width, height, title, NULL, temp_window ? temp_window : common_context);
    if (temp_window) { glfwDestroyWindow(temp_window); temp_window = NULL; }
    if (glfw_window == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to create GLFWwindow"); return NULL; }
    glfwMakeContextCurrent(glfw_window);
    if (is_first_window) {
        gl_init();
    }
    bool is_semi_transparent = glfwGetWindowAttrib(glfw_window, GLFW_TRANSPARENT_FRAMEBUFFER);
    // blank the window once so that there is no initial flash of color
    // changing, in case the background color is not black
    blank_canvas(is_semi_transparent ? OPT(background_opacity) : 1.0f, OPT(background));
#ifndef __APPLE__
    if (is_first_window) glfwSwapInterval(OPT(sync_to_monitor) && !global_state.is_wayland ? 1 : 0);
#endif
    glfwSwapBuffers(glfw_window);
    glfwSetInputMode(glfw_window, GLFW_LOCK_KEY_MODS, true);
    if (!global_state.is_wayland) {
        PyObject *pret = PyObject_CallFunction(pre_show_callback, "N", native_window_handle(glfw_window));
        if (pret == NULL) return NULL;
        Py_DECREF(pret);
        if (x != -1 && y != -1) glfwSetWindowPos(glfw_window, x, y);
        glfwShowWindow(glfw_window);
#ifdef __APPLE__
        float n_xscale, n_yscale;
        double n_xdpi, n_ydpi;
        get_window_content_scale(glfw_window, &n_xscale, &n_yscale, &n_xdpi, &n_ydpi);
        if (n_xdpi != xdpi || n_ydpi != ydpi) {
            // this can happen if the window is moved by the OS to a different monitor when shown
            xdpi = n_xdpi; ydpi = n_ydpi;
            fonts_data = load_fonts_data(global_state.font_sz_in_pts, xdpi, ydpi);
        }
#endif
    }
    if (is_first_window) {
        PyObject *ret = PyObject_CallFunction(load_programs, "O", is_semi_transparent ? Py_True : Py_False);
        if (ret == NULL) return NULL;
        Py_DECREF(ret);
#define CC(dest, shape) {\
    if (!dest##_cursor) { \
        dest##_cursor = glfwCreateStandardCursor(GLFW_##shape##_CURSOR); \
        if (dest##_cursor == NULL) { log_error("Failed to create the %s mouse cursor, using default cursor.", #shape); } \
}}
    CC(standard, IBEAM); CC(click, HAND); CC(arrow, ARROW);
#undef CC
        if (OPT(click_interval) < 0) OPT(click_interval) = glfwGetDoubleClickInterval(glfw_window);
        if (OPT(cursor_blink_interval) < 0) {
            OPT(cursor_blink_interval) = ms_to_monotonic_t(500ll);
#ifdef __APPLE__
            monotonic_t cbi = cocoa_cursor_blink_interval();
            if (cbi >= 0) OPT(cursor_blink_interval) = cbi / 2;
#endif
        }
        is_first_window = false;
    }
    OSWindow *w = add_os_window();
    w->handle = glfw_window;
    update_os_window_references();
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        // On some platforms (macOS) newly created windows don't get the initial focus in event
        OSWindow *q = global_state.os_windows + i;
        q->is_focused = q == w ? true : false;
    }
    w->logical_dpi_x = xdpi; w->logical_dpi_y = ydpi;
    w->fonts_data = fonts_data;
    w->shown_once = true;
    w->last_focused_counter = ++focus_counter;
    if (OPT(resize_in_steps)) os_window_update_size_increments(w);
#ifdef __APPLE__
    if (OPT(macos_option_as_alt)) glfwSetCocoaTextInputFilter(glfw_window, filter_option);
    glfwSetCocoaToggleFullscreenIntercept(glfw_window, intercept_cocoa_fullscreen);
#endif
    send_prerendered_sprites_for_window(w);
    if (logo.pixels && logo.width && logo.height) glfwSetWindowIcon(glfw_window, 1, &logo);
    glfwSetCursor(glfw_window, standard_cursor);
    update_os_window_viewport(w, false);
    // missing pos callback
    // missing size callback
    glfwSetWindowCloseCallback(glfw_window, window_close_callback);
    glfwSetWindowRefreshCallback(glfw_window, refresh_callback);
    glfwSetWindowFocusCallback(glfw_window, window_focus_callback);
    glfwSetWindowOcclusionCallback(glfw_window, window_occlusion_callback);
    glfwSetWindowIconifyCallback(glfw_window, window_iconify_callback);
    // missing maximize/restore callback
    glfwSetFramebufferSizeCallback(glfw_window, framebuffer_size_callback);
    glfwSetLiveResizeCallback(glfw_window, live_resize_callback);
    glfwSetWindowContentScaleCallback(glfw_window, dpi_change_callback);
    glfwSetMouseButtonCallback(glfw_window, mouse_button_callback);
    glfwSetCursorPosCallback(glfw_window, cursor_pos_callback);
    glfwSetCursorEnterCallback(glfw_window, cursor_enter_callback);
    glfwSetScrollCallback(glfw_window, scroll_callback);
    glfwSetKeyboardCallback(glfw_window, key_callback);
    glfwSetDropCallback(glfw_window, drop_callback);
#ifdef __APPLE__
    if (glfwGetCocoaWindow) {
        if (OPT(hide_window_decorations) & 2) {
            glfwHideCocoaTitlebar(glfw_window, true);
        } else if (!(OPT(macos_show_window_title_in) & WINDOW)) {
            cocoa_hide_window_title(glfwGetCocoaWindow(glfw_window));
        }
        cocoa_make_window_resizable(glfwGetCocoaWindow(glfw_window), OPT(macos_window_resizable));
    } else log_error("Failed to load glfwGetCocoaWindow");
#endif
    monotonic_t now = monotonic();
    w->is_focused = true;
    w->cursor_blink_zero_time = now;
    w->last_mouse_activity_at = now;
    w->is_semi_transparent = is_semi_transparent;
    if (want_semi_transparent && !w->is_semi_transparent) {
        static bool warned = false;
        if (!warned) {
            log_error("Failed to enable transparency. This happens when your desktop environment does not support compositing.");
            warned = true;
        }
    }
    return PyLong_FromUnsignedLongLong(w->id);
}

void
os_window_update_size_increments(OSWindow *window) {
    if (window->handle && window->fonts_data) glfwSetWindowSizeIncrements(
            window->handle, window->fonts_data->cell_width, window->fonts_data->cell_height);
}

#ifdef __APPLE__
static inline bool
window_in_same_cocoa_workspace(void *w, size_t *source_workspaces, size_t source_workspace_count) {
    static size_t workspaces[64];
    size_t workspace_count = cocoa_get_workspace_ids(w, workspaces, arraysz(workspaces));
    for (size_t i = 0; i < workspace_count; i++) {
        for (size_t s = 0; s < source_workspace_count; s++) {
            if (source_workspaces[s] == workspaces[i]) return true;
        }
    }
    return false;
}

static inline void
cocoa_focus_last_window(id_type source_window_id, size_t *source_workspaces, size_t source_workspace_count) {
    id_type highest_focus_number = 0;
    OSWindow *window_to_focus = NULL;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (
                w->id != source_window_id && w->handle && w->shown_once &&
                w->last_focused_counter >= highest_focus_number &&
                (!source_workspace_count || window_in_same_cocoa_workspace(glfwGetCocoaWindow(w->handle), source_workspaces, source_workspace_count))
        ) {
            highest_focus_number = w->last_focused_counter;
            window_to_focus = w;
        }
    }
    if (window_to_focus) {
        glfwFocusWindow(window_to_focus->handle);
    }
}
#endif

void
destroy_os_window(OSWindow *w) {
#ifdef __APPLE__
    static size_t source_workspaces[64];
    size_t source_workspace_count = 0;
#endif
    if (w->handle) {
#ifdef __APPLE__
        source_workspace_count = cocoa_get_workspace_ids(glfwGetCocoaWindow(w->handle), source_workspaces, arraysz(source_workspaces));
#endif
        // Ensure mouse cursor is visible and reset to default shape, needed on macOS
        show_mouse_cursor(w->handle);
        glfwSetCursor(w->handle, NULL);
        glfwDestroyWindow(w->handle);
    }
    w->handle = NULL;
#ifdef __APPLE__
    // On macOS when closing a window, any other existing windows belonging to the same application do not
    // automatically get focus, so we do it manually.
    cocoa_focus_last_window(w->id, source_workspaces, source_workspace_count);
#endif
}

void
focus_os_window(OSWindow *w, bool also_raise) {
    if (w->handle) {
#ifdef __APPLE__
        if (!also_raise) cocoa_focus_window(glfwGetCocoaWindow(w->handle));
        else glfwFocusWindow(w->handle);
#else
        (void)also_raise;
        glfwFocusWindow(w->handle);
#endif
    }
}

// Global functions {{{
static void
error_callback(int error, const char* description) {
    log_error("[glfw error %d]: %s", error, description);
}


#ifndef __APPLE__
static void
dbus_user_notification_activated(uint32_t notification_id, const char* action) {
    unsigned long nid = notification_id;
    call_boss(dbus_notification_callback, "Oks", Py_True, nid, action);
}
#endif

static PyObject*
glfw_init(PyObject UNUSED *self, PyObject *args) {
    const char* path;
    int debug_keyboard = 0, debug_rendering = 0;
    if (!PyArg_ParseTuple(args, "s|pp", &path, &debug_keyboard, &debug_rendering)) return NULL;
    const char* err = load_glfw(path);
    if (err) { PyErr_SetString(PyExc_RuntimeError, err); return NULL; }
    glfwSetErrorCallback(error_callback);
    glfwInitHint(GLFW_DEBUG_KEYBOARD, debug_keyboard);
    glfwInitHint(GLFW_DEBUG_RENDERING, debug_rendering);
    OPT(debug_keyboard) = debug_keyboard != 0;
#ifdef __APPLE__
    glfwInitHint(GLFW_COCOA_CHDIR_RESOURCES, 0);
    glfwInitHint(GLFW_COCOA_MENUBAR, 0);
#else
    if (glfwDBusSetUserNotificationHandler) {
        glfwDBusSetUserNotificationHandler(dbus_user_notification_activated);
    }
#endif
    PyObject *ans = glfwInit(monotonic_start_time) ? Py_True: Py_False;
    if (ans == Py_True) {
#ifdef __APPLE__
        glfwSetCocoaFileOpenCallback(apple_file_open_callback);
#else
        glfwSetDrawTextFunction(draw_text_callback);
#endif
        OSWindow w = {0};
        set_os_window_dpi(&w);
        global_state.default_dpi.x = w.logical_dpi_x;
        global_state.default_dpi.y = w.logical_dpi_y;
    }
    Py_INCREF(ans);
    return ans;
}

static PyObject*
glfw_terminate(PYNOARG) {
    glfwTerminate();
    Py_RETURN_NONE;
}

static PyObject*
get_physical_dpi(GLFWmonitor *m) {
    int width = 0, height = 0;
    glfwGetMonitorPhysicalSize(m, &width, &height);
    if (width == 0 || height == 0) { PyErr_SetString(PyExc_ValueError, "Failed to get primary monitor size"); return NULL; }
    const GLFWvidmode *vm = glfwGetVideoMode(m);
    if (vm == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to get video mode for monitor"); return NULL; }
    float dpix = (float)(vm->width / (width / 25.4));
    float dpiy = (float)(vm->height / (height / 25.4));
    return Py_BuildValue("ff", dpix, dpiy);
}

static PyObject*
glfw_get_physical_dpi(PYNOARG) {
    GLFWmonitor *m = glfwGetPrimaryMonitor();
    if (m == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to get primary monitor"); return NULL; }
    return get_physical_dpi(m);
}

static PyObject*
glfw_get_key_name(PyObject UNUSED *self, PyObject *args) {
    int key, native_key;
    if (!PyArg_ParseTuple(args, "ii", &key, &native_key)) return NULL;
    if (key) {
        switch (key) {
            /* start glfw functional key names (auto generated by gen-key-constants.py do not edit) */
            case GLFW_FKEY_ESCAPE: return PyUnicode_FromString("escape");
            case GLFW_FKEY_ENTER: return PyUnicode_FromString("enter");
            case GLFW_FKEY_TAB: return PyUnicode_FromString("tab");
            case GLFW_FKEY_BACKSPACE: return PyUnicode_FromString("backspace");
            case GLFW_FKEY_INSERT: return PyUnicode_FromString("insert");
            case GLFW_FKEY_DELETE: return PyUnicode_FromString("delete");
            case GLFW_FKEY_LEFT: return PyUnicode_FromString("left");
            case GLFW_FKEY_RIGHT: return PyUnicode_FromString("right");
            case GLFW_FKEY_UP: return PyUnicode_FromString("up");
            case GLFW_FKEY_DOWN: return PyUnicode_FromString("down");
            case GLFW_FKEY_PAGE_UP: return PyUnicode_FromString("page_up");
            case GLFW_FKEY_PAGE_DOWN: return PyUnicode_FromString("page_down");
            case GLFW_FKEY_HOME: return PyUnicode_FromString("home");
            case GLFW_FKEY_END: return PyUnicode_FromString("end");
            case GLFW_FKEY_CAPS_LOCK: return PyUnicode_FromString("caps_lock");
            case GLFW_FKEY_SCROLL_LOCK: return PyUnicode_FromString("scroll_lock");
            case GLFW_FKEY_NUM_LOCK: return PyUnicode_FromString("num_lock");
            case GLFW_FKEY_PRINT_SCREEN: return PyUnicode_FromString("print_screen");
            case GLFW_FKEY_PAUSE: return PyUnicode_FromString("pause");
            case GLFW_FKEY_MENU: return PyUnicode_FromString("menu");
            case GLFW_FKEY_F1: return PyUnicode_FromString("f1");
            case GLFW_FKEY_F2: return PyUnicode_FromString("f2");
            case GLFW_FKEY_F3: return PyUnicode_FromString("f3");
            case GLFW_FKEY_F4: return PyUnicode_FromString("f4");
            case GLFW_FKEY_F5: return PyUnicode_FromString("f5");
            case GLFW_FKEY_F6: return PyUnicode_FromString("f6");
            case GLFW_FKEY_F7: return PyUnicode_FromString("f7");
            case GLFW_FKEY_F8: return PyUnicode_FromString("f8");
            case GLFW_FKEY_F9: return PyUnicode_FromString("f9");
            case GLFW_FKEY_F10: return PyUnicode_FromString("f10");
            case GLFW_FKEY_F11: return PyUnicode_FromString("f11");
            case GLFW_FKEY_F12: return PyUnicode_FromString("f12");
            case GLFW_FKEY_F13: return PyUnicode_FromString("f13");
            case GLFW_FKEY_F14: return PyUnicode_FromString("f14");
            case GLFW_FKEY_F15: return PyUnicode_FromString("f15");
            case GLFW_FKEY_F16: return PyUnicode_FromString("f16");
            case GLFW_FKEY_F17: return PyUnicode_FromString("f17");
            case GLFW_FKEY_F18: return PyUnicode_FromString("f18");
            case GLFW_FKEY_F19: return PyUnicode_FromString("f19");
            case GLFW_FKEY_F20: return PyUnicode_FromString("f20");
            case GLFW_FKEY_F21: return PyUnicode_FromString("f21");
            case GLFW_FKEY_F22: return PyUnicode_FromString("f22");
            case GLFW_FKEY_F23: return PyUnicode_FromString("f23");
            case GLFW_FKEY_F24: return PyUnicode_FromString("f24");
            case GLFW_FKEY_F25: return PyUnicode_FromString("f25");
            case GLFW_FKEY_F26: return PyUnicode_FromString("f26");
            case GLFW_FKEY_F27: return PyUnicode_FromString("f27");
            case GLFW_FKEY_F28: return PyUnicode_FromString("f28");
            case GLFW_FKEY_F29: return PyUnicode_FromString("f29");
            case GLFW_FKEY_F30: return PyUnicode_FromString("f30");
            case GLFW_FKEY_F31: return PyUnicode_FromString("f31");
            case GLFW_FKEY_F32: return PyUnicode_FromString("f32");
            case GLFW_FKEY_F33: return PyUnicode_FromString("f33");
            case GLFW_FKEY_F34: return PyUnicode_FromString("f34");
            case GLFW_FKEY_F35: return PyUnicode_FromString("f35");
            case GLFW_FKEY_KP_0: return PyUnicode_FromString("kp_0");
            case GLFW_FKEY_KP_1: return PyUnicode_FromString("kp_1");
            case GLFW_FKEY_KP_2: return PyUnicode_FromString("kp_2");
            case GLFW_FKEY_KP_3: return PyUnicode_FromString("kp_3");
            case GLFW_FKEY_KP_4: return PyUnicode_FromString("kp_4");
            case GLFW_FKEY_KP_5: return PyUnicode_FromString("kp_5");
            case GLFW_FKEY_KP_6: return PyUnicode_FromString("kp_6");
            case GLFW_FKEY_KP_7: return PyUnicode_FromString("kp_7");
            case GLFW_FKEY_KP_8: return PyUnicode_FromString("kp_8");
            case GLFW_FKEY_KP_9: return PyUnicode_FromString("kp_9");
            case GLFW_FKEY_KP_DECIMAL: return PyUnicode_FromString("kp_decimal");
            case GLFW_FKEY_KP_DIVIDE: return PyUnicode_FromString("kp_divide");
            case GLFW_FKEY_KP_MULTIPLY: return PyUnicode_FromString("kp_multiply");
            case GLFW_FKEY_KP_SUBTRACT: return PyUnicode_FromString("kp_subtract");
            case GLFW_FKEY_KP_ADD: return PyUnicode_FromString("kp_add");
            case GLFW_FKEY_KP_ENTER: return PyUnicode_FromString("kp_enter");
            case GLFW_FKEY_KP_EQUAL: return PyUnicode_FromString("kp_equal");
            case GLFW_FKEY_KP_SEPARATOR: return PyUnicode_FromString("kp_separator");
            case GLFW_FKEY_KP_LEFT: return PyUnicode_FromString("kp_left");
            case GLFW_FKEY_KP_RIGHT: return PyUnicode_FromString("kp_right");
            case GLFW_FKEY_KP_UP: return PyUnicode_FromString("kp_up");
            case GLFW_FKEY_KP_DOWN: return PyUnicode_FromString("kp_down");
            case GLFW_FKEY_KP_PAGE_UP: return PyUnicode_FromString("kp_page_up");
            case GLFW_FKEY_KP_PAGE_DOWN: return PyUnicode_FromString("kp_page_down");
            case GLFW_FKEY_KP_HOME: return PyUnicode_FromString("kp_home");
            case GLFW_FKEY_KP_END: return PyUnicode_FromString("kp_end");
            case GLFW_FKEY_KP_INSERT: return PyUnicode_FromString("kp_insert");
            case GLFW_FKEY_KP_DELETE: return PyUnicode_FromString("kp_delete");
            case GLFW_FKEY_KP_BEGIN: return PyUnicode_FromString("kp_begin");
            case GLFW_FKEY_MEDIA_PLAY: return PyUnicode_FromString("media_play");
            case GLFW_FKEY_MEDIA_PAUSE: return PyUnicode_FromString("media_pause");
            case GLFW_FKEY_MEDIA_PLAY_PAUSE: return PyUnicode_FromString("media_play_pause");
            case GLFW_FKEY_MEDIA_REVERSE: return PyUnicode_FromString("media_reverse");
            case GLFW_FKEY_MEDIA_STOP: return PyUnicode_FromString("media_stop");
            case GLFW_FKEY_MEDIA_FAST_FORWARD: return PyUnicode_FromString("media_fast_forward");
            case GLFW_FKEY_MEDIA_REWIND: return PyUnicode_FromString("media_rewind");
            case GLFW_FKEY_MEDIA_TRACK_NEXT: return PyUnicode_FromString("media_track_next");
            case GLFW_FKEY_MEDIA_TRACK_PREVIOUS: return PyUnicode_FromString("media_track_previous");
            case GLFW_FKEY_MEDIA_RECORD: return PyUnicode_FromString("media_record");
            case GLFW_FKEY_LOWER_VOLUME: return PyUnicode_FromString("lower_volume");
            case GLFW_FKEY_RAISE_VOLUME: return PyUnicode_FromString("raise_volume");
            case GLFW_FKEY_MUTE_VOLUME: return PyUnicode_FromString("mute_volume");
            case GLFW_FKEY_LEFT_SHIFT: return PyUnicode_FromString("left_shift");
            case GLFW_FKEY_LEFT_CONTROL: return PyUnicode_FromString("left_control");
            case GLFW_FKEY_LEFT_ALT: return PyUnicode_FromString("left_alt");
            case GLFW_FKEY_LEFT_SUPER: return PyUnicode_FromString("left_super");
            case GLFW_FKEY_LEFT_HYPER: return PyUnicode_FromString("left_hyper");
            case GLFW_FKEY_LEFT_META: return PyUnicode_FromString("left_meta");
            case GLFW_FKEY_RIGHT_SHIFT: return PyUnicode_FromString("right_shift");
            case GLFW_FKEY_RIGHT_CONTROL: return PyUnicode_FromString("right_control");
            case GLFW_FKEY_RIGHT_ALT: return PyUnicode_FromString("right_alt");
            case GLFW_FKEY_RIGHT_SUPER: return PyUnicode_FromString("right_super");
            case GLFW_FKEY_RIGHT_HYPER: return PyUnicode_FromString("right_hyper");
            case GLFW_FKEY_RIGHT_META: return PyUnicode_FromString("right_meta");
            case GLFW_FKEY_ISO_LEVEL3_SHIFT: return PyUnicode_FromString("iso_level3_shift");
            case GLFW_FKEY_ISO_LEVEL5_SHIFT: return PyUnicode_FromString("iso_level5_shift");
/* end glfw functional key names */
        }
        char buf[8] = {0};
        encode_utf8(key, buf);
        return PyUnicode_FromString(buf);
    }
    if (!glfwGetKeyName) {
        return PyUnicode_FromFormat("0x%x", native_key);
    }
    return Py_BuildValue("z", glfwGetKeyName(key, native_key));
}

static PyObject*
glfw_window_hint(PyObject UNUSED *self, PyObject *args) {
    int key, val;
    if (!PyArg_ParseTuple(args, "ii", &key, &val)) return NULL;
    glfwWindowHint(key, val);
    Py_RETURN_NONE;
}


// }}}

static PyObject*
get_clipboard_string(PYNOARG) {
    OSWindow *w = current_os_window();
    if (w) return Py_BuildValue("s", glfwGetClipboardString(w->handle));
    return Py_BuildValue("s", "");
}

static void
ring_audio_bell(void) {
    static monotonic_t last_bell_at = -1;
    monotonic_t now = monotonic();
    if (last_bell_at >= 0 && now - last_bell_at <= ms_to_monotonic_t(100ll)) return;
    last_bell_at = now;
#ifdef __APPLE__
    cocoa_system_beep();
#else
    play_canberra_sound("bell", "kitty bell");
#endif
}

static PyObject*
ring_bell(PYNOARG) {
    ring_audio_bell();
    Py_RETURN_NONE;
}

static PyObject*
get_content_scale_for_window(PYNOARG) {
    OSWindow *w = global_state.callback_os_window ? global_state.callback_os_window : global_state.os_windows;
    float xscale, yscale;
    glfwGetWindowContentScale(w->handle, &xscale, &yscale);
    return Py_BuildValue("ff", xscale, yscale);
}

static PyObject*
set_clipboard_string(PyObject UNUSED *self, PyObject *args) {
    char *title;
    Py_ssize_t sz;
    if(!PyArg_ParseTuple(args, "s#", &title, &sz)) return NULL;
    OSWindow *w = current_os_window();
    if (w) glfwSetClipboardString(w->handle, title);
    Py_RETURN_NONE;
}

static PyObject*
toggle_fullscreen(PYNOARG) {
    OSWindow *w = current_os_window();
    if (!w) Py_RETURN_NONE;
    if (toggle_fullscreen_for_os_window(w)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject*
toggle_maximized(PYNOARG) {
    OSWindow *w = current_os_window();
    if (!w) Py_RETURN_NONE;
    if (toggle_maximized_for_os_window(w)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject*
change_os_window_state(PyObject *self UNUSED, PyObject *args) {
    char *state;
    if (!PyArg_ParseTuple(args, "s", &state)) return NULL;
    OSWindow *w = current_os_window();
    if (!w || !w->handle) Py_RETURN_NONE;
    if (strcmp(state, "maximized") == 0) glfwMaximizeWindow(w->handle);
    else if (strcmp(state, "minimized") == 0) glfwIconifyWindow(w->handle);
    else { PyErr_SetString(PyExc_ValueError, "Unknown window state"); return NULL; }
    Py_RETURN_NONE;
}

void
request_window_attention(id_type kitty_window_id, bool audio_bell) {
    OSWindow *w = os_window_for_kitty_window(kitty_window_id);
    if (w) {
        if (audio_bell) ring_audio_bell();
        if (OPT(window_alert_on_bell)) glfwRequestWindowAttention(w->handle);
        glfwPostEmptyEvent();
    }
}

void
set_os_window_title(OSWindow *w, const char *title) {
    glfwSetWindowTitle(w->handle, title);
}

void
hide_mouse(OSWindow *w) {
    glfwSetInputMode(w->handle, GLFW_CURSOR, GLFW_CURSOR_HIDDEN);
}

bool
is_mouse_hidden(OSWindow *w) {
    return w->handle && glfwGetInputMode(w->handle, GLFW_CURSOR) == GLFW_CURSOR_HIDDEN;
}


void
swap_window_buffers(OSWindow *os_window) {
    glfwSwapBuffers(os_window->handle);
}

void
wakeup_main_loop() {
    glfwPostEmptyEvent();
}

bool
should_os_window_be_rendered(OSWindow* w) {
    return (
            glfwGetWindowAttrib(w->handle, GLFW_ICONIFIED) ||
            !glfwGetWindowAttrib(w->handle, GLFW_VISIBLE) ||
            glfwGetWindowAttrib(w->handle, GLFW_OCCLUDED)
       ) ? false : true;
}

static PyObject*
primary_monitor_size(PYNOARG) {
    GLFWmonitor* monitor = glfwGetPrimaryMonitor();
    const GLFWvidmode* mode = glfwGetVideoMode(monitor);
    return Py_BuildValue("ii", mode->width, mode->height);
}

static PyObject*
primary_monitor_content_scale(PYNOARG) {
    GLFWmonitor* monitor = glfwGetPrimaryMonitor();
    float xscale = 1.0, yscale = 1.0;
    if (monitor) glfwGetMonitorContentScale(monitor, &xscale, &yscale);
    return Py_BuildValue("ff", xscale, yscale);
}

static PyObject*
x11_display(PYNOARG) {
    if (glfwGetX11Display) {
        return PyLong_FromVoidPtr(glfwGetX11Display());
    } else log_error("Failed to load glfwGetX11Display");
    Py_RETURN_NONE;
}

static OSWindow*
find_os_window(PyObject *os_wid) {
    id_type os_window_id = PyLong_AsUnsignedLongLong(os_wid);
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (w->id == os_window_id) return w;
    }
    return NULL;
}

static PyObject*
x11_window_id(PyObject UNUSED *self, PyObject *os_wid) {
    OSWindow *w = find_os_window(os_wid);
    if (!w) { PyErr_SetString(PyExc_ValueError, "No OSWindow with the specified id found"); return NULL; }
    if (!glfwGetX11Window) { PyErr_SetString(PyExc_RuntimeError, "Failed to load glfwGetX11Window"); return NULL; }
    return Py_BuildValue("l", (long)glfwGetX11Window(w->handle));
}

static PyObject*
cocoa_window_id(PyObject UNUSED *self, PyObject *os_wid) {
    OSWindow *w = find_os_window(os_wid);
    if (!w) { PyErr_SetString(PyExc_ValueError, "No OSWindow with the specified id found"); return NULL; }
    if (!glfwGetCocoaWindow) { PyErr_SetString(PyExc_RuntimeError, "Failed to load glfwGetCocoaWindow"); return NULL; }
#ifdef __APPLE__
    return Py_BuildValue("l", (long)cocoa_window_number(glfwGetCocoaWindow(w->handle)));
#else
    PyErr_SetString(PyExc_RuntimeError, "cocoa_window_id() is only supported on Mac");
    return NULL;
#endif
}

static PyObject*
get_primary_selection(PYNOARG) {
    if (glfwGetPrimarySelectionString) {
        OSWindow *w = current_os_window();
        if (w) return Py_BuildValue("y", glfwGetPrimarySelectionString(w->handle));
    } else log_error("Failed to load glfwGetPrimarySelectionString");
    Py_RETURN_NONE;
}

static PyObject*
set_primary_selection(PyObject UNUSED *self, PyObject *args) {
    char *text;
    Py_ssize_t sz;
    if (!PyArg_ParseTuple(args, "s#", &text, &sz)) return NULL;
    if (glfwSetPrimarySelectionString) {
        OSWindow *w = current_os_window();
        if (w) glfwSetPrimarySelectionString(w->handle, text);
    }
    else log_error("Failed to load glfwSetPrimarySelectionString");
    Py_RETURN_NONE;
}

static PyObject*
set_custom_cursor(PyObject *self UNUSED, PyObject *args) {
    int shape;
    int x=0, y=0;
    Py_ssize_t sz;
    PyObject *images;
    if (!PyArg_ParseTuple(args, "iO!|ii", &shape, &PyTuple_Type, &images, &x, &y)) return NULL;
    static GLFWimage gimages[16] = {{0}};
    size_t count = MIN((size_t)PyTuple_GET_SIZE(images), arraysz(gimages));
    for (size_t i = 0; i < count; i++) {
        if (!PyArg_ParseTuple(PyTuple_GET_ITEM(images, i), "s#ii", &gimages[i].pixels, &sz, &gimages[i].width, &gimages[i].height)) return NULL;
        if ((Py_ssize_t)gimages[i].width * gimages[i].height * 4 != sz) {
            PyErr_SetString(PyExc_ValueError, "The image data size does not match its width and height");
            return NULL;
        }
    }
#define CASE(which, dest) {\
    case which: \
        dest = glfwCreateCursor(gimages, x, y, count); \
        if (dest == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to create custom cursor"); return NULL; } \
        break; \
}
    switch(shape) {
        CASE(GLFW_IBEAM_CURSOR, standard_cursor);
        CASE(GLFW_HAND_CURSOR, click_cursor);
        CASE(GLFW_ARROW_CURSOR, arrow_cursor);
        default:
            PyErr_SetString(PyExc_ValueError, "Unknown cursor shape");
            return NULL;
    }
    Py_RETURN_NONE;
}

#ifdef __APPLE__
void
get_cocoa_key_equivalent(uint32_t key, int mods, char *cocoa_key, size_t key_sz, int *cocoa_mods) {
    memset(cocoa_key, 0, key_sz);
    uint32_t ans = glfwGetCocoaKeyEquivalent(key, mods, cocoa_mods);
    if (ans) encode_utf8(ans, cocoa_key);
}

static void
cocoa_frame_request_callback(GLFWwindow *window) {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        if (global_state.os_windows[i].handle == window) {
            global_state.os_windows[i].render_state = RENDER_FRAME_READY;
            global_state.os_windows[i].last_render_frame_received_at = monotonic();
            request_tick_callback();
            break;
        }
    }
}

void
request_frame_render(OSWindow *w) {
    glfwCocoaRequestRenderFrame(w->handle, cocoa_frame_request_callback);
    w->render_state = RENDER_FRAME_REQUESTED;
}

#else

static void
wayland_frame_request_callback(id_type os_window_id) {
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        if (global_state.os_windows[i].id == os_window_id) {
            global_state.os_windows[i].render_state = RENDER_FRAME_READY;
            global_state.os_windows[i].last_render_frame_received_at = monotonic();
            request_tick_callback();
            break;
        }
    }
}

void
request_frame_render(OSWindow *w) {
    // Some Wayland compositors are too fragile to handle multiple
    // render frame requests, see https://github.com/kovidgoyal/kitty/issues/2329
    if (w->render_state != RENDER_FRAME_REQUESTED) {
        glfwRequestWaylandFrameEvent(w->handle, w->id, wayland_frame_request_callback);
        w->render_state = RENDER_FRAME_REQUESTED;
    }
}

void
dbus_notification_created_callback(unsigned long long notification_id, uint32_t new_notification_id, void* data UNUSED) {
    unsigned long new_id = new_notification_id;
    call_boss(dbus_notification_callback, "OKk", Py_False, notification_id, new_id);
}

static PyObject*
dbus_send_notification(PyObject *self UNUSED, PyObject *args) {
    char *app_name, *icon, *summary, *body, *action_name;
    int timeout = -1;
    if (!PyArg_ParseTuple(args, "sssss|i", &app_name, &icon, &summary, &body, &action_name, &timeout)) return NULL;
    if (!glfwDBusUserNotify) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to load glfwDBusUserNotify, did you call glfw_init?");
        return NULL;
    }
    unsigned long long notification_id = glfwDBusUserNotify(app_name, icon, summary, body, action_name, timeout, dbus_notification_created_callback, NULL);
    return PyLong_FromUnsignedLongLong(notification_id);
}
#endif

id_type
add_main_loop_timer(monotonic_t interval, bool repeats, timer_callback_fun callback, void *callback_data, timer_callback_fun free_callback) {
    return glfwAddTimer(interval, repeats, callback, callback_data, free_callback);
}

void
update_main_loop_timer(id_type timer_id, monotonic_t interval, bool enabled) {
    glfwUpdateTimer(timer_id, interval, enabled);
}

void
remove_main_loop_timer(id_type timer_id) {
    glfwRemoveTimer(timer_id);
}

void
run_main_loop(tick_callback_fun cb, void* cb_data) {
    glfwRunMainLoop(cb, cb_data);
}

void
stop_main_loop(void) {
#ifdef __APPLE__
    if (apple_preserve_common_context) glfwDestroyWindow(apple_preserve_common_context);
    apple_preserve_common_context = NULL;
#endif
    glfwStopMainLoop();
}


// Boilerplate {{{

static PyMethodDef module_methods[] = {
    METHODB(set_custom_cursor, METH_VARARGS),
    METHODB(create_os_window, METH_VARARGS),
    METHODB(set_default_window_icon, METH_VARARGS),
    METHODB(get_clipboard_string, METH_NOARGS),
    METHODB(get_content_scale_for_window, METH_NOARGS),
    METHODB(ring_bell, METH_NOARGS),
    METHODB(set_clipboard_string, METH_VARARGS),
    METHODB(toggle_fullscreen, METH_NOARGS),
    METHODB(toggle_maximized, METH_NOARGS),
    METHODB(change_os_window_state, METH_VARARGS),
    METHODB(glfw_window_hint, METH_VARARGS),
    METHODB(get_primary_selection, METH_NOARGS),
    METHODB(x11_display, METH_NOARGS),
    METHODB(x11_window_id, METH_O),
    METHODB(set_primary_selection, METH_VARARGS),
#ifndef __APPLE__
    METHODB(dbus_send_notification, METH_VARARGS),
#endif
    METHODB(cocoa_window_id, METH_O),
    {"glfw_init", (PyCFunction)glfw_init, METH_VARARGS, ""},
    {"glfw_terminate", (PyCFunction)glfw_terminate, METH_NOARGS, ""},
    {"glfw_get_physical_dpi", (PyCFunction)glfw_get_physical_dpi, METH_NOARGS, ""},
    {"glfw_get_key_name", (PyCFunction)glfw_get_key_name, METH_VARARGS, ""},
    {"glfw_primary_monitor_size", (PyCFunction)primary_monitor_size, METH_NOARGS, ""},
    {"glfw_primary_monitor_content_scale", (PyCFunction)primary_monitor_content_scale, METH_NOARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

void cleanup_glfw(void) {
    if (logo.pixels) free(logo.pixels);
    logo.pixels = NULL;
#ifndef __APPLE__
    release_freetype_render_context(csd_title_render_ctx);
#endif
}

// constants {{{
bool
init_glfw(PyObject *m) {
    if (PyModule_AddFunctions(m, module_methods) != 0) return false;
    register_at_exit_cleanup_func(GLFW_CLEANUP_FUNC, cleanup_glfw);
#define ADDC(n) if(PyModule_AddIntConstant(m, #n, n) != 0) return false;
    ADDC(GLFW_RELEASE);
    ADDC(GLFW_PRESS);
    ADDC(GLFW_REPEAT);
    ADDC(true); ADDC(false);
    ADDC(GLFW_IBEAM_CURSOR); ADDC(GLFW_HAND_CURSOR); ADDC(GLFW_ARROW_CURSOR);

    /* start glfw functional keys (auto generated by gen-key-constants.py do not edit) */
    ADDC(GLFW_FKEY_ESCAPE);
    ADDC(GLFW_FKEY_ENTER);
    ADDC(GLFW_FKEY_TAB);
    ADDC(GLFW_FKEY_BACKSPACE);
    ADDC(GLFW_FKEY_INSERT);
    ADDC(GLFW_FKEY_DELETE);
    ADDC(GLFW_FKEY_LEFT);
    ADDC(GLFW_FKEY_RIGHT);
    ADDC(GLFW_FKEY_UP);
    ADDC(GLFW_FKEY_DOWN);
    ADDC(GLFW_FKEY_PAGE_UP);
    ADDC(GLFW_FKEY_PAGE_DOWN);
    ADDC(GLFW_FKEY_HOME);
    ADDC(GLFW_FKEY_END);
    ADDC(GLFW_FKEY_CAPS_LOCK);
    ADDC(GLFW_FKEY_SCROLL_LOCK);
    ADDC(GLFW_FKEY_NUM_LOCK);
    ADDC(GLFW_FKEY_PRINT_SCREEN);
    ADDC(GLFW_FKEY_PAUSE);
    ADDC(GLFW_FKEY_MENU);
    ADDC(GLFW_FKEY_F1);
    ADDC(GLFW_FKEY_F2);
    ADDC(GLFW_FKEY_F3);
    ADDC(GLFW_FKEY_F4);
    ADDC(GLFW_FKEY_F5);
    ADDC(GLFW_FKEY_F6);
    ADDC(GLFW_FKEY_F7);
    ADDC(GLFW_FKEY_F8);
    ADDC(GLFW_FKEY_F9);
    ADDC(GLFW_FKEY_F10);
    ADDC(GLFW_FKEY_F11);
    ADDC(GLFW_FKEY_F12);
    ADDC(GLFW_FKEY_F13);
    ADDC(GLFW_FKEY_F14);
    ADDC(GLFW_FKEY_F15);
    ADDC(GLFW_FKEY_F16);
    ADDC(GLFW_FKEY_F17);
    ADDC(GLFW_FKEY_F18);
    ADDC(GLFW_FKEY_F19);
    ADDC(GLFW_FKEY_F20);
    ADDC(GLFW_FKEY_F21);
    ADDC(GLFW_FKEY_F22);
    ADDC(GLFW_FKEY_F23);
    ADDC(GLFW_FKEY_F24);
    ADDC(GLFW_FKEY_F25);
    ADDC(GLFW_FKEY_F26);
    ADDC(GLFW_FKEY_F27);
    ADDC(GLFW_FKEY_F28);
    ADDC(GLFW_FKEY_F29);
    ADDC(GLFW_FKEY_F30);
    ADDC(GLFW_FKEY_F31);
    ADDC(GLFW_FKEY_F32);
    ADDC(GLFW_FKEY_F33);
    ADDC(GLFW_FKEY_F34);
    ADDC(GLFW_FKEY_F35);
    ADDC(GLFW_FKEY_KP_0);
    ADDC(GLFW_FKEY_KP_1);
    ADDC(GLFW_FKEY_KP_2);
    ADDC(GLFW_FKEY_KP_3);
    ADDC(GLFW_FKEY_KP_4);
    ADDC(GLFW_FKEY_KP_5);
    ADDC(GLFW_FKEY_KP_6);
    ADDC(GLFW_FKEY_KP_7);
    ADDC(GLFW_FKEY_KP_8);
    ADDC(GLFW_FKEY_KP_9);
    ADDC(GLFW_FKEY_KP_DECIMAL);
    ADDC(GLFW_FKEY_KP_DIVIDE);
    ADDC(GLFW_FKEY_KP_MULTIPLY);
    ADDC(GLFW_FKEY_KP_SUBTRACT);
    ADDC(GLFW_FKEY_KP_ADD);
    ADDC(GLFW_FKEY_KP_ENTER);
    ADDC(GLFW_FKEY_KP_EQUAL);
    ADDC(GLFW_FKEY_KP_SEPARATOR);
    ADDC(GLFW_FKEY_KP_LEFT);
    ADDC(GLFW_FKEY_KP_RIGHT);
    ADDC(GLFW_FKEY_KP_UP);
    ADDC(GLFW_FKEY_KP_DOWN);
    ADDC(GLFW_FKEY_KP_PAGE_UP);
    ADDC(GLFW_FKEY_KP_PAGE_DOWN);
    ADDC(GLFW_FKEY_KP_HOME);
    ADDC(GLFW_FKEY_KP_END);
    ADDC(GLFW_FKEY_KP_INSERT);
    ADDC(GLFW_FKEY_KP_DELETE);
    ADDC(GLFW_FKEY_KP_BEGIN);
    ADDC(GLFW_FKEY_MEDIA_PLAY);
    ADDC(GLFW_FKEY_MEDIA_PAUSE);
    ADDC(GLFW_FKEY_MEDIA_PLAY_PAUSE);
    ADDC(GLFW_FKEY_MEDIA_REVERSE);
    ADDC(GLFW_FKEY_MEDIA_STOP);
    ADDC(GLFW_FKEY_MEDIA_FAST_FORWARD);
    ADDC(GLFW_FKEY_MEDIA_REWIND);
    ADDC(GLFW_FKEY_MEDIA_TRACK_NEXT);
    ADDC(GLFW_FKEY_MEDIA_TRACK_PREVIOUS);
    ADDC(GLFW_FKEY_MEDIA_RECORD);
    ADDC(GLFW_FKEY_LOWER_VOLUME);
    ADDC(GLFW_FKEY_RAISE_VOLUME);
    ADDC(GLFW_FKEY_MUTE_VOLUME);
    ADDC(GLFW_FKEY_LEFT_SHIFT);
    ADDC(GLFW_FKEY_LEFT_CONTROL);
    ADDC(GLFW_FKEY_LEFT_ALT);
    ADDC(GLFW_FKEY_LEFT_SUPER);
    ADDC(GLFW_FKEY_LEFT_HYPER);
    ADDC(GLFW_FKEY_LEFT_META);
    ADDC(GLFW_FKEY_RIGHT_SHIFT);
    ADDC(GLFW_FKEY_RIGHT_CONTROL);
    ADDC(GLFW_FKEY_RIGHT_ALT);
    ADDC(GLFW_FKEY_RIGHT_SUPER);
    ADDC(GLFW_FKEY_RIGHT_HYPER);
    ADDC(GLFW_FKEY_RIGHT_META);
    ADDC(GLFW_FKEY_ISO_LEVEL3_SHIFT);
    ADDC(GLFW_FKEY_ISO_LEVEL5_SHIFT);
/* end glfw functional keys */
// --- Modifiers ---------------------------------------------------------------
    ADDC(GLFW_MOD_SHIFT);
    ADDC(GLFW_MOD_CONTROL);
    ADDC(GLFW_MOD_ALT);
    ADDC(GLFW_MOD_SUPER);
    ADDC(GLFW_MOD_HYPER);
    ADDC(GLFW_MOD_META);
    ADDC(GLFW_MOD_KITTY);
    ADDC(GLFW_MOD_CAPS_LOCK);
    ADDC(GLFW_MOD_NUM_LOCK);

// --- Mouse -------------------------------------------------------------------
    ADDC(GLFW_MOUSE_BUTTON_1);
    ADDC(GLFW_MOUSE_BUTTON_2);
    ADDC(GLFW_MOUSE_BUTTON_3);
    ADDC(GLFW_MOUSE_BUTTON_4);
    ADDC(GLFW_MOUSE_BUTTON_5);
    ADDC(GLFW_MOUSE_BUTTON_6);
    ADDC(GLFW_MOUSE_BUTTON_7);
    ADDC(GLFW_MOUSE_BUTTON_8);
    ADDC(GLFW_MOUSE_BUTTON_LAST);
    ADDC(GLFW_MOUSE_BUTTON_LEFT);
    ADDC(GLFW_MOUSE_BUTTON_RIGHT);
    ADDC(GLFW_MOUSE_BUTTON_MIDDLE);


// --- Joystick ----------------------------------------------------------------
    ADDC(GLFW_JOYSTICK_1);
    ADDC(GLFW_JOYSTICK_2);
    ADDC(GLFW_JOYSTICK_3);
    ADDC(GLFW_JOYSTICK_4);
    ADDC(GLFW_JOYSTICK_5);
    ADDC(GLFW_JOYSTICK_6);
    ADDC(GLFW_JOYSTICK_7);
    ADDC(GLFW_JOYSTICK_8);
    ADDC(GLFW_JOYSTICK_9);
    ADDC(GLFW_JOYSTICK_10);
    ADDC(GLFW_JOYSTICK_11);
    ADDC(GLFW_JOYSTICK_12);
    ADDC(GLFW_JOYSTICK_13);
    ADDC(GLFW_JOYSTICK_14);
    ADDC(GLFW_JOYSTICK_15);
    ADDC(GLFW_JOYSTICK_16);
    ADDC(GLFW_JOYSTICK_LAST);


// --- Error codes -------------------------------------------------------------
    ADDC(GLFW_NOT_INITIALIZED);
    ADDC(GLFW_NO_CURRENT_CONTEXT);
    ADDC(GLFW_INVALID_ENUM);
    ADDC(GLFW_INVALID_VALUE);
    ADDC(GLFW_OUT_OF_MEMORY);
    ADDC(GLFW_API_UNAVAILABLE);
    ADDC(GLFW_VERSION_UNAVAILABLE);
    ADDC(GLFW_PLATFORM_ERROR);
    ADDC(GLFW_FORMAT_UNAVAILABLE);

// ---
    ADDC(GLFW_FOCUSED);
    ADDC(GLFW_ICONIFIED);
    ADDC(GLFW_RESIZABLE);
    ADDC(GLFW_VISIBLE);
    ADDC(GLFW_DECORATED);
    ADDC(GLFW_AUTO_ICONIFY);
    ADDC(GLFW_FLOATING);

// ---
    ADDC(GLFW_RED_BITS);
    ADDC(GLFW_GREEN_BITS);
    ADDC(GLFW_BLUE_BITS);
    ADDC(GLFW_ALPHA_BITS);
    ADDC(GLFW_DEPTH_BITS);
    ADDC(GLFW_STENCIL_BITS);
    ADDC(GLFW_ACCUM_RED_BITS);
    ADDC(GLFW_ACCUM_GREEN_BITS);
    ADDC(GLFW_ACCUM_BLUE_BITS);
    ADDC(GLFW_ACCUM_ALPHA_BITS);
    ADDC(GLFW_AUX_BUFFERS);
    ADDC(GLFW_STEREO);
    ADDC(GLFW_SAMPLES);
    ADDC(GLFW_SRGB_CAPABLE);
    ADDC(GLFW_REFRESH_RATE);
    ADDC(GLFW_DOUBLEBUFFER);

// ---
    ADDC(GLFW_CLIENT_API);
    ADDC(GLFW_CONTEXT_VERSION_MAJOR);
    ADDC(GLFW_CONTEXT_VERSION_MINOR);
    ADDC(GLFW_CONTEXT_REVISION);
    ADDC(GLFW_CONTEXT_ROBUSTNESS);
    ADDC(GLFW_OPENGL_FORWARD_COMPAT);
    ADDC(GLFW_CONTEXT_DEBUG);
    ADDC(GLFW_OPENGL_PROFILE);

// ---
    ADDC(GLFW_OPENGL_API);
    ADDC(GLFW_OPENGL_ES_API);

// ---
    ADDC(GLFW_NO_ROBUSTNESS);
    ADDC(GLFW_NO_RESET_NOTIFICATION);
    ADDC(GLFW_LOSE_CONTEXT_ON_RESET);

// ---
    ADDC(GLFW_OPENGL_ANY_PROFILE);
    ADDC(GLFW_OPENGL_CORE_PROFILE);
    ADDC(GLFW_OPENGL_COMPAT_PROFILE);

// ---
    ADDC(GLFW_CURSOR);
    ADDC(GLFW_STICKY_KEYS);
    ADDC(GLFW_STICKY_MOUSE_BUTTONS);

// ---
    ADDC(GLFW_CURSOR_NORMAL);
    ADDC(GLFW_CURSOR_HIDDEN);
    ADDC(GLFW_CURSOR_DISABLED);

// ---
    ADDC(GLFW_CONNECTED);
    ADDC(GLFW_DISCONNECTED);

return true;
#undef ADDC
}
// }}}
// }}}
