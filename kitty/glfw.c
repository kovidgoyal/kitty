/*
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include <structmember.h>
#include "glfw-wrapper.h"
extern bool cocoa_make_window_resizable(void *w);
extern void cocoa_create_global_menu(void);
extern void cocoa_set_titlebar_color(void *w);

#if GLFW_KEY_LAST >= MAX_KEY_COUNT
#error "glfw has too many keys, you should increase MAX_KEY_COUNT"
#endif

static GLFWcursor *standard_cursor = NULL, *click_cursor = NULL, *arrow_cursor = NULL;

void
update_os_window_viewport(OSWindow *window, bool notify_boss) {
    int w, h;
    glfwGetFramebufferSize(window->handle, &window->viewport_width, &window->viewport_height);
    glfwGetWindowSize(window->handle, &w, &h);
    double xr = window->viewport_x_ratio, yr = window->viewport_y_ratio;
    window->viewport_x_ratio = (double)window->viewport_width / (double)w;
    window->viewport_y_ratio = (double)window->viewport_height / (double)h;
    bool dpi_changed = (xr != 0.0 && xr != window->viewport_x_ratio) || (yr != 0.0 && yr != window->viewport_y_ratio);
    window->viewport_size_dirty = true;
    window->has_pending_resizes = false;
    window->viewport_width = MAX(window->viewport_width, 100);
    window->viewport_height = MAX(window->viewport_height, 100);
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
    if (glfwGetInputMode(w, GLFW_CURSOR) != GLFW_CURSOR_NORMAL) { glfwSetInputMode(w, GLFW_CURSOR, GLFW_CURSOR_NORMAL); }
}

static void
framebuffer_size_callback(GLFWwindow *w, int width, int height) {
    if (!set_callback_window(w)) return;
    if (width > 100 && height > 100) {
        OSWindow *window = global_state.callback_os_window;
        window->has_pending_resizes = true; global_state.has_pending_resizes = true;
        window->last_resize_event_at = monotonic();
    } else fprintf(stderr, "Ignoring resize request for tiny size: %dx%d\n", width, height);
    global_state.callback_os_window = NULL;
}

static void
refresh_callback(GLFWwindow *w) {
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->is_damaged = true;
    global_state.callback_os_window = NULL;
}

static void
char_mods_callback(GLFWwindow *w, unsigned int codepoint, int mods) {
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->cursor_blink_zero_time = monotonic();
    if (is_window_ready_for_callbacks()) on_text_input(codepoint, mods);
    global_state.callback_os_window = NULL;
}

static void
key_callback(GLFWwindow *w, int key, int scancode, int action, int mods) {
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->cursor_blink_zero_time = monotonic();
    if (key >= 0 && key <= GLFW_KEY_LAST) {
        global_state.callback_os_window->is_key_pressed[key] = action == GLFW_RELEASE ? false : true;
        if (is_window_ready_for_callbacks()) on_key_input(key, scancode, action, mods);
    }
    global_state.callback_os_window = NULL;
}

static void
mouse_button_callback(GLFWwindow *w, int button, int action, int mods) {
    if (!set_callback_window(w)) return;
    show_mouse_cursor(w);
    double now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    if (button >= 0 && (unsigned int)button < sizeof(global_state.callback_os_window->mouse_button_pressed)/sizeof(global_state.callback_os_window->mouse_button_pressed[0])) {
        global_state.callback_os_window->mouse_button_pressed[button] = action == GLFW_PRESS ? true : false;
        if (is_window_ready_for_callbacks()) mouse_event(button, mods);
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
    if (is_window_ready_for_callbacks()) mouse_event(-1, 0);
    global_state.callback_os_window = NULL;
}

static void
scroll_callback(GLFWwindow *w, double xoffset, double yoffset) {
    if (!set_callback_window(w)) return;
    show_mouse_cursor(w);
    double now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    if (is_window_ready_for_callbacks()) scroll_event(xoffset, yoffset);
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
    if(!PyArg_ParseTuple(args, "s#ii", &(logo.pixels), &sz, &(logo.width), &(logo.height))) return NULL;
    Py_RETURN_NONE;
}

static GLFWwindow *current_os_window_ctx = NULL;

void
make_os_window_context_current(OSWindow *w) {
    if (w->handle != current_os_window_ctx) {
        current_os_window_ctx = w->handle;
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


void
set_dpi_from_os_window(OSWindow *w) {
    GLFWmonitor *monitor = NULL;
    if (w) { monitor = current_monitor(w->handle); }
    if (monitor == NULL) monitor = glfwGetPrimaryMonitor();
    float xscale = 1, yscale = 1;
    if (monitor) glfwGetMonitorContentScale(monitor, &xscale, &yscale);
#ifdef __APPLE__
    double factor = 72.0;
#else
    double factor = 96.0;
#endif
    global_state.logical_dpi_x = xscale * factor;
    global_state.logical_dpi_y = yscale * factor;
}


static PyObject*
create_os_window(PyObject UNUSED *self, PyObject *args) {
    int width, height, x = -1, y = -1;
    char *title, *wm_class_class, *wm_class_name;
    PyObject *load_programs = NULL;
    if (!PyArg_ParseTuple(args, "iisss|Oiii", &width, &height, &title, &wm_class_name, &wm_class_class, &load_programs, &x, &y)) return NULL;
    bool is_first_window = standard_cursor == NULL;

    if (is_first_window) {
        glfwWindowHint(GLFW_VISIBLE, GLFW_FALSE);
        glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, OPENGL_REQUIRED_VERSION_MAJOR);
        glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, OPENGL_REQUIRED_VERSION_MINOR);
        glfwWindowHint(GLFW_OPENGL_PROFILE, GLFW_OPENGL_CORE_PROFILE);
        glfwWindowHint(GLFW_OPENGL_FORWARD_COMPAT, true);
        // We dont use depth and stencil buffers
        glfwWindowHint(GLFW_DEPTH_BITS, 0);
        glfwWindowHint(GLFW_STENCIL_BITS, 0);
#ifdef __APPLE__
        if (OPT(macos_hide_titlebar)) glfwWindowHint(GLFW_DECORATED, false);
        glfwWindowHint(GLFW_COCOA_GRAPHICS_SWITCHING, true);
#endif

        standard_cursor = glfwCreateStandardCursor(GLFW_IBEAM_CURSOR);
        click_cursor = glfwCreateStandardCursor(GLFW_HAND_CURSOR);
        arrow_cursor = glfwCreateStandardCursor(GLFW_ARROW_CURSOR);
        if (standard_cursor == NULL || click_cursor == NULL || arrow_cursor == NULL) {
            PyErr_SetString(PyExc_ValueError, "Failed to create standard mouse cursors"); return NULL;
        }
    }

#ifndef __APPLE__
    glfwWindowHintString(GLFW_X11_INSTANCE_NAME, wm_class_name);
    glfwWindowHintString(GLFW_X11_CLASS_NAME, wm_class_class);
#endif

    if (global_state.num_os_windows >= MAX_CHILDREN) {
        PyErr_SetString(PyExc_ValueError, "Too many windows");
        return NULL;
    }
    bool want_semi_transparent = (1.0 - OPT(background_opacity) > 0.1) ? true : false;
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER, want_semi_transparent);
    GLFWwindow *glfw_window = glfwCreateWindow(width, height, title, NULL, global_state.num_os_windows ? global_state.os_windows[0].handle : NULL);
    if (glfw_window == NULL) {
        fprintf(stderr, "Failed to create a window at size: %dx%d, using a standard size instead.\n", width, height);
        glfw_window = glfwCreateWindow(640, 400, title, NULL, global_state.num_os_windows ? global_state.os_windows[0].handle : NULL);
    }
    if (glfw_window == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to create GLFWwindow"); return NULL; }
    glfwMakeContextCurrent(glfw_window);
    if (x != -1 && y != -1) glfwSetWindowPos(glfw_window, x, y);
    current_os_window_ctx = glfw_window;
    glfwSwapInterval(OPT(sync_to_monitor) ? 1 : 0);  // a value of 1 makes mouse selection laggy
    if (is_first_window) {
        set_dpi_from_os_window(NULL);
        gl_init();
        PyObject *ret = PyObject_CallFunction(load_programs, "i", glfwGetWindowAttrib(glfw_window, GLFW_TRANSPARENT_FRAMEBUFFER));
        if (ret == NULL) return NULL;
        Py_DECREF(ret);
#ifdef __APPLE__
        cocoa_create_global_menu();
#endif
    }

    OSWindow *w = add_os_window();
    w->handle = glfw_window;
    update_os_window_references();
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        // On some platforms (macOS) newly created windows dont get the initial focus in event
        OSWindow *q = global_state.os_windows + i;
        q->is_focused = q == w ? true : false;
    }
    if (logo.pixels && logo.width && logo.height) glfwSetWindowIcon(glfw_window, 1, &logo);
    glfwSetCursor(glfw_window, standard_cursor);
    update_os_window_viewport(w, false);
    glfwSetFramebufferSizeCallback(glfw_window, framebuffer_size_callback);
    glfwSetWindowRefreshCallback(glfw_window, refresh_callback);
    glfwSetCharModsCallback(glfw_window, char_mods_callback);
    glfwSetMouseButtonCallback(glfw_window, mouse_button_callback);
    glfwSetScrollCallback(glfw_window, scroll_callback);
    glfwSetCursorPosCallback(glfw_window, cursor_pos_callback);
    glfwSetKeyCallback(glfw_window, key_callback);
    glfwSetWindowFocusCallback(glfw_window, window_focus_callback);
    glfwSetDropCallback(glfw_window, drop_callback);
#ifdef __APPLE__
    if (OPT(macos_hide_titlebar)) {
        if (glfwGetCocoaWindow) { if (!cocoa_make_window_resizable(glfwGetCocoaWindow(glfw_window))) { PyErr_Print(); } }
        else fprintf(stderr, "Failed to load glfwGetCocoaWindow\n");
    }
    cocoa_set_titlebar_color(glfwGetCocoaWindow(glfw_window));
#endif
    double now = monotonic();
    w->is_focused = true;
    w->cursor_blink_zero_time = now;
    w->last_mouse_activity_at = now;
    w->is_semi_transparent = glfwGetWindowAttrib(w->handle, GLFW_TRANSPARENT_FRAMEBUFFER);
    if (want_semi_transparent && !w->is_semi_transparent) {
        static bool warned = false;
        if (!warned) {
            fprintf(stderr, "Failed to enable transparency. This happens when your desktop environment does not support compositing.\n");
            warned = true;
        }
    }
    return PyLong_FromUnsignedLongLong(w->id);
}

static PyObject*
show_window(PyObject UNUSED *self, PyObject *args) {
    id_type os_window_id;
    int yes = 1;
    bool dpi_changed = false;
    if (!PyArg_ParseTuple(args, "K|p", &os_window_id, &yes)) return NULL;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (w->id == os_window_id) {
            if (yes) {
                bool first_show = !w->shown_once;
                glfwShowWindow(w->handle);
                w->shown_once = true;
                push_focus_history(w);
                if (first_show) {
                    double before_x = global_state.logical_dpi_x, before_y = global_state.logical_dpi_y;
                    set_dpi_from_os_window(w);
                    dpi_changed = before_x != global_state.logical_dpi_x || before_y != global_state.logical_dpi_y;
                    w->has_pending_resizes = true;
                    global_state.has_pending_resizes = true;
                }
            } else glfwHideWindow(w->handle);
            break;
        }
    }
    if (dpi_changed) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

void
destroy_os_window(OSWindow *w) {
    if (w->handle) {
        glfwDestroyWindow(w->handle);
        if (current_os_window_ctx == w->handle) current_os_window_ctx = NULL;
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

// Global functions {{{
static void
error_callback(int error, const char* description) {
    fprintf(stderr, "[glfw error %d]: %s\n", error, description);
}


PyObject*
glfw_init(PyObject UNUSED *self, PyObject *args) {
    const char* path;
    if (!PyArg_ParseTuple(args, "s", &path)) return NULL;
    const char* err = load_glfw(path);
    if (err) { PyErr_SetString(PyExc_RuntimeError, err); return NULL; }
    glfwSetErrorCallback(error_callback);
#ifdef __APPLE__
    glfwInitHint(GLFW_COCOA_CHDIR_RESOURCES, 0);
    glfwInitHint(GLFW_COCOA_MENUBAR, 0);
#endif
    PyObject *ans = glfwInit() ? Py_True: Py_False;
    Py_INCREF(ans);
    return ans;
}

PyObject*
glfw_terminate(PyObject UNUSED *self) {
    glfwTerminate();
    Py_RETURN_NONE;
}

PyObject*
glfw_wait_events(PyObject UNUSED *self, PyObject *args) {
    double time = -1;
    if (PyTuple_GET_SIZE(args) > 0) {
        time = PyFloat_AsDouble(PyTuple_GET_ITEM(args, 0));
        if (PyErr_Occurred()) PyErr_Clear();
    }
    if (time < 0) glfwWaitEvents();
    else glfwWaitEventsTimeout(time);
    Py_RETURN_NONE;
}

PyObject*
glfw_post_empty_event(PyObject UNUSED *self) {
    glfwPostEmptyEvent();
    Py_RETURN_NONE;
}

PyObject*
glfw_poll_events(PyObject UNUSED *self) {
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
glfw_get_physical_dpi(PyObject UNUSED *self) {
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
get_clipboard_string(PyObject UNUSED *self) {
    OSWindow *w = current_os_window();
    if (w) return Py_BuildValue("s", glfwGetClipboardString(w->handle));
    return Py_BuildValue("s", "");
}

static PyObject*
get_content_scale_for_window(PyObject UNUSED *self) {
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
toggle_fullscreen(PyObject UNUSED *self) {
    GLFWmonitor *monitor;
    OSWindow *w = current_os_window();
    if (!w) Py_RETURN_NONE;
    if ((monitor = glfwGetWindowMonitor(w->handle)) == NULL) {
        // make fullscreen
        monitor = current_monitor(w->handle);
        if (monitor == NULL) return NULL;
        const GLFWvidmode* mode = glfwGetVideoMode(monitor);
        w->before_fullscreen.is_set = true;
        glfwGetWindowSize(w->handle, &w->before_fullscreen.w, &w->before_fullscreen.h);
        glfwGetWindowPos(w->handle, &w->before_fullscreen.x, &w->before_fullscreen.y);
        glfwSetWindowMonitor(w->handle, monitor, 0, 0, mode->width, mode->height, mode->refreshRate);
        Py_RETURN_TRUE;
    } else {
        // make windowed
        const GLFWvidmode* mode = glfwGetVideoMode(monitor);
        if (w->before_fullscreen.is_set) glfwSetWindowMonitor(w->handle, NULL, w->before_fullscreen.x, w->before_fullscreen.y, w->before_fullscreen.w, w->before_fullscreen.h, mode->refreshRate);
        else glfwSetWindowMonitor(w->handle, NULL, 0, 0, 600, 400, mode->refreshRate);
        Py_RETURN_FALSE;
    }
}

void
ring_audio_bell(OSWindow *w) {
    static double last_bell_at = -1;
    double now = monotonic();
    if (now - last_bell_at <= 0.1) return;
    last_bell_at = now;
    if (w->handle) {
        glfwWindowBell(w->handle, OPT(x11_bell_volume));
    }
}

void
request_window_attention(id_type kitty_window_id, bool audio_bell) {
    OSWindow *w = os_window_for_kitty_window(kitty_window_id);
    if (w) {
        if (audio_bell) ring_audio_bell(w);
        glfwRequestWindowAttention(w->handle);
        glfwPostEmptyEvent();
    }
}

void
set_os_window_title(OSWindow *w, const char *title) {
    glfwSetWindowTitle(w->handle, title);
}

void
hide_mouse(OSWindow *w) {
    if (glfwGetInputMode(w->handle, GLFW_CURSOR) != GLFW_CURSOR_HIDDEN) {
        glfwSetInputMode(w->handle, GLFW_CURSOR, GLFW_CURSOR_HIDDEN);
    }
}

void
swap_window_buffers(OSWindow *w) {
    glfwSwapBuffers(w->handle);
}

void
event_loop_wait(double timeout) {
    if (timeout < 0) glfwWaitEvents();
    else if (timeout > 0) glfwWaitEventsTimeout(timeout);
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
primary_monitor_size(PyObject UNUSED *self) {
    GLFWmonitor* monitor = glfwGetPrimaryMonitor();
    const GLFWvidmode* mode = glfwGetVideoMode(monitor);
    return Py_BuildValue("ii", mode->width, mode->height);
}

static PyObject*
primary_monitor_content_scale(PyObject UNUSED *self) {
    GLFWmonitor* monitor = glfwGetPrimaryMonitor();
    float xscale, yscale;
    glfwGetMonitorContentScale(monitor, &xscale, &yscale);
    return Py_BuildValue("ff", xscale, yscale);
}

static PyObject*
x11_display(PyObject UNUSED *self) {
    if (glfwGetX11Display) {
        return PyLong_FromVoidPtr(glfwGetX11Display());
    } else fprintf(stderr, "Failed to load glfwGetX11Display\n");
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
get_primary_selection(PyObject UNUSED *self) {
    if (glfwGetX11SelectionString) {
        return Py_BuildValue("y", glfwGetX11SelectionString());
    } else fprintf(stderr, "Failed to load glfwGetX11SelectionString\n");
    Py_RETURN_NONE;
}

static PyObject*
set_primary_selection(PyObject UNUSED *self, PyObject *args) {
    char *text;
    if (!PyArg_ParseTuple(args, "s", &text)) return NULL;
    if (glfwSetX11SelectionString) glfwSetX11SelectionString(text);
    else fprintf(stderr, "Failed to load glfwSetX11SelectionString\n");
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

// Boilerplate {{{

static PyMethodDef module_methods[] = {
    METHODB(create_os_window, METH_VARARGS),
    METHODB(set_default_window_icon, METH_VARARGS),
    METHODB(get_clipboard_string, METH_NOARGS),
    METHODB(get_content_scale_for_window, METH_NOARGS),
    METHODB(set_clipboard_string, METH_VARARGS),
    METHODB(toggle_fullscreen, METH_NOARGS),
    METHODB(show_window, METH_VARARGS),
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
    {"glfw_wait_events", (PyCFunction)glfw_wait_events, METH_VARARGS, ""},
    {"glfw_post_empty_event", (PyCFunction)glfw_post_empty_event, METH_NOARGS, ""},
    {"glfw_get_physical_dpi", (PyCFunction)glfw_get_physical_dpi, METH_NOARGS, ""},
    {"glfw_get_key_name", (PyCFunction)glfw_get_key_name, METH_VARARGS, ""},
    {"glfw_primary_monitor_size", (PyCFunction)primary_monitor_size, METH_NOARGS, ""},
    {"glfw_primary_monitor_content_scale", (PyCFunction)primary_monitor_content_scale, METH_NOARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

// constants {{{
bool
init_glfw(PyObject *m) {
    if (PyModule_AddFunctions(m, module_methods) != 0) return false;
#define ADDC(n) if(PyModule_AddIntConstant(m, #n, n) != 0) return false;
    ADDC(GLFW_RELEASE);
    ADDC(GLFW_PRESS);
    ADDC(GLFW_REPEAT);
    ADDC(GLFW_TRUE); ADDC(GLFW_FALSE);

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
