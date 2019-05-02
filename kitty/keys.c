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

static bool needs_special_handling[128 * 16] = {0};

const char*
key_to_bytes(int glfw_key, bool smkx, bool extended, int mods, int action) {
    if ((action & 3) == 3) return NULL;
    if ((unsigned)glfw_key >= sizeof(key_map)/sizeof(key_map[0]) || glfw_key < 0) return NULL;
    uint16_t key = key_map[glfw_key];
    if (key == UINT8_MAX) return NULL;
    KeyboardMode mode = extended ? EXTENDED : (smkx ? APPLICATION : NORMAL);
    return key_lookup(key, mode, mods, action);
}

#define SPECIAL_INDEX(key) ((key & 0x7f) | ( (mods & 0xF) << 7))
#define IS_ALT_MODS(mods) (mods == GLFW_MOD_ALT || mods == (GLFW_MOD_ALT | GLFW_MOD_SHIFT))

typedef struct { int mods, scancode; } NativeKey;
static NativeKey *native_special_keys = NULL;
static size_t native_special_keys_capacity = 0, native_special_keys_count = 0;

void
set_special_key_combo(int glfw_key, int mods, bool is_native) {
    if (is_native) {
        if (native_special_keys_count >= native_special_keys_capacity) {
            native_special_keys_capacity = MAX(128, 2 * native_special_keys_capacity);
            native_special_keys = realloc(native_special_keys, sizeof(native_special_keys[0]) * native_special_keys_capacity);
            if (native_special_keys == NULL) fatal("Out of memory");
        }
        native_special_keys[native_special_keys_count].mods = mods;
        native_special_keys[native_special_keys_count++].scancode = glfw_key;
    } else {
        uint16_t key = key_map[glfw_key];
        if (key != UINT8_MAX) {
            key = SPECIAL_INDEX(key);
            needs_special_handling[key] = true;
        }
    }
}

static inline Window*
active_window() {
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
            return true;
        default:
            return false;
    }
}

static inline void
send_key_to_child(Window *w, int key, int mods, int action) {
    Screen *screen = w->render_data.screen;
    const char *data = key_to_bytes(key, screen->modes.mDECCKM, screen->modes.mEXTENDED_KEYBOARD, mods, action);
    if (data) {
        if (screen->modes.mEXTENDED_KEYBOARD) {
            if (*data == 1) schedule_write_to_child(w->id, 1, (data + 1), 1);
            else write_escape_code_to_child(screen, APC, data + 1);
        } else {
            if (*data > 2 && data[1] == 0x1b && data[2] == '[') { // CSI code
                write_escape_code_to_child(screen, CSI, data + 3);
            } else schedule_write_to_child(w->id, 1, (data + 1), *data);
        }
    }
}

static inline bool
is_ascii_control_char(char c) {
    return c == 0 || (1 <= c && c <= 31) || c == 127;
}

static inline bool
check_if_special(int key, int mods, int scancode) {
    uint16_t qkey = (0 <= key && key < (ssize_t)arraysz(key_map)) ? key_map[key] : UINT8_MAX;
    bool special = false;
    if (qkey != UINT8_MAX) {
        qkey = SPECIAL_INDEX(qkey);
        special = needs_special_handling[qkey];
    }
    for (size_t i = 0; !special && i < native_special_keys_count; i++) {
        if (scancode == native_special_keys[i].scancode && mods == native_special_keys[i].mods) special = true;
    }
    return special;
}

static inline void
update_ime_position(OSWindow *os_window, Window* w, Screen *screen) {
    unsigned int cell_width = os_window->fonts_data->cell_width, cell_height = os_window->fonts_data->cell_height;
    unsigned int left = w->geometry.left, top = w->geometry.top;
    left += screen->cursor->x * cell_width;
    top += screen->cursor->y * cell_height;
    glfwUpdateIMEState(global_state.callback_os_window->handle, 2, left, top, cell_width, cell_height);
}

#define debug(...) if (OPT(debug_keyboard)) printf(__VA_ARGS__);

void
on_key_input(int key, int scancode, int action, int mods, const char* text, int state) {
    Window *w = active_window();
    debug("on_key_input: glfw key: %d native_code: 0x%x action: %s mods: 0x%x text: '%s' state: %d ",
            key, scancode,
            (action == GLFW_RELEASE ? "RELEASE" : (action == GLFW_PRESS ? "PRESS" : "REPEAT")),
            mods, text, state);
    if (!w) { debug("no active window, ignoring\n"); return; }
    if (OPT(mouse_hide_wait) < 0 && !is_modifier_key(key)) hide_mouse(global_state.callback_os_window);
    Screen *screen = w->render_data.screen;
    switch(state) {
        case 1:  // update pre-edit text
            update_ime_position(global_state.callback_os_window, w, screen);
            screen_draw_overlay_text(screen, text);
            debug("updated pre-edit text: '%s'\n", text);
            return;
        case 2:  // commit text
            if (text && *text) {
                schedule_write_to_child(w->id, 1, text, strlen(text));
                debug("committed pre-edit text: %s\n", text);
            } else debug("committed pre-edit text: (null)\n");
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
        ) call_boss(process_sequence, "iiii", key, scancode, action, mods);
        return;
    }
    bool has_text = text && !is_ascii_control_char(text[0]);
    if (action == GLFW_PRESS || action == GLFW_REPEAT) {
        if (check_if_special(key, mods, scancode)) {
            PyObject *ret = PyObject_CallMethod(global_state.boss, "dispatch_special_key", "iiii", key, scancode, action, mods);
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
    }
    if (action == GLFW_REPEAT && !screen->modes.mDECARM) {
        debug("discarding repeat key event as DECARM is off\n");
        return;
    }
    if (screen->scrolled_by && action == GLFW_PRESS && !is_modifier_key(key)) {
        screen_history_scroll(screen, SCROLL_FULL, false);  // scroll back to bottom
    }
    bool ok_to_send = action == GLFW_PRESS || action == GLFW_REPEAT || screen->modes.mEXTENDED_KEYBOARD;
    if (ok_to_send) {
        if (has_text) {
            schedule_write_to_child(w->id, 1, text, strlen(text));
            debug("sent text to child\n");
        } else {
            send_key_to_child(w, key, mods, action);
            debug("sent key to child\n");
        }
    } else {
        debug("ignoring as keyboard mode does not allow %s events\n", action == GLFW_RELEASE ? "release" : "repeat");
    }
}

void
fake_scroll(int amount, bool upwards) {
    Window *w = active_window();
    if (!w) return;
    int key = upwards ? GLFW_KEY_UP : GLFW_KEY_DOWN;
    while (amount-- > 0) {
        send_key_to_child(w, key, 0, GLFW_PRESS);
        send_key_to_child(w, key, 0, GLFW_RELEASE);
    }
}

#define PYWRAP1(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args)
#define PA(fmt, ...) if(!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;
#define M(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}

PYWRAP1(key_to_bytes) {
    int glfw_key, smkx, extended, mods, action;
    PA("ippii", &glfw_key, &smkx, &extended, &mods, &action);
    const char *ans = key_to_bytes(glfw_key, smkx & 1, extended & 1, mods, action);
    if (ans == NULL) return Py_BuildValue("y#", "", 0);
    return Py_BuildValue("y#", ans + 1, *ans);
}

PYWRAP1(key_for_native_key_name) {
    const char *name;
    int case_sensitive = 0;
    PA("s|p", &name, case_sensitive);
#ifndef __APPLE__
    if (glfwGetXKBScancode) {  // if this function is called before GLFW is initialized glfwGetXKBScancode will be NULL
        int scancode = glfwGetXKBScancode(name, case_sensitive);
        if (scancode) return Py_BuildValue("i", scancode);
    }
#endif
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    M(key_to_bytes, METH_VARARGS),
    M(key_for_native_key_name, METH_VARARGS),
    {0}
};

void
finalize(void) {
    free(native_special_keys);
}

bool
init_keys(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (Py_AtExit(finalize) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to register the keys at exit handler");
        return false;
    }
    return true;
}
