/*
 * version.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

// The version of the Metal Shading Language shaders are compiled to, as
// major * 10 + minor. MSL 3.1 is the version supported by macOS 14, the
// minimum macOS version required by kitty.
#define MSL_VERSION 31
