/*
 * keys.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "keys.h"
#include "state.h"
#include "screen.h"
#include <GLFW/glfw3.h>

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

void
set_special_key_combo(int glfw_key, int mods) {
    uint16_t key = key_map[glfw_key];
    if (key != UINT8_MAX) {
        key = SPECIAL_INDEX(key);
        needs_special_handling[key] = true;
    }
}

static inline Window*
active_window() {
    Tab *t = global_state.callback_os_window->tabs + global_state.callback_os_window->active_tab;
    Window *w = t->windows + t->active_window;
    if (w->render_data.screen) return w;
    return NULL;
}

void
on_text_input(unsigned int codepoint, int mods) {
    Window *w = active_window();
    static char buf[16];
    unsigned int sz = 0;

    if (w != NULL) {
        bool is_text = mods <= GLFW_MOD_SHIFT;
        if (is_text) sz = encode_utf8(codepoint, buf);
#ifdef __APPLE__
        if (!OPT(macos_option_as_alt) && IS_ALT_MODS(mods)) sz = encode_utf8(codepoint, buf);
#endif
        if (sz) schedule_write_to_child(w->id, buf, sz);
    }
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

static inline int
get_localized_key(int key, int scancode) {
    const char *name = glfwGetKeyName(key, scancode);
    if (name == NULL || name[1] != 0) return key;
    switch(name[0]) {
#define K(ch, name) case ch: return GLFW_KEY_##name
        // key names {{{
        K('A', A); K('a', A);
        K('B', B); K('b', B);
        K('C', C); K('c', C); 
        K('D', D); K('d', D);
        K('E', E); K('e', E);
        K('F', F); K('f', F);
        K('G', G); K('g', G);
        K('H', H); K('h', H);
        K('I', I); K('i', I);
        K('J', J); K('j', J);
        K('K', K); K('k', K);
        K('L', L); K('l', L);
        K('M', M); K('m', M);
        K('N', N); K('n', N);
        K('O', O); K('o', O);
        K('P', P); K('p', P);
        K('Q', Q); K('q', Q);
        K('R', R); K('r', R);
        K('S', S); K('s', S);
        K('T', T); K('t', T);
        K('U', U); K('u', U);
        K('V', V); K('v', V);
        K('W', W); K('w', W);
        K('X', X); K('x', X);
        K('Y', Y); K('y', Y);
        K('Z', Z); K('z', Z);
        K('0', 0);
        K('1', 1);
        K('2', 2);
        K('3', 3);
        K('5', 5);
        K('6', 6);
        K('7', 7);
        K('8', 8);
        K('9', 9);
        K('\'', APOSTROPHE);
        K(',', COMMA);
        K('.', PERIOD);
        K('/', SLASH);
        K('-', MINUS);
        K(';', SEMICOLON);
        K('=', EQUAL);
        K('[', LEFT_BRACKET);
        K(']', RIGHT_BRACKET);
        K('`', GRAVE_ACCENT);
        K('\\', BACKSLASH);
        // }}}
#undef K
        default:
            return key;
    }
}

void
on_key_input(int key, int scancode, int action, int mods) {
    Window *w = active_window();
    if (!w) return;
    Screen *screen = w->render_data.screen;
    int lkey = get_localized_key(key, scancode);
    if (action == GLFW_PRESS || action == GLFW_REPEAT) {
        uint16_t qkey = key_map[lkey];
        bool special = false;
        if (qkey != UINT8_MAX) {
            qkey = SPECIAL_INDEX(qkey);
            special = needs_special_handling[qkey];
        }
        /* printf("key: %s mods: %d special: %d\n", key_name(lkey), mods, special); */
        if (special) {
            PyObject *ret = PyObject_CallMethod(global_state.boss, "dispatch_special_key", "iiii", lkey, scancode, action, mods);
            if (ret == NULL) { PyErr_Print(); }
            else {
                bool consumed = ret == Py_True;
                Py_DECREF(ret);
                if (consumed) return;
            }
        }
    }
    if (screen->scrolled_by && action == GLFW_PRESS && !is_modifier_key(key)) {
        screen_history_scroll(screen, SCROLL_FULL, false);  // scroll back to bottom
    }
#ifdef __APPLE__
    if (!OPT(macos_option_as_alt) && IS_ALT_MODS(mods)) return;
#endif
    if (
            action == GLFW_PRESS ||
            (action == GLFW_REPEAT && screen->modes.mDECARM) ||
            screen->modes.mEXTENDED_KEYBOARD
       ) {
        const char *data = key_to_bytes(lkey, screen->modes.mDECCKM, screen->modes.mEXTENDED_KEYBOARD, mods, action);
        if (data) schedule_write_to_child(w->id, (data + 1), *data);
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

static PyMethodDef module_methods[] = {
    M(key_to_bytes, METH_VARARGS), 
    {0}
};

bool
init_keys(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
