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
#include <structmember.h>

#ifndef __APPLE__
#include <xkbcommon/xkbcommon.h>
#endif

// python KeyEvent object {{{
typedef struct {
    PyObject_HEAD
    PyObject *key, *shifted_key, *alternate_key;
    PyObject *mods, *action, *native_key, *ime_state;
    PyObject *text;
} PyKeyEvent;

static PyObject* convert_glfw_key_event_to_python(const GLFWkeyevent *ev);

static PyObject*
new_keyevent_object(PyTypeObject *type UNUSED, PyObject *args, PyObject *kw) {
    static char *kwds[] = {"key", "shifted_key", "alternate_key", "mods", "action", "native_key", "ime_state", "text", NULL};
    GLFWkeyevent ev = {.action=GLFW_PRESS};
    if (!PyArg_ParseTupleAndKeywords(args, kw, "I|IIiiiiz", kwds, &ev.key, &ev.shifted_key, &ev.alternate_key, &ev.mods, &ev.action, &ev.native_key, &ev.ime_state, &ev.text)) return NULL;
    return convert_glfw_key_event_to_python(&ev);
}

bool
is_modifier_key(const uint32_t key) {
    START_ALLOW_CASE_RANGE
    switch (key) {
        case GLFW_FKEY_LEFT_SHIFT ... GLFW_FKEY_ISO_LEVEL5_SHIFT:
        case GLFW_FKEY_CAPS_LOCK:
        case GLFW_FKEY_SCROLL_LOCK:
        case GLFW_FKEY_NUM_LOCK:
            return true;
        default:
            return false;
    }
    END_ALLOW_CASE_RANGE
}

static bool
is_no_action_key(const uint32_t key, const uint32_t native_key) {
    switch (native_key) {
#ifndef __APPLE__
        case XKB_KEY_XF86Fn:
        case XKB_KEY_XF86WakeUp:
            return true;
#endif
        default:
            return is_modifier_key(key);
    }
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
    .tp_new = new_keyevent_object,
};

static PyObject*
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

static Window*
active_window(void) {
    Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
    Window *w = t->windows + t->active_window;
    if (!w->render_data.screen) return NULL;
    if (w->redirect_keys_to_overlay) {
        for (unsigned i = 0; i < t->num_windows; i++) {
            if (t->windows[i].id == w->redirect_keys_to_overlay && w->render_data.screen) return t->windows + i;
        }
    }
    return w;
}

void
update_ime_focus(OSWindow *osw, bool focused) {
    if (!osw || !osw->handle) return;
    GLFWIMEUpdateEvent ev = { .focused = focused, .type = GLFW_IME_UPDATE_FOCUS };
    glfwUpdateIMEState(osw->handle, &ev);
}

void
prepare_ime_position_update_event(OSWindow *osw, Window *w, Screen *screen, GLFWIMEUpdateEvent *ev) {
    unsigned int cell_width = osw->fonts_data->fcm.cell_width, cell_height = osw->fonts_data->fcm.cell_height;
    unsigned int left = w->geometry.left, top = w->geometry.top;
    if (screen_is_overlay_active(screen)) {
        left += screen->overlay_line.cursor_x * cell_width;
        top += MIN(screen->overlay_line.ynum + screen->scrolled_by, screen->lines - 1) * cell_height;
    } else {
        left += screen->cursor->x * cell_width;
        top += screen->cursor->y * cell_height;
    }
    ev->cursor.left = left; ev->cursor.top = top; ev->cursor.width = cell_width; ev->cursor.height = cell_height;
}

void
update_ime_position(Window* w UNUSED, Screen *screen UNUSED) {
    GLFWIMEUpdateEvent ev = { .type = GLFW_IME_UPDATE_CURSOR_POSITION };
#ifndef __APPLE__
    prepare_ime_position_update_event(global_state.callback_os_window, w, screen, &ev);
#endif
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

static void
send_key_to_child(id_type window_id, Screen *screen, const GLFWkeyevent *ev) {
    const int action = ev->action;
    const uint32_t key = ev->key, native_key = ev->native_key;
    const char *text = ev->text ? ev->text : "";

    if (action == GLFW_REPEAT && !screen->modes.mDECARM) {
        debug("discarding repeat key event as DECARM is off\n");
        return;
    }
    if (screen->scrolled_by && action == GLFW_PRESS && !is_no_action_key(key, native_key)) {
        screen_history_scroll(screen, SCROLL_FULL, false);  // scroll back to bottom
    }
    char encoded_key[KEY_BUFFER_SIZE] = {0};
    int size = encode_glfw_key_event(ev, screen->modes.mDECCKM, screen_current_key_encoding_flags(screen), encoded_key);
    if (size == SEND_TEXT_TO_CHILD) {
        schedule_write_to_child(window_id, 1, text, strlen(text));
        debug("sent key as text to child (window_id: %llu): %s\n", window_id, text);
    } else if (size > 0) {
        if (size == 1 && screen->modes.mHANDLE_TERMIOS_SIGNALS) {
            if (screen_send_signal_for_key(screen, *encoded_key)) return;
        }
        schedule_write_to_child(window_id, 1, encoded_key, size);
        if (OPT(debug_keyboard)) {
            debug("sent encoded key to child (window_id: %llu): ", window_id);
            for (int ki = 0; ki < size; ki++) {
                if (encoded_key[ki] == 27) { debug("^[ "); }
                else if (encoded_key[ki] == ' ') { debug("SPC "); }
                else if (isprint(encoded_key[ki])) { debug("%c ", encoded_key[ki]); }
                else { debug("0x%x ", encoded_key[ki]); }
            }
            debug("\n");
        }
    } else {
        debug("ignoring as keyboard mode does not support encoding this event\n");
    }
}

void
dispatch_buffered_keys(Window *w) {
    if (!w->render_data.screen || !w->buffered_keys.count) return;
    GLFWkeyevent *keys = w->buffered_keys.key_data;
    for (size_t i = 0; i < w->buffered_keys.count; i++) {
        debug("Sending previously buffered key ");
        send_key_to_child(w->id, w->render_data.screen, keys + i);
    }
    free(w->buffered_keys.key_data); zero_at_ptr(&w->buffered_keys);
}

void
on_key_input(const GLFWkeyevent *ev) {
    Window *w = active_window();
    const int action = ev->action, mods = ev->mods;
    const uint32_t key = ev->key, native_key = ev->native_key;
    const char *text = ev->text ? ev->text : "";

    if (OPT(debug_keyboard)) {
        if (!key && !native_key && text[0]) {
            debug("\x1b[33mon_IME_input\x1b[m: text: %s ", text);
        } else {
            debug("\x1b[33mon_key_input\x1b[m: glfw key: 0x%x native_code: 0x%x action: %s %stext: '%s' state: %d ",
                    key, native_key,
                    (action == GLFW_RELEASE ? "RELEASE" : (action == GLFW_PRESS ? "PRESS" : "REPEAT")),
                    format_mods(mods), text, ev->ime_state);
        }
    }
    if (!w) { debug("no active window, ignoring\n"); return; }
    send_pending_click_to_window(w, -1);
    if (OPT(mouse_hide.hide_wait) < 0 && !is_no_action_key(key, native_key)) hide_mouse(global_state.callback_os_window);
    Screen *screen = w->render_data.screen;
    id_type active_window_id = w->id;

    switch(ev->ime_state) {
        case GLFW_IME_WAYLAND_DONE_EVENT:
            // If we update IME position here it sends GNOME's text input system into
            // an infinite loop. See https://github.com/kovidgoyal/kitty/issues/5105
            // and also: https://github.com/kovidgoyal/kitty/pull/7283
            screen_update_overlay_text(screen, text);
            debug("handled wayland IME done event\n");
            return;
        case GLFW_IME_PREEDIT_CHANGED:
            screen_update_overlay_text(screen, text);
            update_ime_position(w, screen);
            debug("updated pre-edit text: '%s'\n", text);
            return;
        case GLFW_IME_COMMIT_TEXT:
            if (*text) {
                schedule_write_to_child(w->id, 1, text, strlen(text));
                debug("committed pre-edit text: %s sent to child as text.\n", text);
            } else debug("committed pre-edit text: (null)\n");
            screen_update_overlay_text(screen, NULL);
            return;
        case GLFW_IME_NONE:
            // for macOS, update ime position on every key input
            // because the position is required before next input
            // On Linux this is needed by Fig integration: https://github.com/kovidgoyal/kitty/issues/5241
            update_ime_position(w, screen);
            break;
        default:
            debug("invalid state, ignoring\n");
            return;
    }
    bool dispatch_ok = true, consumed = false;
#define dispatch_key_event(name) { \
    PyObject *ke = NULL, *ret = NULL; \
    ke = convert_glfw_key_event_to_python(ev); if (!ke) { PyErr_Print(); return; }; \
    ret = PyObject_CallMethod(global_state.boss, #name, "O", ke); Py_CLEAR(ke); \
    if (ret == NULL) { PyErr_Print(); dispatch_ok = false; } \
    else { consumed = ret == Py_True; Py_CLEAR(ret); } \
    w = window_for_window_id(active_window_id); \
}
    if (action == GLFW_PRESS || action == GLFW_REPEAT) {
        w->last_special_key_pressed = 0;
        dispatch_key_event(dispatch_possible_special_key);
        if (dispatch_ok) {
            if (consumed) {
                debug("handled as shortcut\n");
                if (w) w->last_special_key_pressed = key;
                return;
            }
        }
        if (!w) return;
        screen = w->render_data.screen;
    } else if (w->last_special_key_pressed == key) {
        w->last_special_key_pressed = 0;
        debug("ignoring release event for previous press that was handled as shortcut\n");
        return;
    }
    if (w->buffered_keys.enabled) {
        if (w->buffered_keys.capacity < w->buffered_keys.count + 1) {
            w->buffered_keys.capacity = MAX(16u, w->buffered_keys.capacity + 8);
            GLFWkeyevent *new = malloc(w->buffered_keys.capacity * sizeof(GLFWkeyevent));
            if (!new) fatal("Out of memory");
            memcpy(new, w->buffered_keys.key_data, w->buffered_keys.count * sizeof(new[0]));
            w->buffered_keys.key_data = new;
        }
        GLFWkeyevent *k = w->buffered_keys.key_data;
        k[w->buffered_keys.count++] = *ev;
        debug("buffering key until child is ready\n");
    } else send_key_to_child(w->id, screen, ev);
#undef dispatch_key_event
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

static PyObject*
pyinject_key(PyObject *self UNUSED, PyObject *args, PyObject *kw) {
    static char *kwds[] = {"key", "shifted_key", "alternate_key", "mods", "action", "text", "os_window_id", NULL};
    unsigned int key = 0, shifted_key = 0, alternate_key = 0, mods = 0, action = GLFW_PRESS;
    unsigned long long os_window_id = 0;
    const char *text = NULL;
    if (!PyArg_ParseTupleAndKeywords(args, kw, "I|IIIIzK", kwds, &key, &shifted_key, &alternate_key, &mods, &action, &text, &os_window_id)) return NULL;
    id_type orig = global_state.callback_os_window ? global_state.callback_os_window->id : 0;
    bool found = false;
    if (os_window_id) {
        for (size_t i = 0; i < global_state.num_os_windows && !found; i++) {
            if (global_state.os_windows[i].id == os_window_id) {
                global_state.callback_os_window = global_state.os_windows + i;
                found = true;
            }
        }
        if (!found) { PyErr_Format(PyExc_IndexError, "Could not find OS Window with id: %llu", os_window_id); return NULL; }
    } else {
        if (!global_state.callback_os_window) {
            for (size_t i = 0; i < global_state.num_os_windows && !found; i++) {
                if (global_state.os_windows[i].is_focused) {
                    global_state.callback_os_window = global_state.os_windows + i;
                    found = true;
                }
            }
            if (!found && ! global_state.num_os_windows) { PyErr_SetString(PyExc_Exception, "No OS Windows available to inject key presses into"); return NULL; }
            global_state.callback_os_window = global_state.os_windows;
            found = true;
        }
    }
    GLFWkeyevent ev = { .key = key, .shifted_key = shifted_key, .alternate_key = alternate_key, .text = text, .action = action, .mods = mods };
    on_key_input(&ev);
    if (orig) {
        found = false;
        for (size_t i = 0; i < global_state.num_os_windows && !found; i++) {
            if (global_state.os_windows[i].id == orig) {
                global_state.callback_os_window = global_state.os_windows + i; found = true;
            }
        }
        if (!found) global_state.callback_os_window = NULL;
    } else global_state.callback_os_window = NULL;
    Py_RETURN_NONE;
}

static PyObject*
pyis_modifier_key(PyObject *self UNUSED, PyObject *a) {
    unsigned long key = PyLong_AsUnsignedLong(a);
    if (PyErr_Occurred()) return NULL;
    if (is_modifier_key(key)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyMethodDef module_methods[] = {
    M(key_for_native_key_name, METH_VARARGS),
    M(encode_key_for_tty, METH_VARARGS | METH_KEYWORDS),
    M(inject_key, METH_VARARGS | METH_KEYWORDS),
    M(is_modifier_key, METH_O),
    {0}
};

// SingleKey {{{
typedef uint64_t keybitfield;
#define KEY_BITS 51
#define MOD_BITS 12
#if 1 << (MOD_BITS-1) < GLFW_MOD_KITTY
#error "Not enough mod bits"
#endif
typedef union Key {
    struct {
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
        keybitfield mods : MOD_BITS;
        keybitfield is_native: 1;
        keybitfield key : KEY_BITS;
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
        keybitfield key : KEY_BITS;
        keybitfield is_native: 1;
        keybitfield mods : MOD_BITS;
#else
#error "Unsupported endianness"
#endif
    };
    keybitfield val;
} Key;

static PyTypeObject SingleKey_Type;
static char *SingleKey_kwds[] = {"mods", "is_native", "key", NULL};
typedef struct {
    PyObject_HEAD

    Key key;
    bool defined_with_kitty_mod;
} SingleKey;

static inline void
SingleKey_set_vals(SingleKey *self, long long key, unsigned short mods, int is_native) {
    if (key >= 0 && (unsigned long long)key <= BIT_MASK(keybitfield, KEY_BITS)) {
        keybitfield k = (keybitfield)(unsigned long long)key;
        self->key.key = k & BIT_MASK(keybitfield, KEY_BITS);
    }
    if (!(mods & 1 << (MOD_BITS + 1))) self->key.mods = mods & BIT_MASK(uint32_t, MOD_BITS);
    if (is_native > -1) self->key.is_native = is_native ? 1 : 0;
}

static PyObject *
SingleKey_new(PyTypeObject *type, PyObject *args, PyObject *kw) {
    long long key = -1; unsigned short mods = 1 << (MOD_BITS + 1); int is_native = -1;
    if (!PyArg_ParseTupleAndKeywords(args, kw, "|HpL", SingleKey_kwds, &mods, &is_native, &key)) return NULL;
    SingleKey *self = (SingleKey *)type->tp_alloc(type, 0);
    if (self) SingleKey_set_vals(self, key, mods, is_native);
    return (PyObject*)self;
}

static void
SingleKey_dealloc(SingleKey* self) {
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
SingleKey_repr(PyObject *s) {
    SingleKey *self = (SingleKey*)s;
    char buf[128];
    int pos = 0;
    pos += PyOS_snprintf(buf + pos, sizeof(buf) - pos, "SingleKey(");
    unsigned int mods = self->key.mods;
    if (mods) pos += PyOS_snprintf(buf + pos, sizeof(buf) - pos, "mods=%u, ", mods);
    if (self->key.is_native) pos += PyOS_snprintf(buf + pos, sizeof(buf) - pos, "is_native=True, ");
    unsigned long long key = self->key.key;
    if (key) pos += PyOS_snprintf(buf + pos, sizeof(buf) - pos, "key=%llu, ", key);
    if (buf[pos-1] == ' ') pos -= 2;
    pos += PyOS_snprintf(buf + pos, sizeof(buf) - pos, ")");
    return PyUnicode_FromString(buf);
}

static PyObject*
SingleKey_get_key(SingleKey *self, void UNUSED *closure) {
    const unsigned long long val = self->key.key;
    return PyLong_FromUnsignedLongLong(val);
}

static PyObject*
SingleKey_get_mods(SingleKey *self, void UNUSED *closure) {
    const unsigned long mods = self->key.mods;
    return PyLong_FromUnsignedLong(mods);

}

static PyObject*
SingleKey_get_is_native(SingleKey *self, void UNUSED *closure) {
    if (self->key.is_native) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject*
SingleKey_defined_with_kitty_mod(SingleKey *self, void UNUSED *closure) {
    if (self->defined_with_kitty_mod || (self->key.mods & GLFW_MOD_KITTY)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}


static PyGetSetDef SingleKey_getsetters[] = {
    {"key", (getter)SingleKey_get_key, NULL, "The key as an integer", NULL},
    {"mods", (getter)SingleKey_get_mods, NULL, "The modifiers as an integer", NULL},
    {"is_native", (getter)SingleKey_get_is_native, NULL, "A bool", NULL},
    {"defined_with_kitty_mod", (getter)SingleKey_defined_with_kitty_mod, NULL, "A bool", NULL},
    {NULL}  /* Sentinel */
};

static Py_hash_t
SingleKey_hash(PyObject *self) {
    Py_hash_t ans = ((SingleKey*)self)->key.val;
    if (ans == -1) ans = -2;
    return ans;
}

static PyObject*
SingleKey_richcompare(PyObject *self, PyObject *other, int op) {
    if (!PyObject_TypeCheck(other, &SingleKey_Type)) { PyErr_SetString(PyExc_TypeError, "Cannot compare SingleKey to other objects"); return NULL; }
    SingleKey *a = (SingleKey*)self, *b = (SingleKey*)other;
    Py_RETURN_RICHCOMPARE(a->key.val, b->key.val, op);
}

static Py_ssize_t
SingleKey___len__(PyObject *self UNUSED) {
    return 3;
}

static PyObject *
SingleKey_item(PyObject *o, Py_ssize_t i) {
    SingleKey *self = (SingleKey*)o;
    switch(i) {
        case 0:
            return SingleKey_get_mods(self, NULL);
        case 1:
            return SingleKey_get_is_native(self, NULL);
        case 2:
            return SingleKey_get_key(self, NULL);
    }
    PyErr_SetString(PyExc_IndexError, "tuple index out of range");
    return NULL;
}

static PySequenceMethods SingleKey_sequence_methods = {
    .sq_length = SingleKey___len__,
    .sq_item = SingleKey_item,
};

static PyObject*
SingleKey_resolve_kitty_mod(SingleKey *self, PyObject *km) {
    if (!(self->key.mods & GLFW_MOD_KITTY)) { Py_INCREF(self); return (PyObject*)self; }
    unsigned long kitty_mod = PyLong_AsUnsignedLong(km);
    if (PyErr_Occurred()) return NULL;
    SingleKey *ans = (SingleKey*)SingleKey_Type.tp_alloc(&SingleKey_Type, 0);
    if (!ans) return NULL;
    ans->key.val = self->key.val;
    ans->key.mods = (ans->key.mods & ~GLFW_MOD_KITTY) | kitty_mod;
    ans->defined_with_kitty_mod = true;
    return (PyObject*)ans;
}

static PyObject*
SingleKey_replace(SingleKey *self, PyObject *args, PyObject *kw) {
    long long key = -2; unsigned short mods = 1 << (MOD_BITS + 1); int is_native = -1;
    if (!PyArg_ParseTupleAndKeywords(args, kw, "|HpL", SingleKey_kwds, &mods, &is_native, &key)) return NULL;
    SingleKey *ans = (SingleKey*)SingleKey_Type.tp_alloc(&SingleKey_Type, 0);
    if (ans) {
        if (key == -1) key = 0;
        ans->key.val = self->key.val;
        SingleKey_set_vals(ans, key, mods, is_native);
    }
    return (PyObject*)ans;
}

static PyMethodDef SingleKey_methods[] = {
    {"_replace", (PyCFunction)(void (*) (void))SingleKey_replace, METH_VARARGS | METH_KEYWORDS, ""},
    {"resolve_kitty_mod", (PyCFunction)SingleKey_resolve_kitty_mod, METH_O, ""},
    {NULL}  /* Sentinel */
};


static PyTypeObject SingleKey_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.SingleKey",
    .tp_basicsize = sizeof(SingleKey),
    .tp_dealloc = (destructor)SingleKey_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Compact and fast representation of a single key as defined in the config",
    .tp_new = SingleKey_new,
    .tp_hash = SingleKey_hash,
    .tp_richcompare = SingleKey_richcompare,
    .tp_as_sequence = &SingleKey_sequence_methods,
    .tp_repr = SingleKey_repr,
    .tp_methods = SingleKey_methods,
    .tp_getset = SingleKey_getsetters,
}; // }}}


bool
init_keys(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (PyType_Ready(&PyKeyEvent_Type) < 0) return false;
    if (PyModule_AddObject(module, "KeyEvent", (PyObject *)&PyKeyEvent_Type) != 0) return 0;
    Py_INCREF(&PyKeyEvent_Type);
    ADD_TYPE(SingleKey);
    return true;
}
