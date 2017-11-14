/*
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include <structmember.h>
#include <GLFW/glfw3.h>
#if defined(__APPLE__)
#define GLFW_EXPOSE_NATIVE_COCOA
#include <GLFW/glfw3native.h>
extern bool cocoa_make_window_resizable(void *w);
#endif

#if GLFW_VERSION_MAJOR < 3 || (GLFW_VERSION_MAJOR == 3 && GLFW_VERSION_MINOR < 2)
#error "glfw >= 3.2 required"
#endif

#if GLFW_VERSION_MAJOR > 3 || (GLFW_VERSION_MAJOR == 3 && GLFW_VERSION_MINOR > 2)
#define has_request_attention
#define has_init_hint_string
#define has_content_scale_query
#endif

#if GLFW_KEY_LAST >= MAX_KEY_COUNT
#error "glfw has too many keys, you should increase MAX_KEY_COUNT"
#endif

static GLFWcursor *standard_cursor = NULL, *click_cursor = NULL, *arrow_cursor = NULL;

#define GLFW_WINDOW(w) ((GLFWwindow*)((w)->handle))

static void 
update_viewport(OSWindow *window) {
    int w, h;
    glfwGetFramebufferSize(GLFW_WINDOW(window), &window->viewport_width, &window->viewport_height);
    glfwGetWindowSize(GLFW_WINDOW(window), &w, &h);
    window->viewport_x_ratio = (double)window->viewport_width / (double)w;
    window->viewport_y_ratio = (double)window->viewport_height / (double)h;
    window->viewport_size_dirty = true;
}

// callbacks {{{

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

#define WINDOW_CALLBACK(name, fmt, ...) call_boss(name, "K" fmt, global_state.callback_os_window->window_id, __VA_ARGS__)

static void 
framebuffer_size_callback(GLFWwindow *w, int width, int height) {
    if (!set_callback_window(w)) return;
    if (width > 100 && height > 100) {
        update_viewport(global_state.callback_os_window);
        WINDOW_CALLBACK(on_window_resize, "ii", width, height);
        glfwPostEmptyEvent();
    } else fprintf(stderr, "Ignoring resize request for tiny size: %dx%d\n", width, height);
    global_state.callback_os_window = NULL;
}

static void 
char_mods_callback(GLFWwindow *w, unsigned int codepoint, int mods) {
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->cursor_blink_zero_time = monotonic();
    on_text_input(codepoint, mods);
    global_state.callback_os_window = NULL;
}

static void 
key_callback(GLFWwindow *w, int key, int scancode, int action, int mods) {
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->cursor_blink_zero_time = monotonic();
    if (key >= 0 && key <= GLFW_KEY_LAST) {
        global_state.callback_os_window->is_key_pressed[key] = action == GLFW_RELEASE ? false : true;
        on_key_input(key, scancode, action, mods);
    }
    global_state.callback_os_window = NULL;
}

static void 
mouse_button_callback(GLFWwindow *w, int button, int action, int mods) {
    if (!set_callback_window(w)) return;
    if (glfwGetInputMode(w, GLFW_CURSOR) != GLFW_CURSOR_NORMAL) { glfwSetInputMode(w, GLFW_CURSOR, GLFW_CURSOR_NORMAL); } 
    double now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    if (button >= 0 && (unsigned int)button < sizeof(global_state.callback_os_window->mouse_button_pressed)/sizeof(global_state.callback_os_window->mouse_button_pressed[0])) {
        global_state.callback_os_window->mouse_button_pressed[button] = action == GLFW_PRESS ? true : false;
        mouse_event(button, mods);
    }
    global_state.callback_os_window = NULL;
}

static void 
cursor_pos_callback(GLFWwindow *w, double x, double y) {
    if (!set_callback_window(w)) return;
    if (glfwGetInputMode(w, GLFW_CURSOR) != GLFW_CURSOR_NORMAL) { glfwSetInputMode(w, GLFW_CURSOR, GLFW_CURSOR_NORMAL); } 
    double now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    global_state.callback_os_window->cursor_blink_zero_time = now;
    global_state.callback_os_window->mouse_x = x * global_state.callback_os_window->viewport_x_ratio;
    global_state.callback_os_window->mouse_y = y * global_state.callback_os_window->viewport_y_ratio;
    mouse_event(-1, 0);
    global_state.callback_os_window = NULL;
}

static void 
scroll_callback(GLFWwindow *w, double xoffset, double yoffset) {
    if (!set_callback_window(w)) return;
    if (glfwGetInputMode(w, GLFW_CURSOR) != GLFW_CURSOR_NORMAL) { glfwSetInputMode(w, GLFW_CURSOR, GLFW_CURSOR_NORMAL); } 
    double now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    scroll_event(xoffset, yoffset);
    global_state.callback_os_window = NULL;
}

static void 
window_focus_callback(GLFWwindow *w, int focused) {
    if (!set_callback_window(w)) return;
    global_state.callback_os_window->is_focused = focused ? true : false;
    if (focused) {
        global_state.focussed_os_window = global_state.callback_os_window;
    } else if (global_state.focussed_os_window == global_state.callback_os_window) global_state.focussed_os_window = NULL;
    double now = monotonic();
    global_state.callback_os_window->last_mouse_activity_at = now;
    global_state.callback_os_window->cursor_blink_zero_time = now;
    WINDOW_CALLBACK(on_focus, "O", focused ? Py_True : Py_False);
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

static PyObject*
create_new_os_window(PyObject UNUSED *self, PyObject *args) {
    int width, height;
    char *title;
    if (!PyArg_ParseTuple(args, "iis", &width, &height, &title)) return NULL;

    if (standard_cursor == NULL) {
        standard_cursor = glfwCreateStandardCursor(GLFW_IBEAM_CURSOR);
        click_cursor = glfwCreateStandardCursor(GLFW_HAND_CURSOR);
        arrow_cursor = glfwCreateStandardCursor(GLFW_ARROW_CURSOR);
        if (standard_cursor == NULL || click_cursor == NULL || arrow_cursor == NULL) {
            Py_CLEAR(self); PyErr_SetString(PyExc_ValueError, "Failed to create standard mouse cursors"); return NULL; }
    }

    if (global_state.num_os_windows >= MAX_CHILDREN) {
        PyErr_SetString(PyExc_ValueError, "Too many windows");
        return NULL;
    }
    GLFWwindow *glfw_window = glfwCreateWindow(width, height, title, NULL, global_state.num_os_windows ? global_state.os_windows[0].handle : NULL);
    if (glfw_window == NULL) { Py_CLEAR(self); PyErr_SetString(PyExc_ValueError, "Failed to create GLFWwindow"); return NULL; }
    OSWindow *w = global_state.os_windows + global_state.num_os_windows++;
    w->window_id = global_state.window_counter++;
    glfwSetWindowUserPointer(glfw_window, w);
    w->handle = glfw_window;
    glfwSetCursor(glfw_window, standard_cursor);
    w->viewport_size_dirty = true;
    update_viewport(w);
    glfwSetFramebufferSizeCallback(glfw_window, framebuffer_size_callback);
    glfwSetCharModsCallback(glfw_window, char_mods_callback);
    glfwSetMouseButtonCallback(glfw_window, mouse_button_callback);
    glfwSetScrollCallback(glfw_window, scroll_callback);
    glfwSetCursorPosCallback(glfw_window, cursor_pos_callback);
    glfwSetKeyCallback(glfw_window, key_callback);
    glfwSetWindowFocusCallback(glfw_window, window_focus_callback);
#ifdef __APPLE__
    if (OPT(macos_hide_titlebar)) {
        if (!cocoa_make_window_resizable(glfwGetCocoaWindow(glfw_window))) { PyErr_Print(); }
    }
#endif
    return PyLong_FromUnsignedLongLong(w->window_id);
}

// Global functions {{{
static void 
error_callback(int error, const char* description) {
    fprintf(stderr, "[glfw error %d]: %s\n", error, description);
}


PyObject*
glfw_init(PyObject UNUSED *self) {
    glfwSetErrorCallback(error_callback);
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
glfw_window_hint(PyObject UNUSED *self, PyObject *args) {
    int hint, value;
    if (!PyArg_ParseTuple(args, "ii", &hint, &value)) return NULL;
    glfwWindowHint(hint, value);
    Py_RETURN_NONE;
}

PyObject* 
glfw_swap_interval(PyObject UNUSED *self, PyObject *args) {
    int value;
    if (!PyArg_ParseTuple(args, "i", &value)) return NULL;
    glfwSwapInterval(value);
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
glfw_init_hint_string(PyObject UNUSED *self, PyObject *args) {
    int hint_id;
    char *hint;
    if (!PyArg_ParseTuple(args, "is", &hint_id, &hint)) return NULL;
#ifdef has_init_hint_string
    glfwInitHintString(hint_id, hint);
#endif
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
#ifdef has_content_scale_query
    OSWindow *w = global_state.callback_os_window ? global_state.callback_os_window : global_state.os_windows;
    float xscale, yscale;
    glfwGetWindowContentScale(w->handle, &xscale, &yscale);
    return Py_BuildValue("ff", xscale, yscale);
#else
    (void)self;
    PyErr_SetString(PyExc_NotImplementedError, "glfw version is too old");
    return NULL;
#endif
}

static PyObject*
set_clipboard_string(PyObject UNUSED *self, PyObject *args) {
    char *title;
    if(!PyArg_ParseTuple(args, "s", &title)) return NULL;
    OSWindow *w = current_os_window();
    if (w) glfwSetClipboardString(w->handle, title);
    Py_RETURN_NONE;
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
request_window_attention(unsigned int kitty_window_id) {
    OSWindow *w = os_window_for_kitty_window(kitty_window_id);
    if (w) {
#ifdef has_request_attention
        glfwRequestWindowAttention(w->handle);
#endif
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

void
make_window_context_current(OSWindow *w) { 
    glfwMakeContextCurrent(w->handle); 
    if (w->viewport_size_dirty) update_viewport_size(w->viewport_width, w->viewport_height);
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
#ifdef has_content_scale_query
    GLFWmonitor* monitor = glfwGetPrimaryMonitor();
    float xscale, yscale;
    glfwGetMonitorContentScale(monitor, &xscale, &yscale);
    return Py_BuildValue("ff", xscale, yscale);
#else
    PyErr_SetString(PyExc_NotImplementedError, "glfw version is too old");
    return NULL;
#endif
}

// Boilerplate {{{

static PyMethodDef module_methods[] = {
    METHODB(create_new_os_window, METH_VARARGS),
    METHODB(get_clipboard_string, METH_NOARGS),
    METHODB(get_content_scale_for_window, METH_NOARGS),
    METHODB(set_clipboard_string, METH_VARARGS),
    METHODB(toggle_fullscreen, METH_NOARGS),
    {"glfw_init", (PyCFunction)glfw_init, METH_NOARGS, ""}, 
    {"glfw_terminate", (PyCFunction)glfw_terminate, METH_NOARGS, ""}, 
    {"glfw_window_hint", (PyCFunction)glfw_window_hint, METH_VARARGS, ""}, 
    {"glfw_swap_interval", (PyCFunction)glfw_swap_interval, METH_VARARGS, ""}, 
    {"glfw_wait_events", (PyCFunction)glfw_wait_events, METH_VARARGS, ""}, 
    {"glfw_post_empty_event", (PyCFunction)glfw_post_empty_event, METH_NOARGS, ""}, 
    {"glfw_get_physical_dpi", (PyCFunction)glfw_get_physical_dpi, METH_NOARGS, ""}, 
    {"glfw_get_key_name", (PyCFunction)glfw_get_key_name, METH_VARARGS, ""}, 
    {"glfw_init_hint_string", (PyCFunction)glfw_init_hint_string, METH_VARARGS, ""}, 
    {"glfw_primary_monitor_size", (PyCFunction)primary_monitor_size, METH_NOARGS, ""}, 
    {"glfw_primary_monitor_content_scale", (PyCFunction)primary_monitor_content_scale, METH_NOARGS, ""}, 
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

// constants {{{
bool
init_glfw(PyObject *m) {
    if (PyModule_AddFunctions(m, module_methods) != 0) return false;
#define ADDC(n) if(PyModule_AddIntConstant(m, #n, n) != 0) return false;
#ifdef GLFW_X11_WM_CLASS_NAME
    ADDC(GLFW_X11_WM_CLASS_NAME)
    ADDC(GLFW_X11_WM_CLASS_CLASS)
#endif
    ADDC(GLFW_RELEASE);
    ADDC(GLFW_PRESS);
    ADDC(GLFW_REPEAT);

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
