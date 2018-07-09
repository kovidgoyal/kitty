//========================================================================
// GLFW 3.3 XKB - www.glfw.org
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

#include <dbus/dbus.h>
#include "backend_utils.h"

typedef struct {
    EventLoopData* eld;
} _GLFWDBUSData;


GLFWbool glfw_dbus_init(_GLFWDBUSData *dbus, EventLoopData *eld);
void glfw_dbus_terminate(_GLFWDBUSData *dbus);
DBusConnection* glfw_dbus_connect_to(const char *path, const char* err_msg);
void glfw_dbus_close_connection(DBusConnection *conn);
GLFWbool glfw_dbus_call_void_method(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, ...);
GLFWbool
glfw_dbus_call_method(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, ...);
void glfw_dbus_dispatch(DBusConnection *);
