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


#include <string.h>
#include <stdlib.h>
#include "internal.h"
#include "xkb_glfw.h"
START_ALLOW_CASE_RANGE

#define debug(...) if (_glfw.hints.init.debugKeyboard) printf(__VA_ARGS__);


#define map_key(key) \
    switch(key) { \
        S(space, SPACE); \
        S(exclam, EXCLAM); \
        S(quotedbl, DOUBLE_QUOTE); \
        S(numbersign, NUMBER_SIGN); \
        S(dollar, DOLLAR); \
        S(ampersand, AMPERSAND); \
        S(apostrophe, APOSTROPHE); \
        S(parenleft, PARENTHESIS_LEFT); \
        S(parenright, PARENTHESIS_RIGHT); \
        S(plus, PLUS); \
        S(comma, COMMA); \
        S(minus, MINUS); \
        S(period, PERIOD); \
        S(slash, SLASH); \
        R(0, 9, 0, 9); \
        S(colon, COLON); \
        S(semicolon, SEMICOLON); \
        S(less, LESS); \
        S(equal, EQUAL); \
        S(greater, GREATER); \
        S(at, AT); \
        D(A, Z, A, Z); \
        S(bracketleft, LEFT_BRACKET); \
        S(backslash, BACKSLASH); \
        S(bracketright, RIGHT_BRACKET); \
        S(asciicircum, CIRCUMFLEX); \
        S(underscore, UNDERSCORE); \
        S(grave, GRAVE_ACCENT); \
        R(a, z, A, Z); \
        S(paragraph, PARAGRAPH); \
        S(masculine, MASCULINE); \
        S(agrave, A_GRAVE); \
        F(Agrave, A_GRAVE); \
        S(adiaeresis, A_DIAERESIS); \
        F(Adiaeresis, A_DIAERESIS); \
        S(aring, A_RING); \
        F(Aring, A_RING); \
        S(ae, AE); \
        F(AE, AE); \
        S(ccedilla, C_CEDILLA); \
        F(Ccedilla, C_CEDILLA); \
        S(egrave, E_GRAVE); \
        F(Egrave, E_GRAVE); \
        S(aacute, E_ACUTE); \
        F(Eacute, E_ACUTE); \
        S(igrave, I_GRAVE); \
        F(Igrave, I_GRAVE); \
        S(ntilde, N_TILDE); \
        F(Ntilde, N_TILDE); \
        S(ograve, O_GRAVE); \
        F(Ograve, O_GRAVE); \
        S(odiaeresis, O_DIAERESIS); \
        F(Odiaeresis, O_DIAERESIS); \
        S(oslash, O_SLASH); \
        F(Oslash, O_SLASH); \
        S(ugrave, U_GRAVE); \
        F(Ugrave, U_GRAVE); \
        S(udiaeresis, U_DIAERESIS); \
        F(Udiaeresis, U_DIAERESIS); \
        S(ssharp, S_SHARP); \
        S(Cyrillic_a, CYRILLIC_A); \
        F(Cyrillic_A, CYRILLIC_A); \
        S(Cyrillic_be, CYRILLIC_BE); \
        F(Cyrillic_BE, CYRILLIC_BE); \
        S(Cyrillic_ve, CYRILLIC_VE); \
        F(Cyrillic_VE, CYRILLIC_VE); \
        S(Cyrillic_ghe, CYRILLIC_GHE); \
        F(Cyrillic_GHE, CYRILLIC_GHE); \
        S(Cyrillic_de, CYRILLIC_DE); \
        F(Cyrillic_DE, CYRILLIC_DE); \
        S(Cyrillic_ie, CYRILLIC_IE); \
        F(Cyrillic_IE, CYRILLIC_IE); \
        S(Cyrillic_zhe, CYRILLIC_ZHE); \
        F(Cyrillic_ZHE, CYRILLIC_ZHE); \
        S(Cyrillic_ze, CYRILLIC_ZE); \
        F(Cyrillic_ZE, CYRILLIC_ZE); \
        S(Cyrillic_i, CYRILLIC_I); \
        F(Cyrillic_I, CYRILLIC_I); \
        S(Cyrillic_shorti, CYRILLIC_SHORT_I); \
        F(Cyrillic_SHORTI, CYRILLIC_SHORT_I); \
        S(Cyrillic_ka, CYRILLIC_KA); \
        F(Cyrillic_KA, CYRILLIC_KA); \
        S(Cyrillic_el, CYRILLIC_EL); \
        F(Cyrillic_EL, CYRILLIC_EL); \
        S(Cyrillic_em, CYRILLIC_EM); \
        F(Cyrillic_EM, CYRILLIC_EM); \
        S(Cyrillic_en, CYRILLIC_EN); \
        F(Cyrillic_EN, CYRILLIC_EN); \
        S(Cyrillic_o, CYRILLIC_O); \
        F(Cyrillic_O, CYRILLIC_O); \
        S(Cyrillic_pe, CYRILLIC_PE); \
        F(Cyrillic_PE, CYRILLIC_PE); \
        S(Cyrillic_er, CYRILLIC_ER); \
        F(Cyrillic_ER, CYRILLIC_ER); \
        S(Cyrillic_es, CYRILLIC_ES); \
        F(Cyrillic_ES, CYRILLIC_ES); \
        S(Cyrillic_te, CYRILLIC_TE); \
        F(Cyrillic_TE, CYRILLIC_TE); \
        S(Cyrillic_u, CYRILLIC_U); \
        F(Cyrillic_U, CYRILLIC_U); \
        S(Cyrillic_ef, CYRILLIC_EF); \
        F(Cyrillic_EF, CYRILLIC_EF); \
        S(Cyrillic_ha, CYRILLIC_HA); \
        F(Cyrillic_HA, CYRILLIC_HA); \
        S(Cyrillic_tse, CYRILLIC_TSE); \
        F(Cyrillic_TSE, CYRILLIC_TSE); \
        S(Cyrillic_che, CYRILLIC_CHE); \
        F(Cyrillic_CHE, CYRILLIC_CHE); \
        S(Cyrillic_sha, CYRILLIC_SHA); \
        F(Cyrillic_SHA, CYRILLIC_SHA); \
        S(Cyrillic_shcha, CYRILLIC_SHCHA); \
        F(Cyrillic_SHCHA, CYRILLIC_SHCHA); \
        S(Cyrillic_hardsign, CYRILLIC_HARD_SIGN); \
        F(Cyrillic_HARDSIGN, CYRILLIC_HARD_SIGN); \
        S(Cyrillic_yeru, CYRILLIC_YERU); \
        F(Cyrillic_YERU, CYRILLIC_YERU); \
        S(Cyrillic_softsign, CYRILLIC_SOFT_SIGN); \
        F(Cyrillic_SOFTSIGN, CYRILLIC_SOFT_SIGN); \
        S(Cyrillic_e, CYRILLIC_E); \
        F(Cyrillic_E, CYRILLIC_E); \
        S(Cyrillic_yu, CYRILLIC_YU); \
        F(Cyrillic_YU, CYRILLIC_YU); \
        S(Cyrillic_ya, CYRILLIC_YA); \
        F(Cyrillic_YA, CYRILLIC_YA); \
        S(Cyrillic_io, CYRILLIC_IO); \
        F(Cyrillic_IO, CYRILLIC_IO); \
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
        R(F1, F25, F1, F25); \
        R(KP_0, KP_9, KP_0, KP_9); \

static int
glfw_key_for_sym(xkb_keysym_t key) {
#define S(f, t) case XKB_KEY_##f: return GLFW_KEY_##t
#define F(f, t) S(f, t)
#define R(s, e, gs, ...) case XKB_KEY_##s ... XKB_KEY_##e: return GLFW_KEY_##gs + key - XKB_KEY_##s
#define D(s, e, gs, ...) R(s, e, gs, __VA_ARGS__)
    map_key(key)
        S(KP_Up, UP);
        S(KP_Down, DOWN);
        S(KP_Left, LEFT);
        S(KP_Right, RIGHT);
        default:
            break;
    }
    return GLFW_KEY_UNKNOWN;
#undef F
#undef D
#undef R
#undef S
}

xkb_keysym_t
glfw_xkb_sym_for_key(int key) {
#define S(f, t) case GLFW_KEY_##t: return XKB_KEY_##f
#define F(...)
#define R(s, e, gs, ge) case GLFW_KEY_##gs ... GLFW_KEY_##ge: return XKB_KEY_##s + key - GLFW_KEY_##gs
#define D(...)
    map_key(key)
    default:
        break;
    }
    return GLFW_KEY_UNKNOWN;
#undef F
#undef D
#undef R
#undef S
}
END_ALLOW_CASE_RANGE

#ifdef _GLFW_X11

bool
glfw_xkb_set_x11_events_mask(void) {
    if (!XkbSelectEvents(_glfw.x11.display, XkbUseCoreKbd, XkbNewKeyboardNotifyMask | XkbMapNotifyMask | XkbStateNotifyMask, XkbNewKeyboardNotifyMask | XkbMapNotifyMask | XkbStateNotifyMask)) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to set XKB events mask");
        return false;
    }
    return true;
}

bool
glfw_xkb_update_x11_keyboard_id(_GLFWXKBData *xkb) {
    xkb->keyboard_device_id = -1;
    xcb_connection_t* conn = XGetXCBConnection(_glfw.x11.display);
    if (!conn) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Failed to retrieve XCB connection");
        return false;
    }

    xkb->keyboard_device_id = xkb_x11_get_core_keyboard_device_id(conn);
    if (xkb->keyboard_device_id == -1) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Failed to retrieve core keyboard device id");
        return false;
    }
    return true;
}

#define xkb_glfw_load_keymap(keymap, ...) {\
    xcb_connection_t* conn = XGetXCBConnection(_glfw.x11.display); \
    if (conn) keymap = xkb_x11_keymap_new_from_device(xkb->context, conn, xkb->keyboard_device_id, XKB_KEYMAP_COMPILE_NO_FLAGS); \
}

#define xkb_glfw_load_state(keymap, state) {\
    xcb_connection_t* conn = XGetXCBConnection(_glfw.x11.display); \
    if (conn) state = xkb_x11_state_new_from_device(keymap, conn, xkb->keyboard_device_id); \
}

#else

#define xkb_glfw_load_keymap(keymap, map_str) keymap = xkb_keymap_new_from_string(xkb->context, map_str, XKB_KEYMAP_FORMAT_TEXT_V1, 0);
#define xkb_glfw_load_state(keymap, state) state = xkb_state_new(keymap);

#endif

static void
release_keyboard_data(_GLFWXKBData *xkb) {
#define US(group, state, unref) if (xkb->group.state) {  unref(xkb->group.state); xkb->group.state = NULL; }
#define UK(keymap) if(xkb->keymap) { xkb_keymap_unref(xkb->keymap); xkb->keymap = NULL; }
    US(states, composeState, xkb_compose_state_unref);
    UK(keymap);
    UK(default_keymap);
    US(states, state, xkb_state_unref);
    US(states, clean_state, xkb_state_unref);
    US(states, default_state, xkb_state_unref);
#undef US
#undef UK

}

void
glfw_xkb_release(_GLFWXKBData *xkb) {
    release_keyboard_data(xkb);
    if (xkb->context) {
        xkb_context_unref(xkb->context);
        xkb->context = NULL;
    }
    glfw_ibus_terminate(&xkb->ibus);
}

bool
glfw_xkb_create_context(_GLFWXKBData *xkb) {
    xkb->context = xkb_context_new(0);
    if (!xkb->context)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Failed to initialize XKB context");
        return false;
    }
    glfw_connect_to_ibus(&xkb->ibus);
    return true;
}

static const char*
load_keymaps(_GLFWXKBData *xkb, const char *map_str) {
    (void)(map_str);  // not needed on X11
    xkb_glfw_load_keymap(xkb->keymap, map_str);
    if (!xkb->keymap) return "Failed to compile XKB keymap";
    // The system default keymap, can be overridden by the XKB_DEFAULT_RULES
    // env var, see
    // https://xkbcommon.org/doc/current/structxkb__rule__names.html
    static struct xkb_rule_names default_rule_names = {0};
    xkb->default_keymap = xkb_keymap_new_from_names(xkb->context, &default_rule_names, XKB_KEYMAP_COMPILE_NO_FLAGS);
    if (!xkb->default_keymap) return "Failed to create default XKB keymap";
    return NULL;
}

static const char*
load_states(_GLFWXKBData *xkb) {
    xkb_glfw_load_state(xkb->keymap, xkb->states.state);
    xkb->states.clean_state = xkb_state_new(xkb->keymap);
    xkb->states.default_state = xkb_state_new(xkb->default_keymap);
    if (!xkb->states.state || !xkb->states.clean_state || !xkb->states.default_state) return "Failed to create XKB state";
    return NULL;
}

static void
load_compose_tables(_GLFWXKBData *xkb) {
    /* Look up the preferred locale, falling back to "C" as default. */
    struct xkb_compose_table* compose_table = NULL;
    const char *locale = getenv("LC_ALL");
    if (!locale) locale = getenv("LC_CTYPE");
    if (!locale) locale = getenv("LANG");
    if (!locale) locale = "C";
    compose_table = xkb_compose_table_new_from_locale(xkb->context, locale, XKB_COMPOSE_COMPILE_NO_FLAGS);
    if (!compose_table) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to create XKB compose table for locale %s", locale);
        return;
    }
    xkb->states.composeState = xkb_compose_state_new(compose_table, XKB_COMPOSE_STATE_NO_FLAGS);
    if (!xkb->states.composeState) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to create XKB compose state");
    }
    xkb_compose_table_unref(compose_table);
}

static inline xkb_mod_mask_t
active_unknown_modifiers(_GLFWXKBData *xkb, struct xkb_state *state) {
    size_t i = 0;
    xkb_mod_mask_t ans = 0;
    while (xkb->unknownModifiers[i] != XKB_MOD_INVALID) {
        if (xkb_state_mod_index_is_active(state, xkb->unknownModifiers[i], XKB_STATE_MODS_EFFECTIVE)) ans |= (1 << xkb->unknownModifiers[i]);
        i++;
    }
    return ans;
}

static void
update_modifiers(_GLFWXKBData *xkb) {
    XKBStateGroup *group = &xkb->states;
#define S(attr, name) if (xkb_state_mod_index_is_active(group->state, xkb->attr##Idx, XKB_STATE_MODS_EFFECTIVE)) group->modifiers |= GLFW_MOD_##name
    S(control, CONTROL); S(alt, ALT); S(shift, SHIFT); S(super, SUPER); S(capsLock, CAPS_LOCK); S(numLock, NUM_LOCK);
#undef S
    xkb->states.activeUnknownModifiers = active_unknown_modifiers(xkb, xkb->states.state);

}

bool
glfw_xkb_compile_keymap(_GLFWXKBData *xkb, const char *map_str) {
    const char *err;
    debug("Loading new XKB keymaps\n");
    release_keyboard_data(xkb);
    err = load_keymaps(xkb, map_str);
    if (err) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "%s", err);
        release_keyboard_data(xkb);
        return false;
    }
    err = load_states(xkb);
    if (err) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "%s", err);
        release_keyboard_data(xkb);
        return false;
    }
    load_compose_tables(xkb);
#define S(a, n) xkb->a##Idx = xkb_keymap_mod_get_index(xkb->keymap, n); xkb->a##Mask = 1 << xkb->a##Idx;
    S(control, XKB_MOD_NAME_CTRL);
    S(alt, XKB_MOD_NAME_ALT);
    S(shift, XKB_MOD_NAME_SHIFT);
    S(super, XKB_MOD_NAME_LOGO);
    S(capsLock, XKB_MOD_NAME_CAPS);
    S(numLock, XKB_MOD_NAME_NUM);
#undef S
    size_t capacity = arraysz(xkb->unknownModifiers), j = 0;
    for (xkb_mod_index_t i = 0; i < capacity; i++) xkb->unknownModifiers[i] = XKB_MOD_INVALID;
    for (xkb_mod_index_t i = 0; i < xkb_keymap_num_mods(xkb->keymap) && j < capacity - 1; i++) {
        if (i != xkb->controlIdx && i != xkb->altIdx && i != xkb->shiftIdx && i != xkb->superIdx && i != xkb->capsLockIdx && i != xkb->numLockIdx) xkb->unknownModifiers[j++] = i;
    }
    xkb->states.modifiers = 0;
    xkb->states.activeUnknownModifiers = 0;
    update_modifiers(xkb);
    return true;
}

void
glfw_xkb_update_modifiers(_GLFWXKBData *xkb, xkb_mod_mask_t depressed, xkb_mod_mask_t latched, xkb_mod_mask_t locked, xkb_layout_index_t base_group, xkb_layout_index_t latched_group, xkb_layout_index_t locked_group) {
    if (!xkb->keymap) return;
    xkb->states.modifiers = 0;
    xkb_state_update_mask(xkb->states.state, depressed, latched, locked, base_group, latched_group, locked_group);
    // We have to update the groups in clean_state, as they change for
    // different keyboard layouts, see https://github.com/kovidgoyal/kitty/issues/488
    xkb_state_update_mask(xkb->states.clean_state, 0, 0, 0, base_group, latched_group, locked_group);
    update_modifiers(xkb);
}

bool
glfw_xkb_should_repeat(_GLFWXKBData *xkb, xkb_keycode_t keycode) {
#ifdef _GLFW_WAYLAND
    keycode += 8;
#endif
    return xkb_keymap_key_repeats(xkb->keymap, keycode);
}


static inline xkb_keysym_t
compose_symbol(struct xkb_compose_state *composeState, xkb_keysym_t sym, int *compose_completed, char *key_text, int n) {
    *compose_completed = 0;
    if (sym == XKB_KEY_NoSymbol || !composeState) return sym;
    if (xkb_compose_state_feed(composeState, sym) != XKB_COMPOSE_FEED_ACCEPTED) return sym;
    switch (xkb_compose_state_get_status(composeState)) {
        case XKB_COMPOSE_COMPOSED:
            xkb_compose_state_get_utf8(composeState, key_text, n);
            *compose_completed = 1;
            return xkb_compose_state_get_one_sym(composeState);
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
glfw_xkb_keysym_from_name(const char *name, bool case_sensitive) {
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
#define pr(x) { \
    int num_needed = -1; \
    ssize_t space_left = sizeof(buf) - (p - buf) - 1; \
    if (space_left > 0) num_needed = snprintf(p, space_left, "%s", x);  \
    if (num_needed > 0) p += num_needed; \
}
    pr(name); pr(": ");
    s = p;
    for (xkb_mod_index_t i = 0; i < xkb_keymap_num_mods(xkb->keymap); i++) {
        xkb_mod_mask_t m = 1 << i;
        if (m & mods) { pr(xkb_keymap_mod_get_name(xkb->keymap, i)); pr("+"); }
    }
    if (p == s) { pr("none"); }
    else p--;
    pr(" ");
#undef pr
    return buf;
}

void
glfw_xkb_update_ime_state(_GLFWwindow *w, _GLFWXKBData *xkb, int which, int a, int b, int c, int d) {
    int x = 0, y = 0;
    switch(which) {
        case 1:
            glfw_ibus_set_focused(&xkb->ibus, a ? true : false);
            break;
        case 2:
            _glfwPlatformGetWindowPos(w, &x, &y);
            x += a; y += b;
            glfw_ibus_set_cursor_geometry(&xkb->ibus, x, y, c, d);
            break;
    }
}

void
glfw_xkb_key_from_ime(_GLFWIBUSKeyEvent *ev, bool handled_by_ime, bool failed) {
    _GLFWwindow *window = _glfwWindowForId(ev->window_id);
    if (failed && window && window->callbacks.keyboard) {
        // notify application to remove any existing pre-edit text
        GLFWkeyevent fake_ev;
        _glfwInitializeKeyEvent(&fake_ev, GLFW_KEY_UNKNOWN, 0, GLFW_PRESS, 0);
        fake_ev.ime_state = 1;
        window->callbacks.keyboard((GLFWwindow*) window, &fake_ev);
    }
    static xkb_keycode_t last_handled_press_keycode = 0;
    // We filter out release events that correspond to the last press event
    // handled by the IME system. This won't fix the case of multiple key
    // presses before a release, but is better than nothing. For that case
    // you'd need to implement a ring buffer to store pending key presses.
    xkb_keycode_t prev_handled_press = last_handled_press_keycode;
    last_handled_press_keycode = 0;
    bool is_release = ev->glfw_ev.action == GLFW_RELEASE;
    debug("From IBUS: native_key: 0x%x name: %s is_release: %d\n", ev->glfw_ev.native_key, glfw_xkb_keysym_name(ev->glfw_ev.key), is_release);
    if (window && !handled_by_ime && !(is_release && ev->glfw_ev.native_key == (int) prev_handled_press)) {
        debug("↳ to application: glfw_keycode: 0x%x (%s) keysym: 0x%x (%s) action: %s %s text: %s\n",
            ev->glfw_ev.native_key, _glfwGetKeyName(ev->glfw_ev.native_key), ev->glfw_ev.key, glfw_xkb_keysym_name(ev->glfw_ev.key),
            (ev->glfw_ev.action == GLFW_RELEASE ? "RELEASE" : (ev->glfw_ev.action == GLFW_PRESS ? "PRESS" : "REPEAT")),
            format_mods(ev->glfw_ev.mods), ev->glfw_ev.text
        );

        ev->glfw_ev.ime_state = 0;
        _glfwInputKeyboard(window, &ev->glfw_ev);
    } else debug("↳ discarded\n");
    if (!is_release && handled_by_ime)
      last_handled_press_keycode = ev->glfw_ev.native_key;
}

void
glfw_xkb_handle_key_event(_GLFWwindow *window, _GLFWXKBData *xkb, xkb_keycode_t xkb_keycode, int action) {
    static char key_text[64] = {0};
    const xkb_keysym_t *syms, *clean_syms, *default_syms;
    xkb_keysym_t xkb_sym;
    xkb_keycode_t code_for_sym = xkb_keycode, ibus_keycode = xkb_keycode;
    GLFWkeyevent glfw_ev;
    _glfwInitializeKeyEvent(&glfw_ev, GLFW_KEY_UNKNOWN, 0, GLFW_PRESS, 0); // init with default values
#ifdef _GLFW_WAYLAND
    code_for_sym += 8;
#else
    ibus_keycode -= 8;
#endif
    debug("%s xkb_keycode: 0x%x ", action == GLFW_RELEASE ? "Release" : "Press", xkb_keycode);
    XKBStateGroup *sg = &xkb->states;
    int num_syms = xkb_state_key_get_syms(sg->state, code_for_sym, &syms);
    int num_clean_syms = xkb_state_key_get_syms(sg->clean_state, code_for_sym, &clean_syms);
    key_text[0] = 0;
    // According to the documentation of xkb_compose_state_feed it does not
    // support multi-sym events, so we ignore them
    if (num_syms != 1 || num_clean_syms != 1) {
        debug("num_syms: %d num_clean_syms: %d ignoring event\n", num_syms, num_clean_syms);
        return;
    }
    xkb_sym = clean_syms[0];
    debug("clean_sym: %s ", glfw_xkb_keysym_name(clean_syms[0]));
    if (action == GLFW_PRESS || action == GLFW_REPEAT) {
        const char *text_type = "composed_text";
        int compose_completed;
        xkb_sym = compose_symbol(sg->composeState, syms[0], &compose_completed, key_text, sizeof(key_text));
        if (xkb_sym == XKB_KEY_NoSymbol && !compose_completed) {
            debug("compose not complete, ignoring.\n");
            return;
        }
        debug("composed_sym: %s ", glfw_xkb_keysym_name(xkb_sym));
        if (xkb_sym == syms[0]) { // composed sym is the same as non-composed sym
            // Only use the clean_sym if no mods other than the mods we report
            // are active (for example if ISO_Shift_Level_* mods are active
            // they are not reported by GLFW so the key should be the shifted
            // key). See https://github.com/kovidgoyal/kitty/issues/171#issuecomment-377557053
            xkb_mod_mask_t consumed_unknown_mods = xkb_state_key_get_consumed_mods(sg->state, code_for_sym) & sg->activeUnknownModifiers;
            if (sg->activeUnknownModifiers) debug("%s", format_xkb_mods(xkb, "active_unknown_mods", sg->activeUnknownModifiers));
            if (consumed_unknown_mods) { debug("%s", format_xkb_mods(xkb, "consumed_unknown_mods", consumed_unknown_mods)); }
            else xkb_sym = clean_syms[0];
            // xkb returns text even if alt and/or super are pressed
            if ( ((GLFW_MOD_CONTROL | GLFW_MOD_ALT | GLFW_MOD_SUPER) & sg->modifiers) == 0) {
              xkb_state_key_get_utf8(sg->state, code_for_sym, key_text, sizeof(key_text));
            }
            text_type = "text";
        }
        if ((1 <= key_text[0] && key_text[0] <= 31) || key_text[0] == 127) {
          key_text[0] = 0;  // don't send text for ascii control codes
        }
        if (key_text[0]) { debug("%s: %s ", text_type, key_text); }
    }
    if (xkb_sym == XKB_KEY_ISO_First_Group || xkb_sym == XKB_KEY_ISO_Last_Group || xkb_sym == XKB_KEY_ISO_Next_Group || xkb_sym == XKB_KEY_ISO_Prev_Group || xkb_sym == XKB_KEY_Mode_switch) {
      return;
    }
    int glfw_sym = glfw_key_for_sym(xkb_sym);
    bool is_fallback = false;
    if (glfw_sym == GLFW_KEY_UNKNOWN && !key_text[0]) {
        int num_default_syms = xkb_state_key_get_syms(sg->default_state, code_for_sym, &default_syms);
        if (num_default_syms > 0) {
            xkb_sym = default_syms[0];
            glfw_sym = glfw_key_for_sym(xkb_sym);
            is_fallback = true;
        }
    }
    debug(
        "%s%s: %d (%s) xkb_key: %d (%s)\n",
        format_mods(sg->modifiers),
        is_fallback ? "glfw_fallback_key" : "glfw_key", glfw_sym, _glfwGetKeyName(glfw_sym),
        xkb_sym, glfw_xkb_keysym_name(xkb_sym)
    );

    // NOTE: On linux, the reported native key identifier is the XKB keysym value.
    // Do not confuse `native_key` with `xkb_keycode` (the native keycode reported for the
    // glfw event VS the X internal code for a key).
    //
    // We use the XKB keysym instead of the X keycode to be able to go back-and-forth between
    // the GLFW keysym and the XKB keysym when needed, which is not possible using the X keycode,
    // because of the lost information when resolving the keycode to the keysym, like consumed
    // mods.
    glfw_ev.native_key = xkb_sym;

    glfw_ev.action = action;
    glfw_ev.key = glfw_sym;
    glfw_ev.mods = sg->modifiers;
    glfw_ev.text = key_text;

    _GLFWIBUSKeyEvent ibus_ev;
    ibus_ev.glfw_ev = glfw_ev;
    ibus_ev.ibus_keycode = ibus_keycode;
    ibus_ev.window_id = window->id;
    ibus_ev.ibus_keysym = syms[0];
    if (ibus_process_key(&ibus_ev, &xkb->ibus)) {
        debug("↳ to IBUS: keycode: 0x%x keysym: 0x%x (%s) %s\n", ibus_ev.ibus_keycode, ibus_ev.ibus_keysym, glfw_xkb_keysym_name(ibus_ev.ibus_keysym), format_mods(ibus_ev.glfw_ev.mods));
    } else {
        _glfwInputKeyboard(window, &glfw_ev);
    }
}
