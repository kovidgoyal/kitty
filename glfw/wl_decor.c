/*
 * wl_decor.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "wl_decor.h"
#include "internal.h"
#include "libdecor-0/libdecor.h"
#include <dlfcn.h>
#include <string.h>
#include <stdlib.h>

// Boilerplate to dynload libdecor {{{
#define funcs F(libdecor_new); F(libdecor_unref); F(libdecor_get_fd); F(libdecor_dispatch); F(libdecor_decorate); F(libdecor_frame_unref); \
    F(libdecor_frame_set_app_id); F(libdecor_frame_set_title); F(libdecor_frame_set_minimized); F(libdecor_frame_set_fullscreen); \
    F(libdecor_frame_unset_fullscreen); F(libdecor_frame_map); F(libdecor_frame_commit); F(libdecor_frame_set_min_content_size); \
    F(libdecor_frame_set_max_content_size); F(libdecor_frame_set_maximized); F(libdecor_frame_unset_maximized); \
    F(libdecor_frame_set_capabilities); F(libdecor_frame_unset_capabilities); F(libdecor_frame_set_visibility); \
    F(libdecor_frame_get_xdg_toplevel); F(libdecor_configuration_get_content_size); F(libdecor_configuration_get_window_state); \
    F(libdecor_state_new); F(libdecor_state_free);

#define F(name) __typeof__(name) (*name)
static struct {
    void* libdecor_handle;
    funcs
} libdecor_funcs = {0};
#undef F

#define LOAD_FUNC(handle, name) { \
    glfw_dlsym(libdecor_funcs.name, handle, #name); \
    if (!libdecor_funcs.name) { \
        const char* error = dlerror(); \
        _glfwInputError(GLFW_PLATFORM_ERROR, "failed to load libdecor function %s with error: %s", #name, error ? error : "(null)"); \
        dlclose(handle); handle = NULL; return false; \
        memset(&libdecor_funcs, 0, sizeof(libdecor_funcs)); \
    } \
}

static bool
glfw_wl_load_libdecor(void) {
    if (libdecor_funcs.libdecor_handle != NULL) return true;
    const char* libnames[] = {
#ifdef _GLFW_DECOR_LIBRARY
        _GLFW_DECOR_LIBRARY,
#else
        "libdecor-0.so",
        // some installs are missing the .so symlink, so try the full name
        "libdecor-0.so.0",
#endif
        NULL
    };
    for (int i = 0; libnames[i]; i++) {
        libdecor_funcs.libdecor_handle = _glfw_dlopen(libnames[i]);
        if (libdecor_funcs.libdecor_handle) break;
    }
    if (!libdecor_funcs.libdecor_handle) {
        libdecor_funcs.libdecor_handle = _glfw_dlopen(libnames[0]);
        if (!libdecor_funcs.libdecor_handle) {
            _glfwInputError(GLFW_PLATFORM_ERROR, "failed to dlopen %s with error: %s", libnames[0], dlerror());
            return false;
        }
    }
    dlerror();    /* Clear any existing error */

#define F(name) LOAD_FUNC(libdecor_funcs.libdecor_handle, name)
    funcs
#undef F
    return true;
}

#define libdecor_new libdecor_funcs.libdecor_new
#define libdecor_unref libdecor_funcs.libdecor_unref
#define libdecor_get_fd libdecor_funcs.libdecor_get_fd
#define libdecor_dispatch libdecor_funcs.libdecor_dispatch
#define libdecor_decorate libdecor_funcs.libdecor_decorate
#define libdecor_frame_unref libdecor_funcs.libdecor_frame_unref
#define libdecor_frame_set_app_id libdecor_funcs.libdecor_frame_set_app_id
#define libdecor_frame_set_title libdecor_funcs.libdecor_frame_set_title
#define libdecor_frame_set_minimized libdecor_funcs.libdecor_frame_set_minimized
#define libdecor_frame_set_fullscreen libdecor_funcs.libdecor_frame_set_fullscreen
#define libdecor_frame_unset_fullscreen libdecor_funcs.libdecor_frame_unset_fullscreen
#define libdecor_frame_map libdecor_funcs.libdecor_frame_map
#define libdecor_frame_commit libdecor_funcs.libdecor_frame_commit
#define libdecor_frame_set_min_content_size libdecor_funcs.libdecor_frame_set_min_content_size
#define libdecor_frame_set_max_content_size libdecor_funcs.libdecor_frame_set_max_content_size
#define libdecor_frame_set_maximized libdecor_funcs.libdecor_frame_set_maximized
#define libdecor_frame_unset_maximized libdecor_funcs.libdecor_frame_unset_maximized
#define libdecor_frame_set_capabilities libdecor_funcs.libdecor_frame_set_capabilities
#define lilibdecor_frame_set_capabilities libdecor_funcs.lilibdecor_frame_set_capabilities
#define libdecor_frame_set_visibility libdecor_funcs.libdecor_frame_set_visibility
#define libdecor_frame_get_xdg_toplevel libdecor_funcs.libdecor_frame_get_xdg_toplevel
#define libdecor_configuration_get_content_size libdecor_funcs.libdecor_configuration_get_content_size
#define libdecor_configuration_get_window_state libdecor_funcs.libdecor_configuration_get_window_state
#define libdecor_state_new libdecor_funcs.libdecor_state_new
#define libdecor_state_free libdecor_funcs.libdecor_state_free

// }}}

typedef struct DecorLibState {
    struct libdecor* libdecor;
} DecorLibState;

void handle_libdecor_error(struct libdecor* context UNUSED, enum libdecor_error error, const char* message) {
    _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: libdecor error %u: %s", error, message);
}

static struct libdecor_interface libdecor_interface = {
    .error = handle_libdecor_error
};


DECOR_LIB_HANDLE
glfw_wl_load_decorations_library(struct wl_display *display) {
    if (!glfw_wl_load_libdecor()) return NULL;
    DecorLibState *ans = calloc(1, sizeof(DecorLibState));
    if (!ans) { _glfwInputError(GLFW_PLATFORM_ERROR, "Out of memory"); return NULL; }
    ans->libdecor = libdecor_new(display, &libdecor_interface);
    if (!ans->libdecor) _glfwInputError(GLFW_PLATFORM_ERROR, "libdecor_new() returned NULL");
    return (DECOR_LIB_HANDLE) ans;
}

void
glfw_wl_unload_decorations_library(DECOR_LIB_HANDLE h_) {
    if (h_) {
        DecorLibState *h = (DecorLibState*)h_;
        if (h->libdecor) { libdecor_unref(h->libdecor); }
    }
    if (libdecor_funcs.libdecor_handle) {
        dlclose(libdecor_funcs.libdecor_handle); libdecor_funcs.libdecor_handle = NULL;
        memset(&libdecor_funcs, 0, sizeof(libdecor_funcs));
    }
}

int
glfw_wl_dispatch_decor_events(void) {
    // TODO: change this to just call while (g_main_context_iteration(NULL, FALSE)); when using the gtk plugin
    // will require a patch to libdecor. The libdecor API currently has no way to either tell what plugin
    // is being used or to just dispatch non-Wayland events.

    return libdecor_dispatch(((DecorLibState*)_glfw.wl.decor)->libdecor, 0);
}

