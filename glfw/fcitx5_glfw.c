#define _GNU_SOURCE
#include <stdio.h>
#include <errno.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <limits.h>

#include "internal.h"
#include "fcitx5_glfw.h"

#define debug(...) if (_glfw.hints.init.debugKeyboard) printf(__VA_ARGS__);
static const char FCITX5_SERVICE[]         = "org.fcitx.Fcitx5";
static const char FCITX5_PATH[]            = "/org/freedesktop/portal/inputmethod";
static const char FCITX5_INTERFACE[]       = "org.fcitx.Fcitx.InputMethod1";
static const char FCITX5_INPUT_INTERFACE[] = "org.fcitx.Fcitx.InputContext1";
enum Capabilities {
    FCITX5_CAP_PREEDIT            = 1 << 1,
    FCITX5_CAP_FORMATTED_PREEDIT  = 1 << 4,
};

static inline size_t
GLFW_MIN(size_t a, size_t b) {
    return a < b ? a : b;
}

static const char*
get_fcitx5_text_from_commit_string(DBusMessage *msg) {
	const char *text = NULL;

	if (!glfw_dbus_get_args(msg, "Failed to get FCITX5 commit string text", DBUS_TYPE_STRING, &text, DBUS_TYPE_INVALID)) return NULL;

	return text;
}

static const char*
get_fcitx5_text_from_update_formatted_preedit(DBusMessage *msg) {
	char *text = NULL;

    DBusMessageIter iter, sub1, sub2;
    if (!dbus_message_iter_init(msg, &iter)) return NULL;
	if (dbus_message_iter_get_arg_type(&iter) != DBUS_TYPE_ARRAY) return NULL;
	int count = dbus_message_iter_get_element_count(&iter);
	if (count > 0) {
#define member_size(type, member) sizeof(((type *)0)->member)
		size_t max_text_size = member_size(_GLFWFCITX5KeyEvent, __embedded_text);
		text = calloc(1, max_text_size);
		if (!text) return NULL;
		size_t len = 0;
		const char *word;
		dbus_message_iter_recurse(&iter, &sub1);
		for (int i = 0; i < count; i++) {
			if (dbus_message_iter_get_arg_type(&sub1) != DBUS_TYPE_STRUCT) return NULL;
			dbus_message_iter_recurse(&sub1, &sub2);
			if (dbus_message_iter_get_arg_type(&sub2) != DBUS_TYPE_STRING) return NULL;
			dbus_message_iter_get_basic(&sub2, &word);
			size_t word_len = GLFW_MIN(strlen(word), max_text_size - len);
			strncpy(&text[len], word, word_len);
			len += word_len;
			dbus_message_iter_next(&sub1);
		}
		text[max_text_size - 1] = '\0';
	}

	return text;
}

static inline void
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
    // To monitor signals from FCITX5, use
    //  dbus-monitor "type='signal',interface='org.fcitx.Fcitx.InputContext1'"
    _GLFWFCITX5Data *fcitx5 = (_GLFWFCITX5Data*)user_data;
    (void)fcitx5;
    const char *text;
    switch(glfw_dbus_match_signal(msg, FCITX5_INPUT_INTERFACE, "CommitString", "UpdateFormattedPreedit", "CurrentIM", NULL)) {
        case 0:
            text = get_fcitx5_text_from_commit_string(msg);
            send_text(text, GLFW_IME_COMMIT_TEXT);
            debug("FCITX5: CommitString: '%s'\n", text ? text : "(nil)");
            break;
        case 1:
            text = get_fcitx5_text_from_update_formatted_preedit(msg);
            send_text(text, GLFW_IME_PREEDIT_CHANGED);
            debug("FCITX5: UpdateFormattedPreedit: '%s'\n", text ? text : "(nil)");
            break;
		case 2:
            debug("FCITX5: CurrentIM\n");
            text = "";
            send_text(text, GLFW_IME_PREEDIT_CHANGED);
            break;
    }
    return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
}

static void
input_context_created(DBusMessage *msg, const char* errmsg, void *data) {
    if (errmsg) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "FCITX5: Failed to create input context with error: %s", errmsg);
        return;
    }
    const char *path = NULL;
    if (!glfw_dbus_get_args(msg, "Failed to get FCITX5 context path from reply", DBUS_TYPE_OBJECT_PATH, &path, DBUS_TYPE_INVALID)) return;
    _GLFWFCITX5Data *fcitx5 = (_GLFWFCITX5Data*)data;
    free((void*)fcitx5->input_ctx_path);
    fcitx5->input_ctx_path = _glfw_strdup(path);
    if (!fcitx5->input_ctx_path) return;


    dbus_bus_add_match(fcitx5->conn, "type='signal',interface='org.fcitx.Fcitx.InputContext1'", NULL);
    DBusObjectPathVTable fcitx5_vtable = {.message_function = message_handler};
    dbus_connection_try_register_object_path(fcitx5->conn, fcitx5->input_ctx_path, &fcitx5_vtable, fcitx5, NULL);
    uint64_t caps = FCITX5_CAP_PREEDIT | FCITX5_CAP_FORMATTED_PREEDIT;
    if (!glfw_dbus_call_method_no_reply(fcitx5->conn, FCITX5_SERVICE, fcitx5->input_ctx_path, FCITX5_INPUT_INTERFACE, "SetCapability", DBUS_TYPE_UINT64, &caps, DBUS_TYPE_INVALID)) return;
    fcitx5->ok = true;
    glfw_fcitx5_set_focused(fcitx5, false);
    glfw_fcitx5_set_cursor_geometry(fcitx5, 0, 0, 0, 0);
    debug("Connected to FCITX5 daemon for IME input management\n");
}

static void
append_create_input_context_args(DBusMessage* msg) {
	const char *key = "program";
    const char *val = "GLFW_Application";
	DBusMessageIter iter, sub1, sub2;
	dbus_message_iter_init_append(msg, &iter);
	dbus_message_iter_open_container(&iter, DBUS_TYPE_ARRAY,
			DBUS_STRUCT_BEGIN_CHAR_AS_STRING
				DBUS_TYPE_STRING_AS_STRING
				DBUS_TYPE_STRING_AS_STRING
			DBUS_STRUCT_END_CHAR_AS_STRING,
			&sub1);
	dbus_message_iter_open_container(&sub1, DBUS_TYPE_STRUCT, NULL, &sub2);
	dbus_message_iter_append_basic(&sub2, DBUS_TYPE_STRING, &key);
	dbus_message_iter_append_basic(&sub2, DBUS_TYPE_STRING, &val);
	dbus_message_iter_close_container(&sub1, &sub2);
	dbus_message_iter_close_container(&iter, &sub1);
}

static bool
setup_connection(_GLFWFCITX5Data *fcitx5) {
    fcitx5->ok = false;
    if (fcitx5->conn) {
        glfw_dbus_close_connection(fcitx5->conn);
        fcitx5->conn = NULL;
    }
    debug("Connecting to FCITX5 daemon @ %s for IME input management\n", fcitx5->address);
	fcitx5->conn = glfw_dbus_session_bus();
    if (!fcitx5->conn) return false;
    free((void*)fcitx5->input_ctx_path); fcitx5->input_ctx_path = NULL;
	DBusMessage* msg = dbus_message_new_method_call(FCITX5_SERVICE, FCITX5_PATH, FCITX5_INTERFACE, "CreateInputContext");
	append_create_input_context_args(msg);
	bool retval = call_method_with_msg(fcitx5->conn, msg, DBUS_TIMEOUT_USE_DEFAULT, input_context_created, fcitx5);
    dbus_message_unref(msg);
	return retval;
}

void
glfw_connect_to_fcitx5(_GLFWFCITX5Data *fcitx5) {
    if (fcitx5->inited) return;
    fcitx5->inited = true;
    setup_connection(fcitx5);
}

void
glfw_fcitx5_terminate(_GLFWFCITX5Data *fcitx5) {
    if (fcitx5->conn) {
		// No need to close the session bus here
        fcitx5->conn = NULL;
    }
#define F(x) if (fcitx5->x) { free((void*)fcitx5->x); fcitx5->x = NULL; }
    F(input_ctx_path);
#undef F

    fcitx5->ok = false;
}

static bool
check_connection(_GLFWFCITX5Data *fcitx5) {
    if (!fcitx5->inited) return false;
    if (fcitx5->conn && dbus_connection_get_is_connected(fcitx5->conn)) {
        return fcitx5->ok;
    }
    return false;
}

void
glfw_fcitx5_dispatch(_GLFWFCITX5Data *fcitx5) {
	if (fcitx5->conn) glfw_dbus_dispatch(fcitx5->conn);
}
// }}}

static void
simple_message(_GLFWFCITX5Data *fcitx5, const char *method) {
    if (check_connection(fcitx5)) {
        glfw_dbus_call_method_no_reply(fcitx5->conn, FCITX5_SERVICE, fcitx5->input_ctx_path, FCITX5_INPUT_INTERFACE, method, DBUS_TYPE_INVALID);
    }
}

void
glfw_fcitx5_set_focused(_GLFWFCITX5Data *fcitx5, bool focused) {
    simple_message(fcitx5, focused ? "FocusIn" : "FocusOut");
}

void
glfw_fcitx5_set_cursor_geometry(_GLFWFCITX5Data *fcitx5, int x, int y, int w, int h) {
    if (check_connection(fcitx5)) {
        glfw_dbus_call_method_no_reply(fcitx5->conn, FCITX5_SERVICE, fcitx5->input_ctx_path, FCITX5_INPUT_INTERFACE, "SetCursorRect",
                DBUS_TYPE_INT32, &x, DBUS_TYPE_INT32, &y, DBUS_TYPE_INT32, &w, DBUS_TYPE_INT32, &h, DBUS_TYPE_INVALID);
    }
}

typedef enum
{
    FCITX5_SHIFT_MASK    = 1 << 0,
    FCITX5_LOCK_MASK     = 1 << 1,
    FCITX5_CONTROL_MASK  = 1 << 2,
    FCITX5_MOD1_MASK     = 1 << 3,
    FCITX5_MOD2_MASK     = 1 << 4,
    FCITX5_MOD3_MASK     = 1 << 5,
    FCITX5_MOD4_MASK     = 1 << 6,
    FCITX5_MOD5_MASK     = 1 << 7,
    FCITX5_BUTTON1_MASK  = 1 << 8,
} FcitxModifierType;

static inline uint32_t
fcitx5_key_state(unsigned int glfw_modifiers) {
    uint32_t ans = 0;
#define M(g, i) if(glfw_modifiers & GLFW_MOD_##g) ans |= i
    M(SHIFT, FCITX5_SHIFT_MASK);
    M(CAPS_LOCK, FCITX5_LOCK_MASK);
    M(CONTROL, FCITX5_CONTROL_MASK);
    M(ALT, FCITX5_MOD1_MASK);
    M(NUM_LOCK, FCITX5_MOD2_MASK);
    M(SUPER, FCITX5_MOD4_MASK);
    /* To do: figure out how to get super/hyper/meta */
#undef M
    return ans;
}

static void
key_event_processed(DBusMessage *msg, const char* errmsg, void *data) {
    uint32_t handled = 0;
    _GLFWFCITX5KeyEvent *ev = (_GLFWFCITX5KeyEvent*)data;
    // Restore key's text from the text embedded in the structure.
    ev->glfw_ev.text = ev->__embedded_text;
    bool is_release = ev->glfw_ev.action == GLFW_RELEASE;
    bool failed = false;
    if (errmsg) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "FCITX5: Failed to process key with error: %s", errmsg);
        failed = true;
    } else {
        glfw_dbus_get_args(msg, "Failed to get FCITX5 handled key from reply", DBUS_TYPE_BOOLEAN, &handled, DBUS_TYPE_INVALID);
        debug("FCITX5 processed native_key: 0x%x release: %d handled: %u\n", ev->glfw_ev.native_key, is_release, handled);
    }
    glfw_xkb_key_from_ime((_GLFWIMEKeyEvent*) ev, _GLFW_IME_MODULE_FCITX5, handled ? true : false, failed);
    free(ev);
}

bool
fcitx5_process_key(const _GLFWFCITX5KeyEvent *ev_, _GLFWFCITX5Data *fcitx5) {
    if (!check_connection(fcitx5)) return false;
    _GLFWFCITX5KeyEvent *ev = calloc(1, sizeof(_GLFWFCITX5KeyEvent));
    if (!ev) return false;
    memcpy(ev, ev_, sizeof(_GLFWFCITX5KeyEvent));
    // Put the key's text in a field IN the structure, for proper serialization.
    if (ev->glfw_ev.text) strncpy(ev->__embedded_text, ev->glfw_ev.text, sizeof(ev->__embedded_text) - 1);
    ev->glfw_ev.text = NULL;
	ev->is_release = ev->glfw_ev.action == GLFW_RELEASE;
	ev->time = 0;
    uint32_t state = fcitx5_key_state(ev->glfw_ev.mods);
    if (!glfw_dbus_call_method_with_reply(
            fcitx5->conn, FCITX5_SERVICE, fcitx5->input_ctx_path, FCITX5_INPUT_INTERFACE, "ProcessKeyEvent",
            3000, key_event_processed, ev,
            DBUS_TYPE_UINT32, &ev->fcitx5_keysym, DBUS_TYPE_UINT32, &ev->fcitx5_keycode, DBUS_TYPE_UINT32,
            &state, DBUS_TYPE_BOOLEAN, &ev->is_release, DBUS_TYPE_UINT32, &ev->time, DBUS_TYPE_INVALID)) {
        free(ev);
        return false;
    }
    return true;
}
