/*
 * keys.h
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */


#pragma once
#include "data-types.h"
#include "glfw-wrapper.h"
#include <limits.h>

#define KEY_BUFFER_SIZE 128
#define SEND_TEXT_TO_CHILD INT_MIN
#define debug debug_input

int
encode_glfw_key_event(const GLFWkeyevent *e, const bool cursor_key_mode, const unsigned flags, char *output);

bool
is_modifier_key(const uint32_t key);
