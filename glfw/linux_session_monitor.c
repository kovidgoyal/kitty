/*
 * linux_session_monitor.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Monitors the state of the desktop session using the Inhibit desktop portal, so that the application can save its state
// before the user is logged out. When the session is about to end, the portal changes the state to Query End and the
// application must acknowledge it within a second. The callback is run before acknowledging, so that the application can save
// its state before the session proceeds to the Ending state.
//
// Creating the monitor is a portal request: the CreateMonitor method returns a request object and the result is reported later by
// the Response signal of that object. Signals are accepted only from the portal that replied to CreateMonitor and only for the
// monitor session created by it, so that other clients on the session bus cannot fake a session ending.
//
// The monitor session ends if the portal exits, for example, because it crashed, so the monitor is created again when that happens.
// This is done only if the monitor was created successfully, so that a portal that crashes when creating it is not restarted in a
// loop by DBUS activation.

#include "linux_session_monitor.h"
#include <stdio.h>
#include <string.h>

#define PORTAL_SERVICE "org.freedesktop.portal.Desktop"
#define PORTAL_PATH "/org/freedesktop/portal/desktop"
#define INHIBIT_INTERFACE "org.freedesktop.portal.Inhibit"
#define REQUEST_INTERFACE "org.freedesktop.portal.Request"
// Object paths include the unique name of the connection, so a fixed token is unique, as there is only one monitor per connection
#define HANDLE_TOKEN "glfw_session_monitor"

static GLFWDBussessionstatefun session_state_callback = NULL;
static uint32_t current_session_state = GLFW_SESSION_STATE_RUNNING;
static bool monitoring = false;
// Whether the portal reported that the monitor was created
static bool established = false;
// The unique name of the portal that replied to CreateMonitor, empty until it replies
static char portal_name[256];
static char request_path[512], session_path[512];

static bool
portal_object_path(DBusConnection *conn, const char *kind, char *buf, size_t sz) {
    // The portal creates objects at PORTAL_PATH/kind/SENDER/TOKEN where SENDER is the unique name of the connection without
    // the leading colon and with dots replaced by underscores
    const char *unique_name = dbus_bus_get_unique_name(conn);
    if (!unique_name || unique_name[0] != ':') return false;
    const int prefix_len = snprintf(buf, sz, PORTAL_PATH "/%s/", kind);
    if (prefix_len < 0 || (size_t)prefix_len >= sz) return false;
    const int n = snprintf(buf + prefix_len, sz - prefix_len, "%s/" HANDLE_TOKEN, unique_name + 1);
    if (n < 0 || (size_t)n >= sz - prefix_len) return false;
    for (char *p = buf + prefix_len; *p && *p != '/'; p++) {
        if (*p == '.') *p = '_';
    }
    return true;
}

static bool
add_response_match(DBusConnection *conn) {
    char rule[sizeof(request_path) + 128];
    const int n = snprintf(rule, sizeof(rule), "type='signal',interface='" REQUEST_INTERFACE "',member='Response',path='%s'", request_path);
    if (n < 0 || (size_t)n >= sizeof(rule)) return false;
    dbus_bus_add_match(conn, rule, NULL);
    return true;
}

static bool
is_from_portal(DBusMessage *msg) {
    const char *sender = dbus_message_get_sender(msg);
    return portal_name[0] && sender && strcmp(sender, portal_name) == 0;
}

static bool
read_session_state(DBusMessageIter *dict, uint32_t *state) {
    DBusMessageIter entry, value;
    while (dbus_message_iter_get_arg_type(dict) == DBUS_TYPE_DICT_ENTRY) {
        dbus_message_iter_recurse(dict, &entry);
        if (dbus_message_iter_get_arg_type(&entry) == DBUS_TYPE_STRING) {
            const char *key;
            dbus_message_iter_get_basic(&entry, &key);
            if (strcmp(key, "session-state") == 0 && dbus_message_iter_next(&entry) && dbus_message_iter_get_arg_type(&entry) == DBUS_TYPE_VARIANT) {
                dbus_message_iter_recurse(&entry, &value);
                if (dbus_message_iter_get_arg_type(&value) != DBUS_TYPE_UINT32) return false;
                dbus_message_iter_get_basic(&value, state);
                return true;
            }
        }
        if (!dbus_message_iter_next(dict)) break;
    }
    // The state dictionary does not have a valid session state
    return false;
}

static void
on_state_changed(DBusConnection *conn, DBusMessage *msg) {
    DBusMessageIter iter, dict;
    const char *session_handle = NULL;
    if (!dbus_message_iter_init(msg, &iter) || dbus_message_iter_get_arg_type(&iter) != DBUS_TYPE_OBJECT_PATH) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: StateChanged signal does not have a session handle");
        return;
    }
    dbus_message_iter_get_basic(&iter, &session_handle);
    if (strcmp(session_handle, session_path) != 0) return;
    if (!dbus_message_iter_next(&iter) || dbus_message_iter_get_arg_type(&iter) != DBUS_TYPE_ARRAY) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: StateChanged signal does not have a state dictionary");
        return;
    }
    dbus_message_iter_recurse(&iter, &dict);
    uint32_t state;
    if (!read_session_state(&dict, &state)) return;
    // The signal is also sent when only the screensaver state changes
    const bool changed = state != current_session_state;
    current_session_state = state;
    if (changed && session_state_callback) session_state_callback(state);
    if (state == GLFW_SESSION_STATE_QUERY_END) {
        if (!glfw_dbus_call_method_no_reply(
                conn, PORTAL_SERVICE, PORTAL_PATH, INHIBIT_INTERFACE, "QueryEndResponse", DBUS_TYPE_OBJECT_PATH, &session_handle, DBUS_TYPE_INVALID))
            _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: Failed to respond to the session ending");
    }
}

static void
on_monitor_response(DBusMessage *msg) {
    DBusMessageIter iter;
    uint32_t response;
    if (!dbus_message_iter_init(msg, &iter) || dbus_message_iter_get_arg_type(&iter) != DBUS_TYPE_UINT32) {
        monitoring = false;
        _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: The response to CreateMonitor does not have a response code");
        return;
    }
    dbus_message_iter_get_basic(&iter, &response);
    if (response != 0) {
        monitoring = false;
        _glfwInputError(
            GLFW_PLATFORM_ERROR,
            "Inhibit portal: Failed to monitor the session state, make sure your desktop portal supports version 3 of the Inhibit "
            "portal. Response code: %u",
            response);
        return;
    }
    established = true;
    // Use the session handle from the results, in case the portal ignored session_handle_token
    DBusMessageIter results, entry, value;
    if (!dbus_message_iter_next(&iter) || dbus_message_iter_get_arg_type(&iter) != DBUS_TYPE_ARRAY) return;
    dbus_message_iter_recurse(&iter, &results);
    for (; dbus_message_iter_get_arg_type(&results) == DBUS_TYPE_DICT_ENTRY; dbus_message_iter_next(&results)) {
        const char *key, *handle;
        dbus_message_iter_recurse(&results, &entry);
        if (dbus_message_iter_get_arg_type(&entry) != DBUS_TYPE_STRING) continue;
        dbus_message_iter_get_basic(&entry, &key);
        if (strcmp(key, "session_handle") != 0 || !dbus_message_iter_next(&entry) || dbus_message_iter_get_arg_type(&entry) != DBUS_TYPE_VARIANT) continue;
        dbus_message_iter_recurse(&entry, &value);
        const int type = dbus_message_iter_get_arg_type(&value);
        if (type != DBUS_TYPE_STRING && type != DBUS_TYPE_OBJECT_PATH) continue;
        dbus_message_iter_get_basic(&value, &handle);
        if (strlen(handle) < sizeof(session_path)) memcpy(session_path, handle, strlen(handle) + 1);
        break;
    }
}

static bool start_monitoring(DBusConnection *session_bus);

static void
on_name_owner_changed(DBusConnection *conn, DBusMessage *msg) {
    const char *name, *old_owner, *new_owner;
    if (!dbus_message_get_args(msg, NULL, DBUS_TYPE_STRING, &name, DBUS_TYPE_STRING, &old_owner, DBUS_TYPE_STRING, &new_owner, DBUS_TYPE_INVALID)) return;
    if (strcmp(name, PORTAL_SERVICE) != 0 || !portal_name[0] || strcmp(old_owner, portal_name) != 0) return;
    // The portal that created the monitor has exited, which ends the monitor session
    const bool restart = monitoring && established;
    monitoring = false;
    established = false;
    portal_name[0] = 0;
    if (restart) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: The desktop portal exited, monitoring the session state again");
        start_monitoring(conn);
    }
}

static DBusHandlerResult
message_filter(DBusConnection *conn, DBusMessage *msg, void *user_data UNUSED) {
    if (dbus_message_is_signal(msg, DBUS_INTERFACE_DBUS, "NameOwnerChanged") && dbus_message_has_sender(msg, DBUS_SERVICE_DBUS)) {
        on_name_owner_changed(conn, msg);
        return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
    }
    if (!monitoring || !is_from_portal(msg)) return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
    if (dbus_message_is_signal(msg, INHIBIT_INTERFACE, "StateChanged")) on_state_changed(conn, msg);
    else if (dbus_message_is_signal(msg, REQUEST_INTERFACE, "Response") && dbus_message_has_path(msg, request_path)) on_monitor_response(msg);
    return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}

static void
monitor_created(DBusMessage *msg, const DBusError *err, void *data UNUSED) {
    if (err) {
        monitoring = false;
        _glfwInputError(
            GLFW_PLATFORM_ERROR,
            "Inhibit portal: Failed to monitor the session state, make sure you have the desktop portal running. Error: %s: %s",
            err->name,
            err->message);
        return;
    }
    const char *sender = dbus_message_get_sender(msg), *handle = NULL;
    if (!sender || strlen(sender) >= sizeof(portal_name) || !dbus_message_get_args(msg, NULL, DBUS_TYPE_OBJECT_PATH, &handle, DBUS_TYPE_INVALID)) {
        monitoring = false;
        _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: Invalid reply to CreateMonitor");
        return;
    }
    memcpy(portal_name, sender, strlen(sender) + 1);
    if (strcmp(handle, request_path) != 0) {
        // Portals that ignore handle_token use a different request path, its Response signal could be missed if it was sent before
        // the match below is added
        if (strlen(handle) >= sizeof(request_path)) {
            monitoring = false;
            _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: The request path returned by CreateMonitor is too long");
            return;
        }
        memcpy(request_path, handle, strlen(handle) + 1);
        if (!add_response_match(glfw_dbus_session_bus())) {
            monitoring = false;
            _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: Failed to watch for the response to CreateMonitor");
        }
    }
}

static bool
append_string_option(DBusMessageIter *options, const char *key, const char *value) {
    DBusMessageIter entry, variant;
    if (!dbus_message_iter_open_container(options, DBUS_TYPE_DICT_ENTRY, NULL, &entry)) return false;
    if (!dbus_message_iter_append_basic(&entry, DBUS_TYPE_STRING, &key)) return false;
    if (!dbus_message_iter_open_container(&entry, DBUS_TYPE_VARIANT, "s", &variant)) return false;
    if (!dbus_message_iter_append_basic(&variant, DBUS_TYPE_STRING, &value)) return false;
    if (!dbus_message_iter_close_container(&entry, &variant)) return false;
    return dbus_message_iter_close_container(options, &entry);
}

static bool
create_monitor(DBusConnection *session_bus) {
    RAII_MSG(msg, dbus_message_new_method_call(PORTAL_SERVICE, PORTAL_PATH, INHIBIT_INTERFACE, "CreateMonitor"));
    if (!msg) return false;
    DBusMessageIter iter, options;
    const char *window = "";
    dbus_message_iter_init_append(msg, &iter);
    if (!dbus_message_iter_append_basic(&iter, DBUS_TYPE_STRING, &window)) return false;
    if (!dbus_message_iter_open_container(&iter, DBUS_TYPE_ARRAY, "{sv}", &options)) return false;
    // Some versions of xdg-desktop-portal abort if the session handle token is missing
    if (!append_string_option(&options, "handle_token", HANDLE_TOKEN)) return false;
    if (!append_string_option(&options, "session_handle_token", HANDLE_TOKEN)) return false;
    if (!dbus_message_iter_close_container(&iter, &options)) return false;
    return call_method_with_msg(session_bus, msg, DBUS_TIMEOUT_USE_DEFAULT, monitor_created, NULL, false);
}

static bool
start_monitoring(DBusConnection *session_bus) {
    static bool filter_added = false;
    if (!portal_object_path(session_bus, "request", request_path, sizeof(request_path)) ||
        !portal_object_path(session_bus, "session", session_path, sizeof(session_path))) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: Failed to get the unique name of the DBUS connection");
        return false;
    }
    if (!filter_added) {
        // Added before calling CreateMonitor, so that the Response signal cannot be missed
        if (!add_response_match(session_bus)) return false;
        dbus_bus_add_match(session_bus, "type='signal',interface='" INHIBIT_INTERFACE "',member='StateChanged'", NULL);
        dbus_bus_add_match(
            session_bus,
            "type='signal',sender='" DBUS_SERVICE_DBUS "',interface='" DBUS_INTERFACE_DBUS "',member='NameOwnerChanged',arg0='" PORTAL_SERVICE "'",
            NULL);
        if (!dbus_connection_add_filter(session_bus, message_filter, NULL, NULL)) {
            _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: Failed to add a DBUS message filter");
            return false;
        }
        filter_added = true;
    }
    portal_name[0] = 0;
    established = false;
    // Reset without running the callback, so that state the application saved for a logout that was in progress when the portal
    // exited is not discarded
    current_session_state = GLFW_SESSION_STATE_RUNNING;
    monitoring = create_monitor(session_bus);
    if (!monitoring) _glfwInputError(GLFW_PLATFORM_ERROR, "Inhibit portal: Failed to call CreateMonitor");
    return monitoring;
}

bool
glfw_dbus_monitor_session_state(GLFWDBussessionstatefun callback) {
    session_state_callback = callback;
    if (monitoring) return true;
    DBusConnection *session_bus = glfw_dbus_session_bus();
    if (!session_bus) return false;
    return start_monitoring(session_bus);
}
