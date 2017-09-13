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
#endif

#if GLFW_VERSION_MAJOR < 3 || (GLFW_VERSION_MAJOR == 3 && GLFW_VERSION_MINOR < 2)
#error "glfw >= 3.2 required"
#endif

extern GlobalState global_state;
#define MAX_WINDOWS 256

#define CALLBACK(name, fmt, ...) \
    if ((name) != NULL) { \
        PyObject *_pyret = PyObject_CallFunction((name), fmt, __VA_ARGS__); \
        if (_pyret == NULL) PyErr_Print(); \
        else Py_DECREF(_pyret); \
    } 

#define WINDOW_CALLBACK(name, fmt, ...) \
    CALLBACK(the_window->name, "O" fmt, the_window, __VA_ARGS__);

typedef struct {
    PyObject_HEAD

    GLFWwindow *window;
    PyObject *framebuffer_size_callback, *char_mods_callback, *key_callback, *mouse_button_callback, *scroll_callback, *cursor_pos_callback, *window_focus_callback;
    GLFWcursor *standard_cursor, *click_cursor;
} WindowWrapper;

// callbacks {{{
static WindowWrapper* the_window = NULL;
update_viewport_size_func update_viewport_size = NULL;

static void 
framebuffer_size_callback(GLFWwindow UNUSED *w, int width, int height) {
    if (width > 100 && height > 100) {
        update_viewport_size(width, height);
        global_state.viewport_width = width; global_state.viewport_height = height;
        WINDOW_CALLBACK(framebuffer_size_callback, "ii", width, height);
        glfwPostEmptyEvent();
    } else fprintf(stderr, "Ignoring resize request for tiny size: %dx%d\n", width, height);
}

static void 
char_mods_callback(GLFWwindow UNUSED *w, unsigned int codepoint, int mods) {
    global_state.cursor_blink_zero_time = monotonic();
    WINDOW_CALLBACK(char_mods_callback, "Ii", codepoint, mods);
}

static void 
key_callback(GLFWwindow UNUSED *w, int key, int scancode, int action, int mods) {
    global_state.cursor_blink_zero_time = monotonic();
    WINDOW_CALLBACK(key_callback, "iiii", key, scancode, action, mods);
}

static void 
mouse_button_callback(GLFWwindow *w, int button, int action, int mods) {
    if (!global_state.mouse_visible) { glfwSetInputMode(w, GLFW_CURSOR, GLFW_CURSOR_NORMAL); global_state.mouse_visible = true; } 
    double now = monotonic();
    global_state.last_mouse_activity_at = now;
    WINDOW_CALLBACK(mouse_button_callback, "iii", button, action, mods);
}

static void 
scroll_callback(GLFWwindow *w, double xoffset, double yoffset) {
    if (!global_state.mouse_visible) { glfwSetInputMode(w, GLFW_CURSOR, GLFW_CURSOR_NORMAL); global_state.mouse_visible = true; } 
    double now = monotonic();
    global_state.last_mouse_activity_at = now;
    WINDOW_CALLBACK(scroll_callback, "dd", xoffset, yoffset);
}

static void 
cursor_pos_callback(GLFWwindow *w, double x, double y) {
    if (!global_state.mouse_visible) { glfwSetInputMode(w, GLFW_CURSOR, GLFW_CURSOR_NORMAL); global_state.mouse_visible = true; } 
    double now = monotonic();
    global_state.last_mouse_activity_at = now;
    global_state.cursor_blink_zero_time = now;
    WINDOW_CALLBACK(cursor_pos_callback, "dd", x, y);
}

void
hide_mouse_cursor() {
    glfwSetInputMode(the_window->window, GLFW_CURSOR, GLFW_CURSOR_HIDDEN);
    global_state.mouse_visible = false;
}

static void 
window_focus_callback(GLFWwindow UNUSED *w, int focused) {
    global_state.application_focused = focused ? true : false;
    double now = monotonic();
    global_state.last_mouse_activity_at = now;
    global_state.cursor_blink_zero_time = now;
    WINDOW_CALLBACK(window_focus_callback, "O", focused ? Py_True : Py_False);
}
// }}}

static PyObject*
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    WindowWrapper *self;
    char *title;
    int width, height;
    if (!PyArg_ParseTuple(args, "iis", &width, &height, &title)) return NULL;
    if (the_window != NULL) { PyErr_SetString(PyExc_ValueError, "Only one glfw window is supported");  return NULL; }

    self = (WindowWrapper *)type->tp_alloc(type, 0);
    if (self != NULL) {
        the_window = self;
        self->window = glfwCreateWindow(width, height, title, NULL, NULL);
        if (self->window == NULL) { Py_CLEAR(self); the_window = NULL; PyErr_SetString(PyExc_ValueError, "Failed to create GLFWwindow"); return NULL; }
        global_state.viewport_width = width; global_state.viewport_height = height;
        self->standard_cursor = glfwCreateStandardCursor(GLFW_IBEAM_CURSOR);
        self->click_cursor = glfwCreateStandardCursor(GLFW_HAND_CURSOR);
        if (self->standard_cursor == NULL || self->click_cursor == NULL) { Py_CLEAR(self); PyErr_SetString(PyExc_ValueError, "Failed to create standard mouse cursors"); return NULL; }
        glfwSetFramebufferSizeCallback(self->window, framebuffer_size_callback);
        glfwSetCharModsCallback(self->window, char_mods_callback);
        glfwSetKeyCallback(self->window, key_callback);
        glfwSetMouseButtonCallback(self->window, mouse_button_callback);
        glfwSetScrollCallback(self->window, scroll_callback);
        glfwSetCursorPosCallback(self->window, cursor_pos_callback);
        glfwSetWindowFocusCallback(self->window, window_focus_callback);
    }
    return (PyObject*)self;
}
 
// Global functions {{{
static PyObject *error_callback = NULL;

static void 
cb_error_callback(int error, const char* description) {
    CALLBACK(error_callback, "is", error, description) else fprintf(stderr, "[glfw error]: %s\n", description);
}

PyObject*
glfw_set_error_callback(PyObject UNUSED *self, PyObject *callback) {
    Py_CLEAR(error_callback);
    error_callback = callback;
    Py_INCREF(callback);
    Py_RETURN_NONE;
}


PyObject*
glfw_init(PyObject UNUSED *self) {
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
#ifdef glfwInitHintString
    glfwInitHintString(hint_id, hint);
#endif
    Py_RETURN_NONE;
}


// }}}

static void
dealloc(WindowWrapper* self) {
    the_window = NULL;
    Py_CLEAR(self->framebuffer_size_callback); Py_CLEAR(self->char_mods_callback); Py_CLEAR(self->key_callback); Py_CLEAR(self->mouse_button_callback); Py_CLEAR(self->scroll_callback); Py_CLEAR(self->cursor_pos_callback); Py_CLEAR(self->window_focus_callback);
    if (self->window != NULL) glfwDestroyWindow(self->window);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
swap_buffers(WindowWrapper *self) {
    glfwSwapBuffers(self->window);
    Py_RETURN_NONE;
}

static PyObject*
make_context_current(WindowWrapper *self) {
    glfwMakeContextCurrent(self->window);
    Py_RETURN_NONE;
}

static PyObject*
window_id(WindowWrapper *self) {
    return PyLong_FromVoidPtr(self->window);
}

static PyObject*
should_close(WindowWrapper *self) {
    PyObject *ans = glfwWindowShouldClose(self->window) ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

static PyObject*
get_clipboard_string(WindowWrapper *self) {
    return Py_BuildValue("s", glfwGetClipboardString(self->window));
}

static PyObject*
get_cursor_pos(WindowWrapper *self) {
    double x=0, y=0;
    glfwGetCursorPos(self->window, &x, &y);
    return Py_BuildValue("dd", x, y);
}

static PyObject*
set_should_close(WindowWrapper *self, PyObject *args) {
    int c;
    if (!PyArg_ParseTuple(args, "p", &c)) return NULL;
    glfwSetWindowShouldClose(self->window, c);
    Py_RETURN_NONE;
}

static PyObject*
set_input_mode(WindowWrapper *self, PyObject *args) {
    int which, value;
    if (!PyArg_ParseTuple(args, "ii", &which, &value)) return NULL;
    glfwSetInputMode(self->window, which, value);
    Py_RETURN_NONE;
}

static PyObject*
is_key_pressed(WindowWrapper *self, PyObject *args) {
    int c;
    if (!PyArg_ParseTuple(args, "i", &c)) return NULL;
    PyObject *ans = glfwGetKey(self->window, c) == GLFW_PRESS ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

static PyObject*
set_click_cursor(WindowWrapper *self, PyObject *args) {
    int c;
    if (!PyArg_ParseTuple(args, "p", &c)) return NULL;
    glfwSetCursor(self->window, c ? self->click_cursor : self->standard_cursor);
    Py_RETURN_NONE;
}

static PyObject*
set_clipboard_string(WindowWrapper *self, PyObject *args) {
    char *title;
    if(!PyArg_ParseTuple(args, "s", &title)) return NULL;
    glfwSetClipboardString(self->window, title);
    Py_RETURN_NONE;
}

static PyObject*
set_window_icon(WindowWrapper *self, PyObject *args) {
    GLFWimage logo;
    Py_ssize_t sz;
    if(!PyArg_ParseTuple(args, "s#ii", &(logo.pixels), &sz, &(logo.width), &(logo.height))) return NULL;
    glfwSetWindowIcon(self->window, 1, &logo);
    Py_RETURN_NONE;
}


static PyObject*
_set_title(WindowWrapper *self, PyObject *args) {
    char *title;
    if(!PyArg_ParseTuple(args, "s", &title)) return NULL;
    glfwSetWindowTitle(self->window, title);
    Py_RETURN_NONE;
}


static PyObject*
get_framebuffer_size(WindowWrapper *self) {
    int w, h;
    glfwGetFramebufferSize(self->window, &w, &h);
    return Py_BuildValue("ii", w, h);
}

static PyObject*
get_window_size(WindowWrapper *self) {
    int w, h;
    glfwGetWindowSize(self->window, &w, &h);
    return Py_BuildValue("ii", w, h);
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
current_monitor_dpi(WindowWrapper *self) {
    GLFWmonitor *m = current_monitor(self->window);
    if (m == NULL) return NULL;
    return get_physical_dpi(m);
}

#ifdef glfwRequestWindowAttention
static PyObject*
request_window_attention(WindowWrapper *self) {
    glfwRequestWindowAttention(self->window);
    Py_RETURN_NONE;
}
#endif

#ifdef __APPLE__
static PyObject*
cocoa_window_id(WindowWrapper *self) {
    void *wid = glfwGetCocoaWindow(self->window);
    if (wid == NULL) { PyErr_SetString(PyExc_ValueError, "Failed to get native window handle"); return NULL; }
    return PyLong_FromVoidPtr(wid);
}
#endif

// Boilerplate {{{
#define MND(name, args) {#name, (PyCFunction)name, args, ""}

static PyMethodDef methods[] = {
    MND(swap_buffers, METH_NOARGS),
    MND(get_clipboard_string, METH_NOARGS),
    MND(get_cursor_pos, METH_NOARGS),
    MND(should_close, METH_NOARGS),
    MND(get_framebuffer_size, METH_NOARGS),
    MND(get_window_size, METH_NOARGS),
    MND(current_monitor_dpi, METH_NOARGS),
#ifdef glfwRequestWindowAttention
    MND(request_window_attention, METH_NOARGS),
#endif
#ifdef __APPLE__
    MND(cocoa_window_id, METH_NOARGS),
#endif
    MND(set_should_close, METH_VARARGS),
    MND(set_input_mode, METH_VARARGS),
    MND(is_key_pressed, METH_VARARGS),
    MND(set_click_cursor, METH_VARARGS),
    MND(set_clipboard_string, METH_VARARGS),
    MND(make_context_current, METH_NOARGS),
    MND(window_id, METH_NOARGS),
    {"set_title", (PyCFunction)_set_title, METH_VARARGS, ""},
    {"set_icon", (PyCFunction)set_window_icon, METH_VARARGS, ""},
    {NULL}  /* Sentinel */
};

static PyMemberDef members[] = {
#define CBE(name) {#name, T_OBJECT_EX, offsetof(WindowWrapper, name), 0, #name}
    CBE(framebuffer_size_callback),
    CBE(char_mods_callback),
    CBE(key_callback),
    CBE(mouse_button_callback),
    CBE(scroll_callback),
    CBE(cursor_pos_callback),
    CBE(window_focus_callback),
    {NULL}
#undef CBE
};
 
PyTypeObject WindowWrapper_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.GLFWWindow",
    .tp_basicsize = sizeof(WindowWrapper),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "A GLFW window",
    .tp_methods = methods,
    .tp_members = members,
    .tp_new = new,                
};

static PyMethodDef module_methods[] = {
    {"glfw_set_error_callback", (PyCFunction)glfw_set_error_callback, METH_O, ""}, \
    {"glfw_init", (PyCFunction)glfw_init, METH_NOARGS, ""}, \
    {"glfw_terminate", (PyCFunction)glfw_terminate, METH_NOARGS, ""}, \
    {"glfw_window_hint", (PyCFunction)glfw_window_hint, METH_VARARGS, ""}, \
    {"glfw_swap_interval", (PyCFunction)glfw_swap_interval, METH_VARARGS, ""}, \
    {"glfw_wait_events", (PyCFunction)glfw_wait_events, METH_VARARGS, ""}, \
    {"glfw_post_empty_event", (PyCFunction)glfw_post_empty_event, METH_NOARGS, ""}, \
    {"glfw_get_physical_dpi", (PyCFunction)glfw_get_physical_dpi, METH_NOARGS, ""}, \
    {"glfw_get_key_name", (PyCFunction)glfw_get_key_name, METH_VARARGS, ""}, \
    {"glfw_init_hint_string", (PyCFunction)glfw_init_hint_string, METH_VARARGS, ""}, \
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

// constants {{{
bool
init_glfw(PyObject *m) {
    if (PyModule_AddFunctions(m, module_methods) != 0) return false;
    if (PyType_Ready(&WindowWrapper_Type) < 0) return false; 
    if (PyModule_AddObject(m, "GLFWWindow", (PyObject *)&WindowWrapper_Type) != 0) return 0;
    Py_INCREF(&WindowWrapper_Type); 
    glfwSetErrorCallback(cb_error_callback);
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
