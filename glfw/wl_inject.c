/*
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Virtual pointer and keyboard injection for the Wayland backend.
// Uses zwlr_virtual_pointer_v1 and zwp_virtual_keyboard_v1.

#define _GNU_SOURCE
#include "internal.h"
#include <stdlib.h>
#include "xkb_glfw.h"
#include "memfd.h"
#include <time.h>
#include <unistd.h>
#include <string.h>
#include <linux/input-event-codes.h>

GLFWAPI bool
glfwWaylandCreateVirtualDevices(void) {
    if (_glfw.wl.virtual_pointer_manager && _glfw.wl.seat)
        _glfw.wl.virtual_pointer = zwlr_virtual_pointer_manager_v1_create_virtual_pointer(_glfw.wl.virtual_pointer_manager, _glfw.wl.seat);
    if (_glfw.wl.virtual_keyboard_manager && _glfw.wl.seat)
        _glfw.wl.virtual_keyboard = zwp_virtual_keyboard_manager_v1_create_virtual_keyboard(_glfw.wl.virtual_keyboard_manager, _glfw.wl.seat);
    if (_glfw.wl.virtual_pointer || _glfw.wl.virtual_keyboard) {
        // Two roundtrips: first ensures the compositor has processed the creation
        // requests, second gives wlroots time to advertise the updated seat
        // capabilities (pointer/keyboard) to any client that connects next.
        wl_display_roundtrip(_glfw.wl.display);
        wl_display_roundtrip(_glfw.wl.display);
    }
    return _glfw.wl.virtual_pointer != NULL;
}

static uint32_t
ms_now(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint32_t)(ts.tv_sec * 1000u + ts.tv_nsec / 1000000u);
}

static uint32_t
glfw_button_to_evdev(int button) {
    switch (button) {
        case GLFW_MOUSE_BUTTON_LEFT: return BTN_LEFT;
        case GLFW_MOUSE_BUTTON_RIGHT: return BTN_RIGHT;
        case GLFW_MOUSE_BUTTON_MIDDLE: return BTN_MIDDLE;
        case 3: return BTN_SIDE;
        case 4: return BTN_EXTRA;
        case 5: return BTN_FORWARD;
        case 6: return BTN_BACK;
        case 7: return BTN_TASK;
        default: return BTN_LEFT;
    }
}

GLFWAPI void
glfwWaylandInjectMouseMotionAbsolute(uint32_t x, uint32_t y, uint32_t x_extent, uint32_t y_extent) {
    if (!_glfw.wl.virtual_pointer) return;
    zwlr_virtual_pointer_v1_motion_absolute(_glfw.wl.virtual_pointer, ms_now(), x, y, x_extent, y_extent);
    zwlr_virtual_pointer_v1_frame(_glfw.wl.virtual_pointer);
    wl_display_flush(_glfw.wl.display);
}

GLFWAPI void
glfwWaylandInjectMouseButton(int button, int action) {
    if (!_glfw.wl.virtual_pointer) return;
    uint32_t state = (action == GLFW_PRESS) ? 1u : 0u;
    zwlr_virtual_pointer_v1_button(_glfw.wl.virtual_pointer, ms_now(), glfw_button_to_evdev(button), state);
    zwlr_virtual_pointer_v1_frame(_glfw.wl.virtual_pointer);
    wl_display_flush(_glfw.wl.display);
}

// --- keyboard injection ---

typedef struct {
    xkb_keysym_t target;
    uint32_t scancode; // evdev scancode = XKB keycode - 8; 0 means not found
} KeySearch;

static void
search_keymap_for_sym(struct xkb_keymap *keymap, xkb_keycode_t keycode, void *data) {
    KeySearch *s = data;
    if (s->scancode) return;
    const xkb_keysym_t *syms;
    int n = xkb_keymap_key_get_syms_by_level(keymap, keycode, 0, 0, &syms);
    for (int i = 0; i < n; i++) {
        if (syms[i] == s->target) {
            s->scancode = keycode - 8;
            return;
        }
    }
}

static bool keymap_sent = false;

static void
ensure_keymap_sent(void) {
    if (keymap_sent || !_glfw.wl.virtual_keyboard) return;
    struct xkb_keymap *km = _glfw.wl.xkb.keymap ? _glfw.wl.xkb.keymap : _glfw.wl.xkb.default_keymap;
    if (!km) return;
    char *str = xkb_keymap_get_as_string(km, XKB_KEYMAP_FORMAT_TEXT_V1);
    if (!str) return;
    size_t len = strlen(str) + 1;
#ifdef HAS_MEMFD_CREATE
    int fd = glfw_memfd_create("vk-keymap", MFD_CLOEXEC);
#else
    char template[] = "/tmp/.vk-keymap-XXXXXX";
    int fd = createTmpfileCloexec(template);
#endif
    if (fd >= 0 && (size_t)write(fd, str, len) == len) {
        zwp_virtual_keyboard_v1_keymap(_glfw.wl.virtual_keyboard, WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1, fd, (uint32_t)len);
        keymap_sent = true;
    }
    free(str);
    if (fd >= 0) close(fd);
}

GLFWAPI void
glfwWaylandInjectKey(int key, int action, int mods) {
    if (!_glfw.wl.virtual_keyboard) return;
    ensure_keymap_sent();
    if (!keymap_sent) return;

    struct xkb_keymap *km = _glfw.wl.xkb.keymap ? _glfw.wl.xkb.keymap : _glfw.wl.xkb.default_keymap;
    if (!km) return;

    xkb_keysym_t sym;
    if ((uint32_t)key >= GLFW_FKEY_FIRST) {
        sym = glfw_xkb_sym_for_key((uint32_t)key);
        if (sym == XKB_KEY_NoSymbol) return;
    } else {
        sym = xkb_utf32_to_keysym((uint32_t)key);
        if (sym == XKB_KEY_NoSymbol) return;
    }

    KeySearch search = {.target = sym, .scancode = 0};
    xkb_keymap_key_for_each(km, search_keymap_for_sym, &search);
    if (!search.scancode) return;

    uint32_t depressed = 0;
    if (mods & GLFW_MOD_SHIFT) {
        xkb_mod_index_t idx = xkb_keymap_mod_get_index(km, XKB_MOD_NAME_SHIFT);
        if (idx != XKB_MOD_INVALID) depressed |= (1u << idx);
    }
    if (mods & GLFW_MOD_CONTROL) {
        xkb_mod_index_t idx = xkb_keymap_mod_get_index(km, XKB_MOD_NAME_CTRL);
        if (idx != XKB_MOD_INVALID) depressed |= (1u << idx);
    }
    if (mods & GLFW_MOD_ALT) {
        xkb_mod_index_t idx = xkb_keymap_mod_get_index(km, XKB_MOD_NAME_ALT);
        if (idx != XKB_MOD_INVALID) depressed |= (1u << idx);
    }
    if (mods & GLFW_MOD_SUPER) {
        xkb_mod_index_t idx = xkb_keymap_mod_get_index(km, XKB_MOD_NAME_LOGO);
        if (idx != XKB_MOD_INVALID) depressed |= (1u << idx);
    }
    zwp_virtual_keyboard_v1_modifiers(_glfw.wl.virtual_keyboard, depressed, 0, 0, 0);
    uint32_t state = (action != GLFW_RELEASE) ? 1u : 0u;
    zwp_virtual_keyboard_v1_key(_glfw.wl.virtual_keyboard, ms_now(), search.scancode, state);
    wl_display_flush(_glfw.wl.display);
}

GLFWAPI void
glfwWaylandInjectCleanup(void) {
    keymap_sent = false;
}
