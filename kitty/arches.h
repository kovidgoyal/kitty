/*
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once


#ifdef __aarch64__
#define KITTY_TARGET_CPU_IS_ARM64
#define KITTY_128BIT_ALLOWED
#define KITTY_256BIT_ALLOWED
#elif defined(__i386__) || defined(__i486__) || defined(__i586__) || defined(__i686__)
#define KITTY_TARGET_CPU_IS_X86
#define KITTY_128BIT_ALLOWED
#elif defined(__amd64__)
#define KITTY_TARGET_CPU_IS_AMD64
#define KITTY_128BIT_ALLOWED
#define KITTY_256BIT_ALLOWED
#endif

#if defined(__clang__) && defined(KITTY_128BIT_ALLOWED)
#define KITTY_START_128BIT_CODE
#elif defined(KITTY_128BIT_ALLOWED)
#define KITTY_START_128BIT_CODE
#else
#define KITTY_START_128BIT_CODE
#endif
