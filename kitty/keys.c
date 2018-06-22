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
            if (*data == 1) schedule_write_to_child(w->id, (data + 1), 1);
            else write_escape_code_to_child(screen, APC, data + 1);
        } else {
            if (*data > 2 && data[1] == 0x1b && data[2] == '[') { // CSI code
                write_escape_code_to_child(screen, CSI, data + 3);
            } else schedule_write_to_child(w->id, (data + 1), *data);
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
#ifdef __APPLE__
    (void)scancode;
#else
        for (size_t i = 0; !special && i < native_special_keys_count; i++) {
            if (scancode == native_special_keys[i].scancode && mods == native_special_keys[i].mods) special = true;
        }
#endif
    return special;
}

void
on_key_input(int key, int scancode, int action, int mods, const char* text, int state UNUSED) {
    Window *w = active_window();
    if (!w) return;
    if (global_state.in_sequence_mode) {
        if (
            action != GLFW_RELEASE &&
            key != GLFW_KEY_LEFT_SHIFT && key != GLFW_KEY_RIGHT_SHIFT && key != GLFW_KEY_LEFT_ALT && key != GLFW_KEY_RIGHT_ALT && key != GLFW_KEY_LEFT_CONTROL && key != GLFW_KEY_RIGHT_CONTROL
        ) call_boss(process_sequence, "iiii", key, scancode, action, mods);
        return;
    }
    Screen *screen = w->render_data.screen;
    bool has_text = text && !is_ascii_control_char(text[0]);
    if (action == GLFW_PRESS || action == GLFW_REPEAT) {
        if (check_if_special(key, mods, scancode)) {
            PyObject *ret = PyObject_CallMethod(global_state.boss, "dispatch_special_key", "iiii", key, scancode, action, mods);
            if (ret == NULL) { PyErr_Print(); }
            else {
                bool consumed = ret == Py_True;
                Py_DECREF(ret);
                if (consumed) return;
            }
        }
    }
    if (action == GLFW_REPEAT && !screen->modes.mDECARM) return;
    if (screen->scrolled_by && action == GLFW_PRESS && !is_modifier_key(key)) {
        screen_history_scroll(screen, SCROLL_FULL, false);  // scroll back to bottom
    }
    bool ok_to_send = action == GLFW_PRESS || action == GLFW_REPEAT || screen->modes.mEXTENDED_KEYBOARD;
    if (ok_to_send) {
        if (has_text) {
            schedule_write_to_child(w->id, text, strlen(text));
        } else {
            send_key_to_child(w, key, mods, action);
        }
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
#ifdef __APPLE__
    Py_RETURN_NONE;
#else
    if (glfwGetXKBScancode) {  // if this function is called before GLFW is initialized glfwGetXKBScancode will be NULL
        int scancode = glfwGetXKBScancode(name, case_sensitive);
        if (scancode) return Py_BuildValue("i", scancode);
    }
    Py_RETURN_NONE;
#endif
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
