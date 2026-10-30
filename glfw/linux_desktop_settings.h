/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "dbus_glfw.h"
#include "internal.h"


void glfw_initialize_desktop_settings(void);
void glfw_wait_for_desktop_settings(monotonic_t timeout);
void glfw_current_cursor_theme(const char **theme, int *size);
GLFWColorScheme glfw_current_system_color_theme(bool);

typedef enum { TITLEBAR_BUTTON_NONE, TITLEBAR_BUTTON_CLOSE, TITLEBAR_BUTTON_MAXIMIZE, TITLEBAR_BUTTON_MINIMIZE, TITLEBAR_BUTTON_COUNT } GLFWTitlebarButton;

typedef struct {
    GLFWTitlebarButton left[TITLEBAR_BUTTON_COUNT - 1], right[TITLEBAR_BUTTON_COUNT - 1];
    unsigned left_count, right_count;
} GLFWTitlebarButtonLayout;

typedef enum { TITLEBAR_ACTION_NONE, TITLEBAR_ACTION_MENU, TITLEBAR_ACTION_MAXIMIZE, TITLEBAR_ACTION_MINIMIZE } GLFWTitlebarAction;
typedef enum { TITLEBAR_GESTURE_DOUBLE_CLICK, TITLEBAR_GESTURE_MIDDLE_CLICK, TITLEBAR_GESTURE_RIGHT_CLICK, TITLEBAR_GESTURE_COUNT } GLFWTitlebarGesture;
GLFWTitlebarAction glfw_current_titlebar_action(GLFWTitlebarGesture gesture);
const GLFWTitlebarButtonLayout *glfw_current_titlebar_button_layout(void);
unsigned glfw_current_titlebar_height(void);
const GLFWTitlebarFont *glfw_current_titlebar_font(void);
