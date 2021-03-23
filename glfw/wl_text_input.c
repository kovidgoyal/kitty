/*
 * wl_text_input.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "wl_text_input.h"
#include "internal.h"
#include "wayland-text-input-unstable-v3-client-protocol.h"

static struct zwp_text_input_v3*                  text_input;
static struct zwp_text_input_manager_v3*          text_input_manager;

static void
text_input_enter(void *data UNUSED, struct zwp_text_input_v3 *text_input UNUSED, struct wl_surface *surface UNUSED) {
    printf("enter text input\n");
}

static void
text_input_leave(void *data UNUSED, struct zwp_text_input_v3 *text_input UNUSED, struct wl_surface *surface UNUSED) {
    printf("leave text input\n");
}

static void
text_input_preedit_string(
        void                     *data UNUSED,
        struct zwp_text_input_v3 *text_input UNUSED,
        const char               *text UNUSED,
        int32_t                  cursor_begin UNUSED,
        int32_t                  cursor_end UNUSED
) {
}

static void
text_input_commit_string(void *data UNUSED, struct zwp_text_input_v3 *text_input UNUSED, const char *text UNUSED) {
}

static void
text_input_delete_surrounding_text(
        void *data UNUSED,
        struct zwp_text_input_v3 *zwp_text_input_v3 UNUSED,
        uint32_t before_length UNUSED,
        uint32_t after_length UNUSED) {
}

static void
text_input_done(void *data UNUSED, struct zwp_text_input_v3 *zwp_text_input_v3 UNUSED, uint32_t serial UNUSED) {
}

void
_glfwWaylandBindTextInput(struct wl_registry* registry, uint32_t name) {
    if (!text_input_manager) {
        text_input_manager =
            wl_registry_bind(registry, name,
                             &zwp_text_input_manager_v3_interface,
                             1);
    }
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
}
