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
#include <structmember.h>

// python KeyEvent object {{{
typedef struct {
    PyObject_HEAD
    PyObject *key, *shifted_key, *alternate_key;
    PyObject *mods, *action, *native_key, *ime_state;
    PyObject *text;
} PyKeyEvent;

static inline PyObject* convert_glfw_key_event_to_python(const GLFWkeyevent *ev);

static PyObject*
new(PyTypeObject *type UNUSED, PyObject *args, PyObject *kw) {
    static char *kwds[] = {"key", "shifted_key", "alternate_key", "mods", "action", "native_key", "ime_state", "text", NULL};
    GLFWkeyevent ev = {.action=GLFW_PRESS};
    if (!PyArg_ParseTupleAndKeywords(args, kw, "I|IIiiiiz", kwds, &ev.key, &ev.shifted_key, &ev.alternate_key, &ev.mods, &ev.action, &ev.native_key, &ev.ime_state, &ev.text)) return NULL;
    return convert_glfw_key_event_to_python(&ev);
}

static void
dealloc(PyKeyEvent* self) {
    Py_CLEAR(self->key); Py_CLEAR(self->shifted_key); Py_CLEAR(self->alternate_key);
    Py_CLEAR(self->mods); Py_CLEAR(self->action); Py_CLEAR(self->native_key); Py_CLEAR(self->ime_state);
    Py_CLEAR(self->text);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyMemberDef members[] = {
#define M(x) {#x, T_OBJECT, offsetof(PyKeyEvent, x), READONLY, #x}
    M(key), M(shifted_key), M(alternate_key),
    M(mods), M(action), M(native_key), M(ime_state),
    M(text),
    {NULL},
#undef M
};

PyTypeObject PyKeyEvent_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.KeyEvent",
    .tp_basicsize = sizeof(PyKeyEvent),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "A key event",
    .tp_members = members,
    .tp_new = new,
};

static inline PyObject*
convert_glfw_key_event_to_python(const GLFWkeyevent *ev) {
    PyKeyEvent *self = (PyKeyEvent*)PyKeyEvent_Type.tp_alloc(&PyKeyEvent_Type, 0);
    if (!self) return NULL;
#define C(x) { unsigned long t = ev->x; self->x = PyLong_FromUnsignedLong(t); if (self->x == NULL) { Py_CLEAR(self); return NULL; } }
    C(key); C(shifted_key); C(alternate_key); C(mods); C(action); C(native_key); C(ime_state);
#undef C
    self->text = PyUnicode_FromString(ev->text ? ev->text : "");
    if (!self->text) { Py_CLEAR(self); return NULL; }
    return (PyObject*)self;
}
// }}}

static inline Window*
active_window(void) {
    Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
    Window *w = t->windows + t->active_window;
    if (w->render_data.screen) return w;
    return NULL;
}

static inline void
update_ime_position(OSWindow *os_window, Window* w, Screen *screen) {
    unsigned int cell_width = os_window->fonts_data->cell_width, cell_height = os_window->fonts_data->cell_height;
    unsigned int left = w->geometry.left, top = w->geometry.top;
    left += screen->cursor->x * cell_width;
    top += screen->cursor->y * cell_height;
    GLFWIMEUpdateEvent ev = { .type = GLFW_IME_UPDATE_CURSOR_POSITION };
    ev.cursor.left = left; ev.cursor.top = top; ev.cursor.width = cell_width; ev.cursor.height = cell_height;
    glfwUpdateIMEState(global_state.callback_os_window->handle, &ev);
}

const char*
format_mods(unsigned mods) {
    static char buf[128];
    char *p = buf, *s;
#define pr(x) p += snprintf(p, sizeof(buf) - (p - buf) - 1, x)
    pr("mods: ");
    s = p;
    if (mods & GLFW_MOD_CONTROL) pr("ctrl+");
    if (mods & GLFW_MOD_ALT) pr("alt+");
    if (mods & GLFW_MOD_SHIFT) pr("shift+");
    if (mods & GLFW_MOD_SUPER) pr("super+");
    if (mods & GLFW_MOD_HYPER) pr("hyper+");
    if (mods & GLFW_MOD_META) pr("meta+");
    if (mods & GLFW_MOD_CAPS_LOCK) pr("capslock+");
    if (mods & GLFW_MOD_NUM_LOCK) pr("numlock+");
    if (p == s) pr("none");
    else p--;
    pr(" ");
#undef pr
    return buf;
}

void
on_key_input(GLFWkeyevent *ev) {
    Window *w = active_window();
    const int action = ev->action, mods = ev->mods;
    const uint32_t key = ev->key, native_key = ev->native_key;
    const char *text = ev->text ? ev->text : "";

    debug("\x1b[33mon_key_input\x1b[m: glfw key: 0x%x native_code: 0x%x action: %s %stext: '%s' state: %d ",
            key, native_key,
            (action == GLFW_RELEASE ? "RELEASE" : (action == GLFW_PRESS ? "PRESS" : "REPEAT")),
            format_mods(mods), text, ev->ime_state);
    if (!w) { debug("no active window, ignoring\n"); return; }
    if (OPT(mouse_hide_wait) < 0 && !is_modifier_key(key)) hide_mouse(global_state.callback_os_window);
    Screen *screen = w->render_data.screen;
    id_type active_window_id = w->id;

    switch(ev->ime_state) {
        case GLFW_IME_PREEDIT_CHANGED:
            update_ime_position(global_state.callback_os_window, w, screen);
            screen_draw_overlay_text(screen, text);
            debug("updated pre-edit text: '%s'\n", text);
            return;
        case GLFW_IME_COMMIT_TEXT:
            if (*text) {
                schedule_write_to_child(w->id, 1, text, strlen(text));
                debug("committed pre-edit text: %s\n", text);
            } else debug("committed pre-edit text: (null)\n");
            screen_draw_overlay_text(screen, NULL);
            return;
        case GLFW_IME_NONE:
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
    PyObject *ke = NULL;
#define create_key_event() { ke = convert_glfw_key_event_to_python(ev); if (!ke) { PyErr_Print(); return; } }
    if (global_state.in_sequence_mode) {
        debug("in sequence mode, handling as shortcut\n");
        if (
            action != GLFW_RELEASE && !is_modifier_key(key)
        ) {
            w->last_special_key_pressed = key;
            create_key_event();
            call_boss(process_sequence, "O", ke);
            Py_CLEAR(ke);
        }
        return;
    }

    if (action == GLFW_PRESS || action == GLFW_REPEAT) {
        create_key_event();
        w->last_special_key_pressed = 0;
        PyObject *ret = PyObject_CallMethod(global_state.boss, "dispatch_possible_special_key", "O", ke);
        Py_CLEAR(ke);
        bool consumed = false;
        // the shortcut could have created a new window or closed the
        // window, rendering the pointer no longer valid
        w = window_for_window_id(active_window_id);
        if (ret == NULL) { PyErr_Print(); }
        else {
            consumed = ret == Py_True;
            Py_DECREF(ret);
            if (consumed) {
                debug("handled as shortcut\n");
                if (w) w->last_special_key_pressed = key;
                return;
            }
        }
        if (!w) return;
    } else if (w->last_special_key_pressed == key) {
        w->last_special_key_pressed = 0;
        debug("ignoring release event for previous press that was handled as shortcut\n");
        return;
    }
#undef create_key_event
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
        debug("ignoring as keyboard mode does not support encoding this event\n");
    }
}

void
fake_scroll(Window *w, int amount, bool upwards) {
    if (!w) return;
    int key = upwards ? GLFW_FKEY_UP : GLFW_FKEY_DOWN;
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
    static char *kwds[] = {"key", "shifted_key", "alternate_key", "mods", "action", "key_encoding_flags", "text", "cursor_key_mode", NULL};
    unsigned int key = 0, shifted_key = 0, alternate_key = 0, mods = 0, action = GLFW_PRESS, key_encoding_flags = 0;
    const char *text = NULL;
    int cursor_key_mode = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kw, "I|IIIIIzp", kwds, &key, &shifted_key, &alternate_key, &mods, &action, &key_encoding_flags, &text, &cursor_key_mode)) return NULL;
    GLFWkeyevent ev = { .key = key, .shifted_key = shifted_key, .alternate_key = alternate_key, .text = text, .action = action, .mods = mods };
    char output[KEY_BUFFER_SIZE+1] = {0};
    int num = encode_glfw_key_event(&ev, cursor_key_mode, key_encoding_flags, output);
    if (num == SEND_TEXT_TO_CHILD) return PyUnicode_FromString(text);
    return PyUnicode_FromStringAndSize(output, MAX(0, num));
}

static PyMethodDef module_methods[] = {
    M(key_for_native_key_name, METH_VARARGS),
    M(encode_key_for_tty, METH_VARARGS | METH_KEYWORDS),
    {0}
};

bool
init_keys(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (PyType_Ready(&PyKeyEvent_Type) < 0) return false;
    if (PyModule_AddObject(module, "KeyEvent", (PyObject *)&PyKeyEvent_Type) != 0) return 0;
    Py_INCREF(&PyKeyEvent_Type);
    return true;
}
