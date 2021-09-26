//========================================================================
// GLFW 3.4 XKB - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2018 Kovid Goyal <kovid@kovidgoyal.net>
//
// This software is provided 'as-is', without any express or implied
// warranty. In no event will the authors be held liable for any damages
// arising from the use of this software.
//
// Permission is granted to anyone to use this software for any purpose,
// including commercial applications, and to alter it and redistribute it
// freely, subject to the following restrictions:
//
// 1. The origin of this software must not be misrepresented; you must not
//    claim that you wrote the original software. If you use this software
//    in a product, an acknowledgment in the product documentation would
//    be appreciated but is not required.
//
// 2. Altered source versions must be plainly marked as such, and must not
//    be misrepresented as being the original software.
//
// 3. This notice may not be removed or altered from any source
//    distribution.
//
//========================================================================


#pragma once

#include "internal.h"
#include "dbus_glfw.h"
#include <xkbcommon/xkbcommon.h>

typedef struct {
    bool ok, inited, name_owner_changed;
    time_t address_file_mtime;
    DBusConnection *conn;
    const char *input_ctx_path, *address_file_name, *address;
} _GLFWIBUSData;

typedef struct {
    xkb_keycode_t ibus_keycode;
    xkb_keysym_t ibus_keysym;
    GLFWid window_id;
    GLFWkeyevent glfw_ev;
    char __embedded_text[64];
} _GLFWIBUSKeyEvent;

void glfw_connect_to_ibus(_GLFWIBUSData *ibus);
void glfw_ibus_terminate(_GLFWIBUSData *ibus);
void glfw_ibus_set_focused(_GLFWIBUSData *ibus, bool focused);
void glfw_ibus_dispatch(_GLFWIBUSData *ibus);
bool ibus_process_key(const _GLFWIBUSKeyEvent *ev_, _GLFWIBUSData *ibus);
void glfw_ibus_set_cursor_geometry(_GLFWIBUSData *ibus, int x, int y, int w, int h);
