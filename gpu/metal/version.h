/*
 * version.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

// The version of the Metal Shading Language shaders are compiled to, as
// major * 10 + minor. MSL 2.4 is supported from macOS 12, the minimum
// version of macOS supported by kitty.
#define MSL_VERSION 24
