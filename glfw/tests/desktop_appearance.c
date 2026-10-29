#define _POSIX_C_SOURCE 200809L
/* Exercise portal appearance replies/signals without changing desktop settings. */
#include "../linux_desktop_settings.c"
#include <assert.h>

static unsigned notifications;
static GLFWColorScheme received;
void
_glfwInputColorScheme(GLFWColorScheme value, bool initial) {
    (void)initial;
    notifications++;
    received = value;
}

static void
change_scheme(uint32_t value) {
    DBusMessage *msg = dbus_message_new_signal(DESKTOP_PATH, DESKTOP_INTERFACE, "SettingChanged");
    assert(msg);
    const char *namespace = FDO_DESKTOP_NAMESPACE, *key = FDO_APPEARANCE_KEY;
    DBusMessageIter iter, variant;
    dbus_message_iter_init_append(msg, &iter);
    assert(dbus_message_iter_append_basic(&iter, DBUS_TYPE_STRING, &namespace));
    assert(dbus_message_iter_append_basic(&iter, DBUS_TYPE_STRING, &key));
    assert(dbus_message_iter_open_container(&iter, DBUS_TYPE_VARIANT, "u", &variant));
    assert(dbus_message_iter_append_basic(&variant, DBUS_TYPE_UINT32, &value));
    assert(dbus_message_iter_close_container(&iter, &variant));
    on_color_scheme_change(msg);
    dbus_message_unref(msg);
}

int
main(void) {
    change_scheme(1);
    assert(notifications == 1 && received == GLFW_COLOR_SCHEME_DARK);
    change_scheme(2);
    assert(notifications == 2 && received == GLFW_COLOR_SCHEME_LIGHT);
    assert(appearance == GLFW_COLOR_SCHEME_LIGHT);
    change_scheme(1);
    assert(notifications == 3 && received == GLFW_COLOR_SCHEME_DARK);
    change_scheme(1);
    assert(notifications == 3);
    puts("Desktop portal appearance: dark/light/dark signals passed");
    return 0;
}
