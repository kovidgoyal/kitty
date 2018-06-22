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


#include <string.h>
#include <stdlib.h>
#include "internal.h"
#include "xkb_glfw.h"

static GLFWbool debug_keyboard = GLFW_FALSE;
#define debug(...) if (debug_keyboard) printf(__VA_ARGS__);

#define map_key(key) { \
    switch(key) { \
        S(space, SPACE); \
        S(apostrophe, APOSTROPHE); \
        S(comma, COMMA); \
        S(minus, MINUS); \
        S(period, PERIOD); \
        S(slash, SLASH); \
        S(semicolon, SEMICOLON); \
        S(equal, EQUAL); \
        S(bracketleft, LEFT_BRACKET); \
        S(backslash, BACKSLASH); \
        S(bracketright, RIGHT_BRACKET); \
        S(grave, GRAVE_ACCENT); \
        S(Escape, ESCAPE); \
        S(Return, ENTER); \
        S(Tab, TAB); \
        S(BackSpace, BACKSPACE); \
        S(Insert, INSERT); \
        S(Delete, DELETE); \
        S(Right, RIGHT); \
        S(Left, LEFT); \
        S(Up, UP); \
        S(Down, DOWN); \
        S(Page_Up, PAGE_UP); \
        S(Page_Down, PAGE_DOWN); \
        S(Home, HOME); \
        S(End, END); \
        S(Caps_Lock, CAPS_LOCK); \
        S(Scroll_Lock, SCROLL_LOCK); \
        S(Num_Lock, NUM_LOCK); \
        S(Print, PRINT_SCREEN); \
        S(Pause, PAUSE); \
        S(KP_Decimal, KP_DECIMAL); \
        S(KP_Divide, KP_DIVIDE); \
        S(KP_Multiply, KP_MULTIPLY); \
        S(KP_Subtract, KP_SUBTRACT); \
        S(KP_Add, KP_ADD); \
        S(KP_Enter, KP_ENTER); \
        S(KP_Equal, KP_EQUAL); \
        F(KP_Home, HOME); \
        F(KP_End, END); \
        F(KP_Page_Up, PAGE_UP); \
        F(KP_Page_Down, PAGE_DOWN); \
        F(KP_Insert, INSERT); \
        F(KP_Delete, DELETE); \
        S(Shift_L, LEFT_SHIFT); \
        S(Control_L, LEFT_CONTROL); \
        S(Alt_L, LEFT_ALT); \
        S(Super_L, LEFT_SUPER); \
        S(Shift_R, RIGHT_SHIFT); \
        S(Control_R, RIGHT_CONTROL); \
        S(Alt_R, RIGHT_ALT); \
        S(Super_R, RIGHT_SUPER); \
        S(Menu, MENU); \
        R(0, 9, 0, 9); \
        R(a, z, A, Z); \
        D(A, Z, A, Z); \
        R(F1, F25, F1, F25); \
        R(KP_0, KP_9, KP_0, KP_9); \
        default: \
            break; \
    } \
}

static int
glfw_key_for_sym(xkb_keysym_t key) {
#define S(f, t) case XKB_KEY_##f: return GLFW_KEY_##t
#define F(f, t) S(f, t)
#define R(s, e, gs, ...) case XKB_KEY_##s ... XKB_KEY_##e: return GLFW_KEY_##gs + key - XKB_KEY_##s
#define D(s, e, gs, ...) R(s, e, gs)
    map_key(key)
    return GLFW_KEY_UNKNOWN;
#undef F
#undef D
#undef R
#undef S
};

xkb_keysym_t
glfw_xkb_sym_for_key(int key) {
#define S(f, t) case GLFW_KEY_##t: return XKB_KEY_##f
#define F(...)
#define R(s, e, gs, ge) case GLFW_KEY_##gs ... GLFW_KEY_##ge: return XKB_KEY_##s + key - GLFW_KEY_##gs
#define D(...)
    map_key(key)
    return GLFW_KEY_UNKNOWN;
#undef F
#undef D
#undef R
#undef S
}

#ifdef _GLFW_X11

GLFWbool
glfw_xkb_set_x11_events_mask(void) {
    if (!XkbSelectEvents(_glfw.x11.display, XkbUseCoreKbd, XkbNewKeyboardNotifyMask | XkbMapNotifyMask | XkbStateNotifyMask, XkbNewKeyboardNotifyMask | XkbMapNotifyMask | XkbStateNotifyMask)) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to set XKB events mask");
        return GLFW_FALSE;
    }
    return GLFW_TRUE;
}

GLFWbool
glfw_xkb_update_x11_keyboard_id(_GLFWXKBData *xkb) {
    xkb->keyboard_device_id = -1;
    xcb_connection_t* conn = XGetXCBConnection(_glfw.x11.display);
    if (!conn) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Failed to retrieve XCB connection");
        return GLFW_FALSE;
    }

    xkb->keyboard_device_id = xkb_x11_get_core_keyboard_device_id(conn);
    if (xkb->keyboard_device_id == -1) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Failed to retrieve core keyboard device id");
        return GLFW_FALSE;
    }
    return GLFW_TRUE;
}

#define xkb_glfw_load_keymap(keymap, ...) {\
    xcb_connection_t* conn = XGetXCBConnection(_glfw.x11.display); \
    if (conn) keymap = xkb_x11_keymap_new_from_device(xkb->context, conn, xkb->keyboard_device_id, XKB_KEYMAP_COMPILE_NO_FLAGS); \
}

#define xkb_glfw_load_state(keymap, state, ...) {\
    xcb_connection_t* conn = XGetXCBConnection(_glfw.x11.display); \
    if (conn) state = xkb_x11_state_new_from_device(keymap, conn, xkb->keyboard_device_id); \
}

#else

#define xkb_glfw_load_keymap(keymap, map_str) keymap = xkb_keymap_new_from_string(xkb->context, map_str, XKB_KEYMAP_FORMAT_TEXT_V1, 0);
#define xkb_glfw_load_state(keymap, state, ...) state = xkb_state_new(keymap);

#endif

void
glfw_xkb_release(_GLFWXKBData *xkb) {
    if (xkb->composeState) {
        xkb_compose_state_unref(xkb->composeState);
        xkb->composeState = NULL;
    }
    if (xkb->keymap) {
        xkb_keymap_unref(xkb->keymap);
        xkb->keymap = NULL;
    }
    if (xkb->default_keymap) {
        xkb_keymap_unref(xkb->default_keymap);
        xkb->default_keymap = NULL;
    }
    if (xkb->state) {
        xkb_state_unref(xkb->state);
        xkb->state = NULL;
    }
    if (xkb->clean_state) {
        xkb_state_unref(xkb->clean_state);
        xkb->clean_state = NULL;
    }
    if (xkb->default_state) {
        xkb_state_unref(xkb->default_state);
        xkb->default_state = NULL;
    }
    if (xkb->context) {
        xkb_context_unref(xkb->context);
        xkb->context = NULL;
    }
}

GLFWbool
glfw_xkb_create_context(_GLFWXKBData *xkb) {
    xkb->context = xkb_context_new(0);
    debug_keyboard = getenv("GLFW_DEBUG_KEYBOARD") != NULL;
    if (!xkb->context)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Failed to initialize XKB context");
        return GLFW_FALSE;
    }
    return GLFW_TRUE;
}

GLFWbool
glfw_xkb_compile_keymap(_GLFWXKBData *xkb, const char *map_str) {
    const char* locale = NULL;
    struct xkb_state* state = NULL, *clean_state = NULL;
    struct xkb_keymap* keymap = NULL;
    struct xkb_compose_table* compose_table = NULL;
    struct xkb_compose_state* compose_state = NULL;
    (void)(map_str);  // not needed on X11
    GLFWbool ok = GLFW_FALSE;

    xkb_glfw_load_keymap(keymap, map_str);
    if (!keymap) _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to compile XKB keymap");
    else {
        xkb_glfw_load_state(keymap, state);
        clean_state = xkb_state_new(keymap);
        if (!state || !clean_state) {
            _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to create XKB state");
            xkb_keymap_unref(keymap); keymap = NULL;
        } else {
            ok = GLFW_TRUE;
            /* Look up the preferred locale, falling back to "C" as default. */
            locale = getenv("LC_ALL");
            if (!locale) locale = getenv("LC_CTYPE");
            if (!locale) locale = getenv("LANG");
            if (!locale) locale = "C";
            compose_table = xkb_compose_table_new_from_locale(xkb->context, locale, XKB_COMPOSE_COMPILE_NO_FLAGS);
            if (!compose_table) {
                _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to create XKB compose table");
            } else {
                compose_state = xkb_compose_state_new(compose_table, XKB_COMPOSE_STATE_NO_FLAGS);
                xkb_compose_table_unref(compose_table); compose_table = NULL;
                if (!compose_state) {
                    _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to create XKB compose state");
                }
            }
        }
    }
    if (keymap && state && clean_state) {
        if (xkb->composeState) xkb_compose_state_unref(xkb->composeState);
        xkb->composeState = compose_state;
        if (xkb->keymap) xkb_keymap_unref(xkb->keymap);
        xkb->keymap = keymap;
        if (xkb->state) xkb_state_unref(xkb->state);
        xkb->state = state;
        if (xkb->clean_state) xkb_state_unref(xkb->clean_state);
        xkb->clean_state = clean_state;
    }
    if (xkb->keymap) {
#define S(a, n) xkb->a##Idx = xkb_keymap_mod_get_index(xkb->keymap, n); xkb->a##Mask = 1 << xkb->a##Idx;
        S(control, XKB_MOD_NAME_CTRL);
        S(alt, XKB_MOD_NAME_ALT);
        S(shift, XKB_MOD_NAME_SHIFT);
        S(super, XKB_MOD_NAME_LOGO);
        S(capsLock, XKB_MOD_NAME_CAPS);
        S(numLock, XKB_MOD_NAME_NUM);
#undef S
        size_t capacity = sizeof(xkb->unknownModifiers)/sizeof(xkb->unknownModifiers[0]), j = 0;
        for (xkb_mod_index_t i = 0; i < capacity; i++) xkb->unknownModifiers[i] = XKB_MOD_INVALID;
        for (xkb_mod_index_t i = 0; i < xkb_keymap_num_mods(xkb->keymap) && j < capacity - 1; i++) {
            if (i != xkb->controlIdx && i != xkb->altIdx && i != xkb->shiftIdx && i != xkb->superIdx && i != xkb->capsLockIdx && i != xkb->numLockIdx) xkb->unknownModifiers[j++] = i;
        }
        xkb->modifiers = 0;
        xkb->activeUnknownModifiers = 0;
    }
    if (!xkb->default_keymap && xkb->context) {
        // The system default keymap, can be overridden by the XKB_DEFAULT_RULES
        // env var, see
        // https://xkbcommon.org/doc/current/structxkb__rule__names.html
        static struct xkb_rule_names default_rule_names = {0};
        xkb->default_keymap = xkb_keymap_new_from_names(xkb->context, &default_rule_names, XKB_KEYMAP_COMPILE_NO_FLAGS);
        if (xkb->default_keymap) {
            xkb->default_state = xkb_state_new(keymap);
            if (!xkb->default_state) {
                _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to create default XKB state, fallback key processing is unavailable");
            }
        } else {
            _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to create default XKB keymap, fallback key processing is unavailable");
        }
    }
    return ok;
}

static inline xkb_mod_mask_t
active_unknown_modifiers(_GLFWXKBData *xkb) {
    size_t i = 0;
    xkb_mod_mask_t ans = 0;
    while (xkb->unknownModifiers[i] != XKB_MOD_INVALID) {
        if (xkb_state_mod_index_is_active(xkb->state, xkb->unknownModifiers[i], XKB_STATE_MODS_EFFECTIVE)) ans |= (1 << xkb->unknownModifiers[i]);
        i++;
    }
    return ans;
}


void
glfw_xkb_update_modifiers(_GLFWXKBData *xkb, xkb_mod_mask_t depressed, xkb_mod_mask_t latched, xkb_mod_mask_t locked, xkb_layout_index_t base_group, xkb_layout_index_t latched_group, xkb_layout_index_t locked_group) {
    if (!xkb->keymap) return;
    xkb->modifiers = 0;
    xkb_state_update_mask(xkb->state, depressed, latched, locked, base_group, latched_group, locked_group);
    // We have to update the groups in clean_state, as they change for
    // different keyboard layouts, see https://github.com/kovidgoyal/kitty/issues/488
    xkb_state_update_mask(xkb->clean_state, 0, 0, 0, base_group, latched_group, locked_group);
#define S(attr, name) if (xkb_state_mod_index_is_active(xkb->state, xkb->attr##Idx, XKB_STATE_MODS_EFFECTIVE)) xkb->modifiers |= GLFW_MOD_##name
    S(control, CONTROL); S(alt, ALT); S(shift, SHIFT); S(super, SUPER); S(capsLock, CAPS_LOCK); S(numLock, NUM_LOCK);
#undef S
    xkb->activeUnknownModifiers = active_unknown_modifiers(xkb);
}

GLFWbool
glfw_xkb_should_repeat(_GLFWXKBData *xkb, xkb_keycode_t scancode) {
#ifdef _GLFW_WAYLAND
    scancode += 8;
#endif
    return xkb_keymap_key_repeats(xkb->keymap, scancode);
}


static char text[256];

static inline xkb_keysym_t
compose_symbol(_GLFWXKBData *xkb, xkb_keysym_t sym) {
    if (sym == XKB_KEY_NoSymbol || !xkb->composeState) return sym;
    if (xkb_compose_state_feed(xkb->composeState, sym) != XKB_COMPOSE_FEED_ACCEPTED) return sym;
    switch (xkb_compose_state_get_status(xkb->composeState)) {
        case XKB_COMPOSE_COMPOSED:
            xkb_compose_state_get_utf8(xkb->composeState, text, sizeof(text));
            return xkb_compose_state_get_one_sym(xkb->composeState);
        case XKB_COMPOSE_COMPOSING:
        case XKB_COMPOSE_CANCELLED:
            return XKB_KEY_NoSymbol;
        case XKB_COMPOSE_NOTHING:
        default:
            return sym;
    }
}


const char*
glfw_xkb_keysym_name(xkb_keysym_t sym) {
    static char name[256];
    name[0] = 0;
    xkb_keysym_get_name(sym, name, sizeof(name));
    return name;
}

int
glfw_xkb_keysym_from_name(const char *name, GLFWbool case_sensitive) {
    return (int)xkb_keysym_from_name(name, case_sensitive ? XKB_KEYSYM_NO_FLAGS : XKB_KEYSYM_CASE_INSENSITIVE);
}

static inline const char*
format_mods(unsigned int mods) {
    static char buf[128];
    char *p = buf, *s;
#define pr(x) p += snprintf(p, sizeof(buf) - (p - buf) - 1, "%s", x)
    pr("mods: ");
    s = p;
    if (mods & GLFW_MOD_CONTROL) pr("ctrl+");
    if (mods & GLFW_MOD_ALT) pr("alt+");
    if (mods & GLFW_MOD_SHIFT) pr("shift+");
    if (mods & GLFW_MOD_SUPER) pr("super+");
    if (mods & GLFW_MOD_CAPS_LOCK) pr("capslock+");
    if (mods & GLFW_MOD_NUM_LOCK) pr("numlock+");
    if (p == s) pr("none");
    else p--;
    pr(" ");
#undef pr
    return buf;
}

static inline const char*
format_xkb_mods(_GLFWXKBData *xkb, const char* name, xkb_mod_mask_t mods) {
    static char buf[512];
    char *p = buf, *s;
#define pr(x) p += snprintf(p, sizeof(buf) - (p - buf) - 1, "%s", x)
    pr(name); pr(": ");
    s = p;
    for (xkb_mod_index_t i = 0; i < xkb_keymap_num_mods(xkb->keymap); i++) {
        xkb_mod_mask_t m = 1 << i;
        if (m & mods) { pr(xkb_keymap_mod_get_name(xkb->keymap, i)); pr("+"); }
    }
    if (p == s) pr("none");
    else p--;
    pr(" ");
#undef pr
    return buf;
}

void
glfw_xkb_handle_key_event(_GLFWwindow *window, _GLFWXKBData *xkb, xkb_keycode_t scancode, int action) {
    const xkb_keysym_t *syms, *clean_syms, *default_syms;
    xkb_keysym_t glfw_sym;
    xkb_keycode_t code_for_sym = scancode;
#ifdef _GLFW_WAYLAND
    code_for_sym += 8;
#endif
    debug("scancode: 0x%x release: %d ", scancode, action == GLFW_RELEASE);
    int num_syms = xkb_state_key_get_syms(xkb->state, code_for_sym, &syms);
    int num_clean_syms = xkb_state_key_get_syms(xkb->clean_state, code_for_sym, &clean_syms);
    text[0] = 0;
    // According to the documentation of xkb_compose_state_feed it does not
    // support multi-sym events, so we ignore them
    if (num_syms != 1 || num_clean_syms != 1) {
        debug("scancode: 0x%x num_syms: %d num_clean_syms: %d ignoring event\n", scancode, num_syms, num_clean_syms);
        return;
    }
    glfw_sym = clean_syms[0];
    debug("clean_sym: %s ", glfw_xkb_keysym_name(clean_syms[0]));
    if (action == GLFW_PRESS || action == GLFW_REPEAT) {
        const char *text_type = "composed_text";
        glfw_sym = compose_symbol(xkb, syms[0]);
        if (glfw_sym == XKB_KEY_NoSymbol) {
            debug("compose not complete, ignoring.\n");
            return;
        }
        debug("composed_sym: %s ", glfw_xkb_keysym_name(glfw_sym));
        if (glfw_sym == syms[0]) { // composed sym is the same as non-composed sym
            // Only use the clean_sym if no mods other than the mods we report
            // are active (for example if ISO_Shift_Level_* mods are active
            // they are not reported by GLFW so the key should be the shifted
            // key). See https://github.com/kovidgoyal/kitty/issues/171#issuecomment-377557053
            xkb_mod_mask_t consumed_unknown_mods = xkb_state_key_get_consumed_mods(xkb->state, code_for_sym) & xkb->activeUnknownModifiers;
            if (xkb->activeUnknownModifiers) debug("%s", format_xkb_mods(xkb, "active_unknown_mods", xkb->activeUnknownModifiers));
            if (consumed_unknown_mods) { debug("%s", format_xkb_mods(xkb, "consumed_unknown_mods", consumed_unknown_mods)); }
            else glfw_sym = clean_syms[0];
            // xkb returns text even if alt and/or super are pressed

            //if ( ((GLFW_MOD_CONTROL | GLFW_MOD_ALT | GLFW_MOD_SUPER) & xkb->modifiers) == 0)
            #define XKB_MOD_SHIFT 1
            #define XKB_MOD_CONTROL 4

            // if Shift and Control are pressed, we want to ignore Control for the evaluation of the text-symbol
            xkb_mod_mask_t mods_depressed = xkb_state_serialize_mods(xkb->state, XKB_STATE_MODS_DEPRESSED);
            if((mods_depressed & XKB_MOD_SHIFT) && (mods_depressed & XKB_MOD_CONTROL)) {
                xkb_mod_mask_t mods_latched = xkb_state_serialize_mods(xkb->state, XKB_STATE_MODS_LATCHED);
                xkb_mod_mask_t mods_locked = xkb_state_serialize_mods(xkb->state, XKB_STATE_MODS_LOCKED);
                xkb_layout_index_t layout_depressed = xkb_state_serialize_layout(xkb->state, XKB_STATE_LAYOUT_DEPRESSED);
                xkb_layout_index_t layout_latched = xkb_state_serialize_layout(xkb->state, XKB_STATE_LAYOUT_LATCHED);
                xkb_layout_index_t layout_locked = xkb_state_serialize_layout(xkb->state, XKB_STATE_LAYOUT_LOCKED);
                xkb_state_update_mask(xkb->state, mods_depressed & ~XKB_MOD_CONTROL, mods_latched, mods_locked, layout_depressed, layout_latched, layout_locked);
                xkb_state_key_get_utf8(xkb->state, code_for_sym, text, sizeof(text));
                xkb_state_update_mask(xkb->state, mods_depressed, mods_latched, mods_locked, layout_depressed, layout_latched, layout_locked);
            }
            else {
                xkb_state_key_get_utf8(xkb->state, code_for_sym, text, sizeof(text));
            }
            text_type = "text";
        }
        if ((1 <= text[0] && text[0] <= 31) || text[0] == 127) text[0] = 0;  // dont send text for ascii control codes
        if (text[0]) { debug("%s: %s ", text_type, text); }
    }
    int glfw_keycode = glfw_key_for_sym(glfw_sym);
    if (glfw_keycode == GLFW_KEY_UNKNOWN && !text[0]) {
        int num_default_syms = xkb_state_key_get_syms(xkb->default_state, code_for_sym, &default_syms);
        if (num_default_syms > 0) {
            glfw_sym = default_syms[0];
            glfw_keycode = glfw_key_for_sym(glfw_sym);
        }
        debug("%sglfw_fallback_key: %s ", format_mods(xkb->modifiers), _glfwGetKeyName(glfw_keycode));
    } else {
        debug("%sglfw_key: %s ", format_mods(xkb->modifiers), _glfwGetKeyName(glfw_keycode));
    }
    debug("text: '%s'\n", text);
    _glfwInputKeyboard(window, glfw_keycode, glfw_sym, action, xkb->modifiers, text, 0);
}
