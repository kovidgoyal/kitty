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
#include <math.h>
#ifdef _GLFW_WAYLAND
GLFWAPI void glfwWaylandRedrawCSDWindowTitle(GLFWwindow *window);
#endif

#define DESKTOP_SERVICE "org.freedesktop.portal.Desktop"
#define DESKTOP_PATH "/org/freedesktop/portal/desktop"
#define DESKTOP_INTERFACE "org.freedesktop.portal.Settings"
#define GNOME_DESKTOP_NAMESPACE "org.gnome.desktop.interface"
#define GNOME_WM_NAMESPACE "org.gnome.desktop.wm.preferences"
#define FDO_DESKTOP_NAMESPACE "org.freedesktop.appearance"
static const char *supported_namespaces[3] = {FDO_DESKTOP_NAMESPACE, GNOME_DESKTOP_NAMESPACE, GNOME_WM_NAMESPACE};
#define FDO_APPEARANCE_KEY "color-scheme"


static char theme_name[128] = {0};
static char interface_font[256] = "sans-serif 11";

static char titlebar_font[256];
static bool titlebar_uses_system_font = true;
static double titlebar_text_scale = 1.;
static GLFWTitlebarAction titlebar_actions[] = {TITLEBAR_ACTION_MAXIMIZE, TITLEBAR_ACTION_NONE, TITLEBAR_ACTION_MENU};
GLFWTitlebarAction glfw_current_titlebar_action(unsigned gesture) {
    return gesture < arraysz(titlebar_actions) ? titlebar_actions[gesture] : TITLEBAR_ACTION_NONE;
}
static GLFWTitlebarButtonLayout button_layout = {.right = {3, 2, 1}, .right_count = 3};

const GLFWTitlebarButtonLayout *
glfw_current_titlebar_button_layout(void) { return &button_layout; }

double
glfw_current_titlebar_text_scale(void) { return titlebar_text_scale; }

const char *
glfw_current_system_font(double *text_scale, bool *bold) {
    bool system_font = titlebar_uses_system_font || !titlebar_font[0];
    if (text_scale) *text_scale = titlebar_text_scale;
    if (bold) *bold = system_font;
    return system_font ? interface_font : titlebar_font;
}

unsigned
glfw_current_titlebar_height(void) {
    const char *font = glfw_current_system_font(NULL, NULL);
    const char *size = strrchr(font, ' ');
    double points = 11;
    if (size) {
        char *end;
        double parsed = strtod(size + 1, &end);
        if (end != size + 1 && !*end && isfinite(parsed) && parsed >= 1 && parsed <= 200) points = parsed;
    }
    return (unsigned)ceil(fmax(38., points * 96. / 72. + 18) * fmax(1, titlebar_text_scale));
}

static void
redraw_titlebars(void) {
#ifdef _GLFW_WAYLAND
    for (_GLFWwindow *w = _glfw.windowListHead; w; w = w->next) {
        w->wl.decorations.pressed_button = 0;
        w->wl.decorations.close.hovered = w->wl.decorations.maximize.hovered = w->wl.decorations.minimize.hovered = false;
        glfwWaylandRedrawCSDWindowTitle((GLFWwindow *)w);
    }
#endif
}

static bool
parse_button_layout(const char *value, GLFWTitlebarButtonLayout *out) {
    if (!value || strlen(value) >= 256) return false;
    char copy[256];
    snprintf(copy, sizeof(copy), "%s", value);
    char *colon = strchr(copy, ':');
    if (!colon || strchr(colon + 1, ':')) return false;
    *colon = 0;
    memset(out, 0, sizeof(*out));
    bool seen[4] = {false};
    for (int side = 0; side < 2; side++) {
        char *token = side ? colon + 1 : copy;
        while (token && *token) {
            char *next = strchr(token, ',');
            if (next) *next++ = 0;
            while (*token == ' ') token++;
            char *end = token + strlen(token);
            while (end > token && end[-1] == ' ') *--end = 0;
            int id = strcmp(token, "close") == 0 ? 1 : strcmp(token, "maximize") == 0 ? 2 : strcmp(token, "minimize") == 0 ? 3 : 0;
            if (id && !seen[id]) {
                seen[id] = true;
                if (side) out->right[out->right_count++] = id;
                else out->left[out->left_count++] = id;
            }
            token = next;
        }
    }
    return true;
}

static bool
read_string_setting(DBusMessageIter *value, char *dest, size_t capacity) {
    if (dbus_message_iter_get_arg_type(value) != DBUS_TYPE_STRING) return false;
    const char *text;
    dbus_message_iter_get_basic(value, &text);
    if (!text || !text[0] || strlen(text) >= capacity || strcmp(dest, text) == 0) return false;
    snprintf(dest, capacity, "%s", text);
    return true;
}

static void
process_wm_setting(const char *key, DBusMessageIter *value) {
    bool changed = false;
    if (strcmp(key, "titlebar-font") == 0) changed = read_string_setting(value, titlebar_font, sizeof(titlebar_font));
    else if (strcmp(key, "titlebar-uses-system-font") == 0 && dbus_message_iter_get_arg_type(value) == DBUS_TYPE_BOOLEAN) {
        dbus_bool_t flag;
        dbus_message_iter_get_basic(value, &flag);
        changed = titlebar_uses_system_font != (flag != 0);
        titlebar_uses_system_font = flag != 0;
    } else if (strcmp(key, "button-layout") == 0 && dbus_message_iter_get_arg_type(value) == DBUS_TYPE_STRING) {
        const char *text;
        dbus_message_iter_get_basic(value, &text);
        GLFWTitlebarButtonLayout parsed;
        if (parse_button_layout(text, &parsed) && memcmp(&parsed, &button_layout, sizeof(parsed)) != 0) {
            button_layout = parsed;
            changed = true;
        }
    }
    static const char *action_keys[] = {"action-double-click-titlebar", "action-middle-click-titlebar", "action-right-click-titlebar"};
    for (unsigned i = 0; i < arraysz(action_keys); i++) {
        if (strcmp(key, action_keys[i]) == 0 && dbus_message_iter_get_arg_type(value) == DBUS_TYPE_STRING) {
            const char *name;
            dbus_message_iter_get_basic(value, &name);
            // xdg-shell has no lower/shade or one-axis maximize request.
            GLFWTitlebarAction action = strcmp(name, "menu") == 0 ? TITLEBAR_ACTION_MENU :
                strcmp(name, "toggle-maximize") == 0 ? TITLEBAR_ACTION_MAXIMIZE :
                strcmp(name, "minimize") == 0 ? TITLEBAR_ACTION_MINIMIZE : TITLEBAR_ACTION_NONE;
            changed |= action != titlebar_actions[i];
            titlebar_actions[i] = action;
            break;
        }
    }
    if (changed) redraw_titlebars();
}

static int theme_size = -1;
static GLFWColorScheme appearance = GLFW_COLOR_SCHEME_NO_PREFERENCE;
static bool cursor_theme_changed = false, appearance_initialized = false;
static bool appearance_received = false;

bool
glfw_has_system_color_theme(void) { return appearance_received; }

static void
set_queried_appearance(uint32_t value) {
    if (value > 2) value = 0;
    bool changed = !appearance_received || appearance != (GLFWColorScheme)value;
    appearance = value;
    appearance_received = true;
    if (changed) redraw_titlebars();
}

#define HANDLER(name_)                                                                                              \
    static void name_(DBusMessage *msg, const DBusError *err, void *data) {                                         \
        (void)data;                                                                                                 \
        if (err) {                                                                                                  \
            _glfwInputError(GLFW_PLATFORM_ERROR, "%s: failed with error: %s: %s", #name_, err->name, err->message); \
            return;                                                                                                 \
        }

HANDLER(get_color_scheme_legacy)
DBusMessageIter iter, variant_iter, variant_iter2;
if (!dbus_message_iter_init(msg, &iter)) return;
dbus_message_iter_recurse(&iter, &variant_iter);
int type = dbus_message_iter_get_arg_type(&variant_iter);
if (type != DBUS_TYPE_VARIANT) {
    _glfwInputError(GLFW_PLATFORM_ERROR, "Read for color-scheme did not return a variant");
    return;
}
dbus_message_iter_recurse(&variant_iter, &variant_iter2);
if (type != DBUS_TYPE_VARIANT) {
    _glfwInputError(GLFW_PLATFORM_ERROR, "Read for color-scheme did not return a nested variant");
    return;
}
uint32_t val;
dbus_message_iter_get_basic(&variant_iter2, &val);
set_queried_appearance(val);
}

static void
get_color_scheme(DBusMessage *msg, const DBusError *err, void *data) {
    (void)data;
    if (err) {
        if (strcmp("org.freedesktop.DBus.Error.UnknownMethod", err->name) == 0) {
            DBusConnection *session_bus = glfw_dbus_session_bus();
            if (session_bus) {
                const char *namespace = FDO_DESKTOP_NAMESPACE, *key = FDO_APPEARANCE_KEY;
                glfw_dbus_call_blocking_method(
                    session_bus,
                    DESKTOP_SERVICE,
                    DESKTOP_PATH,
                    DESKTOP_INTERFACE,
                    "Read",
                    DBUS_TIMEOUT_USE_DEFAULT,
                    get_color_scheme_legacy,
                    NULL,
                    DBUS_TYPE_STRING,
                    &namespace,
                    DBUS_TYPE_STRING,
                    &key,
                    DBUS_TYPE_INVALID);
            }
            return;
        } else {
            _glfwInputError(GLFW_PLATFORM_ERROR, "%s: failed with error: %s: %s", "get_color_scheme", err->name, err->message);
            return;
        }
    }
    uint32_t val;
    DBusMessageIter iter, variant_iter;
    if (!dbus_message_iter_init(msg, &iter)) return;
    dbus_message_iter_recurse(&iter, &variant_iter);
    int type = dbus_message_iter_get_arg_type(&variant_iter);
    if (type != DBUS_TYPE_UINT32) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "ReadOne for color-scheme did not return a uint32");
        return;
    }
    dbus_message_iter_get_basic(&variant_iter, &val);
    set_queried_appearance(val);
}

GLFWColorScheme
glfw_current_system_color_theme(bool query_if_unintialized) {
    if (!appearance_initialized && query_if_unintialized) {
        appearance_initialized = true;
        DBusConnection *session_bus = glfw_dbus_session_bus();
        if (session_bus) {
            const char *namespace = FDO_DESKTOP_NAMESPACE, *key = FDO_APPEARANCE_KEY;
            glfw_dbus_call_blocking_method(
                session_bus,
                DESKTOP_SERVICE,
                DESKTOP_PATH,
                DESKTOP_INTERFACE,
                "ReadOne",
                DBUS_TIMEOUT_USE_DEFAULT,
                get_color_scheme,
                NULL,
                DBUS_TYPE_STRING,
                &namespace,
                DBUS_TYPE_STRING,
                &key,
                DBUS_TYPE_INVALID);
        }
    }
    return appearance;
}

static void
process_fdo_setting(const char *key, DBusMessageIter *value) {
    if (strcmp(key, FDO_APPEARANCE_KEY) == 0) {
        if (dbus_message_iter_get_arg_type(value) == DBUS_TYPE_UINT32) {
            uint32_t val;
            dbus_message_iter_get_basic(value, &val);
            if (val > 2) val = 0;
            if (!appearance_received) {
                appearance_received = true;
                appearance_initialized = true;
                appearance = val;
                _glfwInputColorScheme(appearance, true);
            }
        }
    }
}

static void
process_gnome_setting(const char *key, DBusMessageIter *value) {
    if (strcmp(key, "cursor-size") == 0) {
        if (dbus_message_iter_get_arg_type(value) == DBUS_TYPE_INT32) {
            int32_t sz;
            dbus_message_iter_get_basic(value, &sz);
            if (sz > 0 && sz != theme_size) {
                theme_size = sz;
                cursor_theme_changed = true;
            }
        }
    } else if (strcmp(key, "font-name") == 0) {
        if (read_string_setting(value, interface_font, sizeof(interface_font))) redraw_titlebars();
    } else if (strcmp(key, "text-scaling-factor") == 0 && dbus_message_iter_get_arg_type(value) == DBUS_TYPE_DOUBLE) {
        double factor;
        dbus_message_iter_get_basic(value, &factor);
        if (isfinite(factor) && factor >= .5 && factor <= 4 && factor != titlebar_text_scale) {
            titlebar_text_scale = factor;
            redraw_titlebars();
        }
    } else if (strcmp(key, "cursor-theme") == 0) {
        if (dbus_message_iter_get_arg_type(value) == DBUS_TYPE_STRING) {
            const char *name;
            dbus_message_iter_get_basic(value, &name);
            if (name && strncmp(theme_name, name, sizeof(theme_name) - 1) != 0) {
                strncpy(theme_name, name, sizeof(theme_name) - 1);
                cursor_theme_changed = true;
            }
        }
    }
}

static void
process_settings_dict(DBusMessageIter *array_iter, void(process_setting)(const char *, DBusMessageIter *)) {
    DBusMessageIter item_iter, value_iter;
    while (dbus_message_iter_get_arg_type(array_iter) == DBUS_TYPE_DICT_ENTRY) {
        dbus_message_iter_recurse(array_iter, &item_iter);
        if (dbus_message_iter_get_arg_type(&item_iter) == DBUS_TYPE_STRING) {
            const char *key;
            dbus_message_iter_get_basic(&item_iter, &key);
            if (dbus_message_iter_next(&item_iter) && dbus_message_iter_get_arg_type(&item_iter) == DBUS_TYPE_VARIANT) {
                dbus_message_iter_recurse(&item_iter, &value_iter);
                process_setting(key, &value_iter);
            }
        }
        if (!dbus_message_iter_next(array_iter)) break;
    }
}

HANDLER(process_desktop_settings)
cursor_theme_changed = false;
DBusMessageIter root, array, item, settings;
dbus_message_iter_init(msg, &root);
#define die(...)                                           \
    {                                                      \
        _glfwInputError(GLFW_PLATFORM_ERROR, __VA_ARGS__); \
        return;                                            \
    }
if (dbus_message_iter_get_arg_type(&root) != DBUS_TYPE_ARRAY) die("Reply to request for desktop settings is not an array");
dbus_message_iter_recurse(&root, &array);
while (dbus_message_iter_get_arg_type(&array) == DBUS_TYPE_DICT_ENTRY) {
    dbus_message_iter_recurse(&array, &item);
    if (dbus_message_iter_get_arg_type(&item) == DBUS_TYPE_STRING) {
        const char *namespace;
        dbus_message_iter_get_basic(&item, &namespace);
        if (dbus_message_iter_next(&item) && dbus_message_iter_get_arg_type(&item) == DBUS_TYPE_ARRAY) {
            dbus_message_iter_recurse(&item, &settings);
            if (strcmp(namespace, FDO_DESKTOP_NAMESPACE) == 0) {
                process_settings_dict(&settings, process_fdo_setting);
            } else if (strcmp(namespace, GNOME_DESKTOP_NAMESPACE) == 0) {
                process_settings_dict(&settings, process_gnome_setting);
            } else if (strcmp(namespace, GNOME_WM_NAMESPACE) == 0) {
                process_settings_dict(&settings, process_wm_setting);
            }
        }
    }
    if (!dbus_message_iter_next(&array)) break;
}
#undef die
#ifndef _GLFW_X11
if (cursor_theme_changed) _glfwPlatformChangeCursorTheme();
#endif
}

#undef HANDLER

static bool
read_desktop_settings(DBusConnection *session_bus) {
    RAII_MSG(msg, dbus_message_new_method_call(DESKTOP_SERVICE, DESKTOP_PATH, DESKTOP_INTERFACE, "ReadAll"));
    if (!msg) return false;
    DBusMessageIter iter, array_iter;
    dbus_message_iter_init_append(msg, &iter);
    if (!dbus_message_iter_open_container(&iter, DBUS_TYPE_ARRAY, "s", &array_iter)) { return false; }
    for (unsigned i = 0; i < arraysz(supported_namespaces); ++i) {
        if (!dbus_message_iter_append_basic(&array_iter, DBUS_TYPE_STRING, &supported_namespaces[i])) return false;
    }
    if (!dbus_message_iter_close_container(&iter, &array_iter)) { return false; }
    return call_method_with_msg(session_bus, msg, DBUS_TIMEOUT_USE_DEFAULT, process_desktop_settings, NULL, false);
}

void
glfw_current_cursor_theme(const char **theme, int *size) {
    *theme = theme_name[0] ? theme_name : NULL;
    *size = (theme_size > 0 && theme_size < 2048) ? theme_size : 32;
}

static void
get_cursor_theme_from_env(void) {
    const char *q = getenv("XCURSOR_THEME");
    if (q) strncpy(theme_name, q, sizeof(theme_name) - 1);
    const char *env = getenv("XCURSOR_SIZE");
    theme_size = 32;
    if (env) {
        const int retval = atoi(env);
        if (retval > 0 && retval < 2048) theme_size = retval;
    }
}

static void
on_color_scheme_change(DBusMessage *message) {
    DBusMessageIter iter[2];
    dbus_message_iter_init(message, &iter[0]);
    int current_type;
    while ((current_type = dbus_message_iter_get_arg_type(&iter[0])) != DBUS_TYPE_INVALID) {
        if (current_type == DBUS_TYPE_VARIANT) {
            dbus_message_iter_recurse(&iter[0], &iter[1]);
            if (dbus_message_iter_get_arg_type(&iter[1]) == DBUS_TYPE_UINT32) {
                uint32_t val = 0;
                dbus_message_iter_get_basic(&iter[1], &val);
                if (val > 2) val = 0;
                if (val != appearance || !appearance_received) {
                    appearance = val;
                    appearance_received = true;
                    appearance_initialized = true;
                    _glfwInputColorScheme(appearance, false);
                }
            }
            break;
        }
        dbus_message_iter_next(&iter[0]);
    }
}

static DBusHandlerResult
setting_changed(DBusConnection *conn UNUSED, DBusMessage *msg, void *user_data UNUSED) {
    /* printf("session_bus settings_changed invoked interface: %s member: %s\n", dbus_message_get_interface(msg), dbus_message_get_member(msg)); */
    if (dbus_message_is_signal(msg, DESKTOP_INTERFACE, "SettingChanged")) {
        const char *namespace = NULL, *key = NULL;
        if (glfw_dbus_get_args(
                msg,
                "Failed to get namespace and key from SettingChanged notification signal",
                DBUS_TYPE_STRING,
                &namespace,
                DBUS_TYPE_STRING,
                &key,
                DBUS_TYPE_INVALID)) {
            if (strcmp(namespace, FDO_DESKTOP_NAMESPACE) == 0) {
                if (strcmp(key, FDO_APPEARANCE_KEY) == 0) { on_color_scheme_change(msg); }
            } else if (strcmp(namespace, GNOME_DESKTOP_NAMESPACE) == 0 || strcmp(namespace, GNOME_WM_NAMESPACE) == 0) {
                DBusMessageIter iter, value;
                if (dbus_message_iter_init(msg, &iter) && dbus_message_iter_next(&iter) && dbus_message_iter_next(&iter)
                    && dbus_message_iter_get_arg_type(&iter) == DBUS_TYPE_VARIANT) {
                    dbus_message_iter_recurse(&iter, &value);
                    if (strcmp(namespace, GNOME_WM_NAMESPACE) == 0) process_wm_setting(key, &value);
                    else process_gnome_setting(key, &value);
                }
            }
        }
    }
    return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}


void
glfw_initialize_desktop_settings(void) {
    get_cursor_theme_from_env();
    DBusConnection *session_bus = glfw_dbus_session_bus();
    if (session_bus) {
        if (!read_desktop_settings(session_bus))
            _glfwInputError(GLFW_PLATFORM_ERROR, "WARNING: Failed to read desktop settings, using defaults, make sure you have the desktop portal running.");
        dbus_bus_add_match(session_bus, "type='signal',interface='" DESKTOP_INTERFACE "',member='SettingChanged'", NULL);
        dbus_connection_add_filter(session_bus, setting_changed, NULL, NULL);
    }
}
