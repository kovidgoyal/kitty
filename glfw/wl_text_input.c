/*
 * wl_text_input.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "wl_text_input.h"
#include "internal.h"
#include "wayland-text-input-unstable-v3-client-protocol.h"
#include <stdlib.h>
#define debug(...) if (_glfw.hints.init.debugKeyboard) printf(__VA_ARGS__);

static struct zwp_text_input_v3*                  text_input;
static struct zwp_text_input_manager_v3*          text_input_manager;
static char *pending_pre_edit = NULL;
static char *pending_commit   = NULL;
uint32_t commit_serial = 0;

static void commit(void) {
    if (text_input) {
        zwp_text_input_v3_commit (text_input);
        commit_serial++;
    }
}

static void
text_input_enter(void *data UNUSED, struct zwp_text_input_v3 *text_input UNUSED, struct wl_surface *surface UNUSED) {
    debug("text-input: enter event\n");
    if (text_input) {
        zwp_text_input_v3_enable(text_input);
        zwp_text_input_v3_set_content_type(text_input, ZWP_TEXT_INPUT_V3_CONTENT_HINT_NONE, ZWP_TEXT_INPUT_V3_CONTENT_PURPOSE_TERMINAL);
        commit();
    }
}

static void
text_input_leave(void *data UNUSED, struct zwp_text_input_v3 *text_input UNUSED, struct wl_surface *surface UNUSED) {
    debug("text-input: leave event\n");
    if (text_input) {
        zwp_text_input_v3_disable(text_input);
        commit();
    }
}

static inline void
send_text(const char *text, GLFWIMEState ime_state) {
    _GLFWwindow *w = _glfwFocusedWindow();
    if (w && w->callbacks.keyboard) {
        GLFWkeyevent fake_ev = {.action = GLFW_PRESS};
        fake_ev.text = text;
        fake_ev.ime_state = ime_state;
        w->callbacks.keyboard((GLFWwindow*) w, &fake_ev);
    }
}

static void
text_input_preedit_string(
        void                     *data UNUSED,
        struct zwp_text_input_v3 *text_input UNUSED,
        const char               *text,
        int32_t                  cursor_begin,
        int32_t                  cursor_end
) {
    debug("text-input: preedit_string event: text: %s cursor_begin: %d cursor_end: %d\n", text, cursor_begin, cursor_end);
    free(pending_pre_edit);
    pending_pre_edit = text ? _glfw_strdup(text) : NULL;
}

static void
text_input_commit_string(void *data UNUSED, struct zwp_text_input_v3 *text_input UNUSED, const char *text) {
    debug("text-input: commit_string event: text: %s\n", text);
    free(pending_commit);
    pending_commit = text ? _glfw_strdup(text) : NULL;
}

static void
text_input_delete_surrounding_text(
        void *data UNUSED,
        struct zwp_text_input_v3 *zwp_text_input_v3 UNUSED,
        uint32_t before_length,
        uint32_t after_length) {
    debug("text-input: delete_surrounding_text event: before_length: %u after_length: %u\n", before_length, after_length);
}

static void
text_input_done(void *data UNUSED, struct zwp_text_input_v3 *zwp_text_input_v3 UNUSED, uint32_t serial UNUSED) {
    debug("text-input: done event: serial: %u current_commit_serial: %u\n", serial, commit_serial);
    if (serial != commit_serial) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: text_input_done serial mismatch, expected=%u got=%u\n", commit_serial, serial);
        return;
    }
    if (pending_pre_edit) {
        send_text(pending_pre_edit, GLFW_IME_PREEDIT_CHANGED);
        free(pending_pre_edit); pending_pre_edit = NULL;
    }
    if (pending_commit) {
        send_text(pending_commit, GLFW_IME_COMMIT_TEXT);
        free(pending_commit); pending_commit = NULL;
    }
}

void
_glfwWaylandBindTextInput(struct wl_registry* registry, uint32_t name) {
    if (!text_input_manager) text_input_manager = wl_registry_bind(registry, name, &zwp_text_input_manager_v3_interface, 1);
}

void
_glfwWaylandInitTextInput(void) {
    static const struct zwp_text_input_v3_listener text_input_listener = {
        .enter = text_input_enter,
        .leave = text_input_leave,
        .preedit_string = text_input_preedit_string,
        .commit_string = text_input_commit_string,
        .delete_surrounding_text = text_input_delete_surrounding_text,
        .done = text_input_done,
    };
    if (!text_input) {
        if (text_input_manager && _glfw.wl.seat) {
            text_input = zwp_text_input_manager_v3_get_text_input(
                    text_input_manager, _glfw.wl.seat);
            if (text_input) zwp_text_input_v3_add_listener(text_input, &text_input_listener, NULL);
        }
    }
}

void
_glfwWaylandDestroyTextInput(void) {
    if (text_input) zwp_text_input_v3_destroy(text_input);
    if (text_input_manager) zwp_text_input_manager_v3_destroy(text_input_manager);
    text_input = NULL; text_input_manager = NULL;
    free(pending_pre_edit); pending_pre_edit = NULL;
    free(pending_commit); pending_commit = NULL;
}

void
_glfwPlatformUpdateIMEState(_GLFWwindow *w, const GLFWIMEUpdateEvent *ev) {
    if (!text_input) return;
    switch(ev->type) {
        case GLFW_IME_UPDATE_FOCUS:
            debug("\ntext-input: updating IME focus state, focused: %d\n", ev->focused);
            if (ev->focused) zwp_text_input_v3_enable(text_input); else zwp_text_input_v3_disable(text_input);
            commit();
            break;
        case GLFW_IME_UPDATE_CURSOR_POSITION: {
            const int scale = w->wl.scale;
            const int left = ev->cursor.left / scale, top = ev->cursor.top / scale, width = ev->cursor.width / scale, height = ev->cursor.height / scale;
            debug("\ntext-input: updating cursor position: left=%d top=%d width=%d height=%d\n", left, top, width, height);
            zwp_text_input_v3_set_cursor_rectangle(text_input, left, top, width, height);
            commit();
        }
            break;
    }
}
