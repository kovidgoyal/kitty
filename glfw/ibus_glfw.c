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

/* To test under X11 start IBUS as:
 * ibus-daemon -drxR
 * Setup the input sources you want with:
 * ibus-setup
 * Switch to the input source you want to test with:
 * ibus engine name
 * You can list available engines with:
 * ibus list-engine
 * Then run kitty as:
 * GLFW_IM_MODULE=ibus kitty
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <limits.h>

#include "internal.h"
#include "ibus_glfw.h"

#define debug debug_input
static const char IBUS_SERVICE[]         = "org.freedesktop.IBus";
static const char IBUS_PATH[]            = "/org/freedesktop/IBus";
static const char IBUS_INTERFACE[]       = "org.freedesktop.IBus";
static const char IBUS_INPUT_INTERFACE[] = "org.freedesktop.IBus.InputContext";
enum Capabilities {
    IBUS_CAP_PREEDIT_TEXT       = 1 << 0,
    IBUS_CAP_AUXILIARY_TEXT     = 1 << 1,
    IBUS_CAP_LOOKUP_TABLE       = 1 << 2,
    IBUS_CAP_FOCUS              = 1 << 3,
    IBUS_CAP_PROPERTY           = 1 << 4,
    IBUS_CAP_SURROUNDING_TEXT   = 1 << 5
};

typedef enum
{
    IBUS_SHIFT_MASK    = 1 << 0,
    IBUS_LOCK_MASK     = 1 << 1,
    IBUS_CONTROL_MASK  = 1 << 2,
    IBUS_MOD1_MASK     = 1 << 3,
    IBUS_MOD2_MASK     = 1 << 4,
    IBUS_MOD3_MASK     = 1 << 5,
    IBUS_MOD4_MASK     = 1 << 6,
    IBUS_MOD5_MASK     = 1 << 7,
    IBUS_BUTTON1_MASK  = 1 << 8,
    IBUS_BUTTON2_MASK  = 1 << 9,
    IBUS_BUTTON3_MASK  = 1 << 10,
    IBUS_BUTTON4_MASK  = 1 << 11,
    IBUS_BUTTON5_MASK  = 1 << 12,

    /* The next few modifiers are used by XKB, so we skip to the end.
     * Bits 15 - 23 are currently unused. Bit 29 is used internally.
     */

    /* ibus mask */
    IBUS_HANDLED_MASK  = 1 << 24,
    IBUS_FORWARD_MASK  = 1 << 25,
    IBUS_IGNORED_MASK  = IBUS_FORWARD_MASK,

    IBUS_SUPER_MASK    = 1 << 26,
    IBUS_HYPER_MASK    = 1 << 27,
    IBUS_META_MASK     = 1 << 28,

    IBUS_RELEASE_MASK  = 1 << 30,

    IBUS_MODIFIER_MASK = 0x5f001fff
} IBusModifierType;


static uint32_t
ibus_key_state_from_glfw(unsigned int glfw_modifiers, int action) {
    uint32_t ans = action == GLFW_RELEASE ? IBUS_RELEASE_MASK : 0;
#define M(g, i) if(glfw_modifiers & GLFW_MOD_##g) ans |= i
    M(SHIFT, IBUS_SHIFT_MASK);
    M(CAPS_LOCK, IBUS_LOCK_MASK);
    M(CONTROL, IBUS_CONTROL_MASK);
    M(ALT, IBUS_MOD1_MASK);
    M(NUM_LOCK, IBUS_MOD2_MASK);
    M(SUPER, IBUS_MOD4_MASK);
    /* To do: figure out how to get super/hyper/meta */
#undef M
    return ans;
}

static unsigned int
glfw_modifiers_from_ibus_state(uint32_t ibus_key_state) {
    unsigned int ans = 0;
#define M(g, i) if(ibus_key_state & i) ans |= GLFW_MOD_##g
    M(SHIFT, IBUS_SHIFT_MASK);
    M(CAPS_LOCK, IBUS_LOCK_MASK);
    M(CONTROL, IBUS_CONTROL_MASK);
    M(ALT, IBUS_MOD1_MASK);
    M(NUM_LOCK, IBUS_MOD2_MASK);
    M(SUPER, IBUS_MOD4_MASK);
    /* To do: figure out how to get super/hyper/meta */
#undef M
    return ans;
}

static bool
test_env_var(const char *name, const char *val) {
    const char *q = getenv(name);
    return (q && strcmp(q, val) == 0) ? true : false;
}

static size_t
GLFW_MIN(size_t a, size_t b) {
    return a < b ? a : b;
}

static const char*
get_ibus_text_from_message(DBusMessage *msg) {
    /* The message structure is (from dbus-monitor)
       variant       struct {
         string "IBusText"
         array [
         ]
         string "ash "
         variant             struct {
               string "IBusAttrList"
               array [
               ]
               array [
               ]
            }
      }
    */
    const char *text = NULL;
    const char *struct_id = NULL;
    DBusMessageIter iter, sub1, sub2;
    dbus_message_iter_init(msg, &iter);

    if (dbus_message_iter_get_arg_type(&iter) != DBUS_TYPE_VARIANT) return NULL;

    dbus_message_iter_recurse(&iter, &sub1);

    if (dbus_message_iter_get_arg_type(&sub1) != DBUS_TYPE_STRUCT) return NULL;

    dbus_message_iter_recurse(&sub1, &sub2);

    if (dbus_message_iter_get_arg_type(&sub2) != DBUS_TYPE_STRING) return NULL;

    dbus_message_iter_get_basic(&sub2, &struct_id);
    if (!struct_id || strncmp(struct_id, "IBusText", sizeof("IBusText")) != 0) return NULL;

    dbus_message_iter_next(&sub2);
    dbus_message_iter_next(&sub2);

    if (dbus_message_iter_get_arg_type(&sub2) != DBUS_TYPE_STRING) return NULL;

    dbus_message_iter_get_basic(&sub2, &text);

    return text;
}

static void
handle_ibus_forward_key_event(DBusMessage *msg) {
    uint32_t keysym, keycode, state;
    DBusMessageIter iter;
    dbus_message_iter_init(msg, &iter);

    if (dbus_message_iter_get_arg_type(&iter) != DBUS_TYPE_UINT32) return;
    dbus_message_iter_get_basic(&iter, &keysym);
    dbus_message_iter_next(&iter);

    if (dbus_message_iter_get_arg_type(&iter) != DBUS_TYPE_UINT32) return;
    dbus_message_iter_get_basic(&iter, &keycode);
    dbus_message_iter_next(&iter);

    if (dbus_message_iter_get_arg_type(&iter) != DBUS_TYPE_UINT32) return;
    dbus_message_iter_get_basic(&iter, &state);

    int mods = glfw_modifiers_from_ibus_state(state);

    debug("IBUS: ForwardKeyEvent: keysym=%x, keycode=%x, state=%x, glfw_mods=%x\n", keysym, keycode, state, mods);
    glfw_xkb_forwarded_key_from_ime(keysym, mods);
}

static void
send_text(const char *text, GLFWIMEState ime_state) {
    _GLFWwindow *w = _glfwFocusedWindow();
    if (w && w->callbacks.keyboard) {
        GLFWkeyevent fake_ev = {.action = GLFW_PRESS};
        fake_ev.text = text;
        fake_ev.ime_state = ime_state;
        w->callbacks.keyboard((GLFWwindow*) w, &fake_ev);
    }
}

// Connection handling {{{

static DBusHandlerResult
message_handler(DBusConnection *conn UNUSED, DBusMessage *msg, void *user_data) {
    // To monitor signals from IBUS, use
    //  dbus-monitor --address `ibus address` "type='signal',interface='org.freedesktop.IBus.InputContext'"
    _GLFWIBUSData *ibus = (_GLFWIBUSData*)user_data;
    (void)ibus;
    const char *text;
    switch(glfw_dbus_match_signal(msg, IBUS_INPUT_INTERFACE, "CommitText", "UpdatePreeditText", "HidePreeditText", "ShowPreeditText", "ForwardKeyEvent", NULL)) {
        case 0:
            text = get_ibus_text_from_message(msg);
            debug("IBUS: CommitText: '%s'\n", text ? text : "(nil)");
            send_text(text, GLFW_IME_COMMIT_TEXT);
            break;
        case 1:
            text = get_ibus_text_from_message(msg);
            debug("IBUS: UpdatePreeditText: '%s'\n", text ? text : "(nil)");
            send_text(text, GLFW_IME_PREEDIT_CHANGED);
            break;
        case 2:
            debug("IBUS: HidePreeditText\n");
            send_text("", GLFW_IME_PREEDIT_CHANGED);
            break;
        case 3:
            debug("IBUS: ShowPreeditText\n");
            break;
        case 4:
            handle_ibus_forward_key_event(msg);
            break;
    }
    return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}

static DBusHandlerResult
ibus_on_owner_change(DBusConnection* conn UNUSED, DBusMessage* msg, void* user_data) {
    if (dbus_message_is_signal(msg, "org.freedesktop.DBus", "NameOwnerChanged")) {
        const char* name;
        const char* old_owner;
        const char* new_owner;

        if (!dbus_message_get_args(msg, NULL,
            DBUS_TYPE_STRING, &name,
            DBUS_TYPE_STRING, &old_owner,
            DBUS_TYPE_STRING, &new_owner,
            DBUS_TYPE_INVALID
        )) {
            return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
        }

        if (strcmp(name, "org.freedesktop.IBus") != 0) {
            return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
        }

        _GLFWIBUSData* ibus = (_GLFWIBUSData*) user_data;
        ibus->name_owner_changed = true;

        return DBUS_HANDLER_RESULT_HANDLED;

    }

    return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}

static const char*
get_ibus_address_file_name(void) {
    const char *addr;
    static char ans[PATH_MAX];
    static char display[64] = {0};
    addr = getenv("IBUS_ADDRESS");
    int offset = 0;
    if (addr && addr[0]) {
        memcpy(ans, addr, GLFW_MIN(strlen(addr), sizeof(ans)));
        return ans;
    }
    const char* disp_num = NULL;
    const char *host = "unix";
    // See https://github.com/ibus/ibus/commit/8ce25208c3f4adfd290a032c6aa739d2b7580eb1 for why we need this dance.
    const char *de = getenv("WAYLAND_DISPLAY");
    if (de) {
        disp_num = de;
    } else {
        const char *de = getenv("DISPLAY");
        if (!de || !de[0]) de = ":0.0";
        strncpy(display, de, sizeof(display) - 1);
        char *dnum = strrchr(display, ':');
        if (!dnum) {
            _glfwInputError(GLFW_PLATFORM_ERROR, "Could not get IBUS address file name as DISPLAY env var has no colon");
            return NULL;
        }
        char *screen_num = strrchr(display, '.');
        *dnum = 0;
        dnum++;
        if (screen_num) *screen_num = 0;
        if (*display) host = display;
        disp_num = dnum;
    }

    memset(ans, 0, sizeof(ans));
    const char *conf_env = getenv("XDG_CONFIG_HOME");
    if (conf_env && conf_env[0]) {
        offset = snprintf(ans, sizeof(ans), "%s", conf_env);
    } else {
        conf_env = getenv("HOME");
        if (!conf_env || !conf_env[0]) {
            _glfwInputError(GLFW_PLATFORM_ERROR, "Could not get IBUS address file name as no HOME env var is set");
            return NULL;
        }
        offset = snprintf(ans, sizeof(ans), "%s/.config", conf_env);
    }
    DBusError err;
    char *key = dbus_try_get_local_machine_id(&err);
    if (!key) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Cannot connect to IBUS as could not get DBUS local machine id with error %s: %s", err.name ? err.name : "", err.message ? err.message : "");
        return NULL;
    }
    snprintf(ans + offset, sizeof(ans) - offset, "/ibus/bus/%s-%s-%s", key, host, disp_num);
    dbus_free(key);
    return ans;
}


static bool
read_ibus_address(_GLFWIBUSData *ibus) {
    static char buf[1024];
    struct stat s;
    FILE *addr_file = fopen(ibus->address_file_name, "r");
    if (!addr_file) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to open IBUS address file: %s with error: %s", ibus->address_file_name, strerror(errno));
        return false;
    }
    int stat_result = fstat(fileno(addr_file), &s);
    bool found = false;
    while (fgets(buf, sizeof(buf), addr_file)) {
        if (strncmp(buf, "IBUS_ADDRESS=", sizeof("IBUS_ADDRESS=")-1) == 0) {
            size_t sz = strlen(buf);
            if (buf[sz-1] == '\n') buf[sz-1] = 0;
            if (buf[sz-2] == '\r') buf[sz-2] = 0;
            found = true;
            break;
        }
    }
    fclose(addr_file); addr_file = NULL;
    if (stat_result != 0) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to stat IBUS address file: %s with error: %s", ibus->address_file_name, strerror(errno));
        return false;
    }
    ibus->address_file_mtime = s.st_mtime;
    if (found) {
        free((void*)ibus->address);
        ibus->address = _glfw_strdup(buf + sizeof("IBUS_ADDRESS=") - 1);
        return true;
    }
    _glfwInputError(GLFW_PLATFORM_ERROR, "Could not find IBUS_ADDRESS in %s", ibus->address_file_name);
    return false;
}

void
input_context_created(DBusMessage *msg, const DBusError *err, void *data) {
    if (err) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "IBUS: Failed to create input context with error: %s: %s", err->name, err->message);
        return;
    }
    const char *path = NULL;
    if (!glfw_dbus_get_args(msg, "Failed to get IBUS context path from reply", DBUS_TYPE_OBJECT_PATH, &path, DBUS_TYPE_INVALID)) return;
    _GLFWIBUSData *ibus = (_GLFWIBUSData*)data;
    free((void*)ibus->input_ctx_path);
    ibus->input_ctx_path = _glfw_strdup(path);
    if (!ibus->input_ctx_path) return;
    dbus_bus_add_match(ibus->conn, "type='signal',interface='org.freedesktop.DBus', member='NameOwnerChanged'", NULL);
    dbus_connection_add_filter(ibus->conn, ibus_on_owner_change, ibus, free);
    dbus_bus_add_match(ibus->conn, "type='signal',interface='org.freedesktop.IBus.InputContext'", NULL);
    DBusObjectPathVTable ibus_vtable = {.message_function = message_handler};
    dbus_connection_try_register_object_path(ibus->conn, ibus->input_ctx_path, &ibus_vtable, ibus, NULL);
    enum Capabilities caps = IBUS_CAP_FOCUS | IBUS_CAP_PREEDIT_TEXT;
    if (!glfw_dbus_call_method_no_reply(ibus->conn, IBUS_SERVICE, ibus->input_ctx_path, IBUS_INPUT_INTERFACE, "SetCapabilities", DBUS_TYPE_UINT32, &caps, DBUS_TYPE_INVALID)) return;
    ibus->ok = true;
    glfw_ibus_set_focused(ibus, _glfwFocusedWindow() != NULL);
    glfw_ibus_set_cursor_geometry(ibus, 0, 0, 0, 0);
    debug("Connected to IBUS daemon for IME input management\n");
}

static bool
setup_connection(_GLFWIBUSData *ibus) {
    const char *client_name = "GLFW_Application";
    const char *address_file_name = get_ibus_address_file_name();
    ibus->ok = false;
    if (!address_file_name) return false;
    free((void*)ibus->address_file_name);
    ibus->address_file_name = _glfw_strdup(address_file_name);
    if (!read_ibus_address(ibus)) return false;
    if (ibus->conn) {
        glfw_dbus_close_connection(ibus->conn);
        ibus->conn = NULL;
    }
    debug("Connecting to IBUS daemon @ %s for IME input management\n", ibus->address);
    ibus->conn = glfw_dbus_connect_to(ibus->address, "Failed to connect to the IBUS daemon, with error", "ibus", true);
    if (!ibus->conn) return false;
    free((void*)ibus->input_ctx_path); ibus->input_ctx_path = NULL;
    if (!glfw_dbus_call_method_with_reply(
            ibus->conn, IBUS_SERVICE, IBUS_PATH, IBUS_INTERFACE, "CreateInputContext", DBUS_TIMEOUT_USE_DEFAULT, input_context_created, ibus,
            DBUS_TYPE_STRING, &client_name, DBUS_TYPE_INVALID)) {
        return false;
    }
    return true;
}


void
glfw_connect_to_ibus(_GLFWIBUSData *ibus) {
    if (ibus->inited) return;
    if (!test_env_var("GLFW_IM_MODULE", "ibus")) return;
    ibus->inited = true;
    ibus->name_owner_changed = false;
    setup_connection(ibus);
}

void
glfw_ibus_terminate(_GLFWIBUSData *ibus) {
    if (ibus->conn) {
        glfw_dbus_close_connection(ibus->conn);
        ibus->conn = NULL;
    }
#define F(x) if (ibus->x) { free((void*)ibus->x); ibus->x = NULL; }
    F(input_ctx_path);
    F(address);
    F(address_file_name);
#undef F

    ibus->ok = false;
}

static bool
check_connection(_GLFWIBUSData *ibus) {
    if (!ibus->inited) return false;
    if (ibus->conn && dbus_connection_get_is_connected(ibus->conn) && !ibus->name_owner_changed) return ibus->ok;
    struct stat s;
    ibus->name_owner_changed = false;
    if (stat(ibus->address_file_name, &s) != 0 || s.st_mtime != ibus->address_file_mtime) {
        if (!read_ibus_address(ibus)) return false;
        return setup_connection(ibus);
    }
    return false;
}


void
glfw_ibus_dispatch(_GLFWIBUSData *ibus) {
    if (ibus->conn) glfw_dbus_dispatch(ibus->conn);
}
// }}}

static void
simple_message(_GLFWIBUSData *ibus, const char *method) {
    if (check_connection(ibus)) {
        glfw_dbus_call_method_no_reply(ibus->conn, IBUS_SERVICE, ibus->input_ctx_path, IBUS_INPUT_INTERFACE, method, DBUS_TYPE_INVALID);
    }
}

void
glfw_ibus_set_focused(_GLFWIBUSData *ibus, bool focused) {
    simple_message(ibus, focused ? "FocusIn" : "FocusOut");
}

void
glfw_ibus_set_cursor_geometry(_GLFWIBUSData *ibus, int x, int y, int w, int h) {
    if (check_connection(ibus)) {
        glfw_dbus_call_method_no_reply(ibus->conn, IBUS_SERVICE, ibus->input_ctx_path, IBUS_INPUT_INTERFACE, "SetCursorLocation",
                DBUS_TYPE_INT32, &x, DBUS_TYPE_INT32, &y, DBUS_TYPE_INT32, &w, DBUS_TYPE_INT32, &h, DBUS_TYPE_INVALID);
    }
}

void
key_event_processed(DBusMessage *msg, const DBusError *err, void *data) {
    uint32_t handled = 0;
    _GLFWIBUSKeyEvent *ev = (_GLFWIBUSKeyEvent*)data;
    // Restore key's text from the text embedded in the structure.
    ev->glfw_ev.text = ev->__embedded_text;
    bool is_release = ev->glfw_ev.action == GLFW_RELEASE;
    bool failed = false;
    if (err) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "IBUS: Failed to process key with error: %s: %s", err->name, err->message);
        failed = true;
    } else {
        glfw_dbus_get_args(msg, "Failed to get IBUS handled key from reply", DBUS_TYPE_BOOLEAN, &handled, DBUS_TYPE_INVALID);
        debug("IBUS processed native_key: 0x%x release: %d handled: %u\n", ev->glfw_ev.native_key, is_release, handled);
    }
    glfw_xkb_key_from_ime(ev, handled ? true : false, failed);
    free(ev);
}

bool
ibus_process_key(const _GLFWIBUSKeyEvent *ev_, _GLFWIBUSData *ibus) {
    if (!check_connection(ibus)) return false;
    _GLFWIBUSKeyEvent *ev = calloc(1, sizeof(_GLFWIBUSKeyEvent));
    if (!ev) return false;
    memcpy(ev, ev_, sizeof(_GLFWIBUSKeyEvent));
    // Put the key's text in a field IN the structure, for proper serialization.
    if (ev->glfw_ev.text) strncpy(ev->__embedded_text, ev->glfw_ev.text, sizeof(ev->__embedded_text) - 1);
    ev->glfw_ev.text = NULL;
    uint32_t state = ibus_key_state_from_glfw(ev->glfw_ev.mods, ev->glfw_ev.action);
    if (!glfw_dbus_call_method_with_reply(
            ibus->conn, IBUS_SERVICE, ibus->input_ctx_path, IBUS_INPUT_INTERFACE, "ProcessKeyEvent",
            3000, key_event_processed, ev,
            DBUS_TYPE_UINT32, &ev->ibus_keysym, DBUS_TYPE_UINT32, &ev->ibus_keycode, DBUS_TYPE_UINT32,
            &state, DBUS_TYPE_INVALID)) {
        free(ev);
        return false;
    }
    return true;
}
