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


#include "internal.h"
#include "dbus_glfw.h"

static inline void
report_error(DBusError *err, const char *msg) {
    const char *prefix = msg ? msg : "DBUS error occurred";
    _glfwInputError(GLFW_PLATFORM_ERROR, "%s: %s", prefix, err->message);
    dbus_error_free(err);
}


GLFWbool
glfw_dbus_init(_GLFWDBUSData *dbus) {
    DBusError err;
    if (!dbus->session_conn) {
        dbus_error_init(&err);
        dbus->session_conn = dbus_bus_get_private(DBUS_BUS_SESSION, &err);
        if (dbus_error_is_set(&err)) {
            report_error(&err, "Failed to connect to DBUS system bus");
            return GLFW_FALSE;
        }
    }
    return GLFW_TRUE;
}

void
glfw_dbus_terminate(_GLFWDBUSData *dbus) {
    if (dbus->session_conn) {
        dbus_connection_close(dbus->session_conn);
        dbus_connection_unref(dbus->session_conn);
        dbus->session_conn = NULL;
    }
}
