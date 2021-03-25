/*
 * linux_cursor_settings.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "linux_desktop_settings.h"
#include <stdlib.h>
#include <strings.h>
#include <string.h>

static const char *DESKTOP_SERVICE = "org.freedesktop.portal.Desktop";
static const char *DESKTOP_PATH = "/org/freedesktop/portal/desktop";
static const char *DESKTOP_INTERFACE = "org.freedesktop.portal.Settings";
static const char *GNOME_DESKTOP_NAMESPACE = "org.gnome.desktop.interface";


static char theme_name[64] = {0};
static int theme_size = -1;
static bool gnome_cursor_theme_read = false, gnome_cursor_size_read = false;

static bool
parse_dbus_message_for_type(DBusMessage *const reply, const char *errmsg, const int type, void *value) {
	DBusMessageIter iter[3];
	dbus_message_iter_init(reply, &iter[0]);
#define FAIL { _glfwInputError(GLFW_PLATFORM_ERROR, "%s", errmsg); return false; }
	if (dbus_message_iter_get_arg_type(&iter[0]) != DBUS_TYPE_VARIANT) FAIL;
	dbus_message_iter_recurse(&iter[0], &iter[1]);
	if (dbus_message_iter_get_arg_type(&iter[1]) != DBUS_TYPE_VARIANT) FAIL;
	dbus_message_iter_recurse(&iter[1], &iter[2]);
	if (dbus_message_iter_get_arg_type(&iter[2]) != type) FAIL;
	dbus_message_iter_get_basic(&iter[2], value);
	return true;
#undef FAIL
}

#define HANDLER(name) void name(DBusMessage *msg, const char* errmsg, void *data) { \
    (void)data; \
    if (errmsg) { \
        _glfwInputError(GLFW_PLATFORM_ERROR, "%s: failed with error: %s", #name, errmsg); \
        return; \
    }

HANDLER(on_gnome_cursor_theme_read)
    const char *name;
    if (!parse_dbus_message_for_type(msg, "Failed to get cursor theme name from reply", DBUS_TYPE_STRING, &name)) return;
    if (name && name[0]) {
        gnome_cursor_theme_read = true;
        strncpy(theme_name, name, sizeof(theme_name) - 1);
        if (gnome_cursor_size_read) _glfwPlatformChangeCursorTheme();
    }
}

HANDLER(on_gnome_cursor_size_read)
    int32_t sz;
    if (!parse_dbus_message_for_type(msg, "Failed to get cursor theme size from reply", DBUS_TYPE_INT32, &sz)) return;
    gnome_cursor_size_read = true;
    theme_size = sz;
    if (gnome_cursor_theme_read) _glfwPlatformChangeCursorTheme();
}
#undef HANDLER


static bool
call_read(DBusConnection *session_bus, dbus_pending_callback callback, const char *namespace, const char *key) {
    return glfw_dbus_call_method_with_reply(
            session_bus, DESKTOP_SERVICE, DESKTOP_PATH, DESKTOP_INTERFACE, "Read", DBUS_TIMEOUT_USE_DEFAULT,
            callback, NULL, DBUS_TYPE_STRING, &namespace, DBUS_TYPE_STRING, &key, DBUS_TYPE_INVALID);
}

static void
get_from_gnome(void) {
    theme_size = 32;
    DBusConnection *session_bus = glfw_dbus_session_bus();
    if (session_bus) {
        const char *theme_key = "cursor-theme";
        call_read(session_bus, on_gnome_cursor_theme_read, GNOME_DESKTOP_NAMESPACE, theme_key);
        const char *size_key = "cursor-size";
        call_read(session_bus, on_gnome_cursor_size_read, GNOME_DESKTOP_NAMESPACE, size_key);
    }
}


void
glfw_current_cursor_theme(const char **theme, int *size) {
    *theme = theme_name[0] ? theme_name : NULL;
    *size =  (theme_size > 0 && theme_size < 2048) ? theme_size : 32;
}

static void
get_cursor_theme_from_env(void) {
    const char *q = getenv("XCURSOR_THEME");
    if (q) strncpy(theme_name, q, sizeof(theme_name)-1);
    const char *env = getenv("XCURSOR_SIZE");
    theme_size = 32;
    if (env) {
        const int retval = atoi(env);
        if (retval > 0 && retval < 2048) theme_size = retval;
    }
}

void
glfw_initialize_desktop_settings(void) {
    get_cursor_theme_from_env();
    const char *desktop = getenv("XDG_CURRENT_DESKTOP");
    bool is_gnome = desktop && strncasecmp(desktop, "GNOME", sizeof("GNOME") - 1) == 0;
    if (is_gnome) get_from_gnome();
}
