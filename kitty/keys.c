/*
 * keys.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "keys.h"
#include "screen.h"
#include "glfw-wrapper.h"
#include "control-codes.h"

static inline Window*
active_window(void) {
    Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
    Window *w = t->windows + t->active_window;
    if (w->render_data.screen) return w;
    return NULL;
}

static inline bool
is_modifier_key(int key) {
    switch(key) {
        case GLFW_KEY_LEFT_SHIFT:
        case GLFW_KEY_RIGHT_SHIFT:
        case GLFW_KEY_LEFT_ALT:
        case GLFW_KEY_RIGHT_ALT:
        case GLFW_KEY_LEFT_CONTROL:
        case GLFW_KEY_RIGHT_CONTROL:
        case GLFW_KEY_LEFT_SUPER:
        case GLFW_KEY_RIGHT_SUPER:
        case GLFW_KEY_CAPS_LOCK:
            return true;
        default:
            return false;
    }
}

static inline void
update_ime_position(OSWindow *os_window, Window* w, Screen *screen) {
    unsigned int cell_width = os_window->fonts_data->cell_width, cell_height = os_window->fonts_data->cell_height;
    unsigned int left = w->geometry.left, top = w->geometry.top;
    left += screen->cursor->x * cell_width;
    top += screen->cursor->y * cell_height;
    glfwUpdateIMEState(global_state.callback_os_window->handle, 2, left, top, cell_width, cell_height);
}

void
on_key_input(GLFWkeyevent *ev) {
    Window *w = active_window();
    const int action = ev->action, native_key = ev->native_key, key = ev->key, mods = ev->mods;
    const char *text = ev->text ? ev->text : "";

    debug("on_key_input: glfw key: %d native_code: 0x%x action: %s mods: 0x%x text: '%s' state: %d ",
            key, native_key,
            (action == GLFW_RELEASE ? "RELEASE" : (action == GLFW_PRESS ? "PRESS" : "REPEAT")),
            mods, text, ev->ime_state);
    if (!w) { debug("no active window, ignoring\n"); return; }
    if (OPT(mouse_hide_wait) < 0 && !is_modifier_key(key)) hide_mouse(global_state.callback_os_window);
    Screen *screen = w->render_data.screen;
    switch(ev->ime_state) {
        case 1:  // update pre-edit text
            update_ime_position(global_state.callback_os_window, w, screen);
            screen_draw_overlay_text(screen, text);
            debug("updated pre-edit text: '%s'\n", text);
            return;
        case 2:  // commit text
            if (*text) {
                schedule_write_to_child(w->id, 1, text, strlen(text));
                debug("committed pre-edit text: %s\n", text);
            } else debug("committed pre-edit text: (null)\n");
            screen_draw_overlay_text(screen, NULL);
            return;
        case 0:
            // for macOS, update ime position on every key input
            // because the position is required before next input
#if defined(__APPLE__)
            update_ime_position(global_state.callback_os_window, w, screen);
#endif
            break;
        default:
            debug("invalid state, ignoring\n");
            return;
    }
    if (global_state.in_sequence_mode) {
        debug("in sequence mode, handling as shortcut\n");
        if (
            action != GLFW_RELEASE &&
            key != GLFW_KEY_LEFT_SHIFT && key != GLFW_KEY_RIGHT_SHIFT && key != GLFW_KEY_LEFT_ALT && key != GLFW_KEY_RIGHT_ALT && key != GLFW_KEY_LEFT_CONTROL && key != GLFW_KEY_RIGHT_CONTROL
        ) call_boss(process_sequence, "iiii", key, native_key, action, mods);
        return;
    }
    if (action == GLFW_PRESS || action == GLFW_REPEAT) {
        PyObject *ret = PyObject_CallMethod(global_state.boss, "dispatch_possible_special_key", "iiii", key, native_key, action, mods);
        if (ret == NULL) { PyErr_Print(); }
        else {
            bool consumed = ret == Py_True;
            Py_DECREF(ret);
            if (consumed) {
                debug("handled as shortcut\n");
                return;
            }
        }
    }
    if (action == GLFW_REPEAT && !screen->modes.mDECARM) {
        debug("discarding repeat key event as DECARM is off\n");
        return;
    }
    if (screen->scrolled_by && action == GLFW_PRESS && !is_modifier_key(key)) {
        screen_history_scroll(screen, SCROLL_FULL, false);  // scroll back to bottom
    }
    char encoded_key[KEY_BUFFER_SIZE] = {0};
    int size = encode_glfw_key_event(ev, screen->modes.mDECCKM, screen_current_key_encoding_flags(screen), encoded_key);
    if (size == SEND_TEXT_TO_CHILD) {
        schedule_write_to_child(w->id, 1, text, strlen(text));
        debug("sent text to child\n");
    } else if (size > 0) {
        schedule_write_to_child(w->id, 1, encoded_key, size);
        debug("sent key to child\n");
    } else {
        debug("ignoring as keyboard mode does not allow %s events\n", action == GLFW_RELEASE ? "release" : "repeat");
    }
}

void
fake_scroll(Window *w, int amount, bool upwards) {
    if (!w) return;
    int key = upwards ? GLFW_KEY_UP : GLFW_KEY_DOWN;
    GLFWkeyevent ev = {.key = key };
    char encoded_key[KEY_BUFFER_SIZE] = {0};
    Screen *screen = w->render_data.screen;
    uint8_t flags = screen_current_key_encoding_flags(screen);
    while (amount-- > 0) {
        ev.action = GLFW_PRESS;
        int size = encode_glfw_key_event(&ev, screen->modes.mDECCKM, flags, encoded_key);
        if (size > 0) schedule_write_to_child(w->id, 1, encoded_key, size);
        ev.action = GLFW_RELEASE;
        size = encode_glfw_key_event(&ev, screen->modes.mDECCKM, flags, encoded_key);
        if (size > 0) schedule_write_to_child(w->id, 1, encoded_key, size);
    }
}

#define PYWRAP1(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args)
#define PA(fmt, ...) if(!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;
#define M(name, arg_type) {#name, (PyCFunction)(void (*) (void))(py##name), arg_type, NULL}

PYWRAP1(key_for_native_key_name) {
    const char *name;
    int case_sensitive = 0;
    PA("s|p", &name, &case_sensitive);
#ifndef __APPLE__
    if (glfwGetNativeKeyForName) {  // if this function is called before GLFW is initialized glfwGetNativeKeyForName will be NULL
        int native_key = glfwGetNativeKeyForName(name, case_sensitive);
        if (native_key) return Py_BuildValue("i", native_key);
    }
#endif
    Py_RETURN_NONE;
}

static PyObject*
pyencode_key_for_tty(PyObject *self UNUSED, PyObject *args, PyObject *kw) {
    char *kwds[] = {"key", "shifted_key", "alternate_key", "mods", "action", "text", "cursor_key_mode", "key_encoding_flags"};
    unsigned int key = 0, shifted_key = 0, alternate_key = 0, mods = 0, action = 0, key_encoding_flags = 0;
    const char *text = NULL;
    int cursor_key_mode = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kw, "IIIIIspI", kwds, &key, &shifted_key, &alternate_key, &mods, &action, &text, &cursor_key_mode, &key_encoding_flags)) return NULL;
    GLFWkeyevent ev = { .key = key, .shifted_key = shifted_key, .alternate_key = alternate_key, .text = text, .action = action, .mods = mods };
    char output[KEY_BUFFER_SIZE+1] = {0};
    int num = encode_glfw_key_event(&ev, cursor_key_mode, key_encoding_flags, output);
    if (num == SEND_TEXT_TO_CHILD) return PyUnicode_FromString(text);
    return PyUnicode_FromString(output);
}

static PyMethodDef module_methods[] = {
    M(key_for_native_key_name, METH_VARARGS),
    M(encode_key_for_tty, METH_VARARGS | METH_KEYWORDS),
    {0}
};

bool
init_keys(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
