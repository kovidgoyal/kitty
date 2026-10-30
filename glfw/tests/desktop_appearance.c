#define _POSIX_C_SOURCE 200809L
/* Exercise portal appearance replies/signals without changing desktop settings. */
#include "../linux_desktop_settings.c"
#include <assert.h>
#include <stdarg.h>

_GLFWlibrary _glfw;
static unsigned redraws;
GLFWAPI void glfwWaylandRedrawCSDWindowTitle(GLFWwindow *window) { (void)window; redraws++; }
void _glfwInputError(int code, const char *format, ...) { (void)code; (void)format; abort(); }
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
    setting_changed(NULL, msg, NULL);
    dbus_message_unref(msg);
}

static void
change_setting(const char *namespace, const char *key, int type, const void *data) {
    DBusMessage *msg = dbus_message_new_signal(DESKTOP_PATH, DESKTOP_INTERFACE, "SettingChanged");
    assert(msg);
    DBusMessageIter iter, variant;
    char signature[] = {(char)type, 0};
    dbus_message_iter_init_append(msg, &iter);
    assert(dbus_message_iter_append_basic(&iter, DBUS_TYPE_STRING, &namespace));
    assert(dbus_message_iter_append_basic(&iter, DBUS_TYPE_STRING, &key));
    assert(dbus_message_iter_open_container(&iter, DBUS_TYPE_VARIANT, signature, &variant));
    assert(dbus_message_iter_append_basic(&variant, type, data));
    assert(dbus_message_iter_close_container(&iter, &variant));
    setting_changed(NULL, msg, NULL);
    dbus_message_unref(msg);
}

int
main(void) {
    assert(!glfw_has_system_color_theme());
    // An attempted/failed query must not hide a later initial reply containing 0.
    appearance_initialized = true;
    DBusMessage *reply = dbus_message_new(DBUS_MESSAGE_TYPE_METHOD_RETURN);
    uint32_t zero = 0;
    assert(dbus_message_append_args(reply, DBUS_TYPE_UINT32, &zero, DBUS_TYPE_INVALID));
    DBusMessageIter value;
    dbus_message_iter_init(reply, &value);
    process_fdo_setting(FDO_APPEARANCE_KEY, &value);
    assert(glfw_has_system_color_theme() && notifications == 1 && received == GLFW_COLOR_SCHEME_NO_PREFERENCE);
    dbus_message_unref(reply);
    notifications = 0;
    change_scheme(1);
    assert(notifications == 1 && received == GLFW_COLOR_SCHEME_DARK);
    change_scheme(2);
    assert(notifications == 2 && received == GLFW_COLOR_SCHEME_LIGHT);
    assert(appearance == GLFW_COLOR_SCHEME_LIGHT);
    change_scheme(1);
    assert(notifications == 3 && received == GLFW_COLOR_SCHEME_DARK);
    change_scheme(1);
    assert(notifications == 3);
    change_scheme(0);
    assert(notifications == 4 && received == GLFW_COLOR_SCHEME_NO_PREFERENCE);
    _GLFWwindow window = {0};
    _glfw.windowListHead = &window;
    double factor;
    bool bold;
    assert(strcmp(glfw_current_system_font(&factor, &bold), "sans-serif 11") == 0 && factor == 1 && bold);
    const char *font = "Ubuntu Sans Bold Italic 13";
    change_setting(GNOME_WM_NAMESPACE, "titlebar-font", DBUS_TYPE_STRING, &font);
    dbus_bool_t flag = false;
    change_setting(GNOME_WM_NAMESPACE, "titlebar-uses-system-font", DBUS_TYPE_BOOLEAN, &flag);
    assert(strcmp(glfw_current_system_font(&factor, &bold), font) == 0 && !bold);
    flag = true;
    change_setting(GNOME_WM_NAMESPACE, "titlebar-uses-system-font", DBUS_TYPE_BOOLEAN, &flag);
    const char *interface = "Ubuntu Sans 12";
    change_setting(GNOME_DESKTOP_NAMESPACE, "font-name", DBUS_TYPE_STRING, &interface);
    assert(strcmp(glfw_current_system_font(&factor, &bold), interface) == 0 && bold);
    double scale = 2.;
    change_setting(GNOME_DESKTOP_NAMESPACE, "text-scaling-factor", DBUS_TYPE_DOUBLE, &scale);
    assert(glfw_current_titlebar_text_scale() == 2.);
    assert(glfw_current_titlebar_height() == 76);
    const char *large = "Ubuntu Sans 32";
    change_setting(GNOME_DESKTOP_NAMESPACE, "font-name", DBUS_TYPE_STRING, &large);
    assert(glfw_current_titlebar_height() == 122);
    change_setting(GNOME_DESKTOP_NAMESPACE, "font-name", DBUS_TYPE_STRING, &interface);
    unsigned previous = redraws;
    scale = NAN;
    change_setting(GNOME_DESKTOP_NAMESPACE, "text-scaling-factor", DBUS_TYPE_DOUBLE, &scale);
    scale = -1.;
    change_setting(GNOME_DESKTOP_NAMESPACE, "text-scaling-factor", DBUS_TYPE_DOUBLE, &scale);
    scale = 9.;
    change_setting(GNOME_DESKTOP_NAMESPACE, "text-scaling-factor", DBUS_TYPE_DOUBLE, &scale);
    assert(glfw_current_titlebar_text_scale() == 2. && redraws == previous);
    const char *buttons = "close:maximize,minimize,close,appmenu";
    change_setting(GNOME_WM_NAMESPACE, "button-layout", DBUS_TYPE_STRING, &buttons);
    assert(button_layout.left_count == 1 && button_layout.left[0] == 1);
    assert(button_layout.right_count == 2 && button_layout.right[0] == 2 && button_layout.right[1] == 3);
    previous = redraws;
    buttons = "close::maximize";
    change_setting(GNOME_WM_NAMESPACE, "button-layout", DBUS_TYPE_STRING, &buttons);
    assert(button_layout.left_count == 1 && redraws == previous);
    buttons = ":";
    change_setting(GNOME_WM_NAMESPACE, "button-layout", DBUS_TYPE_STRING, &buttons);
    assert(button_layout.left_count == 0 && button_layout.right_count == 0);
    const char *action = "minimize";
    change_setting(GNOME_WM_NAMESPACE, "action-double-click-titlebar", DBUS_TYPE_STRING, &action);
    assert(glfw_current_titlebar_action(0) == TITLEBAR_ACTION_MINIMIZE);
    action = "none";
    change_setting(GNOME_WM_NAMESPACE, "action-right-click-titlebar", DBUS_TYPE_STRING, &action);
    assert(glfw_current_titlebar_action(2) == TITLEBAR_ACTION_NONE);
    action = "menu";
    change_setting(GNOME_WM_NAMESPACE, "action-middle-click-titlebar", DBUS_TYPE_STRING, &action);
    assert(glfw_current_titlebar_action(1) == TITLEBAR_ACTION_MENU);
    action = "lower";
    change_setting(GNOME_WM_NAMESPACE, "action-middle-click-titlebar", DBUS_TYPE_STRING, &action);
    assert(glfw_current_titlebar_action(1) == TITLEBAR_ACTION_NONE);
    assert(redraws > 0);
    puts("Desktop portal: appearance, font preferences, scale validation and button layout signals passed");
    return 0;
}
