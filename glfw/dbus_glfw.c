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
#include <stdlib.h>

static inline void
report_error(DBusError *err, const char *fmt, ...) {
    static char buf[1024];
    va_list args;
    va_start(args, fmt);
    int n = vsnprintf(buf, sizeof(buf), fmt, args);
    va_end(args);
    snprintf(buf + n, sizeof(buf), ". DBUS error: %s", err->message);
    _glfwInputError(GLFW_PLATFORM_ERROR, "%s", buf);
    dbus_error_free(err);
}

static _GLFWDBUSData *dbus_data = NULL;

GLFWbool
glfw_dbus_init(_GLFWDBUSData *dbus, EventLoopData *eld) {
    dbus->eld = eld;
    dbus_data = dbus;
    return GLFW_TRUE;
}

static void
on_dbus_watch_ready(int fd, int events, void *data) {
    DBusWatch *watch = (DBusWatch*)data;
    unsigned int flags = 0;
    if (events & POLLERR) flags |= DBUS_WATCH_ERROR;
    if (events & POLLHUP) flags |= DBUS_WATCH_HANGUP;
    if (events & POLLIN) flags |= DBUS_WATCH_READABLE;
    if (events & POLLOUT) flags |= DBUS_WATCH_WRITABLE;
    dbus_watch_handle(watch, flags);
}

static inline int
events_for_watch(DBusWatch *watch) {
    int events = 0;
    unsigned int flags = dbus_watch_get_flags(watch);
    if (flags & DBUS_WATCH_READABLE) events |= POLLIN;
    if (flags & DBUS_WATCH_WRITABLE) events |= POLLOUT;
    return events;
}

static dbus_bool_t
add_dbus_watch(DBusWatch *watch, void *data) {
    id_type watch_id = addWatch(dbus_data->eld, dbus_watch_get_unix_fd(watch), events_for_watch(watch), dbus_watch_get_enabled(watch), on_dbus_watch_ready, watch);
    if (!watch_id) return FALSE;
    id_type *idp = malloc(sizeof(id_type));
    if (!idp) return FALSE;
    *idp = watch_id;
    dbus_watch_set_data(watch, idp, free);
    return TRUE;
}

static void
remove_dbus_watch(DBusWatch *watch, void *data) {
    id_type *idp = dbus_watch_get_data(watch);
    if (idp) removeWatch(dbus_data->eld, *idp);
}

static void
toggle_dbus_watch(DBusWatch *watch, void *data) {
    id_type *idp = dbus_watch_get_data(watch);
    if (idp) toggleWatch(dbus_data->eld, *idp, dbus_watch_get_enabled(watch));
}

static void
on_dbus_timer_ready(id_type timer_id, void *data) {
    DBusTimeout *t = (DBusTimeout*)data;
    dbus_timeout_handle(t);
}


static dbus_bool_t
add_dbus_timeout(DBusTimeout *timeout, void *data) {
    int enabled = dbus_timeout_get_enabled(timeout) ? 1 : 0;
    double interval = ((double)dbus_timeout_get_interval(timeout)) / 1000.0;
    if (interval < 0) return FALSE;
    id_type timer_id = addTimer(dbus_data->eld, interval, enabled, on_dbus_timer_ready, timeout);
    if (!timer_id) return FALSE;
    id_type *idp = malloc(sizeof(id_type));
    if (!idp) return FALSE;
    *idp = timer_id;
    dbus_timeout_set_data(timeout, idp, free);
    return TRUE;

}

static void
remove_dbus_timeout(DBusTimeout *timeout, void *data) {
    id_type *idp = dbus_timeout_get_data(timeout);
    if (idp) removeTimer(dbus_data->eld, *idp);
}

static void
toggle_dbus_timeout(DBusTimeout *timeout, void *data) {
    id_type *idp = dbus_timeout_get_data(timeout);
    if (idp) toggleTimer(dbus_data->eld, *idp, dbus_timeout_get_enabled(timeout));
}


DBusConnection*
glfw_dbus_connect_to(const char *path, const char* err_msg) {
    DBusError err;
    dbus_error_init(&err);
    DBusConnection *ans = dbus_connection_open_private(path, &err);
    if (!ans) {
        report_error(&err, err_msg);
        return NULL;
    }
    dbus_connection_set_exit_on_disconnect(ans, FALSE);
    dbus_connection_flush(ans);
    dbus_error_free(&err);
    if (!dbus_bus_register(ans, &err)) {
        report_error(&err, err_msg);
        return NULL;
    }
    dbus_connection_flush(ans);
    if (!dbus_connection_set_watch_functions(ans, add_dbus_watch, remove_dbus_watch, toggle_dbus_watch, NULL, NULL)) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to set DBUS watches on connection to: %s", path);
        dbus_connection_close(ans);
        dbus_connection_unref(ans);
        return NULL;
    }
    if (!dbus_connection_set_timeout_functions(ans, add_dbus_timeout, remove_dbus_timeout, toggle_dbus_timeout, NULL, NULL)) {
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
glfw_dbus_terminate(_GLFWDBUSData *dbus) {
    if (dbus_data) {
        dbus_data->eld = NULL;
        dbus_data = NULL;
    }
}

void
glfw_dbus_close_connection(DBusConnection *conn) {
    dbus_connection_close(conn);
    dbus_connection_unref(conn);
}

static GLFWbool
call_void_method(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, va_list ap) {
    GLFWbool retval = GLFW_FALSE;

    if (conn) {
        DBusMessage *msg = dbus_message_new_method_call(node, path, interface, method);
        if (msg) {
            int firstarg = va_arg(ap, int);
            if ((firstarg == DBUS_TYPE_INVALID) || dbus_message_append_args_valist(msg, firstarg, ap)) {
                if (dbus_connection_send(conn, msg, NULL)) {
                    dbus_connection_flush(conn);
                    retval = GLFW_TRUE;
                }
            }

            dbus_message_unref(msg);
        }
    }

    return retval;
}

GLFWbool
glfw_dbus_call_void_method(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, ...) {
    GLFWbool retval;
    va_list ap;
    va_start(ap, method);
    retval = call_void_method(conn, node, path, interface, method, ap);
    va_end(ap);
    return retval;
}

GLFWbool
glfw_dbus_get_args(DBusMessage *msg, const char *failmsg, ...) {
    DBusError err;
    dbus_error_init(&err);
    va_list ap;
    va_start(ap, failmsg);
    int firstarg = va_arg(ap, int);
    GLFWbool ret = dbus_message_get_args_valist(msg, &err, firstarg, ap) ? GLFW_TRUE : GLFW_FALSE;
    va_end(ap);
    if (!ret) report_error(&err, failmsg);
    return ret;
}

typedef struct {
    dbus_pending_callback callback;
    void *user_data;
} MethodResponse;

static const char*
format_message_error(DBusError *err) {
    static char buf[1024];
    snprintf(buf, sizeof(buf), "[%s] %s", err->name ? err->name : "", err->message);
    return buf;
}

static void
method_reply_received(DBusPendingCall *pending, void *user_data) {
    MethodResponse *res = (MethodResponse*)user_data;
    DBusMessage *msg = dbus_pending_call_steal_reply(pending);
    if (msg) {
        DBusError err;
        dbus_error_init(&err);
        if (dbus_set_error_from_message(&err, msg)) res->callback(NULL, format_message_error(&err), res->user_data);
        else res->callback(msg, NULL, res->user_data);
        dbus_message_unref(msg);
    }
}

static GLFWbool
call_method(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, dbus_pending_callback callback, void *user_data, va_list ap) {
    if (!conn) return GLFW_FALSE;
    DBusMessage *msg = dbus_message_new_method_call(node, path, interface, method);
    if (!msg) return GLFW_FALSE;
    GLFWbool retval = GLFW_FALSE;
    MethodResponse *res = malloc(sizeof(MethodResponse));
    if (!res) { dbus_message_unref(msg); return GLFW_FALSE; }
    res->callback = callback;
    res->user_data = user_data;

    int firstarg = va_arg(ap, int);
    if ((firstarg == DBUS_TYPE_INVALID) || dbus_message_append_args_valist(msg, firstarg, ap)) {
        if (callback) {
            DBusPendingCall *pending = NULL;
            if (dbus_connection_send_with_reply(conn, msg, &pending, DBUS_TIMEOUT_USE_DEFAULT)) {
                dbus_pending_call_set_notify(pending, method_reply_received, res, free);
            } else {
                _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to call DBUS method: %s on node: %s and interface: %s out of memory", method, node, interface);
            }
        } else {
            if (!dbus_connection_send(conn, msg, NULL)) {
                _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to call DBUS method: %s on node: %s and interface: %s out of memory", method, node, interface);
            }
        }
    } else {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to call DBUS method: %s on node: %s and interface: %s could not add arguments", method, node, interface);
    }
    dbus_message_unref(msg);

    return retval;
}

GLFWbool
glfw_dbus_call_method_with_reply(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, dbus_pending_callback callback, void* user_data, ...) {
    GLFWbool retval;
    va_list ap;
    va_start(ap, user_data);
    retval = call_method(conn, node, path, interface, method, callback, user_data, ap);
    va_end(ap);
    return retval;
}

GLFWbool
glfw_dbus_call_method_no_reply(DBusConnection *conn, const char *node, const char *path, const char *interface, const char *method, ...) {
    GLFWbool retval;
    va_list ap;
    va_start(ap, method);
    retval = call_method(conn, node, path, interface, method, NULL, NULL, ap);
    va_end(ap);
    return retval;
}
