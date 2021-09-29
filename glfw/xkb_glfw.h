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

#pragma once

#include <xkbcommon/xkbcommon.h>
#include <xkbcommon/xkbcommon-compose.h>
#ifdef _GLFW_X11
#include <xkbcommon/xkbcommon-x11.h>
#endif

#include "ibus_glfw.h"

typedef struct {
    struct xkb_state*       state;
    struct xkb_state*       clean_state;
    struct xkb_state*       default_state;
    struct xkb_compose_state* composeState;
    xkb_mod_mask_t          activeUnknownModifiers;
    unsigned int            modifiers;
} XKBStateGroup;


typedef struct {
    struct xkb_context*     context;
    struct xkb_keymap*      keymap;
    struct xkb_keymap*      default_keymap;
    XKBStateGroup           states;

    xkb_mod_index_t         controlIdx;
    xkb_mod_index_t         altIdx;
    xkb_mod_index_t         shiftIdx;
    xkb_mod_index_t         superIdx;
    xkb_mod_index_t         hyperIdx;
    xkb_mod_index_t         metaIdx;
    xkb_mod_index_t         capsLockIdx;
    xkb_mod_index_t         numLockIdx;
    xkb_mod_mask_t          controlMask;
    xkb_mod_mask_t          altMask;
    xkb_mod_mask_t          shiftMask;
    xkb_mod_mask_t          superMask;
    xkb_mod_mask_t          hyperMask;
    xkb_mod_mask_t          metaMask;
    xkb_mod_mask_t          capsLockMask;
    xkb_mod_mask_t          numLockMask;
    xkb_mod_index_t         unknownModifiers[256];
    _GLFWIBUSData           ibus;

#ifdef _GLFW_X11
    int32_t                 keyboard_device_id;
    bool                    available;
    bool                    detectable;
    int                     majorOpcode;
    int                     eventBase;
    int                     errorBase;
    int                     major;
    int                     minor;
#endif

} _GLFWXKBData;

#ifdef _GLFW_X11
bool glfw_xkb_set_x11_events_mask(void);
bool glfw_xkb_update_x11_keyboard_id(_GLFWXKBData *xkb);
#endif

void glfw_xkb_release(_GLFWXKBData *xkb);
bool glfw_xkb_create_context(_GLFWXKBData *xkb);
bool glfw_xkb_compile_keymap(_GLFWXKBData *xkb, const char *map_str);
void glfw_xkb_update_modifiers(_GLFWXKBData *xkb, xkb_mod_mask_t depressed, xkb_mod_mask_t latched, xkb_mod_mask_t locked, xkb_layout_index_t base_group, xkb_layout_index_t latched_group, xkb_layout_index_t locked_group);
bool glfw_xkb_should_repeat(_GLFWXKBData *xkb, xkb_keycode_t keycode);
const char* glfw_xkb_keysym_name(xkb_keysym_t sym);
xkb_keysym_t glfw_xkb_sym_for_key(uint32_t key);
void glfw_xkb_handle_key_event(_GLFWwindow *window, _GLFWXKBData *xkb, xkb_keycode_t keycode, int action);
int glfw_xkb_keysym_from_name(const char *name, bool case_sensitive);
void glfw_xkb_update_ime_state(_GLFWwindow *w, _GLFWXKBData *xkb, const GLFWIMEUpdateEvent *ev);
void glfw_xkb_key_from_ime(_GLFWIBUSKeyEvent *ev, bool handled_by_ime, bool failed);
void glfw_xkb_forwarded_key_from_ime(xkb_keysym_t keysym, unsigned int glfw_mods);
