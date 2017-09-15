/*
 * keys.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "keys.h"
#include "state.h"
#include <GLFW/glfw3.h>

const uint8_t*
key_to_bytes(int glfw_key, bool smkx, bool extended, int mods, int action) {
    if ((action & 3) == 3) return NULL;
    if ((unsigned)glfw_key >= sizeof(key_map)/sizeof(key_map[0]) || glfw_key < 0) return NULL;
    uint16_t key = key_map[glfw_key];
    if (key == UINT8_MAX) return NULL;
    mods &= 0xF;
    key |= (mods & 0xF) << 7;
    key |= (action & 3) << 11;
    key |= (smkx & 1) << 13;
    key |= (extended & 1) << 14;
    if (key >= SIZE_OF_KEY_BYTES_MAP) return NULL;
    return key_bytes[key];
}

void
set_special_key_combo(int glfw_key, int mods) {
    int k = (glfw_key & 0x7f) | ( (mods & 0xF) << 7);
    needs_special_handling[k] = true;
}

static inline Window*
active_window() {
    Tab *t = global_state.tabs + global_state.active_tab;
    Window *w = t->windows + t->active_window;
    if (w->render_data.screen) return w;
    return NULL;
}

void
on_text_input(unsigned int codepoint, int mods) {
    Window *w = active_window();
    static char buf[10];

    if (w != NULL) {
        Screen *screen = w->render_data.screen;
        bool handle_event = (
                mods <= GLFW_MOD_SHIFT ||
                (!screen->modes.mEXTENDED_KEYBOARD && (mods == GLFW_MOD_ALT || mods == (GLFW_MOD_ALT | GLFW_MOD_SHIFT)))
            ) ? true : false;  // non text input is handle in on_key_input
        if (handle_event) {
            unsigned int sz = encode_utf8(codepoint, buf);
            if (sz) schedule_write_to_child(w->id, buf, sz);
        }
    }
}

#define PYWRAP1(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args)
#define PA(fmt, ...) if(!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;
#define M(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}

PYWRAP1(key_to_bytes) {
    int glfw_key, smkx, extended, mods, action;
    PA("ippii", &glfw_key, &smkx, &extended, &mods, &action);
    const uint8_t *ans = key_to_bytes(glfw_key, smkx & 1, extended & 1, mods, action);
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
