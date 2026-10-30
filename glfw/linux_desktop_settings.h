/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "dbus_glfw.h"
#include "internal.h"


void glfw_initialize_desktop_settings(void);
void glfw_current_cursor_theme(const char **theme, int *size);
GLFWColorScheme glfw_current_system_color_theme(bool);

typedef struct {
    int left[3], right[3]; // close=1, maximize=2, minimize=3
    unsigned left_count, right_count;
} GLFWTitlebarButtonLayout;

typedef enum { TITLEBAR_ACTION_NONE, TITLEBAR_ACTION_MENU, TITLEBAR_ACTION_MAXIMIZE, TITLEBAR_ACTION_MINIMIZE } GLFWTitlebarAction;
// Gesture: 0=double click, 1=middle click, 2=right click.
GLFWTitlebarAction glfw_current_titlebar_action(unsigned gesture);
const GLFWTitlebarButtonLayout *glfw_current_titlebar_button_layout(void);
double glfw_current_titlebar_text_scale(void);
unsigned glfw_current_titlebar_height(void);
const char *glfw_current_system_font(double *text_scale, bool *bold);
