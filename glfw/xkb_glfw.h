//========================================================================
// GLFW 3.3 XKB - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2014 Kovid Goyal <kovid@kovidgoyal.net>
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

#pragma once

#include <xkbcommon/xkbcommon.h>
#include <xkbcommon/xkbcommon-compose.h>

typedef struct xkb_context* (* PFN_xkb_context_new)(enum xkb_context_flags);
typedef void (* PFN_xkb_context_unref)(struct xkb_context*);
typedef struct xkb_keymap* (* PFN_xkb_keymap_new_from_string)(struct xkb_context*, const char*, enum xkb_keymap_format, enum xkb_keymap_compile_flags);
typedef void (* PFN_xkb_keymap_unref)(struct xkb_keymap*);
typedef xkb_mod_index_t (* PFN_xkb_keymap_mod_get_index)(struct xkb_keymap*, const char*);
typedef int (* PFN_xkb_keymap_key_repeats)(struct xkb_keymap*, xkb_keycode_t);
typedef struct xkb_state* (* PFN_xkb_state_new)(struct xkb_keymap*);
typedef void (* PFN_xkb_state_unref)(struct xkb_state*);
typedef int (* PFN_xkb_state_key_get_syms)(struct xkb_state*, xkb_keycode_t, const xkb_keysym_t**);
typedef enum xkb_state_component (* PFN_xkb_state_update_mask)(struct xkb_state*, xkb_mod_mask_t, xkb_mod_mask_t, xkb_mod_mask_t, xkb_layout_index_t, xkb_layout_index_t, xkb_layout_index_t);
typedef xkb_mod_mask_t (* PFN_xkb_state_serialize_mods)(struct xkb_state*, enum xkb_state_component);

#define xkb_context_new GLFW_XKB_GLOBAL_NAME.context_new
#define xkb_context_unref GLFW_XKB_GLOBAL_NAME.context_unref
#define xkb_keymap_new_from_string GLFW_XKB_GLOBAL_NAME.keymap_new_from_string
#define xkb_keymap_unref GLFW_XKB_GLOBAL_NAME.keymap_unref
#define xkb_keymap_mod_get_index GLFW_XKB_GLOBAL_NAME.keymap_mod_get_index
#define xkb_keymap_key_repeats GLFW_XKB_GLOBAL_NAME.keymap_key_repeats
#define xkb_state_new GLFW_XKB_GLOBAL_NAME.state_new
#define xkb_state_unref GLFW_XKB_GLOBAL_NAME.state_unref
#define xkb_state_key_get_syms GLFW_XKB_GLOBAL_NAME.state_key_get_syms
#define xkb_state_update_mask GLFW_XKB_GLOBAL_NAME.state_update_mask
#define xkb_state_serialize_mods GLFW_XKB_GLOBAL_NAME.state_serialize_mods

typedef struct xkb_compose_table* (* PFN_xkb_compose_table_new_from_locale)(struct xkb_context*, const char*, enum xkb_compose_compile_flags);
typedef void (* PFN_xkb_compose_table_unref)(struct xkb_compose_table*);
typedef struct xkb_compose_state* (* PFN_xkb_compose_state_new)(struct xkb_compose_table*, enum xkb_compose_state_flags);
typedef void (* PFN_xkb_compose_state_unref)(struct xkb_compose_state*);
typedef enum xkb_compose_feed_result (* PFN_xkb_compose_state_feed)(struct xkb_compose_state*, xkb_keysym_t);
typedef enum xkb_compose_status (* PFN_xkb_compose_state_get_status)(struct xkb_compose_state*);
typedef xkb_keysym_t (* PFN_xkb_compose_state_get_one_sym)(struct xkb_compose_state*);

#define xkb_compose_table_new_from_locale GLFW_XKB_GLOBAL_NAME.compose_table_new_from_locale
#define xkb_compose_table_unref GLFW_XKB_GLOBAL_NAME.compose_table_unref
#define xkb_compose_state_new GLFW_XKB_GLOBAL_NAME.compose_state_new
#define xkb_compose_state_unref GLFW_XKB_GLOBAL_NAME.compose_state_unref
#define xkb_compose_state_feed GLFW_XKB_GLOBAL_NAME.compose_state_feed
#define xkb_compose_state_get_status GLFW_XKB_GLOBAL_NAME.compose_state_get_status
#define xkb_compose_state_get_one_sym GLFW_XKB_GLOBAL_NAME.compose_state_get_one_sym


typedef struct {
    void*                   handle;
    struct xkb_context*     context;
    struct xkb_keymap*      keymap;
    struct xkb_state*       state;
    struct xkb_compose_state* composeState;
    short int               keycodes[256];
    short int               scancodes[GLFW_KEY_LAST + 1];

    xkb_mod_mask_t          controlMask;
    xkb_mod_mask_t          altMask;
    xkb_mod_mask_t          shiftMask;
    xkb_mod_mask_t          superMask;
    xkb_mod_mask_t          capsLockMask;
    xkb_mod_mask_t          numLockMask;
    unsigned int            modifiers;

    PFN_xkb_context_new context_new;
    PFN_xkb_context_unref context_unref;
    PFN_xkb_keymap_new_from_string keymap_new_from_string;
    PFN_xkb_keymap_unref keymap_unref;
    PFN_xkb_keymap_mod_get_index keymap_mod_get_index;
    PFN_xkb_keymap_key_repeats keymap_key_repeats;
    PFN_xkb_state_new state_new;
    PFN_xkb_state_unref state_unref;
    PFN_xkb_state_key_get_syms state_key_get_syms;
    PFN_xkb_state_update_mask state_update_mask;
    PFN_xkb_state_serialize_mods state_serialize_mods;

    PFN_xkb_compose_table_new_from_locale compose_table_new_from_locale;
    PFN_xkb_compose_table_unref compose_table_unref;
    PFN_xkb_compose_state_new compose_state_new;
    PFN_xkb_compose_state_unref compose_state_unref;
    PFN_xkb_compose_state_feed compose_state_feed;
    PFN_xkb_compose_state_get_status compose_state_get_status;
    PFN_xkb_compose_state_get_one_sym compose_state_get_one_sym;
} _GLFWXKBData;

#define bind_xkb_sym(name) GLFW_XKB_GLOBAL_NAME.name = (PFN_xkb_##name) _glfw_dlsym(GLFW_XKB_GLOBAL_NAME.handle, "xkb_" #name)
#define load_glfw_xkb() {\
    GLFW_XKB_GLOBAL_NAME.handle = _glfw_dlopen("libxkbcommon.so.0"); \
    if (!GLFW_XKB_GLOBAL_NAME.handle) \
    { \
        _glfwInputError(GLFW_PLATFORM_ERROR, \
                        "Failed to open libxkbcommon"); \
        return GLFW_FALSE; \
    } \
    bind_xkb_sym(context_new); \
    bind_xkb_sym(context_unref); \
    bind_xkb_sym(keymap_new_from_string); \
    bind_xkb_sym(keymap_unref); \
    bind_xkb_sym(keymap_mod_get_index); \
    bind_xkb_sym(keymap_key_repeats); \
    bind_xkb_sym(state_new); \
    bind_xkb_sym(state_unref); \
    bind_xkb_sym(state_key_get_syms); \
    bind_xkb_sym(state_update_mask); \
    bind_xkb_sym(state_serialize_mods); \
    bind_xkb_sym(compose_table_new_from_locale); \
    bind_xkb_sym(compose_table_unref); \
    bind_xkb_sym(compose_state_new); \
    bind_xkb_sym(compose_state_unref); \
    bind_xkb_sym(compose_state_feed); \
    bind_xkb_sym(compose_state_get_status); \
    bind_xkb_sym(compose_state_get_one_sym); \
}

#define release_glfw_xkb() {\
    if (GLFW_XKB_GLOBAL_NAME.composeState) { \
        xkb_compose_state_unref(GLFW_XKB_GLOBAL_NAME.composeState); \
        GLFW_XKB_GLOBAL_NAME.composeState = NULL; \
    } \
    if (GLFW_XKB_GLOBAL_NAME.keymap) { \
        xkb_keymap_unref(GLFW_XKB_GLOBAL_NAME.keymap); \
        GLFW_XKB_GLOBAL_NAME.keymap = NULL; \
    } \
    if (GLFW_XKB_GLOBAL_NAME.state) { \
        xkb_state_unref(GLFW_XKB_GLOBAL_NAME.state); \
        GLFW_XKB_GLOBAL_NAME.state = NULL; \
    } \
    if (GLFW_XKB_GLOBAL_NAME.context) { \
        xkb_context_unref(GLFW_XKB_GLOBAL_NAME.context); \
        GLFW_XKB_GLOBAL_NAME.context = NULL; \
    } \
    if (GLFW_XKB_GLOBAL_NAME.handle) { \
        _glfw_dlclose(GLFW_XKB_GLOBAL_NAME.handle); \
        GLFW_XKB_GLOBAL_NAME.handle = NULL; \
    } \
}

#define create_glfw_xkb_context() {\
    GLFW_XKB_GLOBAL_NAME.context = xkb_context_new(0); \
    if (!GLFW_XKB_GLOBAL_NAME.context) \
    { \
        _glfwInputError(GLFW_PLATFORM_ERROR, \
                        "Failed to initialize XKB context"); \
        return GLFW_FALSE; \
    } \
    int scancode; \
    memset(GLFW_XKB_GLOBAL_NAME.keycodes, -1, sizeof(GLFW_XKB_GLOBAL_NAME.keycodes)); \
    memset(GLFW_XKB_GLOBAL_NAME.scancodes, -1, sizeof(GLFW_XKB_GLOBAL_NAME.scancodes)); \
\
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_GRAVE]      = GLFW_KEY_GRAVE_ACCENT; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_1]          = GLFW_KEY_1; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_2]          = GLFW_KEY_2; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_3]          = GLFW_KEY_3; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_4]          = GLFW_KEY_4; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_5]          = GLFW_KEY_5; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_6]          = GLFW_KEY_6; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_7]          = GLFW_KEY_7; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_8]          = GLFW_KEY_8; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_9]          = GLFW_KEY_9; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_0]          = GLFW_KEY_0; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_SPACE]      = GLFW_KEY_SPACE; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_MINUS]      = GLFW_KEY_MINUS; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_EQUAL]      = GLFW_KEY_EQUAL; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_Q]          = GLFW_KEY_Q; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_W]          = GLFW_KEY_W; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_E]          = GLFW_KEY_E; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_R]          = GLFW_KEY_R; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_T]          = GLFW_KEY_T; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_Y]          = GLFW_KEY_Y; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_U]          = GLFW_KEY_U; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_I]          = GLFW_KEY_I; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_O]          = GLFW_KEY_O; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_P]          = GLFW_KEY_P; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_LEFTBRACE]  = GLFW_KEY_LEFT_BRACKET; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_RIGHTBRACE] = GLFW_KEY_RIGHT_BRACKET; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_A]          = GLFW_KEY_A; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_S]          = GLFW_KEY_S; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_D]          = GLFW_KEY_D; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F]          = GLFW_KEY_F; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_G]          = GLFW_KEY_G; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_H]          = GLFW_KEY_H; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_J]          = GLFW_KEY_J; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_K]          = GLFW_KEY_K; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_L]          = GLFW_KEY_L; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_SEMICOLON]  = GLFW_KEY_SEMICOLON; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_APOSTROPHE] = GLFW_KEY_APOSTROPHE; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_Z]          = GLFW_KEY_Z; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_X]          = GLFW_KEY_X; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_C]          = GLFW_KEY_C; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_V]          = GLFW_KEY_V; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_B]          = GLFW_KEY_B; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_N]          = GLFW_KEY_N; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_M]          = GLFW_KEY_M; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_COMMA]      = GLFW_KEY_COMMA; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_DOT]        = GLFW_KEY_PERIOD; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_SLASH]      = GLFW_KEY_SLASH; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_BACKSLASH]  = GLFW_KEY_BACKSLASH; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_ESC]        = GLFW_KEY_ESCAPE; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_TAB]        = GLFW_KEY_TAB; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_LEFTSHIFT]  = GLFW_KEY_LEFT_SHIFT; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_RIGHTSHIFT] = GLFW_KEY_RIGHT_SHIFT; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_LEFTCTRL]   = GLFW_KEY_LEFT_CONTROL; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_RIGHTCTRL]  = GLFW_KEY_RIGHT_CONTROL; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_LEFTALT]    = GLFW_KEY_LEFT_ALT; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_RIGHTALT]   = GLFW_KEY_RIGHT_ALT; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_LEFTMETA]   = GLFW_KEY_LEFT_SUPER; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_RIGHTMETA]  = GLFW_KEY_RIGHT_SUPER; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_MENU]       = GLFW_KEY_MENU; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_NUMLOCK]    = GLFW_KEY_NUM_LOCK; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_CAPSLOCK]   = GLFW_KEY_CAPS_LOCK; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_PRINT]      = GLFW_KEY_PRINT_SCREEN; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_SCROLLLOCK] = GLFW_KEY_SCROLL_LOCK; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_PAUSE]      = GLFW_KEY_PAUSE; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_DELETE]     = GLFW_KEY_DELETE; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_BACKSPACE]  = GLFW_KEY_BACKSPACE; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_ENTER]      = GLFW_KEY_ENTER; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_HOME]       = GLFW_KEY_HOME; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_END]        = GLFW_KEY_END; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_PAGEUP]     = GLFW_KEY_PAGE_UP; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_PAGEDOWN]   = GLFW_KEY_PAGE_DOWN; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_INSERT]     = GLFW_KEY_INSERT; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_LEFT]       = GLFW_KEY_LEFT; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_RIGHT]      = GLFW_KEY_RIGHT; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_DOWN]       = GLFW_KEY_DOWN; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_UP]         = GLFW_KEY_UP; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F1]         = GLFW_KEY_F1; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F2]         = GLFW_KEY_F2; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F3]         = GLFW_KEY_F3; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F4]         = GLFW_KEY_F4; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F5]         = GLFW_KEY_F5; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F6]         = GLFW_KEY_F6; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F7]         = GLFW_KEY_F7; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F8]         = GLFW_KEY_F8; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F9]         = GLFW_KEY_F9; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F10]        = GLFW_KEY_F10; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F11]        = GLFW_KEY_F11; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F12]        = GLFW_KEY_F12; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F13]        = GLFW_KEY_F13; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F14]        = GLFW_KEY_F14; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F15]        = GLFW_KEY_F15; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F16]        = GLFW_KEY_F16; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F17]        = GLFW_KEY_F17; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F18]        = GLFW_KEY_F18; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F19]        = GLFW_KEY_F19; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F20]        = GLFW_KEY_F20; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F21]        = GLFW_KEY_F21; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F22]        = GLFW_KEY_F22; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F23]        = GLFW_KEY_F23; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_F24]        = GLFW_KEY_F24; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KPSLASH]    = GLFW_KEY_KP_DIVIDE; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KPDOT]      = GLFW_KEY_KP_MULTIPLY; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KPMINUS]    = GLFW_KEY_KP_SUBTRACT; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KPPLUS]     = GLFW_KEY_KP_ADD; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KP0]        = GLFW_KEY_KP_0; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KP1]        = GLFW_KEY_KP_1; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KP2]        = GLFW_KEY_KP_2; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KP3]        = GLFW_KEY_KP_3; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KP4]        = GLFW_KEY_KP_4; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KP5]        = GLFW_KEY_KP_5; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KP6]        = GLFW_KEY_KP_6; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KP7]        = GLFW_KEY_KP_7; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KP8]        = GLFW_KEY_KP_8; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KP9]        = GLFW_KEY_KP_9; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KPCOMMA]    = GLFW_KEY_KP_DECIMAL; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KPEQUAL]    = GLFW_KEY_KP_EQUAL; \
    GLFW_XKB_GLOBAL_NAME.keycodes[KEY_KPENTER]    = GLFW_KEY_KP_ENTER; \
\
    for (scancode = 0;  scancode < 256;  scancode++) \
    { \
        if (GLFW_XKB_GLOBAL_NAME.keycodes[scancode] > 0) \
            GLFW_XKB_GLOBAL_NAME.scancodes[GLFW_XKB_GLOBAL_NAME.keycodes[scancode]] = scancode; \
    } \
\
}


#define xkb_glfw_compile_keymap(map_str) { \
    const char* locale = NULL; \
    struct xkb_state* state = NULL;  \
    struct xkb_keymap* keymap = NULL; \
    struct xkb_compose_table* compose_table = NULL;  \
    struct xkb_compose_state* compose_state = NULL;  \
\
    keymap = xkb_keymap_new_from_string(GLFW_XKB_GLOBAL_NAME.context, map_str, XKB_KEYMAP_FORMAT_TEXT_V1, 0); \
    if (!keymap) _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to compile XKB keymap"); \
    else { \
        state = xkb_state_new(keymap); \
        if (!state) { \
            _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to create XKB state"); \
            xkb_keymap_unref(keymap); keymap = NULL; \
        } else { \
            /* Look up the preferred locale, falling back to "C" as default. */ \
            locale = getenv("LC_ALL"); \
            if (!locale) locale = getenv("LC_CTYPE"); \
            if (!locale) locale = getenv("LANG"); \
            if (!locale) locale = "C"; \
            compose_table = xkb_compose_table_new_from_locale(GLFW_XKB_GLOBAL_NAME.context, locale, XKB_COMPOSE_COMPILE_NO_FLAGS); \
            if (!compose_table) { \
                _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to create XKB compose table"); \
                xkb_keymap_unref(keymap); keymap = NULL; \
                xkb_state_unref(state); state = NULL; \
            } else { \
                compose_state = xkb_compose_state_new(compose_table, XKB_COMPOSE_STATE_NO_FLAGS); \
                xkb_compose_table_unref(compose_table); compose_table = NULL; \
                if (!compose_state) { \
                    _glfwInputError(GLFW_PLATFORM_ERROR, "Failed to create XKB compose state"); \
                    xkb_keymap_unref(keymap); keymap = NULL; \
                    xkb_state_unref(state); state = NULL; \
                }\
            } \
        } \
    } \
    if (keymap && state && compose_state) { \
        if (GLFW_XKB_GLOBAL_NAME.composeState) xkb_compose_state_unref(GLFW_XKB_GLOBAL_NAME.composeState); \
        GLFW_XKB_GLOBAL_NAME.composeState = compose_state; \
        if (GLFW_XKB_GLOBAL_NAME.keymap) xkb_keymap_unref(GLFW_XKB_GLOBAL_NAME.keymap); \
        GLFW_XKB_GLOBAL_NAME.keymap = keymap; \
        if (GLFW_XKB_GLOBAL_NAME.state) xkb_state_unref(GLFW_XKB_GLOBAL_NAME.state); \
        GLFW_XKB_GLOBAL_NAME.state = state; \
    }\
    if (GLFW_XKB_GLOBAL_NAME.keymap) { \
        GLFW_XKB_GLOBAL_NAME.controlMask = 1 << xkb_keymap_mod_get_index(GLFW_XKB_GLOBAL_NAME.keymap, "Control"); \
        GLFW_XKB_GLOBAL_NAME.altMask = 1 << xkb_keymap_mod_get_index(GLFW_XKB_GLOBAL_NAME.keymap, "Mod1"); \
        GLFW_XKB_GLOBAL_NAME.shiftMask = 1 << xkb_keymap_mod_get_index(GLFW_XKB_GLOBAL_NAME.keymap, "Shift"); \
        GLFW_XKB_GLOBAL_NAME.superMask = 1 << xkb_keymap_mod_get_index(GLFW_XKB_GLOBAL_NAME.keymap, "Mod4"); \
        GLFW_XKB_GLOBAL_NAME.capsLockMask = 1 << xkb_keymap_mod_get_index(GLFW_XKB_GLOBAL_NAME.keymap, "Lock"); \
        GLFW_XKB_GLOBAL_NAME.numLockMask = 1 << xkb_keymap_mod_get_index(GLFW_XKB_GLOBAL_NAME.keymap, "Mod2"); \
    } \
}


#define xkb_glfw_update_modifiers(depressed, latched, locked, group) {\
    xkb_mod_mask_t mask; \
    unsigned int modifiers = 0; \
    if (!GLFW_XKB_GLOBAL_NAME.keymap) return; \
    xkb_state_update_mask(GLFW_XKB_GLOBAL_NAME.state, depressed, latched, locked, 0, 0, group); \
    mask = xkb_state_serialize_mods(GLFW_XKB_GLOBAL_NAME.state, XKB_STATE_MODS_DEPRESSED | XKB_STATE_LAYOUT_DEPRESSED | XKB_STATE_MODS_LATCHED | XKB_STATE_LAYOUT_LATCHED); \
    if (mask & GLFW_XKB_GLOBAL_NAME.controlMask) modifiers |= GLFW_MOD_CONTROL; \
    if (mask & GLFW_XKB_GLOBAL_NAME.altMask) modifiers |= GLFW_MOD_ALT; \
    if (mask & GLFW_XKB_GLOBAL_NAME.shiftMask) modifiers |= GLFW_MOD_SHIFT; \
    if (mask & GLFW_XKB_GLOBAL_NAME.superMask) modifiers |= GLFW_MOD_SUPER; \
    if (mask & GLFW_XKB_GLOBAL_NAME.capsLockMask) modifiers |= GLFW_MOD_CAPS_LOCK; \
    if (mask & GLFW_XKB_GLOBAL_NAME.numLockMask) modifiers |= GLFW_MOD_NUM_LOCK; \
    GLFW_XKB_GLOBAL_NAME.modifiers = modifiers; \
}


#define xkb_glfw_to_glfw_key_code(key) \
    ((key < sizeof(GLFW_XKB_GLOBAL_NAME.keycodes) / sizeof(GLFW_XKB_GLOBAL_NAME.keycodes[0])) ? GLFW_XKB_GLOBAL_NAME.keycodes[key] : GLFW_KEY_UNKNOWN)
