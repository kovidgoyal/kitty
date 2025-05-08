/*
 * linux_notify.c
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define _POSIX_C_SOURCE 200809L
#include "internal.h"
#include "linux_notify.h"
#include <stdlib.h>
#include <string.h>

#define NOTIFICATIONS_SERVICE  "org.freedesktop.Notifications"
#define NOTIFICATIONS_PATH "/org/freedesktop/Notifications"
#define NOTIFICATIONS_IFACE "org.freedesktop.Notifications"

static inline void cleanup_free(void *p) { free(*(void**)p); }
#define RAII_ALLOC(type, name, initializer) __attribute__((cleanup(cleanup_free))) type *name = initializer

typedef struct {
    notification_id_type next_id;
    GLFWDBusnotificationcreatedfun callback;
    void *data;
} NotificationCreatedData;

static GLFWDBusnotificationactivatedfun activated_handler = NULL;

void
glfw_dbus_set_user_notification_activated_handler(GLFWDBusnotificationactivatedfun handler) {
    activated_handler = handler;
}

void
notification_created(DBusMessage *msg, const DBusError* err, void *data) {
    if (err) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Notify: Failed to create notification error: %s: %s", err->name, err->message);
        if (data) free(data);
        return;
    }
    uint32_t id;
    if (!glfw_dbus_get_args(msg, "Failed to get Notification uid", DBUS_TYPE_UINT32, &id, DBUS_TYPE_INVALID)) return;
    NotificationCreatedData *ncd = (NotificationCreatedData*)data;
    if (ncd) {
        if (ncd->callback) ncd->callback(ncd->next_id, id, ncd->data);
        free(ncd);
    }
}

static DBusHandlerResult
message_handler(DBusConnection *conn UNUSED, DBusMessage *msg, void *user_data UNUSED) {
    /* printf("session_bus message_handler invoked interface: %s member: %s\n", dbus_message_get_interface(msg), dbus_message_get_member(msg)); */
    if (dbus_message_is_signal(msg, NOTIFICATIONS_IFACE, "ActionInvoked")) {
        uint32_t id;
        const char *action = NULL;
        if (glfw_dbus_get_args(msg, "Failed to get args from ActionInvoked notification signal",
                    DBUS_TYPE_UINT32, &id, DBUS_TYPE_STRING, &action, DBUS_TYPE_INVALID)) {
            if (activated_handler) {
                activated_handler(id, 2, action);
                return DBUS_HANDLER_RESULT_HANDLED;
            }
        }

    }

    if (dbus_message_is_signal(msg, NOTIFICATIONS_IFACE, "ActivationToken")) {
        uint32_t id;
        const char *token = NULL;
        if (glfw_dbus_get_args(msg, "Failed to get args from ActivationToken notification signal",
                    DBUS_TYPE_UINT32, &id, DBUS_TYPE_STRING, &token, DBUS_TYPE_INVALID)) {
            if (activated_handler) {
                activated_handler(id, 1, token);
                return DBUS_HANDLER_RESULT_HANDLED;
            }
        }

    }

    if (dbus_message_is_signal(msg, NOTIFICATIONS_IFACE, "NotificationClosed")) {
        uint32_t id;
        if (glfw_dbus_get_args(msg, "Failed to get args from NotificationClosed notification signal",
                    DBUS_TYPE_UINT32, &id, DBUS_TYPE_INVALID)) {
            if (activated_handler) {
                activated_handler(id, 0, "");
                return DBUS_HANDLER_RESULT_HANDLED;
            }
        }
    }
    return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}

static bool
cancel_user_notification(DBusConnection *session_bus, uint32_t *id) {
    return glfw_dbus_call_method_no_reply(session_bus, NOTIFICATIONS_SERVICE, NOTIFICATIONS_PATH, NOTIFICATIONS_IFACE, "CloseNotification", DBUS_TYPE_UINT32, id, DBUS_TYPE_INVALID);
}

static void
got_capabilities(DBusMessage *msg, const DBusError* err, void* data UNUSED) {
    if (err) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Notify: Failed to get server capabilities error: %s: %s", err->name, err->message);
        return;
    }
#define check_call(func, err, ...) if (!func(__VA_ARGS__)) { _glfwInputError(GLFW_PLATFORM_ERROR, "Notify: GetCapabilities: %s", err); return;  }
    DBusMessageIter iter, array_iter;
    check_call(dbus_message_iter_init, "message has no parameters", msg, &iter);
    if (dbus_message_iter_get_arg_type(&iter) != DBUS_TYPE_ARRAY || dbus_message_iter_get_element_type(&iter) != DBUS_TYPE_STRING) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Notify: GetCapabilities: %s", "reply is not an array of strings");
        return;
    }
    dbus_message_iter_recurse(&iter, &array_iter);
    char buf[2048] = {0}, *p = buf, *end = buf + sizeof(buf);
    while (dbus_message_iter_get_arg_type(&array_iter) == DBUS_TYPE_STRING) {
        const char *str;
        dbus_message_iter_get_basic(&array_iter, &str);
        size_t len = strlen(str);
        if (len && p + len + 2 < end) { p = stpcpy(p, str); *(p++) = '\n'; }
        dbus_message_iter_next(&array_iter);
    }
    if (activated_handler) activated_handler(0, -1, buf);
#undef check_call

}

static bool
get_capabilities(DBusConnection *session_bus) {
    return glfw_dbus_call_method_with_reply(session_bus, NOTIFICATIONS_SERVICE, NOTIFICATIONS_PATH, NOTIFICATIONS_IFACE, "GetCapabilities", 60, got_capabilities, NULL, DBUS_TYPE_INVALID);
}

notification_id_type
glfw_dbus_send_user_notification(const GLFWDBUSNotificationData *n, GLFWDBusnotificationcreatedfun callback, void *user_data) {
    DBusConnection *session_bus = glfw_dbus_session_bus();
    if (!session_bus) return 0;
    if (n->timeout == -9999 && n->urgency == 255) return cancel_user_notification(session_bus, user_data) ? 1 : 0;
    if (n->timeout == -99999 && n->urgency == 255) return get_capabilities(session_bus) ? 1 : 0;
    static DBusConnection *added_signal_match = NULL;
    if (added_signal_match != session_bus) {
        dbus_bus_add_match(session_bus, "type='signal',interface='" NOTIFICATIONS_IFACE "',member='ActionInvoked'", NULL);
        dbus_bus_add_match(session_bus, "type='signal',interface='" NOTIFICATIONS_IFACE "',member='NotificationClosed'", NULL);
        dbus_bus_add_match(session_bus, "type='signal',interface='" NOTIFICATIONS_IFACE "',member='ActivationToken'", NULL);
        dbus_connection_add_filter(session_bus, message_handler, NULL, NULL);
        added_signal_match = session_bus;
    }
    RAII_ALLOC(NotificationCreatedData, data, malloc(sizeof(NotificationCreatedData)));
    if (!data) return 0;
    static notification_id_type notification_id = 0;
    data->next_id = ++notification_id;
    data->callback = callback; data->data = user_data;
    if (!data->next_id) data->next_id = ++notification_id;

    RAII_MSG(msg, dbus_message_new_method_call(NOTIFICATIONS_SERVICE, NOTIFICATIONS_PATH, NOTIFICATIONS_IFACE, "Notify"));
    if (!msg) { return 0; }
    DBusMessageIter args, array, variant, dict;
    dbus_message_iter_init_append(msg, &args);
#define check_call(func, ...) if (!func(__VA_ARGS__)) { _glfwInputError(GLFW_PLATFORM_ERROR, "%s", "Out of memory allocating DBUS message for notification\n"); return 0; }
#define APPEND(to, type, val) check_call(dbus_message_iter_append_basic, &to, type, &val);
    APPEND(args, DBUS_TYPE_STRING, n->app_name)
    APPEND(args, DBUS_TYPE_UINT32, n->replaces)
    APPEND(args, DBUS_TYPE_STRING, n->icon)
    APPEND(args, DBUS_TYPE_STRING, n->summary)
    APPEND(args, DBUS_TYPE_STRING, n->body)
    check_call(dbus_message_iter_open_container, &args, DBUS_TYPE_ARRAY, "s", &array);
    if (n->actions) {
        for (size_t i = 0; i < n->num_actions; i++) {
            APPEND(array, DBUS_TYPE_STRING, n->actions[i]);
        }
    }
    check_call(dbus_message_iter_close_container, &args, &array);
    check_call(dbus_message_iter_open_container, &args, DBUS_TYPE_ARRAY, "{sv}", &array);

#define append_sv_dictionary_entry(k, val_type, val) { \
    check_call(dbus_message_iter_open_container, &array, DBUS_TYPE_DICT_ENTRY, NULL, &dict); \
    static const char *key = k; \
    APPEND(dict, DBUS_TYPE_STRING, key); \
    check_call(dbus_message_iter_open_container, &dict, DBUS_TYPE_VARIANT, val_type##_AS_STRING, &variant); \
    APPEND(variant, val_type, val); \
    check_call(dbus_message_iter_close_container, &dict, &variant); \
    check_call(dbus_message_iter_close_container, &array, &dict); \
}
    append_sv_dictionary_entry("urgency", DBUS_TYPE_BYTE, n->urgency);
    if (n->category && n->category[0]) append_sv_dictionary_entry("category", DBUS_TYPE_STRING, n->category);
    if (n->muted) append_sv_dictionary_entry("suppress-sound", DBUS_TYPE_BOOLEAN, n->muted);

    check_call(dbus_message_iter_close_container, &args, &array);
    APPEND(args, DBUS_TYPE_INT32, n->timeout)
#undef check_call
#undef APPEND
    if (!call_method_with_msg(session_bus, msg, 5000, notification_created, data, false)) return 0;
    notification_id_type ans = data->next_id;
    data = NULL;
    return ans;
}
