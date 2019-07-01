/*
 * linux_notify.c
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "internal.h"
#include "linux_notify.h"
#include <stdlib.h>

#define NOTIFICATIONS_SERVICE  "org.freedesktop.Notifications"
#define NOTIFICATIONS_PATH "/org/freedesktop/Notifications"
#define NOTIFICATIONS_IFACE "org.freedesktop.Notifications"

static notification_id_type notification_id = 0;

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
notification_created(DBusMessage *msg, const char* errmsg, void *data) {
    if (errmsg) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Notify: Failed to create notification error: %s", errmsg);
        if (data) free(data);
        return;
    }
    uint32_t notification_id;
    if (!glfw_dbus_get_args(msg, "Failed to get Notification uid", DBUS_TYPE_UINT32, &notification_id, DBUS_TYPE_INVALID)) return;
    NotificationCreatedData *ncd = (NotificationCreatedData*)data;
    if (ncd->callback) ncd->callback(ncd->next_id, notification_id, ncd->data);
    if (data) free(data);
}

static DBusHandlerResult
message_handler(DBusConnection *conn UNUSED, DBusMessage *msg, void *user_data UNUSED) {
    /* printf("session_bus message_handler invoked interface: %s member: %s\n", dbus_message_get_interface(msg), dbus_message_get_member(msg)); */
    if (dbus_message_is_signal(msg, NOTIFICATIONS_IFACE, "ActionInvoked")) {
        uint32_t notification_id;
        const char *action;
        if (glfw_dbus_get_args(msg, "Failed to get args from ActionInvoked notification signal",
                    DBUS_TYPE_UINT32, &notification_id, DBUS_TYPE_STRING, &action, DBUS_TYPE_INVALID)) {
            if (activated_handler) {
                activated_handler(notification_id, action);
                return DBUS_HANDLER_RESULT_HANDLED;
            }
        }

    }
    return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}

notification_id_type
glfw_dbus_send_user_notification(const char *app_name, const char* icon, const char *summary, const char *body, const char* action_name, int32_t timeout, GLFWDBusnotificationcreatedfun callback, void *user_data) {
    DBusConnection *session_bus = glfw_dbus_session_bus();
    static DBusConnection *added_signal_match = NULL;
    if (!session_bus) return 0;
    if (added_signal_match != session_bus) {
        dbus_bus_add_match(session_bus, "type='signal',interface='" NOTIFICATIONS_IFACE "',member='ActionInvoked'", NULL);
        dbus_connection_add_filter(session_bus, message_handler, NULL, NULL);
        added_signal_match = session_bus;
    }
    NotificationCreatedData *data = malloc(sizeof(NotificationCreatedData));
    if (!data) return 0;
    data->next_id = ++notification_id;
    data->callback = callback; data->data = user_data;
    if (!data->next_id) data->next_id = ++notification_id;
    uint32_t replaces_id = 0;

    DBusMessage *msg = dbus_message_new_method_call(NOTIFICATIONS_SERVICE, NOTIFICATIONS_PATH, NOTIFICATIONS_IFACE, "Notify");
    if (!msg) { free(data); return 0; }
    DBusMessageIter args, array;
    dbus_message_iter_init_append(msg, &args);
#define OOMMSG { free(data); data = NULL; dbus_message_unref(msg); _glfwInputError(GLFW_PLATFORM_ERROR, "%s", "Out of memory allocating DBUS message for notification\n"); return 0; }
#define APPEND(type, val) { if (!dbus_message_iter_append_basic(&args, type, val)) OOMMSG }
    APPEND(DBUS_TYPE_STRING, &app_name)
    APPEND(DBUS_TYPE_UINT32, &replaces_id)
    APPEND(DBUS_TYPE_STRING, &icon)
    APPEND(DBUS_TYPE_STRING, &summary)
    APPEND(DBUS_TYPE_STRING, &body)
    if (!dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "s", &array)) OOMMSG;
    if (action_name) {
        static const char* default_action = "default";
        dbus_message_iter_append_basic(&array, DBUS_TYPE_STRING, &default_action);
        dbus_message_iter_append_basic(&array, DBUS_TYPE_STRING, &action_name);
    }
    if (!dbus_message_iter_close_container(&args, &array)) OOMMSG;
    if (!dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "{sv}", &array)) OOMMSG;
    if (!dbus_message_iter_close_container(&args, &array)) OOMMSG;
    APPEND(DBUS_TYPE_INT32, &timeout)
#undef OOMMSG
#undef APPEND
    if (!call_method_with_msg(session_bus, msg, 5000, notification_created, data)) return 0;
    return data->next_id;
}
