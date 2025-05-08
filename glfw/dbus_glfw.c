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


#include "internal.h"
#include "dbus_glfw.h"
#include "../kitty/monotonic.h"
#include <stdlib.h>
#include <string.h>

static void
report_error(DBusError *err, const char *fmt, ...) {
    static char buf[4096];
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    if (n >= 0 && (size_t)n < (sizeof(buf) - 256)) snprintf(buf + n, sizeof(buf) - n, ". DBUS error: %s", err->message ? err->message : "(null)");
    _glfwInputError(GLFW_PLATFORM_ERROR, "%s", buf);
    dbus_error_free(err);
}

static _GLFWDBUSData *dbus_data = NULL;
static DBusConnection *session_bus = NULL;

bool
glfw_dbus_init(_GLFWDBUSData *dbus, EventLoopData *eld) {
    dbus->eld = eld;
    dbus_data = dbus;
    return true;
}

static void
on_dbus_watch_ready(int fd UNUSED, int events, void *data) {
    DBusWatch *watch = (DBusWatch*)data;
    unsigned int flags = 0;
    if (events & POLLERR) flags |= DBUS_WATCH_ERROR;
    if (events & POLLHUP) flags |= DBUS_WATCH_HANGUP;
    if (events & POLLIN) flags |= DBUS_WATCH_READABLE;
    if (events & POLLOUT) flags |= DBUS_WATCH_WRITABLE;
    dbus_watch_handle(watch, flags);
}

static int
events_for_watch(DBusWatch *watch) {
    int events = 0;
    unsigned int flags = dbus_watch_get_flags(watch);
    if (flags & DBUS_WATCH_READABLE) events |= POLLIN;
    if (flags & DBUS_WATCH_WRITABLE) events |= POLLOUT;
    return events;
}

static dbus_bool_t
add_dbus_watch(DBusWatch *watch, void *data) {
    id_type watch_id = addWatch(dbus_data->eld, data, dbus_watch_get_unix_fd(watch), events_for_watch(watch), dbus_watch_get_enabled(watch), on_dbus_watch_ready, watch);
    if (!watch_id) return FALSE;
    id_type *idp = malloc(sizeof(id_type));
    if (!idp) return FALSE;
    *idp = watch_id;
    dbus_watch_set_data(watch, idp, free);
    return TRUE;
}

static void
remove_dbus_watch(DBusWatch *watch, void *data UNUSED) {
    id_type *idp = dbus_watch_get_data(watch);
    if (idp) removeWatch(dbus_data->eld, *idp);
}

static void
toggle_dbus_watch(DBusWatch *watch, void *data UNUSED) {
    id_type *idp = dbus_watch_get_data(watch);
    if (idp) toggleWatch(dbus_data->eld, *idp, dbus_watch_get_enabled(watch));
}

static void
on_dbus_timer_ready(id_type timer_id UNUSED, void *data) {
    if (data) {
        DBusTimeout *t = (DBusTimeout*)data;
        dbus_timeout_handle(t);
    }
}


static dbus_bool_t
add_dbus_timeout(DBusTimeout *timeout, void *data) {
    int enabled = dbus_timeout_get_enabled(timeout) ? 1 : 0;
    monotonic_t interval = ms_to_monotonic_t(dbus_timeout_get_interval(timeout));
    if (interval < 0) return FALSE;
    id_type timer_id = addTimer(dbus_data->eld, data, interval, enabled, true, on_dbus_timer_ready, timeout, NULL);
    if (!timer_id) return FALSE;
    id_type *idp = malloc(sizeof(id_type));
    if (!idp) {
        removeTimer(dbus_data->eld, timer_id);
        return FALSE;
    }
    *idp = timer_id;
    dbus_timeout_set_data(timeout, idp, free);
    return TRUE;

}

static void
remove_dbus_timeout(DBusTimeout *timeout, void *data UNUSED) {
    id_type *idp = dbus_timeout_get_data(timeout);
    if (idp) removeTimer(dbus_data->eld, *idp);
}

static void
toggle_dbus_timeout(DBusTimeout *timeout, void *data UNUSED) {
    id_type *idp = dbus_timeout_get_data(timeout);
    if (idp) toggleTimer(dbus_data->eld, *idp, dbus_timeout_get_enabled(timeout));
}


DBusConnection*
glfw_dbus_connect_to(const char *path, const char* err_msg, const char *name, bool register_on_bus) {
    DBusError err;
    dbus_error_init(&err);
    DBusConnection *ans = dbus_connection_open_private(path, &err);
    if (!ans) {
        report_error(&err, err_msg);
        return NULL;
    }
    dbus_connection_set_exit_on_disconnect(ans, FALSE);
    dbus_error_free(&err);
    if (register_on_bus) {
        if (!dbus_bus_register(ans, &err)) {
            report_error(&err, err_msg);
            return NULL;
        }
    }
    if (!dbus_connection_set_watch_functions(ans, add_dbus_watch, remove_dbus_watch, toggle_dbus_watch, (void*)name, NULL)) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to set DBUS watches on connection to: %s", path);
        dbus_connection_close(ans);
        dbus_connection_unref(ans);
        return NULL;
    }
    if (!dbus_connection_set_timeout_functions(ans, add_dbus_timeout, remove_dbus_timeout, toggle_dbus_timeout, (void*)name, NULL)) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to set DBUS timeout functions on connection to: %s", path);
        dbus_connection_close(ans);
        dbus_connection_unref(ans);
        return NULL;
    }
    return ans;
}

void
glfw_dbus_dispatch(DBusConnection *conn) {
    while(dbus_connection_dispatch(conn) == DBUS_DISPATCH_DATA_REMAINS);
}

void
glfw_dbus_session_bus_dispatch(void) {
    if (session_bus) glfw_dbus_dispatch(session_bus);
}

void
glfw_dbus_terminate(_GLFWDBUSData *dbus UNUSED) {
    if (dbus_data) {
        dbus_data->eld = NULL;
        dbus_data = NULL;
    }
    if (session_bus) {
        dbus_connection_unref(session_bus);
        session_bus = NULL;
    }
}

void
glfw_dbus_close_connection(DBusConnection *conn) {
    dbus_connection_close(conn);
    dbus_connection_unref(conn);
}

bool
glfw_dbus_get_args(DBusMessage *msg, const char *failmsg, ...) {
    DBusError err;
    dbus_error_init(&err);
    va_list ap;
    va_start(ap, failmsg);
    int firstarg = va_arg(ap, int);
    bool ret = dbus_message_get_args_valist(msg, &err, firstarg, ap) ? true : false;
    va_end(ap);
    if (!ret) report_error(&err, failmsg);
    return ret;
}

typedef struct {
    dbus_pending_callback callback;
    void *user_data;
} MethodResponse;

static void
method_reply_received(DBusPendingCall *pending, void *user_data) {
    MethodResponse *res = (MethodResponse*)user_data;
    RAII_MSG(msg, dbus_pending_call_steal_reply(pending));
    if (msg) {
        DBusError err;
        dbus_error_init(&err);
        if (dbus_set_error_from_message(&err, msg)) res->callback(NULL, &err, res->user_data);
        else res->callback(msg, NULL, res->user_data);
    }
}

bool
call_method_with_msg(DBusConnection *conn, DBusMessage *msg, int timeout, dbus_pending_callback callback, void *user_data, bool block) {
    bool retval = false;
#define REPORT(errs) _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to call DBUS method: node=%s path=%s interface=%s method=%s, with error: %s", dbus_message_get_destination(msg), dbus_message_get_path(msg), dbus_message_get_interface(msg), dbus_message_get_member(msg), errs)
    if (callback) {
        DBusPendingCall *pending = NULL;
        if (block) {
            DBusError error; dbus_error_init(&error);
            RAII_MSG(reply, dbus_connection_send_with_reply_and_block(session_bus, msg, timeout, &error));
            if (dbus_error_is_set(&error)) {
                callback(reply, &error, user_data);
                return false;
            } else if (reply) {
                callback(reply, NULL, user_data);
            } else return false;
        } else if (dbus_connection_send_with_reply(conn, msg, &pending, timeout)) {
            MethodResponse *res = malloc(sizeof(MethodResponse));
            if (!res) return false;
            res->callback = callback;
            res->user_data = user_data;
            dbus_pending_call_set_notify(pending, method_reply_received, res, free);
            retval = true;
        } else {
            REPORT("out of memory");
        }
    } else {
        if (dbus_connection_send(conn, msg, NULL)) {
            retval = true;
        } else {
            REPORT("out of memory");
        }
    }
    return retval;
#undef REPORT
}

static bool
call_method(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, int timeout, dbus_pending_callback callback, void *user_data, bool blocking, va_list ap) {
    if (!conn || !path) return false;
    RAII_MSG(msg, dbus_message_new_method_call(node, path, interface, method));
    if (!msg) return false;
    bool retval = false;

    int firstarg = va_arg(ap, int);
    if ((firstarg == DBUS_TYPE_INVALID) || dbus_message_append_args_valist(msg, firstarg, ap)) {
        retval = call_method_with_msg(conn, msg, timeout, callback, user_data, blocking);
    } else {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to call DBUS method: %s on node: %s and interface: %s could not add arguments", method, node, interface);
    }

    return retval;
}

bool
glfw_dbus_call_method_with_reply(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, int timeout, dbus_pending_callback callback, void* user_data, ...) {
    bool retval;
    va_list ap;
    va_start(ap, user_data);
    retval = call_method(conn, node, path, interface, method, timeout, callback, user_data, false, ap);
    va_end(ap);
    return retval;
}

bool
glfw_dbus_call_blocking_method(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, int timeout, dbus_pending_callback callback, void* user_data, ...) {
    bool retval;
    va_list ap;
    va_start(ap, user_data);
    retval = call_method(conn, node, path, interface, method, timeout, callback, user_data, true, ap);
    va_end(ap);
    return retval;
}

bool
glfw_dbus_call_method_no_reply(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, ...) {
    bool retval;
    va_list ap;
    va_start(ap, method);
    retval = call_method(conn, node, path, interface, method, DBUS_TIMEOUT_USE_DEFAULT, NULL, NULL, false, ap);
    va_end(ap);
    return retval;
}

int
glfw_dbus_match_signal(DBusMessage *msg, const char *interface, ...) {
    va_list ap;
    va_start(ap, interface);
    int ans = -1, num = -1;
    while(1) {
        num++;
        const char *name = va_arg(ap, const char*);
        if (!name) break;
        if (dbus_message_is_signal(msg, interface, name)) { ans = num; break; }
    }
    va_end(ap);
    return ans;
}

static void
glfw_dbus_connect_to_session_bus(void) {
    DBusError error;
    dbus_error_init(&error);
    if (session_bus) {
        dbus_connection_unref(session_bus);
    }
    session_bus = dbus_bus_get(DBUS_BUS_SESSION, &error);
    if (dbus_error_is_set(&error)) {
        report_error(&error, "Failed to connect to DBUS session bus");
        session_bus = NULL;
        return;
    }
    static const char *name = "session-bus";
    if (!dbus_connection_set_watch_functions(session_bus, add_dbus_watch, remove_dbus_watch, toggle_dbus_watch, (void*)name, NULL)) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to set DBUS watches on connection to: %s", name);
        dbus_connection_close(session_bus);
        dbus_connection_unref(session_bus);
        return;
    }
    if (!dbus_connection_set_timeout_functions(session_bus, add_dbus_timeout, remove_dbus_timeout, toggle_dbus_timeout, (void*)name, NULL)) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to set DBUS timeout functions on connection to: %s", name);
        dbus_connection_close(session_bus);
        dbus_connection_unref(session_bus);
        return;
    }

}

DBusConnection *
glfw_dbus_session_bus(void) {
    if (!session_bus) glfw_dbus_connect_to_session_bus();
    return session_bus;
}
