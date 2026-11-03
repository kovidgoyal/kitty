/*
 * version.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

// Required minimum Vulkan version
#define VULKAN_REQUIRED_VERSION_MAJOR 1
#define VULKAN_REQUIRED_VERSION_MINOR 3
// The SPIR-V version shaders are compiled to, as major * 10 + minor. Vulkan
// 1.3 guarantees support for SPIR-V 1.6.
#define SPIRV_VERSION 16
