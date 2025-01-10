/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

typedef void (*kitty_cleanup_at_exit_func)(void);

typedef enum {
    STATE_CLEANUP_FUNC,
    GLFW_CLEANUP_FUNC,
    DESKTOP_CLEANUP_FUNC,
    CORE_TEXT_CLEANUP_FUNC,
    COCOA_CLEANUP_FUNC,
    PNG_READER_CLEANUP_FUNC,
    FONTCONFIG_CLEANUP_FUNC,
    FREETYPE_CLEANUP_FUNC,
    SYSTEMD_CLEANUP_FUNC,
    SHADERS_CLEANUP_FUNC,

    NUM_CLEANUP_FUNCS
} AtExitCleanupFunc;

void register_at_exit_cleanup_func(AtExitCleanupFunc which, kitty_cleanup_at_exit_func func);
void run_at_exit_cleanup_functions(void);
