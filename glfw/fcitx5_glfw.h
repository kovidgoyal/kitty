#pragma once

#include "internal.h"
#include "dbus_glfw.h"
#include <xkbcommon/xkbcommon.h>

typedef struct {
    bool ok, inited;
    DBusConnection *conn;
    const char *input_ctx_path, *address_file_name, *address;

} _GLFWFCITX5Data;

typedef struct {
    xkb_keycode_t fcitx5_keycode;
    xkb_keysym_t fcitx5_keysym;
    uint32_t is_release;    // This is a uint32_t instead of bool because unfortunate padding can make it difficult to marshal for dbus
    uint32_t time;
    GLFWid window_id;
    GLFWkeyevent glfw_ev;
    char __embedded_text[64];
} _GLFWFCITX5KeyEvent;

void glfw_connect_to_fcitx5(_GLFWFCITX5Data *fcitx5);
void glfw_fcitx5_terminate(_GLFWFCITX5Data *fcitx5);
void glfw_fcitx5_set_focused(_GLFWFCITX5Data *fcitx5, bool focused);
void glfw_fcitx5_dispatch(_GLFWFCITX5Data *fcitx5);
bool fcitx5_process_key(const _GLFWFCITX5KeyEvent *ev_, _GLFWFCITX5Data *fcitx5);
void glfw_fcitx5_set_cursor_geometry(_GLFWFCITX5Data *fcitx5, int x, int y, int w, int h);
