/*
 * platform.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// The interface between the OpenGL driver and the code that creates OpenGL
// contexts for native windows using a platform specific API: GLX on X11, EGL
// on Wayland and NSGL on macOS.

#pragma once

#include "../api.h"
#include <stdarg.h>

typedef void (*gl_proc)(void);

// Callbacks into the driver for error reporting
typedef struct GLPlatformHost {
    // Record an error, retrievable with last_error()
    void (*set_error)(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
    // Report a non-fatal problem to the user
    void (*log_error)(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
    // Print debug output, only if debug rendering is enabled
    void (*debug)(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
    // X11: Capture X errors, see x11_push_error_trap() in GPUDriverInitParams
    void (*x11_push_error_trap)(void);
    int (*x11_pop_error_trap)(void);
} GLPlatformHost;

// A platform specific OpenGL context together with the drawable it renders to.
// Every context created by a platform shares objects with all other contexts
// created by that platform.
typedef struct GLSurface GLSurface;

typedef struct GLPlatform {
    const char *name;
    bool (*choose_native_visual)(const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint64_t *visual_id);
    GLSurface *(*surface_create)(const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint32_t width, uint32_t height);
    void (*surface_destroy)(GLSurface *s);
    // NULL to make no context current
    bool (*make_current)(GLSurface *s);
    void (*surface_resize)(GLSurface *s, uint32_t width, uint32_t height);
    bool (*present)(GLSurface *s);
    void (*set_swap_interval)(GLSurface *s, int interval);
    void (*native_changed)(GLSurface *s);
    bool (*recreate)(GLSurface *s);
    // Must be called with a current context
    gl_proc (*get_proc_address)(const char *name);
    // Release all resources, all surfaces must have been destroyed
    void (*terminate)(void);
} GLPlatform;

#ifdef __APPLE__
const GLPlatform *nsgl_platform(const GLPlatformHost *host);
#else
const GLPlatform *glx_platform(const GLPlatformHost *host);
const GLPlatform *egl_platform(const GLPlatformHost *host);
#endif

// Returns true if the space separated list of extension names contains name
bool gl_extension_in_string(const char *name, const char *extensions);
