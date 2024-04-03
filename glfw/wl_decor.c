/*
 * wl_decor.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define _POSIX_C_SOURCE  200809L
#include "wl_decor.h"
#include "wl_client_side_decorations.h"
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

static DECOR_LIB_HANDLE
glfw_wl_load_decorations_library_(struct wl_display *display) {
    if (!glfw_wl_load_libdecor()) return NULL;
    DecorLibState *ans = calloc(1, sizeof(DecorLibState));
    if (!ans) { _glfwInputError(GLFW_PLATFORM_ERROR, "Out of memory"); return NULL; }
    ans->libdecor = libdecor_new(display, &libdecor_interface);
    if (!ans->libdecor) _glfwInputError(GLFW_PLATFORM_ERROR, "libdecor_new() returned NULL");
    return (DECOR_LIB_HANDLE) ans;
}

DECOR_LIB_HANDLE
glfw_wl_load_decorations_library(struct wl_display *display) {
    // See https://gitlab.freedesktop.org/libdecor/libdecor/-/issues/65 for why we need this nautanki with GDK_BACKEND
    char *gdk_backend = getenv("GDK_BACKEND");
    if (gdk_backend && strcmp(gdk_backend, "wayland") != 0) {
        gdk_backend = strdup(gdk_backend);
        setenv("GDK_BACKEND", "wayland", 1);
    }
    DECOR_LIB_HANDLE ans = glfw_wl_load_decorations_library_(display);
    if (gdk_backend) {
        setenv("GDK_BACKEND", gdk_backend, 1);
        free(gdk_backend);
    }
    return ans;
}

void
glfw_wl_unload_decorations_library(DECOR_LIB_HANDLE h_) {
    if (h_) {
        DecorLibState *h = (DecorLibState*)h_;
        if (h->libdecor) { libdecor_unref(h->libdecor); }
        free(h);
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
    // https://gitlab.freedesktop.org/libdecor/libdecor/-/issues/70

    return libdecor_dispatch(((DecorLibState*)_glfw.wl.decor)->libdecor, 0);
}

typedef struct Frame {
    struct libdecor_frame *libdecor;
} Frame;


void
glfw_wl_set_fullscreen(_GLFWwindow *w, bool on, struct wl_output *monitor) {
    Frame *d = (Frame*)w->wl.frame;
    if (d && d->libdecor) {
        if (on) libdecor_frame_set_fullscreen(d->libdecor, monitor);
        else libdecor_frame_unset_fullscreen(d->libdecor);
    } else if (w->wl.xdg.toplevel) {
        if (on) {
            xdg_toplevel_set_fullscreen(w->wl.xdg.toplevel, monitor);
            if (!w->wl.decorations.serverSide) free_csd_surfaces(w);
        } else {
            xdg_toplevel_unset_fullscreen(w->wl.xdg.toplevel);
            ensure_csd_resources(w);
        }
    }
}

void
glfw_wl_set_maximized(_GLFWwindow *w, bool on) {
    Frame *d = (Frame*)w->wl.frame;
    if (d && d->libdecor) {
        if (on) libdecor_frame_set_maximized(d->libdecor);
        else libdecor_frame_unset_maximized(d->libdecor);
    } else if (w->wl.xdg.toplevel) {
        if (on) xdg_toplevel_set_maximized(w->wl.xdg.toplevel);
        else xdg_toplevel_unset_maximized(w->wl.xdg.toplevel);
    }
}

void
glfw_wl_set_minimized(_GLFWwindow *w) {
    Frame *d = (Frame*)w->wl.frame;
    if (d && d->libdecor) libdecor_frame_set_minimized(d->libdecor);
    else if (w->wl.xdg.toplevel) xdg_toplevel_set_minimized(w->wl.xdg.toplevel);
}

void
glfw_wl_set_title(_GLFWwindow *w, const char *title) {
    // Wayland cannot handle requests larger than ~8200 bytes. Sending
    // one causes an abort(). Since titles this large are meaningless anyway
    // ensure they do not happen.
    if (!title) title = "";
    char *safe_title = utf_8_strndup(title, 2048);
    if (!safe_title) return;
    if (w->wl.title && strcmp(w->wl.title, safe_title) == 0) { free(safe_title); return; }
    free(w->wl.title); w->wl.title = safe_title;
    Frame *d = (Frame*)w->wl.frame;
    if (d && d->libdecor) libdecor_frame_set_title(d->libdecor, w->wl.title);
    else if (w->wl.xdg.toplevel) {
        xdg_toplevel_set_title(w->wl.xdg.toplevel, w->wl.title);
        change_csd_title(w);
    }
}

void
glfw_wl_set_app_id(_GLFWwindow *w, const char *appid) {
    if (!appid || !appid[0]) return;
    Frame *d = (Frame*)w->wl.frame;
    if (d && d->libdecor) libdecor_frame_set_app_id(d->libdecor, appid);
    else if (w->wl.xdg.toplevel) xdg_toplevel_set_app_id(w->wl.xdg.toplevel, appid);
}
