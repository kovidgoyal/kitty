/*
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "fonts.h"
#include <structmember.h>
#include "glfw-wrapper.h"
extern bool cocoa_make_window_resizable(void *w, bool);
extern void cocoa_focus_window(void *w);
extern bool cocoa_toggle_fullscreen(void *w, bool);
extern void cocoa_create_global_menu(void);
extern void cocoa_set_hide_from_tasks(void);
extern void cocoa_set_titlebar_color(void *w, color_type color);
extern void cocoa_update_nsgl_context(void* id);


#if GLFW_KEY_LAST >= MAX_KEY_COUNT
#error "glfw has too many keys, you should increase MAX_KEY_COUNT"
#endif

static GLFWcursor *standard_cursor = NULL, *click_cursor = NULL, *arrow_cursor = NULL;
static bool event_loop_blocking_with_no_timeout = false;

static void set_os_window_dpi(OSWindow *w);

void
update_os_window_viewport(OSWindow *window, bool notify_boss) {
    int w, h;
    glfwGetFramebufferSize(window->handle, &window->viewport_width, &window->viewport_height);
    glfwGetWindowSize(window->handle, &w, &h);
    double xr = window->viewport_x_ratio, yr = window->viewport_y_ratio;
    window->viewport_x_ratio = (double)window->viewport_width / (double)w;
    window->viewport_y_ratio = (double)window->viewport_height / (double)h;
    double xdpi = window->logical_dpi_x, ydpi = window->logical_dpi_y;
    set_os_window_dpi(window);
    bool dpi_changed = (xr != 0.0 && xr != window->viewport_x_ratio) || (yr != 0.0 && yr != window->viewport_y_ratio) || (xdpi != window->logical_dpi_x) || (ydpi != window->logical_dpi_y);

    window->viewport_size_dirty = true;
    window->has_pending_resizes = false;
    window->viewport_width = MAX(window->viewport_width, 100);
    window->viewport_height = MAX(window->viewport_height, 100);
    window->window_width = MAX(w, 100);
    window->window_height = MAX(h, 100);
    if (notify_boss) {
        call_boss(on_window_resize, "KiiO", window->id, window->viewport_width, window->viewport_height, dpi_changed ? Py_True : Py_False);
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
is_window_ready_for_callbacks() {
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

static int min_width = 100, min_height = 100;
// On Cocoa, glfwWaitEvents() can block indefinitely because of the way Cocoa
// works. See https://github.com/glfw/glfw/issues/1251. I have noticed this
// happening in particular with window resize events, when waiting with no
// timeout. See https://github.com/kovidgoyal/kitty/issues/458
// So we use an unlovely hack to workaround that case
#ifdef __APPLE__
#define unjam_event_loop() { if (event_loop_blocking_with_no_timeout) wakeup_main_loop(); }
#else
#define unjam_event_loop()
#endif

static void
framebuffer_size_callback(GLFWwindow *w, int width, int height) {
    if (!set_callback_window(w)) return;
    if (width >= min_width && height >= min_height) {
        OSWindow *window = global_state.callback_os_window;
        window->has_pending_resizes = true; global_state.has_pending_resizes = true;
        window->last_resize_event_at = monotonic();
        unjam_event_loop();
#ifdef __APPLE__
        // Cocoa starts a sub-loop inside wait events which means main_loop
        // stays stuck and no rendering happens. This causes the window to be
        // blank. This is particularly bad for semi-transparent windows since
        // they are rendered as invisible, so for that case we manually render.
        if (global_state.callback_os_window->is_semi_transparent) {
            make_os_window_context_current(global_state.callback_os_window);
            blank_os_window(global_state.callback_os_window);
            swap_window_buffers(global_state.callback_os_window);
        }
#endif
    } else log_error("Ignoring resize request for tiny size: %dx%d", width, height);
    global_state.callback_os_window = NULL;
}

static void
dpi_change_callback(GLFWwindow *w, float x_scale UNUSED, float y_scale UNUSED) {
    if (!set_callback_window(w)) return;
    // Ensure update_os_window_viewport() is called in the near future, it will
    // take care of DPI changes.
    OSWindow *window = global_state.callback_os_window;
    window->has_pending_resizes = true; global_state.has_pending_resizes = true;
    window->last_resize_event_at = monotonic();
    global_state.callback_os_window = NULL;
}

static void
refresh_callback(GLFWwindow *w) {
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->is_damaged = true;
    global_state.callback_os_window = NULL;
}

static void
key_callback(GLFWwindow *w, int key, int scancode, int action, int mods, const char* text, int state) {
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->cursor_blink_zero_time = monotonic();
    if (key >= 0 && key <= GLFW_KEY_LAST) {
        global_state.callback_os_window->is_key_pressed[key] = action == GLFW_RELEASE ? false : true;
    }
    if (is_window_ready_for_callbacks()) on_key_input(key, scancode, action, mods, text, state);
    global_state.callback_os_window = NULL;
}

static void
cursor_enter_callback(GLFWwindow *w, int entered) {
    if (!set_callback_window(w)) return;
    if (entered) {
        show_mouse_cursor(w);
        double now = monotonic();
        global_state.callback_os_window->last_mouse_activity_at = now;
        if (is_window_ready_for_callbacks()) enter_event();
    }
    global_state.callback_os_window = NULL;
}

static void
mouse_button_callback(GLFWwindow *w, int button, int action, int mods) {
    if (!set_callback_window(w)) return;
    show_mouse_cursor(w);
    double now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    if (button >= 0 && (unsigned int)button < arraysz(global_state.callback_os_window->mouse_button_pressed)) {
        global_state.callback_os_window->mouse_button_pressed[button] = action == GLFW_PRESS ? true : false;
        if (is_window_ready_for_callbacks()) mouse_event(button, mods, action);
    }
    global_state.callback_os_window = NULL;
}

static void
cursor_pos_callback(GLFWwindow *w, double x, double y) {
    if (!set_callback_window(w)) return;
    show_mouse_cursor(w);
    double now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    global_state.callback_os_window->cursor_blink_zero_time = now;
    global_state.callback_os_window->mouse_x = x * global_state.callback_os_window->viewport_x_ratio;
    global_state.callback_os_window->mouse_y = y * global_state.callback_os_window->viewport_y_ratio;
    if (is_window_ready_for_callbacks()) mouse_event(-1, 0, -1);
    global_state.callback_os_window = NULL;
}

static void
scroll_callback(GLFWwindow *w, double xoffset, double yoffset, int flags) {
    if (!set_callback_window(w)) return;
    show_mouse_cursor(w);
    double now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    if (is_window_ready_for_callbacks()) scroll_event(xoffset, yoffset, flags);
    global_state.callback_os_window = NULL;
}

static struct {
    id_type entries[16];
    int next_entry;
} focus_history;

#ifdef __APPLE__
static inline id_type
pop_focus_history() {
    int index = --focus_history.next_entry;
    if (index < 0) {
        focus_history.next_entry = index = 0;
    }

    id_type result = focus_history.entries[index];
    focus_history.entries[index] = 0;

    return result;
}
#endif

static inline void
push_focus_history(OSWindow *w) {
    focus_history.entries[focus_history.next_entry++] = w->id;
    focus_history.next_entry %= (sizeof(focus_history.entries) / sizeof(*(focus_history.entries)));
}

static void
window_focus_callback(GLFWwindow *w, int focused) {
    global_state.active_drag_in_window = 0;
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->is_focused = focused ? true : false;
    if (focused) {
        show_mouse_cursor(w);
        focus_in_event();
        push_focus_history(global_state.callback_os_window);
    }
    double now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    global_state.callback_os_window->cursor_blink_zero_time = now;
    if (is_window_ready_for_callbacks()) {
        WINDOW_CALLBACK(on_focus, "O", focused ? Py_True : Py_False);
        glfwUpdateIMEState(global_state.callback_os_window->handle, 1, focused, 0, 0, 0);
    }
    global_state.callback_os_window = NULL;
}

static void
drop_callback(GLFWwindow *w, int count, const char **paths) {
    if (!set_callback_window(w)) return;
    PyObject *p = PyTuple_New(count);
    if (p) {
        for (int i = 0; i < count; i++) PyTuple_SET_ITEM(p, i, PyUnicode_FromString(paths[i]));
        WINDOW_CALLBACK(on_drop, "O", p);
        Py_CLEAR(p);
    }
    global_state.callback_os_window = NULL;
}

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
    Py_ssize_t sz;
    const char *logo_data;
    if(!PyArg_ParseTuple(args, "s#ii", &(logo_data), &sz, &(logo.width), &(logo.height))) return NULL;
    sz = (MAX(logo.width * logo.height, sz));
    logo.pixels = malloc(sz);
    if (logo.pixels) memcpy(logo.pixels, logo_data, sz);
    Py_RETURN_NONE;
}


void
make_os_window_context_current(OSWindow *w) {
    GLFWwindow *current_context = glfwGetCurrentContext();
    if (w->handle != current_context) {
        glfwMakeContextCurrent(w->handle);
    }
}


static GLFWmonitor*
current_monitor(GLFWwindow *window) {
    // Find the monitor that has the maximum overlap with this window
    int nmonitors, i;
    int wx, wy, ww, wh;
    int mx, my, mw, mh;
    int overlap = 0, bestoverlap = 0;
    GLFWmonitor *bestmonitor = NULL;
    GLFWmonitor **monitors = NULL;
    const GLFWvidmode *mode;

    glfwGetWindowPos(window, &wx, &wy);
    glfwGetWindowSize(window, &ww, &wh);
    monitors = glfwGetMonitors(&nmonitors);
    if (monitors == NULL || nmonitors < 1) { PyErr_SetString(PyExc_ValueError, "No monitors connected"); return NULL; }

    for (i = 0; i < nmonitors; i++) {
        mode = glfwGetVideoMode(monitors[i]);
        glfwGetMonitorPos(monitors[i], &mx, &my);
        mw = mode->width;
        mh = mode->height;

        overlap =
            MAX(0, MIN(wx + ww, mx + mw) - MAX(wx, mx)) *
            MAX(0, MIN(wy + wh, my + mh) - MAX(wy, my));

        if (bestoverlap < overlap || bestmonitor == NULL) {
            bestoverlap = overlap;
            bestmonitor = monitors[i];
        }
    }

    return bestmonitor;
}

static inline void
get_window_dpi(GLFWwindow *w, double *x, double *y) {
    GLFWmonitor *monitor = NULL;
    if (w) monitor = current_monitor(w);
    if (monitor == NULL) { PyErr_Print(); monitor = glfwGetPrimaryMonitor(); }
    float xscale = 1, yscale = 1;
    if (monitor) glfwGetMonitorContentScale(monitor, &xscale, &yscale);
#ifdef __APPLE__
    double factor = 72.0;
#else
    double factor = 96.0;
#endif
    *x = xscale * factor;
    *y = yscale * factor;
}

static void
set_os_window_dpi(OSWindow *w) {
    get_window_dpi(w->handle, &w->logical_dpi_x, &w->logical_dpi_y);
}

static bool
toggle_fullscreen_for_os_window(OSWindow *w) {
    int width, height, x, y;
    glfwGetWindowSize(w->handle, &width, &height);
    glfwGetWindowPos(w->handle, &x, &y);
#ifdef __APPLE__
    if (OPT(macos_traditional_fullscreen)) {
        if (cocoa_toggle_fullscreen(glfwGetCocoaWindow(w->handle), true)) {
            w->before_fullscreen.is_set = true;
            w->before_fullscreen.w = width; w->before_fullscreen.h = height; w->before_fullscreen.x = x; w->before_fullscreen.y = y;
            return true;
        }
        if (w->before_fullscreen.is_set) {
            glfwSetWindowSize(w->handle, w->before_fullscreen.w, w->before_fullscreen.h);
            glfwSetWindowPos(w->handle, w->before_fullscreen.x, w->before_fullscreen.y);
        }
        return false;
    } else {
        return cocoa_toggle_fullscreen(glfwGetCocoaWindow(w->handle), false);
    }
#else
    GLFWmonitor *monitor;
    if ((monitor = glfwGetWindowMonitor(w->handle)) == NULL) {
        // make fullscreen
        monitor = current_monitor(w->handle);
        if (monitor == NULL) { PyErr_Print(); return false; }
        const GLFWvidmode* mode = glfwGetVideoMode(monitor);
        w->before_fullscreen.is_set = true;
        w->before_fullscreen.w = width; w->before_fullscreen.h = height; w->before_fullscreen.x = x; w->before_fullscreen.y = y;
        glfwGetWindowSize(w->handle, &w->before_fullscreen.w, &w->before_fullscreen.h);
        glfwGetWindowPos(w->handle, &w->before_fullscreen.x, &w->before_fullscreen.y);
        glfwSetWindowMonitor(w->handle, monitor, 0, 0, mode->width, mode->height, mode->refreshRate);
        return true;
    } else {
        // make windowed
        const GLFWvidmode* mode = glfwGetVideoMode(monitor);
        if (w->before_fullscreen.is_set) glfwSetWindowMonitor(w->handle, NULL, w->before_fullscreen.x, w->before_fullscreen.y, w->before_fullscreen.w, w->before_fullscreen.h, mode->refreshRate);
        else glfwSetWindowMonitor(w->handle, NULL, 0, 0, 600, 400, mode->refreshRate);
        return false;
    }
#endif
}


#ifdef __APPLE__
static int
filter_option(int key UNUSED, int mods, unsigned int scancode UNUSED) {
    return ((mods == GLFW_MOD_ALT) || (mods == (GLFW_MOD_ALT | GLFW_MOD_SHIFT))) ? 1 : 0;
}

static GLFWwindow *application_quit_canary = NULL;

static int
on_application_reopen(int has_visible_windows) {
    if (has_visible_windows) return true;
    set_cocoa_pending_action(NEW_OS_WINDOW);
    // Without unjam wait_for_events() blocks until the next event
    unjam_event_loop();
    return false;
}

static int
intercept_cocoa_fullscreen(GLFWwindow *w) {
    if (!OPT(macos_traditional_fullscreen) || !set_callback_window(w)) return 0;
    toggle_fullscreen_for_os_window(global_state.callback_os_window);
    global_state.callback_os_window = NULL;
    return 1;
}
#endif

void
set_titlebar_color(OSWindow *w, color_type color) {
    if (w->handle && (!w->last_titlebar_color || (w->last_titlebar_color & 0xffffff) != (color & 0xffffff))) {
        w->last_titlebar_color = (1 << 24) | (color & 0xffffff);
#ifdef __APPLE__
        cocoa_set_titlebar_color(glfwGetCocoaWindow(w->handle), color);
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
#ifdef __APPLE__
        if (OPT(macos_hide_titlebar)) glfwWindowHint(GLFW_DECORATED, false);
        glfwWindowHint(GLFW_COCOA_GRAPHICS_SWITCHING, true);
        glfwSetApplicationShouldHandleReopen(on_application_reopen);
#endif

    }

#ifndef __APPLE__
    glfwWindowHintString(GLFW_X11_INSTANCE_NAME, wm_class_name);
    glfwWindowHintString(GLFW_X11_CLASS_NAME, wm_class_class);
    glfwWindowHintString(GLFW_WAYLAND_APP_ID, wm_class_class);
    if (OPT(x11_hide_window_decorations)) {
        glfwWindowHint(GLFW_DECORATED, GLFW_FALSE);
    }
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
    glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE);
    GLFWwindow *common_context = global_state.num_os_windows ? global_state.os_windows[0].handle : NULL;
#ifdef __APPLE__
    if (is_first_window && !application_quit_canary) {
        application_quit_canary = glfwCreateWindow(100, 200, "quit_canary", NULL, NULL);
    }
    if (!common_context) common_context = application_quit_canary;
#endif

    GLFWwindow *temp_window = glfwCreateWindow(640, 480, "temp", NULL, common_context);
    if (temp_window == NULL) { fatal("Failed to create GLFW temp window! This usually happens because of old/broken OpenGL drivers. kitty requires working OpenGL 3.3 drivers."); }

    double dpi_x, dpi_y;
    get_window_dpi(temp_window, &dpi_x, &dpi_y);
    FONTS_DATA_HANDLE fonts_data = load_fonts_data(global_state.font_sz_in_pts, dpi_x, dpi_y);
    PyObject *ret = PyObject_CallFunction(get_window_size, "IIdd", fonts_data->cell_width, fonts_data->cell_height, fonts_data->logical_dpi_x, fonts_data->logical_dpi_y);
    if (ret == NULL) return NULL;
    int width = PyLong_AsLong(PyTuple_GET_ITEM(ret, 0)), height = PyLong_AsLong(PyTuple_GET_ITEM(ret, 1));
    Py_CLEAR(ret);
    // The GLFW Wayland backend cannot create and show windows separately so we
    // cannot call the pre_show_callback. See
    // https://github.com/glfw/glfw/issues/1268 It doesn't matter since there
    // is no startup notification in Wayland anyway. It amazes me that anyone
    // uses Wayland as anything other than a butt for jokes.
    if (global_state.is_wayland) glfwWindowHint(GLFW_VISIBLE, GLFW_TRUE);
    GLFWwindow *glfw_window = glfwCreateWindow(width, height, title, NULL, temp_window);
    glfwDestroyWindow(temp_window); temp_window = NULL;
    if (glfw_window == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to create GLFWwindow"); return NULL; }
    if (!global_state.is_wayland) {
        PyObject *pret = PyObject_CallFunction(pre_show_callback, "N", native_window_handle(glfw_window));
        if (pret == NULL) return NULL;
        Py_DECREF(pret);
        if (x != -1 && y != -1) glfwSetWindowPos(glfw_window, x, y);
        glfwShowWindow(glfw_window);
    }
    glfwMakeContextCurrent(glfw_window);
    if (is_first_window) {
        gl_init();
        PyObject *ret = PyObject_CallFunction(load_programs, "i", glfwGetWindowAttrib(glfw_window, GLFW_TRANSPARENT_FRAMEBUFFER));
        if (ret == NULL) return NULL;
        Py_DECREF(ret);
#ifdef __APPLE__
        cocoa_create_global_menu();
        // This needs to be done only after the first window has been created, because glfw only sets the activation policy once upon initialization.
        if (OPT(macos_hide_from_tasks)) cocoa_set_hide_from_tasks();
#endif
#define CC(dest, shape) {\
    if (!dest##_cursor) { \
        dest##_cursor = glfwCreateStandardCursor(GLFW_##shape##_CURSOR); \
        if (dest##_cursor == NULL) { log_error("Failed to create the %s mouse cursor, using default cursor.", #shape); } \
}}
    CC(standard, IBEAM); CC(click, HAND); CC(arrow, ARROW);
#undef CC
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
    w->logical_dpi_x = dpi_x; w->logical_dpi_y = dpi_y;
    w->fonts_data = fonts_data;
    w->shown_once = true;
    push_focus_history(w);
    glfwSwapInterval(OPT(sync_to_monitor) ? 1 : 0);
#ifdef __APPLE__
    if (OPT(macos_option_as_alt)) glfwSetCocoaTextInputFilter(glfw_window, filter_option);
    glfwSetCocoaToggleFullscreenIntercept(glfw_window, intercept_cocoa_fullscreen);
#endif
    send_prerendered_sprites_for_window(w);
    if (logo.pixels && logo.width && logo.height) glfwSetWindowIcon(glfw_window, 1, &logo);
    glfwSetCursor(glfw_window, standard_cursor);
    update_os_window_viewport(w, false);
    glfwSetFramebufferSizeCallback(glfw_window, framebuffer_size_callback);
    glfwSetWindowContentScaleCallback(glfw_window, dpi_change_callback);
    glfwSetWindowRefreshCallback(glfw_window, refresh_callback);
    glfwSetCursorEnterCallback(glfw_window, cursor_enter_callback);
    glfwSetMouseButtonCallback(glfw_window, mouse_button_callback);
    glfwSetScrollCallback(glfw_window, scroll_callback);
    glfwSetCursorPosCallback(glfw_window, cursor_pos_callback);
    glfwSetKeyboardCallback(glfw_window, key_callback);
    glfwSetWindowFocusCallback(glfw_window, window_focus_callback);
    glfwSetDropCallback(glfw_window, drop_callback);
#ifdef __APPLE__
    if (glfwGetCocoaWindow) cocoa_make_window_resizable(glfwGetCocoaWindow(glfw_window), OPT(macos_window_resizable));
    else log_error("Failed to load glfwGetCocoaWindow");
#endif
    double now = monotonic();
    w->is_focused = true;
    w->cursor_blink_zero_time = now;
    w->last_mouse_activity_at = now;
    w->is_semi_transparent = glfwGetWindowAttrib(w->handle, GLFW_TRANSPARENT_FRAMEBUFFER);
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
destroy_os_window(OSWindow *w) {
    if (w->handle) {
        // Ensure mouse cursor is visible and reset to default shape, needed on macOS
        show_mouse_cursor(w->handle);
        glfwSetCursor(w->handle, NULL);
        glfwDestroyWindow(w->handle);
    }
    w->handle = NULL;
#ifdef __APPLE__
    // On macOS when closing a window, any other existing windows belonging to the same application do not
    // automatically get focus, so we do it manually.
    bool change_focus = true;
    while (change_focus) {
        id_type new_focus_id = pop_focus_history();
        if (new_focus_id == 0) break;
        for (size_t i = 0; i < global_state.num_os_windows; i++) {
            OSWindow *c = global_state.os_windows + i;
            if (c->id != w->id && c->handle && c->shown_once && (c->id == new_focus_id)) {
                glfwFocusWindow(c->handle);
                change_focus = false;
                break;
            }
        }
    }
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

#ifdef __APPLE__
bool
application_quit_requested() {
    return !application_quit_canary || glfwWindowShouldClose(application_quit_canary);
}
#endif

// Global functions {{{
static void
error_callback(int error, const char* description) {
    log_error("[glfw error %d]: %s", error, description);
}


PyObject*
glfw_init(PyObject UNUSED *self, PyObject *args) {
    const char* path;
    int debug_keyboard = 0;
    if (!PyArg_ParseTuple(args, "s|p", &path, &debug_keyboard)) return NULL;
    const char* err = load_glfw(path);
    if (err) { PyErr_SetString(PyExc_RuntimeError, err); return NULL; }
    glfwSetErrorCallback(error_callback);
    glfwInitHint(GLFW_DEBUG_KEYBOARD, debug_keyboard);
    // Joysticks cause slow startup on some linux systems, see
    // https://github.com/kovidgoyal/kitty/issues/830
    glfwInitHint(GLFW_ENABLE_JOYSTICKS, 0);
    global_state.opts.debug_keyboard = debug_keyboard != 0;
#ifdef __APPLE__
    glfwInitHint(GLFW_COCOA_CHDIR_RESOURCES, 0);
    glfwInitHint(GLFW_COCOA_MENUBAR, 0);
#endif
    PyObject *ans = glfwInit() ? Py_True: Py_False;
    if (ans == Py_True) {
        OSWindow w = {0};
        set_os_window_dpi(&w);
        global_state.default_dpi.x = w.logical_dpi_x;
        global_state.default_dpi.y = w.logical_dpi_y;
    }
    Py_INCREF(ans);
    return ans;
}

PyObject*
glfw_terminate(PYNOARG) {
    glfwTerminate();
    Py_RETURN_NONE;
}

PyObject*
glfw_post_empty_event(PYNOARG) {
    glfwPostEmptyEvent();
    Py_RETURN_NONE;
}

PyObject*
glfw_poll_events(PYNOARG) {
    glfwPollEvents();
    Py_RETURN_NONE;
}

static PyObject*
get_physical_dpi(GLFWmonitor *m) {
    int width = 0, height = 0;
    glfwGetMonitorPhysicalSize(m, &width, &height);
    if (width == 0 || height == 0) { PyErr_SetString(PyExc_ValueError, "Failed to get primary monitor size"); return NULL; }
    const GLFWvidmode *vm = glfwGetVideoMode(m);
    if (vm == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to get video mode for monitor"); return NULL; }
    float dpix = vm->width / (width / 25.4);
    float dpiy = vm->height / (height / 25.4);
    return Py_BuildValue("ff", dpix, dpiy);
}

PyObject*
glfw_get_physical_dpi(PYNOARG) {
    GLFWmonitor *m = glfwGetPrimaryMonitor();
    if (m == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to get primary monitor"); return NULL; }
    return get_physical_dpi(m);
}

PyObject*
glfw_get_key_name(PyObject UNUSED *self, PyObject *args) {
    int key, scancode;
    if (!PyArg_ParseTuple(args, "ii", &key, &scancode)) return NULL;
    return Py_BuildValue("s", glfwGetKeyName(key, scancode));
}

PyObject*
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
    if(!PyArg_ParseTuple(args, "s", &title)) return NULL;
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
ring_audio_bell(OSWindow *w) {
    static double last_bell_at = -1;
    double now = monotonic();
    if (now - last_bell_at <= 0.1) return;
    last_bell_at = now;
    if (w->handle) {
        glfwWindowBell(w->handle);
    }
}

void
request_window_attention(id_type kitty_window_id, bool audio_bell) {
    OSWindow *w = os_window_for_kitty_window(kitty_window_id);
    if (w) {
        if (audio_bell) ring_audio_bell(w);
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
swap_window_buffers(OSWindow *w) {
#ifdef __APPLE__
    if (w->nsgl_ctx_updated++ < 2) {
        // Needed on Mojave for initial window render, see
        // https://github.com/kovidgoyal/kitty/issues/887
        cocoa_update_nsgl_context(glfwGetNSGLContext(w->handle));
    }
#endif
    glfwSwapBuffers(w->handle);
}

void
event_loop_wait(double timeout) {
    if (timeout < 0) { event_loop_blocking_with_no_timeout = true; glfwWaitEvents(); event_loop_blocking_with_no_timeout = false; }
    else glfwWaitEventsTimeout(timeout);
}

void
wakeup_main_loop() {
    glfwPostEmptyEvent();
}

void
mark_os_window_for_close(OSWindow* w, bool yes) {
    glfwSetWindowShouldClose(w->handle, yes);
}

bool
should_os_window_be_rendered(OSWindow* w) {
    if (glfwGetWindowAttrib(w->handle, GLFW_ICONIFIED)) return false;
    if (!glfwGetWindowAttrib(w->handle, GLFW_VISIBLE)) return false;
    return true;
}

bool
should_os_window_close(OSWindow* w) {
    return glfwWindowShouldClose(w->handle) ? true : false;
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
    float xscale, yscale;
    glfwGetMonitorContentScale(monitor, &xscale, &yscale);
    return Py_BuildValue("ff", xscale, yscale);
}

static PyObject*
x11_display(PYNOARG) {
    if (glfwGetX11Display) {
        return PyLong_FromVoidPtr(glfwGetX11Display());
    } else log_error("Failed to load glfwGetX11Display");
    Py_RETURN_NONE;
}

static PyObject*
x11_window_id(PyObject UNUSED *self, PyObject *os_wid) {
    if (glfwGetX11Window) {
        id_type os_window_id = PyLong_AsUnsignedLongLong(os_wid);
        for (size_t i = 0; i < global_state.num_os_windows; i++) {
            OSWindow *w = global_state.os_windows + i;
            if (w->id == os_window_id) return Py_BuildValue("l", (long)glfwGetX11Window(w->handle));
        }
    }
    else { PyErr_SetString(PyExc_RuntimeError, "Failed to load glfwGetX11Window"); return NULL; }
    PyErr_SetString(PyExc_ValueError, "No OSWindow with the specified id found");
    return NULL;
}

static PyObject*
get_primary_selection(PYNOARG) {
    if (glfwGetX11SelectionString) {
        return Py_BuildValue("y", glfwGetX11SelectionString());
    } else log_error("Failed to load glfwGetX11SelectionString");
    Py_RETURN_NONE;
}

static PyObject*
set_primary_selection(PyObject UNUSED *self, PyObject *args) {
    char *text;
    if (!PyArg_ParseTuple(args, "s", &text)) return NULL;
    if (glfwSetX11SelectionString) glfwSetX11SelectionString(text);
    else log_error("Failed to load glfwSetX11SelectionString");
    Py_RETURN_NONE;
}

static PyObject*
os_window_should_close(PyObject UNUSED *self, PyObject *args) {
    int q = -1001;
    id_type os_window_id;
    if (!PyArg_ParseTuple(args, "K|i", &os_window_id, &q)) return NULL;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (w->id == os_window_id) {
            if (q == -1001) {
                if (should_os_window_close(w)) Py_RETURN_TRUE;
                Py_RETURN_FALSE;
            }
            glfwSetWindowShouldClose(w->handle, q ? GLFW_TRUE : GLFW_FALSE);
            Py_RETURN_NONE;
        }
    }
    PyErr_SetString(PyExc_ValueError, "no such OSWindow");
    return NULL;
}

static PyObject*
os_window_swap_buffers(PyObject UNUSED *self, PyObject *args) {
    id_type os_window_id;
    if (!PyArg_ParseTuple(args, "K", &os_window_id)) return NULL;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (w->id == os_window_id) {
            swap_window_buffers(w); Py_RETURN_NONE;
        }
    }
    PyErr_SetString(PyExc_ValueError, "no such OSWindow");
    return NULL;
}

static PyObject*
set_smallest_allowed_resize(PyObject *self UNUSED, PyObject *args) {
    if (!PyArg_ParseTuple(args, "ii", &min_width, &min_height)) return NULL;
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
        if (gimages[i].width * gimages[i].height * 4 != sz) {
            PyErr_SetString(PyExc_ValueError, "The image data size does not match its width and height");
            return NULL;
        }
    }
#define CASE(which, dest) {\
    case which: \
        standard_cursor = glfwCreateCursor(gimages, x, y, count); \
        if (standard_cursor == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to create custom cursor"); return NULL; } \
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
get_cocoa_key_equivalent(int key, int mods, unsigned short *cocoa_key, int *cocoa_mods) {
    glfwGetCocoaKeyEquivalent(key, mods, cocoa_key, cocoa_mods);
}
#endif
// Boilerplate {{{

static PyMethodDef module_methods[] = {
    METHODB(set_custom_cursor, METH_VARARGS),
    METHODB(set_smallest_allowed_resize, METH_VARARGS),
    METHODB(create_os_window, METH_VARARGS),
    METHODB(set_default_window_icon, METH_VARARGS),
    METHODB(get_clipboard_string, METH_NOARGS),
    METHODB(get_content_scale_for_window, METH_NOARGS),
    METHODB(set_clipboard_string, METH_VARARGS),
    METHODB(toggle_fullscreen, METH_NOARGS),
    METHODB(change_os_window_state, METH_VARARGS),
    METHODB(glfw_window_hint, METH_VARARGS),
    METHODB(os_window_should_close, METH_VARARGS),
    METHODB(os_window_swap_buffers, METH_VARARGS),
    METHODB(get_primary_selection, METH_NOARGS),
    METHODB(x11_display, METH_NOARGS),
    METHODB(x11_window_id, METH_O),
    METHODB(set_primary_selection, METH_VARARGS),
    METHODB(glfw_poll_events, METH_NOARGS),
    {"glfw_init", (PyCFunction)glfw_init, METH_VARARGS, ""},
    {"glfw_terminate", (PyCFunction)glfw_terminate, METH_NOARGS, ""},
    {"glfw_post_empty_event", (PyCFunction)glfw_post_empty_event, METH_NOARGS, ""},
    {"glfw_get_physical_dpi", (PyCFunction)glfw_get_physical_dpi, METH_NOARGS, ""},
    {"glfw_get_key_name", (PyCFunction)glfw_get_key_name, METH_VARARGS, ""},
    {"glfw_primary_monitor_size", (PyCFunction)primary_monitor_size, METH_NOARGS, ""},
    {"glfw_primary_monitor_content_scale", (PyCFunction)primary_monitor_content_scale, METH_NOARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

void cleanup_glfw(void) {
    if (logo.pixels) free(logo.pixels);
    logo.pixels = NULL;
}

// constants {{{
bool
init_glfw(PyObject *m) {
    if (PyModule_AddFunctions(m, module_methods) != 0) return false;
    if (Py_AtExit(cleanup_glfw) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to register the glfw exit handler");
        return false;
    }
#define ADDC(n) if(PyModule_AddIntConstant(m, #n, n) != 0) return false;
    ADDC(GLFW_RELEASE);
    ADDC(GLFW_PRESS);
    ADDC(GLFW_REPEAT);
    ADDC(GLFW_TRUE); ADDC(GLFW_FALSE);
    ADDC(GLFW_IBEAM_CURSOR); ADDC(GLFW_HAND_CURSOR); ADDC(GLFW_ARROW_CURSOR);

// --- Keys --------------------------------------------------------------------

// --- The unknown key ---------------------------------------------------------
    ADDC(GLFW_KEY_UNKNOWN);

// --- Printable keys ----------------------------------------------------------
    ADDC(GLFW_KEY_SPACE);
    ADDC(GLFW_KEY_APOSTROPHE);
    ADDC(GLFW_KEY_COMMA);
    ADDC(GLFW_KEY_MINUS);
    ADDC(GLFW_KEY_PERIOD);
    ADDC(GLFW_KEY_SLASH);
    ADDC(GLFW_KEY_0);
    ADDC(GLFW_KEY_1);
    ADDC(GLFW_KEY_2);
    ADDC(GLFW_KEY_3);
    ADDC(GLFW_KEY_4);
    ADDC(GLFW_KEY_5);
    ADDC(GLFW_KEY_6);
    ADDC(GLFW_KEY_7);
    ADDC(GLFW_KEY_8);
    ADDC(GLFW_KEY_9);
    ADDC(GLFW_KEY_SEMICOLON);
    ADDC(GLFW_KEY_EQUAL);
    ADDC(GLFW_KEY_A);
    ADDC(GLFW_KEY_B);
    ADDC(GLFW_KEY_C);
    ADDC(GLFW_KEY_D);
    ADDC(GLFW_KEY_E);
    ADDC(GLFW_KEY_F);
    ADDC(GLFW_KEY_G);
    ADDC(GLFW_KEY_H);
    ADDC(GLFW_KEY_I);
    ADDC(GLFW_KEY_J);
    ADDC(GLFW_KEY_K);
    ADDC(GLFW_KEY_L);
    ADDC(GLFW_KEY_M);
    ADDC(GLFW_KEY_N);
    ADDC(GLFW_KEY_O);
    ADDC(GLFW_KEY_P);
    ADDC(GLFW_KEY_Q);
    ADDC(GLFW_KEY_R);
    ADDC(GLFW_KEY_S);
    ADDC(GLFW_KEY_T);
    ADDC(GLFW_KEY_U);
    ADDC(GLFW_KEY_V);
    ADDC(GLFW_KEY_W);
    ADDC(GLFW_KEY_X);
    ADDC(GLFW_KEY_Y);
    ADDC(GLFW_KEY_Z);
    ADDC(GLFW_KEY_LEFT_BRACKET);
    ADDC(GLFW_KEY_BACKSLASH);
    ADDC(GLFW_KEY_RIGHT_BRACKET);
    ADDC(GLFW_KEY_GRAVE_ACCENT);
    ADDC(GLFW_KEY_WORLD_1);
    ADDC(GLFW_KEY_WORLD_2);

// --- Function keys -----------------------------------------------------------
    ADDC(GLFW_KEY_ESCAPE);
    ADDC(GLFW_KEY_ENTER);
    ADDC(GLFW_KEY_TAB);
    ADDC(GLFW_KEY_BACKSPACE);
    ADDC(GLFW_KEY_INSERT);
    ADDC(GLFW_KEY_DELETE);
    ADDC(GLFW_KEY_RIGHT);
    ADDC(GLFW_KEY_LEFT);
    ADDC(GLFW_KEY_DOWN);
    ADDC(GLFW_KEY_UP);
    ADDC(GLFW_KEY_PAGE_UP);
    ADDC(GLFW_KEY_PAGE_DOWN);
    ADDC(GLFW_KEY_HOME);
    ADDC(GLFW_KEY_END);
    ADDC(GLFW_KEY_CAPS_LOCK);
    ADDC(GLFW_KEY_SCROLL_LOCK);
    ADDC(GLFW_KEY_NUM_LOCK);
    ADDC(GLFW_KEY_PRINT_SCREEN);
    ADDC(GLFW_KEY_PAUSE);
    ADDC(GLFW_KEY_F1);
    ADDC(GLFW_KEY_F2);
    ADDC(GLFW_KEY_F3);
    ADDC(GLFW_KEY_F4);
    ADDC(GLFW_KEY_F5);
    ADDC(GLFW_KEY_F6);
    ADDC(GLFW_KEY_F7);
    ADDC(GLFW_KEY_F8);
    ADDC(GLFW_KEY_F9);
    ADDC(GLFW_KEY_F10);
    ADDC(GLFW_KEY_F11);
    ADDC(GLFW_KEY_F12);
    ADDC(GLFW_KEY_F13);
    ADDC(GLFW_KEY_F14);
    ADDC(GLFW_KEY_F15);
    ADDC(GLFW_KEY_F16);
    ADDC(GLFW_KEY_F17);
    ADDC(GLFW_KEY_F18);
    ADDC(GLFW_KEY_F19);
    ADDC(GLFW_KEY_F20);
    ADDC(GLFW_KEY_F21);
    ADDC(GLFW_KEY_F22);
    ADDC(GLFW_KEY_F23);
    ADDC(GLFW_KEY_F24);
    ADDC(GLFW_KEY_F25);
    ADDC(GLFW_KEY_KP_0);
    ADDC(GLFW_KEY_KP_1);
    ADDC(GLFW_KEY_KP_2);
    ADDC(GLFW_KEY_KP_3);
    ADDC(GLFW_KEY_KP_4);
    ADDC(GLFW_KEY_KP_5);
    ADDC(GLFW_KEY_KP_6);
    ADDC(GLFW_KEY_KP_7);
    ADDC(GLFW_KEY_KP_8);
    ADDC(GLFW_KEY_KP_9);
    ADDC(GLFW_KEY_KP_DECIMAL);
    ADDC(GLFW_KEY_KP_DIVIDE);
    ADDC(GLFW_KEY_KP_MULTIPLY);
    ADDC(GLFW_KEY_KP_SUBTRACT);
    ADDC(GLFW_KEY_KP_ADD);
    ADDC(GLFW_KEY_KP_ENTER);
    ADDC(GLFW_KEY_KP_EQUAL);
    ADDC(GLFW_KEY_LEFT_SHIFT);
    ADDC(GLFW_KEY_LEFT_CONTROL);
    ADDC(GLFW_KEY_LEFT_ALT);
    ADDC(GLFW_KEY_LEFT_SUPER);
    ADDC(GLFW_KEY_RIGHT_SHIFT);
    ADDC(GLFW_KEY_RIGHT_CONTROL);
    ADDC(GLFW_KEY_RIGHT_ALT);
    ADDC(GLFW_KEY_RIGHT_SUPER);
    ADDC(GLFW_KEY_MENU);
    ADDC(GLFW_KEY_LAST);

// --- Modifiers ---------------------------------------------------------------
    ADDC(GLFW_MOD_SHIFT);
    ADDC(GLFW_MOD_CONTROL);
    ADDC(GLFW_MOD_ALT);
    ADDC(GLFW_MOD_SUPER);
    ADDC(GLFW_MOD_KITTY);

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
    ADDC(GLFW_OPENGL_DEBUG_CONTEXT);
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
