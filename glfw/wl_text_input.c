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
#include <string.h>
#define debug debug_input

static struct zwp_text_input_v3*                  text_input;
static struct zwp_text_input_manager_v3*          text_input_manager;
static char *pending_pre_edit = NULL;
static char *current_pre_edit = NULL;
static char *pending_commit   = NULL;
static bool ime_focused = false;
static int last_cursor_left = 0, last_cursor_top = 0, last_cursor_width = 0, last_cursor_height = 0;
uint32_t commit_serial = 0;

static void commit(void) {
    if (text_input) {
        zwp_text_input_v3_commit (text_input);
        commit_serial++;
    }
}

static void
text_input_enter(void *data UNUSED, struct zwp_text_input_v3 *txt_input, struct wl_surface *surface UNUSED) {
    debug("text-input: enter event\n");
    if (txt_input) {
        ime_focused = true;
        zwp_text_input_v3_enable(txt_input);
        zwp_text_input_v3_set_content_type(txt_input, ZWP_TEXT_INPUT_V3_CONTENT_HINT_NONE, ZWP_TEXT_INPUT_V3_CONTENT_PURPOSE_TERMINAL);
        commit();
    }
}

static void
text_input_leave(void *data UNUSED, struct zwp_text_input_v3 *txt_input, struct wl_surface *surface UNUSED) {
    debug("text-input: leave event\n");
    if (txt_input) {
        ime_focused = false;
        zwp_text_input_v3_disable(txt_input);
        commit();
    }
}

static void
send_text(const char *text, GLFWIMEState ime_state) {
    _GLFWwindow *w = _glfwFocusedWindow();
    if (w && w->callbacks.keyboard) {
        GLFWkeyevent fake_ev = {.action = text ? GLFW_PRESS : GLFW_RELEASE};
        fake_ev.text = text;
        fake_ev.ime_state = ime_state;
        w->callbacks.keyboard((GLFWwindow*) w, &fake_ev);
    }
}

static void
text_input_preedit_string(
        void                     *data UNUSED,
        struct zwp_text_input_v3 *txt_input UNUSED,
        const char               *text,
        int32_t                  cursor_begin,
        int32_t                  cursor_end
) {
    debug("text-input: preedit_string event: text: %s cursor_begin: %d cursor_end: %d\n", text, cursor_begin, cursor_end);
    free(pending_pre_edit);
    pending_pre_edit = text ? _glfw_strdup(text) : NULL;
}

static void
text_input_commit_string(void *data UNUSED, struct zwp_text_input_v3 *txt_input UNUSED, const char *text) {
    debug("text-input: commit_string event: text: %s\n", text);
    free(pending_commit);
    pending_commit = text ? _glfw_strdup(text) : NULL;
}

static void
text_input_delete_surrounding_text(
        void *data UNUSED,
        struct zwp_text_input_v3 *txt_input UNUSED,
        uint32_t before_length,
        uint32_t after_length) {
    debug("text-input: delete_surrounding_text event: before_length: %u after_length: %u\n", before_length, after_length);
}

static void
text_input_done(void *data UNUSED, struct zwp_text_input_v3 *txt_input UNUSED, uint32_t serial) {
    debug("text-input: done event: serial: %u current_commit_serial: %u\n", serial, commit_serial);
    const bool bad_event = serial != commit_serial;
    // See https://wayland.app/protocols/text-input-unstable-v3#zwp_text_input_v3:event:done
    // for handling of bad events. As best as I can tell spec says we perform all client side actions as usual
    // but send nothing back to the compositor, aka no cursor position update.
    // See https://github.com/kovidgoyal/kitty/pull/7283 for discussion
    if ((pending_pre_edit == NULL && current_pre_edit == NULL) ||
        (pending_pre_edit && current_pre_edit && strcmp(pending_pre_edit, current_pre_edit) == 0)) {
        free(pending_pre_edit); pending_pre_edit = NULL;
    } else {
        free(current_pre_edit);
        current_pre_edit = pending_pre_edit;
        pending_pre_edit = NULL;
        if (current_pre_edit) {
            send_text(current_pre_edit, bad_event ? GLFW_IME_WAYLAND_DONE_EVENT : GLFW_IME_PREEDIT_CHANGED);
        } else {
            // Clear pre-edit text
            send_text(NULL, GLFW_IME_WAYLAND_DONE_EVENT);
        }
    }
    if (pending_commit) {
        send_text(pending_commit, GLFW_IME_COMMIT_TEXT);
        free(pending_commit); pending_commit = NULL;
    }
}

void
_glfwWaylandBindTextInput(struct wl_registry* registry, uint32_t name) {
    if (!text_input_manager && _glfw.hints.init.wl.ime) text_input_manager = wl_registry_bind(registry, name, &zwp_text_input_manager_v3_interface, 1);
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
    if (_glfw.hints.init.wl.ime && !text_input && text_input_manager && _glfw.wl.seat) {
        text_input = zwp_text_input_manager_v3_get_text_input(text_input_manager, _glfw.wl.seat);
        if (text_input) zwp_text_input_v3_add_listener(text_input, &text_input_listener, NULL);
    }
}

void
_glfwWaylandDestroyTextInput(void) {
    if (text_input) zwp_text_input_v3_destroy(text_input);
    if (text_input_manager) zwp_text_input_manager_v3_destroy(text_input_manager);
    text_input = NULL; text_input_manager = NULL;
    free(pending_pre_edit); pending_pre_edit = NULL;
    free(current_pre_edit); current_pre_edit = NULL;
    free(pending_commit); pending_commit = NULL;
}

void
_glfwPlatformUpdateIMEState(_GLFWwindow *w, const GLFWIMEUpdateEvent *ev) {
    if (!text_input) return;
    switch(ev->type) {
        case GLFW_IME_UPDATE_FOCUS:
            debug("\ntext-input: updating IME focus state, ime_focused: %d ev->focused: %d\n", ime_focused, ev->focused);
            if (ime_focused) {
                zwp_text_input_v3_enable(text_input);
                zwp_text_input_v3_set_content_type(text_input, ZWP_TEXT_INPUT_V3_CONTENT_HINT_NONE, ZWP_TEXT_INPUT_V3_CONTENT_PURPOSE_TERMINAL);
            } else {
                free(pending_pre_edit); pending_pre_edit = NULL;
                if (current_pre_edit) {
                    // Clear pre-edit text
                    send_text(NULL, GLFW_IME_PREEDIT_CHANGED);
                    free(current_pre_edit); current_pre_edit = NULL;
                }
                if (pending_commit) {
                    free(pending_commit); pending_commit = NULL;
                }
                zwp_text_input_v3_disable(text_input);
            }
            commit();
            break;
        case GLFW_IME_UPDATE_CURSOR_POSITION: {
            const double scale = _glfwWaylandWindowScale(w);
#define s(x) (int)round((x) / scale)
            const int left = s(ev->cursor.left), top = s(ev->cursor.top), width = s(ev->cursor.width), height = s(ev->cursor.height);
#undef s
            if (left != last_cursor_left || top != last_cursor_top || width != last_cursor_width || height != last_cursor_height) {
                last_cursor_left = left;
                last_cursor_top = top;
                last_cursor_width = width;
                last_cursor_height = height;
                debug("\ntext-input: updating cursor position: left=%d top=%d width=%d height=%d\n", left, top, width, height);
                zwp_text_input_v3_set_cursor_rectangle(text_input, left, top, width, height);
                commit();
            }
        }
            break;
    }
}
