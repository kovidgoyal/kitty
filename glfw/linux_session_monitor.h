/*
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "dbus_glfw.h"
#include "internal.h"

// The session states reported by the Inhibit desktop portal
#define GLFW_SESSION_STATE_RUNNING 1
#define GLFW_SESSION_STATE_QUERY_END 2
#define GLFW_SESSION_STATE_ENDING 3

typedef void (*GLFWDBussessionstatefun)(uint32_t);
bool glfw_dbus_monitor_session_state(GLFWDBussessionstatefun callback);
