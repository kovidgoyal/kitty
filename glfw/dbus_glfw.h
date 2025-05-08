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

#include <dbus/dbus.h>
#include "backend_utils.h"

static inline void cleanup_msg(void *p) { DBusMessage *m = *(DBusMessage**)p; if (m) dbus_message_unref(m); m = NULL; }
#define RAII_MSG(name, initializer) __attribute__((cleanup(cleanup_msg))) DBusMessage *name = initializer

typedef void(*dbus_pending_callback)(DBusMessage *msg, const DBusError *err, void* data);

typedef struct {
    EventLoopData* eld;
} _GLFWDBUSData;


bool glfw_dbus_init(_GLFWDBUSData *dbus, EventLoopData *eld);
void glfw_dbus_terminate(_GLFWDBUSData *dbus);
DBusConnection* glfw_dbus_connect_to(const char *path, const char* err_msg, const char* name, bool register_on_bus);
void glfw_dbus_close_connection(DBusConnection *conn);
bool
call_method_with_msg(DBusConnection *conn, DBusMessage *msg, int timeout, dbus_pending_callback callback, void *user_data, bool block);
bool
glfw_dbus_call_method_no_reply(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, ...);
bool
glfw_dbus_call_method_with_reply(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, int timeout_ms, dbus_pending_callback callback, void *user_data, ...);
bool
glfw_dbus_call_blocking_method(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, int timeout, dbus_pending_callback callback, void* user_data, ...);
void glfw_dbus_dispatch(DBusConnection *);
void glfw_dbus_session_bus_dispatch(void);
bool glfw_dbus_get_args(DBusMessage *msg, const char *failmsg, ...);
int glfw_dbus_match_signal(DBusMessage *msg, const char *interface, ...);
DBusConnection* glfw_dbus_session_bus(void);
