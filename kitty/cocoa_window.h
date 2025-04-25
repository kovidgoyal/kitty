/*
 * cocoa_window.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef enum {
    PREFERENCES_WINDOW,
    NEW_OS_WINDOW,
    NEW_OS_WINDOW_WITH_WD,
    NEW_TAB_WITH_WD,
    CLOSE_OS_WINDOW,
    CLOSE_TAB,
    NEW_TAB,
    NEXT_TAB,
    PREVIOUS_TAB,
    DETACH_TAB,
    LAUNCH_URLS,
    NEW_WINDOW,
    CLOSE_WINDOW,
    RESET_TERMINAL,
    CLEAR_TERMINAL_AND_SCROLLBACK,
    CLEAR_SCROLLBACK,
    CLEAR_SCREEN,
    RELOAD_CONFIG,
    TOGGLE_MACOS_SECURE_KEYBOARD_ENTRY,
    TOGGLE_FULLSCREEN,
    OPEN_KITTY_WEBSITE,
    HIDE,
    HIDE_OTHERS,
    MINIMIZE,
    QUIT,
    USER_MENU_ACTION,
    COCOA_NOTIFICATION_UNTRACKED,

    NUM_COCOA_PENDING_ACTIONS
} CocoaPendingAction;

void cocoa_focus_window(void *w);
long cocoa_window_number(void *w);
void cocoa_application_lifecycle_event(bool);
void cocoa_recreate_global_menu(void);
void cocoa_system_beep(const char*);
void cocoa_set_activation_policy(bool);
bool cocoa_alt_option_key_pressed(unsigned long);
void cocoa_toggle_secure_keyboard_entry(void);
void cocoa_hide(void);
void cocoa_clear_global_shortcuts(void);
void cocoa_hide_others(void);
void cocoa_minimize(void *w);
void cocoa_set_uncaught_exception_handler(void);
void cocoa_update_menu_bar_title(PyObject*);
size_t cocoa_get_workspace_ids(void *w, size_t *workspace_ids, size_t array_sz);
monotonic_t cocoa_cursor_blink_interval(void);
bool cocoa_render_line_of_text(const char *text, const color_type fg, const color_type bg, uint8_t *rgba_output, const size_t width, const size_t height);
extern uint8_t* render_single_ascii_char_as_mask(const char ch, size_t *result_width, size_t *result_height);
void get_cocoa_key_equivalent(uint32_t, int, char *key, size_t key_sz, int*);
void set_cocoa_pending_action(CocoaPendingAction action, const char*);
void cocoa_report_live_notifications(const char* ident);
