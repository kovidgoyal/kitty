//========================================================================
// GLFW 3.4 Wayland - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2014 Jonas Ådahl <jadahl@gmail.com>
//
// This software is provided 'as-is', without any express or implied
// warranty. In no event will the authors be held liable for any damages
// arising from the use of this software.
//
// Permission is granted to anyone to use this software for any purpose,
// including commercial applications, and to alter it and redistribute it
// freely, subject to the following restrictions:
//
// 1. The origin of this software must not be misrepresented; you must not
//    claim that you wrote the original software. If you use this software
//    in a product, an acknowledgment in the product documentation would
//    be appreciated but is not required.
//
// 2. Altered source versions must be plainly marked as such, and must not
//    be misrepresented as being the original software.
//
// 3. This notice may not be removed or altered from any source
//    distribution.
//
//========================================================================
// It is fine to use C99 in this file because it will not be built with VS
//========================================================================

#define _GNU_SOURCE

#include "internal.h"
#include "backend_utils.h"
#include "linux_notify.h"
#include "wl_client_side_decorations.h"
#include "../kitty/monotonic.h"

#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>
#include <sys/mman.h>

#define debug debug_rendering

static bool
is_layer_shell(_GLFWwindow *window) { return window->wl.layer_shell.config.type != GLFW_LAYER_SHELL_NONE; }

static void
inhibit_shortcuts_for(_GLFWwindow *window, bool inhibit) {
    if (inhibit) {
        if (window->wl.keyboard_shortcuts_inhibitor) return;
        window->wl.keyboard_shortcuts_inhibitor = zwp_keyboard_shortcuts_inhibit_manager_v1_inhibit_shortcuts(_glfw.wl.keyboard_shortcuts_inhibit_manager, window->wl.surface, _glfw.wl.seat);
    } else {
        if (!window->wl.keyboard_shortcuts_inhibitor) return;
        zwp_keyboard_shortcuts_inhibitor_v1_destroy(window->wl.keyboard_shortcuts_inhibitor);
        window->wl.keyboard_shortcuts_inhibitor = NULL;
    }
}

static void
activation_token_done(void *data, struct xdg_activation_token_v1 *xdg_token, const char *token) {
    for (size_t i = 0; i < _glfw.wl.activation_requests.sz; i++) {
        glfw_wl_xdg_activation_request *r = _glfw.wl.activation_requests.array + i;
        if (r->request_id == (uintptr_t)data) {
            _GLFWwindow *window = _glfwWindowForId(r->window_id);
            if (r->callback) r->callback((GLFWwindow*)window, token, r->callback_data);
            remove_i_from_array(_glfw.wl.activation_requests.array, i, _glfw.wl.activation_requests.sz);
            break;
        }
    }
    xdg_activation_token_v1_destroy(xdg_token);
}


static const struct
xdg_activation_token_v1_listener activation_token_listener = {
    .done = &activation_token_done,
};


static bool
get_activation_token(
    _GLFWwindow *window, uint32_t serial, GLFWactivationcallback cb, void *cb_data
) {
#define fail(msg) { _glfwInputError(GLFW_PLATFORM_ERROR, msg); if (cb) cb((GLFWwindow*)window, NULL, cb_data); return false; }
    if (_glfw.wl.xdg_activation_v1 == NULL) fail("Wayland: activation requests not supported by this Wayland compositor");
    struct xdg_activation_token_v1 *token = xdg_activation_v1_get_activation_token(_glfw.wl.xdg_activation_v1);
    if (token == NULL) fail("Wayland: failed to create activation request token");
    if (_glfw.wl.activation_requests.capacity < _glfw.wl.activation_requests.sz + 1) {
        _glfw.wl.activation_requests.capacity = MAX(64u, _glfw.wl.activation_requests.capacity * 2);
        _glfw.wl.activation_requests.array = realloc(_glfw.wl.activation_requests.array, _glfw.wl.activation_requests.capacity * sizeof(_glfw.wl.activation_requests.array[0]));
        if (!_glfw.wl.activation_requests.array) {
            _glfw.wl.activation_requests.capacity = 0;
            fail("Wayland: Out of memory while allocation activation request");
        }
    }
    glfw_wl_xdg_activation_request *r = _glfw.wl.activation_requests.array + _glfw.wl.activation_requests.sz++;
    memset(r, 0, sizeof(*r));
    static uintptr_t rq = 0;
    r->window_id = window->id;
    r->callback = cb; r->callback_data = cb_data;
    r->request_id = ++rq; r->token = token;
    if (serial != 0)
        xdg_activation_token_v1_set_serial(token, serial, _glfw.wl.seat);

    xdg_activation_token_v1_set_surface(token, window->wl.surface);
    xdg_activation_token_v1_add_listener(token, &activation_token_listener, (void*)r->request_id);
    xdg_activation_token_v1_commit(token);
    return true;
#undef fail
}

static void
convert_glfw_image_to_wayland_image(const GLFWimage* image, unsigned char *target) {
    // convert RGBA non-premultiplied to ARGB pre-multiplied
    unsigned char* source = (unsigned char*) image->pixels;
    for (int i = 0;  i < image->width * image->height;  i++, source += 4) {
        unsigned int alpha = source[3];
        *target++ = (unsigned char) ((source[2] * alpha) / 255);
        *target++ = (unsigned char) ((source[1] * alpha) / 255);
        *target++ = (unsigned char) ((source[0] * alpha) / 255);
        *target++ = (unsigned char) alpha;
    }
}

static struct wl_buffer* createShmBuffer(const GLFWimage* image, bool is_opaque, bool init_data)
{
    struct wl_shm_pool* pool;
    struct wl_buffer* buffer;
    int stride = image->width * 4;
    int length = image->width * image->height * 4;
    void* data;
    int fd;

    fd = createAnonymousFile(length);
    if (fd < 0)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Creating a buffer file for %d B failed: %s",
                        length, strerror(errno));
        return NULL;
    }

    data = mmap(NULL, length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (data == MAP_FAILED)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: mmap failed: %s", strerror(errno));
        close(fd);
        return NULL;
    }

    pool = wl_shm_create_pool(_glfw.wl.shm, fd, length);

    close(fd);
    if (init_data) convert_glfw_image_to_wayland_image(image, data);

    buffer =
        wl_shm_pool_create_buffer(pool, 0,
                                  image->width,
                                  image->height,
                                  stride, is_opaque ? WL_SHM_FORMAT_XRGB8888 : WL_SHM_FORMAT_ARGB8888);
    munmap(data, length);
    wl_shm_pool_destroy(pool);

    return buffer;
}

wayland_cursor_shape
glfw_cursor_shape_to_wayland_cursor_shape(GLFWCursorShape g) {
    wayland_cursor_shape ans = {-1, ""};
#define C(g, w) case g: ans.which = w; ans.name = #w; return ans;
    switch(g) {
        /* start glfw to wayland mapping (auto generated by gen-key-constants.py do not edit) */
        C(GLFW_DEFAULT_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_DEFAULT);
        C(GLFW_TEXT_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_TEXT);
        C(GLFW_POINTER_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_POINTER);
        C(GLFW_HELP_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_HELP);
        C(GLFW_WAIT_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_WAIT);
        C(GLFW_PROGRESS_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_PROGRESS);
        C(GLFW_CROSSHAIR_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_CROSSHAIR);
        C(GLFW_CELL_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_CELL);
        C(GLFW_VERTICAL_TEXT_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_VERTICAL_TEXT);
        C(GLFW_MOVE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_MOVE);
        C(GLFW_E_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_E_RESIZE);
        C(GLFW_NE_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_NE_RESIZE);
        C(GLFW_NW_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_NW_RESIZE);
        C(GLFW_N_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_N_RESIZE);
        C(GLFW_SE_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_SE_RESIZE);
        C(GLFW_SW_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_SW_RESIZE);
        C(GLFW_S_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_S_RESIZE);
        C(GLFW_W_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_W_RESIZE);
        C(GLFW_EW_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_EW_RESIZE);
        C(GLFW_NS_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_NS_RESIZE);
        C(GLFW_NESW_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_NESW_RESIZE);
        C(GLFW_NWSE_RESIZE_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_NWSE_RESIZE);
        C(GLFW_ZOOM_IN_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_ZOOM_IN);
        C(GLFW_ZOOM_OUT_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_ZOOM_OUT);
        C(GLFW_ALIAS_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_ALIAS);
        C(GLFW_COPY_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_COPY);
        C(GLFW_NOT_ALLOWED_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_NOT_ALLOWED);
        C(GLFW_NO_DROP_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_NO_DROP);
        C(GLFW_GRAB_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_GRAB);
        C(GLFW_GRABBING_CURSOR, WP_CURSOR_SHAPE_DEVICE_V1_SHAPE_GRABBING);
/* end glfw to wayland mapping */
        default: return ans;
    }
#undef C
}

static void
commit_window_surface(_GLFWwindow *window) {
    // debug("Window %llu surface committed\n", window->id); dont log as every frame request causes a surface commit
    wl_surface_commit(window->wl.surface);
}

static void
commit_window_surface_if_safe(_GLFWwindow *window) {
    // we only commit if the buffer attached to the surface is the correct size,
    // which means that at least one frame is drawn after resizeFramebuffer()
    if (!window->wl.waiting_for_swap_to_commit) commit_window_surface(window);
}

static void
set_cursor_surface(struct wl_surface *surface, int hotspot_x, int hotspot_y, const char *from_where) {
    debug("Calling wl_pointer_set_cursor in %s with surface: %p and serial: %u\n", from_where, (void*)surface, _glfw.wl.pointer_enter_serial);
    wl_pointer_set_cursor(_glfw.wl.pointer, _glfw.wl.pointer_enter_serial, surface, hotspot_x, hotspot_y);
}

static void
setCursorImage(_GLFWwindow* window, bool on_theme_change) {
    _GLFWcursorWayland defaultCursor = {.shape = GLFW_DEFAULT_CURSOR};
    _GLFWcursorWayland* cursorWayland = window->cursor ? &window->cursor->wl : &defaultCursor;
    if (_glfw.wl.wp_cursor_shape_device_v1) {
        wayland_cursor_shape s = glfw_cursor_shape_to_wayland_cursor_shape(cursorWayland->shape);
        if (s.which > -1) {
            debug("Changing cursor shape to: %s with serial: %u\n", s.name, _glfw.wl.pointer_enter_serial);
            wp_cursor_shape_device_v1_set_shape(_glfw.wl.wp_cursor_shape_device_v1, _glfw.wl.pointer_enter_serial, (uint32_t)s.which);
            return;
        }
    }
    struct wl_cursor_image* image = NULL;
    struct wl_buffer* buffer = NULL;
    struct wl_surface* surface = _glfw.wl.cursorSurface;
    const int scale = _glfwWaylandIntegerWindowScale(window);
    if (!_glfw.wl.pointer) return;

    if (cursorWayland->scale < 0) {
        buffer = cursorWayland->buffer;
        toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, 0);
    } else {
        if (on_theme_change || cursorWayland->scale != scale) {
            struct wl_cursor *newCursor = NULL;
            struct wl_cursor_theme *theme = glfw_wlc_theme_for_scale(scale);
            if (theme) newCursor = _glfwLoadCursor(cursorWayland->shape, theme);
            if (newCursor != NULL) {
                cursorWayland->cursor = newCursor;
                cursorWayland->scale = scale;
                cursorWayland->currentImage = 0;
            } else {
                _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: late cursor load failed; proceeding with existing cursor");
            }
        }
        if (!cursorWayland->cursor || !cursorWayland->cursor->image_count || !cursorWayland->cursor->images) return;
        if (cursorWayland->currentImage >= cursorWayland->cursor->image_count) cursorWayland->currentImage = 0;
        image = cursorWayland->cursor->images[cursorWayland->currentImage];
        if (!image) image = cursorWayland->cursor->images[0];
        if (!image) return;
        buffer = wl_cursor_image_get_buffer(image);
        if (image->delay && window->cursor) {
            changeTimerInterval(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, ms_to_monotonic_t(image->delay));
            toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, 1);
        } else {
            toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, 0);
        }

        if (!buffer)
            return;

        cursorWayland->width = image->width;
        cursorWayland->height = image->height;
        cursorWayland->xhot = image->hotspot_x;
        cursorWayland->yhot = image->hotspot_y;
    }

    set_cursor_surface(surface, cursorWayland->xhot / scale, cursorWayland->yhot / scale, "setCursorImage");
    wl_surface_set_buffer_scale(surface, scale);
    wl_surface_attach(surface, buffer, 0, 0);
    wl_surface_damage(surface, 0, 0,
                      cursorWayland->width, cursorWayland->height);
    wl_surface_commit(surface);
}


static bool
checkScaleChange(_GLFWwindow* window) {
    if (window->wl.expect_scale_from_compositor) return false;
    unsigned int scale = 1, monitorScale;
    int i;

    // Check if we will be able to set the buffer scale or not.
    if (_glfw.wl.compositorVersion < 3)
        return false;

    // Get the scale factor from the highest scale monitor that this window is on
    for (i = 0; i < window->wl.monitorsCount; ++i)
    {
        monitorScale = window->wl.monitors[i]->wl.scale;
        if (scale < monitorScale)
            scale = monitorScale;
    }
    if (window->wl.monitorsCount < 1 && _glfw.monitorCount > 0) {
        // The window has not yet been assigned to any monitors, use the primary monitor
        _GLFWmonitor *m = _glfw.monitors[0];
        if (m && m->wl.scale > (int)scale) scale = m->wl.scale;
    }

    // Only change the framebuffer size if the scale changed.
    if (scale != window->wl.integer_scale.deduced && !window->wl.fractional_scale)
    {
        window->wl.integer_scale.deduced = scale;
        setCursorImage(window, false);
        return true;
    }
    if (window->wl.monitorsCount > 0 && !window->wl.initial_scale_notified) {
        window->wl.initial_scale_notified = true;
        return true;
    }
    return false;
}

static void
update_regions(_GLFWwindow* window) {
    if (!window->wl.transparent) {
        struct wl_region* region = wl_compositor_create_region(_glfw.wl.compositor);
        if (!region) return;
        wl_region_add(region, 0, 0, window->wl.width, window->wl.height);
        // Makes the surface considered as XRGB instead of ARGB.
        wl_surface_set_opaque_region(window->wl.surface, region);
        wl_region_destroy(region);
    }
    // Set blur region
    if (_glfw.wl.org_kde_kwin_blur_manager) {
        if (window->wl.has_blur) {
            if (!window->wl.org_kde_kwin_blur)
                window->wl.org_kde_kwin_blur = org_kde_kwin_blur_manager_create(_glfw.wl.org_kde_kwin_blur_manager, window->wl.surface);
            if (window->wl.org_kde_kwin_blur) {
                // NULL means entire window
                org_kde_kwin_blur_set_region(window->wl.org_kde_kwin_blur, NULL);
                org_kde_kwin_blur_commit(window->wl.org_kde_kwin_blur);
            }
        } else {
            org_kde_kwin_blur_manager_unset(_glfw.wl.org_kde_kwin_blur_manager, window->wl.surface);
            if (window->wl.org_kde_kwin_blur) { org_kde_kwin_blur_release(window->wl.org_kde_kwin_blur); window->wl.org_kde_kwin_blur = NULL; }
        }
    }

}

int
_glfwWaylandIntegerWindowScale(_GLFWwindow *window) {
    int ans = (window->wl.integer_scale.preferred) ? window->wl.integer_scale.preferred : window->wl.integer_scale.deduced;
    if (ans < 1) ans = 1;
    return ans;
}

double
_glfwWaylandWindowScale(_GLFWwindow *window) {
    double ans = _glfwWaylandIntegerWindowScale(window);
    if (window->wl.fractional_scale) ans = window->wl.fractional_scale / 120.;
    return ans;
}

static void
wait_for_swap_to_commit(_GLFWwindow *window) {
    window->wl.waiting_for_swap_to_commit = true;
    debug("Waiting for swap to commit Wayland surface for window: %llu\n", window->id);
}

static void
resizeFramebuffer(_GLFWwindow* window) {
    GLFWwindow *ctx = glfwGetCurrentContext();
    bool ctx_changed = false;
    if (ctx != (GLFWwindow*)window && window->context.client != GLFW_NO_API) { ctx_changed = true;  glfwMakeContextCurrent((GLFWwindow*)window); }
    double scale = _glfwWaylandWindowScale(window);
    int scaled_width = (int)round(window->wl.width * scale);
    int scaled_height = (int)round(window->wl.height * scale);
    debug("Resizing framebuffer of window: %llu to: %dx%d window size: %dx%d at scale: %.3f\n",
            window->id, scaled_width, scaled_height, window->wl.width, window->wl.height, scale);
    wl_egl_window_resize(window->wl.native, scaled_width, scaled_height, 0, 0);
    update_regions(window);
    wait_for_swap_to_commit(window);
    if (ctx_changed) glfwMakeContextCurrent(ctx);
    _glfwInputFramebufferSize(window, scaled_width, scaled_height);
}

void
_glfwWaylandAfterBufferSwap(_GLFWwindow* window) {
    if (window->wl.temp_buffer_used_during_window_creation) {
        wl_buffer_destroy(window->wl.temp_buffer_used_during_window_creation);
        window->wl.temp_buffer_used_during_window_creation = NULL;
    }
    if (window->wl.waiting_for_swap_to_commit) {
        debug("Window %llu swapped committing surface\n", window->id);
        window->wl.waiting_for_swap_to_commit = false;
        // this is not really needed, since I think eglSwapBuffers() calls wl_surface_commit()
        // but lets be safe. See https://gitlab.freedesktop.org/mesa/mesa/-/blob/main/src/egl/drivers/dri2/platform_wayland.c#L1510
        commit_window_surface(window);
    }
}

static const char*
clipboard_mime(void) {
    static char buf[128] = {0};
    if (buf[0] == 0) {
        snprintf(buf, sizeof(buf), "application/glfw+clipboard-%d", getpid());
    }
    return buf;
}

static void
apply_scale_changes(_GLFWwindow *window, bool resize_framebuffer, bool update_csd) {
    double scale = _glfwWaylandWindowScale(window);
    if (resize_framebuffer) resizeFramebuffer(window);
    _glfwInputWindowContentScale(window, (float)scale, (float)scale);
    if (update_csd) csd_set_visible(window, csd_should_window_be_decorated(window));  // resize the csd iff the window currently has CSD
    int buffer_scale = window->wl.fractional_scale ? 1 : (int)scale;
    wl_surface_set_buffer_scale(window->wl.surface, buffer_scale);
}

static bool
dispatchChangesAfterConfigure(_GLFWwindow *window, int32_t width, int32_t height) {
    bool size_changed = width != window->wl.width || height != window->wl.height;
    bool scale_changed = checkScaleChange(window);

    if (size_changed) {
        _glfwInputWindowSize(window, width, height);
        window->wl.width = width; window->wl.height = height;
        resizeFramebuffer(window);
    }

    if (scale_changed) {
        debug("Scale changed to %.3f in dispatchChangesAfterConfigure for window: %llu\n", _glfwWaylandWindowScale(window), window->id);
        apply_scale_changes(window, !size_changed, false);
    }

    _glfwInputWindowDamage(window);

    return size_changed || scale_changed;
}

static void
inform_compositor_of_window_geometry(_GLFWwindow *window, const char *event) {
#define geometry window->wl.decorations.geometry
    debug("Setting window %llu \"visible area\" geometry in %s event: x=%d y=%d %dx%d viewport: %dx%d\n",
            window->id, event, geometry.x, geometry.y, geometry.width, geometry.height, window->wl.width, window->wl.height);
    xdg_surface_set_window_geometry(window->wl.xdg.surface, geometry.x, geometry.y, geometry.width, geometry.height);
    if (window->wl.wp_viewport) wp_viewport_set_destination(window->wl.wp_viewport, window->wl.width, window->wl.height);
#undef geometry
}


static void
xdgDecorationHandleConfigure(void* data,
                                         struct zxdg_toplevel_decoration_v1* decoration UNUSED,
                                         uint32_t mode)
{
    _GLFWwindow* window = data;
    window->wl.pending.decoration_mode = mode;
    window->wl.pending_state |= PENDING_STATE_DECORATION;
    debug("XDG decoration configure event received for window %llu: has_server_side_decorations: %d\n", window->id, (mode == ZXDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE));
}

static const struct zxdg_toplevel_decoration_v1_listener xdgDecorationListener = {
    xdgDecorationHandleConfigure,
};

static void surfaceHandleEnter(void *data,
                               struct wl_surface *surface UNUSED,
                               struct wl_output *output)
{
    _GLFWwindow* window = data;
    _GLFWmonitor* monitor = wl_output_get_user_data(output);

    if (window->wl.monitorsCount + 1 > window->wl.monitorsSize)
    {
        ++window->wl.monitorsSize;
        window->wl.monitors =
            realloc(window->wl.monitors,
                    window->wl.monitorsSize * sizeof(_GLFWmonitor*));
    }

    window->wl.monitors[window->wl.monitorsCount++] = monitor;

    if (checkScaleChange(window)) {
        debug("Scale changed to %.3f for window %llu in surfaceHandleEnter\n", _glfwWaylandWindowScale(window), window->id);
        apply_scale_changes(window, true, true);
    }
}

static void surfaceHandleLeave(void *data,
                               struct wl_surface *surface UNUSED,
                               struct wl_output *output)
{
    _GLFWwindow* window = data;
    _GLFWmonitor* monitor = wl_output_get_user_data(output);
    bool found;
    int i;

    for (i = 0, found = false; i < window->wl.monitorsCount - 1; ++i)
    {
        if (monitor == window->wl.monitors[i])
            found = true;
        if (found)
            window->wl.monitors[i] = window->wl.monitors[i + 1];
    }
    window->wl.monitors[--window->wl.monitorsCount] = NULL;

    if (checkScaleChange(window)) {
        debug("Scale changed to %.3f for window %llu in surfaceHandleLeave\n", _glfwWaylandWindowScale(window), window->id);
        apply_scale_changes(window, true, true);
    }
}

#ifdef WL_SURFACE_PREFERRED_BUFFER_SCALE_SINCE_VERSION
static void
surface_preferred_buffer_scale(void *data, struct wl_surface *surface UNUSED, int32_t scale) {
    _GLFWwindow* window = data;
    window->wl.once.preferred_scale_received = true;
    if ((int)window->wl.integer_scale.preferred == scale && window->wl.window_fully_created) return;
    debug("Preferred integer buffer scale changed to: %d for window %llu\n", scale, window->id);
    window->wl.integer_scale.preferred = scale;
    window->wl.window_fully_created = window->wl.once.surface_configured;
    if (!window->wl.fractional_scale) apply_scale_changes(window, true, true);
}

static void
surface_preferred_buffer_transform(void *data, struct wl_surface *surface, uint32_t transform) {
    (void)data; (void)surface; (void)transform;
}
#endif


static const struct wl_surface_listener surfaceListener = {
    .enter = surfaceHandleEnter,
    .leave = surfaceHandleLeave,
#ifdef WL_SURFACE_PREFERRED_BUFFER_SCALE_SINCE_VERSION
    .preferred_buffer_scale = &surface_preferred_buffer_scale,
    .preferred_buffer_transform = &surface_preferred_buffer_transform,
#endif
};

static void
fractional_scale_preferred_scale(void *data, struct wp_fractional_scale_v1 *wp_fractional_scale_v1 UNUSED, uint32_t scale) {
    _GLFWwindow *window = data;
    window->wl.once.fractional_scale_received = true;
    if (scale == window->wl.fractional_scale && window->wl.window_fully_created) return;
    debug("Fractional scale requested: %u/120 = %.2f for window %llu\n", scale, scale / 120., window->id);
    window->wl.fractional_scale = scale;
    // niri and up-to-date mutter and up-to-date kwin all send the fractional
    // scale before configure (as of Jan 2025). sway as of 1.10 and Hyprland send it after configure.
    // https://github.com/hyprwm/Hyprland/issues/9126
    // labwc doesnt support preferred buffer scale and seems to send only a
    // single fraction scale event before configure https://github.com/kovidgoyal/kitty/issues/7540
    window->wl.window_fully_created = window->wl.once.surface_configured;
    apply_scale_changes(window, true, true);
}

static const struct wp_fractional_scale_v1_listener fractional_scale_listener = {
    .preferred_scale = &fractional_scale_preferred_scale,
};

static bool createSurface(_GLFWwindow* window,
                              const _GLFWwndconfig* wndconfig)
{
    window->wl.surface = wl_compositor_create_surface(_glfw.wl.compositor);
    if (!window->wl.surface)
        return false;

    wl_surface_add_listener(window->wl.surface,
                            &surfaceListener,
                            window);

    wl_surface_set_user_data(window->wl.surface, window);

    // If we already have been notified of the primary monitor scale, assume
    // the window will be created on it and so avoid a rescale roundtrip in the common
    // case of the window being shown on the primary monitor or all monitors having the same scale.
    // If you change this also change get_window_content_scale() in the kitty code.
    GLFWmonitor* monitor = glfwGetPrimaryMonitor();
    float xscale = 1.0, yscale = 1.0;
    int scale = 1;
    if (monitor) {
        glfwGetMonitorContentScale(monitor, &xscale, &yscale);
        // see wl_monitor.c xscale is always == yscale
        if (xscale <= 0.0001 || xscale != xscale || xscale >= 24) xscale = 1.0;
        if (xscale > 1) scale = (int)xscale;
    }
    window->wl.expect_scale_from_compositor = _glfw.wl.has_preferred_buffer_scale;
    if (_glfw.wl.wp_fractional_scale_manager_v1 && _glfw.wl.wp_viewporter) {
        window->wl.wp_fractional_scale_v1 = wp_fractional_scale_manager_v1_get_fractional_scale(_glfw.wl.wp_fractional_scale_manager_v1, window->wl.surface);
        if (window->wl.wp_fractional_scale_v1) {
            window->wl.wp_viewport = wp_viewporter_get_viewport(_glfw.wl.wp_viewporter, window->wl.surface);
            if (window->wl.wp_viewport) {
                wp_fractional_scale_v1_add_listener(window->wl.wp_fractional_scale_v1, &fractional_scale_listener, window);
                window->wl.expect_scale_from_compositor = true;
            }
        }
    }
    window->wl.window_fully_created = !window->wl.expect_scale_from_compositor;
    if (_glfw.wl.org_kde_kwin_blur_manager && wndconfig->blur_radius > 0) _glfwPlatformSetWindowBlur(window, wndconfig->blur_radius);

    window->wl.integer_scale.deduced = scale;
    if (_glfw.wl.has_preferred_buffer_scale) { scale = 1; window->wl.integer_scale.preferred = 1; }

    debug("Creating window %llu at size: %dx%d and scale %d\n", window->id, wndconfig->width, wndconfig->height, scale);
    window->wl.native = wl_egl_window_create(window->wl.surface, wndconfig->width * scale, wndconfig->height * scale);
    if (!window->wl.native)
        return false;

    window->wl.width = wndconfig->width;
    window->wl.height = wndconfig->height;
    window->wl.user_requested_content_size.width = wndconfig->width;
    window->wl.user_requested_content_size.height = wndconfig->height;


    update_regions(window);

    wl_surface_set_buffer_scale(window->wl.surface, scale);
    if (_glfw.keyboard_grabbed) inhibit_shortcuts_for(window, true);
    return true;
}

static void
setFullscreen(_GLFWwindow* window, _GLFWmonitor* monitor, bool on) {
    if (!window->wl.xdg.toplevel) return;
    if (!window->wl.wm_capabilities.fullscreen) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland compositor does not support fullscreen");
        return;
    }
    if (on) xdg_toplevel_set_fullscreen(window->wl.xdg.toplevel, monitor ? monitor->wl.output : NULL);
    else xdg_toplevel_unset_fullscreen(window->wl.xdg.toplevel);
}


bool
_glfwPlatformIsFullscreen(_GLFWwindow *window, unsigned int flags UNUSED) {
    return window->wl.current.toplevel_states & TOPLEVEL_STATE_FULLSCREEN;
}

bool
_glfwPlatformToggleFullscreen(_GLFWwindow *window, unsigned int flags UNUSED) {
    bool already_fullscreen = _glfwPlatformIsFullscreen(window, flags);
    setFullscreen(window, NULL, !already_fullscreen);
    return !already_fullscreen;
}

static void
report_live_resize(_GLFWwindow *w, bool started) {
    // disabled as mutter, for instance, does not send a configure event when the user stops resizing (aka releases the mouse button)
    if (false) _glfwInputLiveResize(w, started);
}

static void
xdgToplevelHandleConfigure(void* data,
                                       struct xdg_toplevel* toplevel UNUSED,
                                       int32_t width,
                                       int32_t height,
                                       struct wl_array* states)
{
    _GLFWwindow* window = data;
    float aspectRatio;
    float targetRatio;
    enum xdg_toplevel_state* state;
    uint32_t new_states = 0;
    debug("XDG top-level configure event for window %llu: size: %dx%d states: ", window->id, width, height);

    wl_array_for_each(state, states) {
        switch (*state) {
#define C(x) case XDG_##x: new_states |= x; debug("%s ", #x); break
            C(TOPLEVEL_STATE_RESIZING);
            C(TOPLEVEL_STATE_MAXIMIZED);
            C(TOPLEVEL_STATE_FULLSCREEN);
            C(TOPLEVEL_STATE_ACTIVATED);
            C(TOPLEVEL_STATE_TILED_LEFT);
            C(TOPLEVEL_STATE_TILED_RIGHT);
            C(TOPLEVEL_STATE_TILED_TOP);
            C(TOPLEVEL_STATE_TILED_BOTTOM);
#ifdef XDG_TOPLEVEL_STATE_SUSPENDED_SINCE_VERSION
            C(TOPLEVEL_STATE_SUSPENDED);
#endif
#ifdef XDG_TOPLEVEL_STATE_CONSTRAINED_LEFT_SINCE_VERSION
            C(TOPLEVEL_STATE_CONSTRAINED_LEFT);
            C(TOPLEVEL_STATE_CONSTRAINED_RIGHT);
            C(TOPLEVEL_STATE_CONSTRAINED_TOP);
            C(TOPLEVEL_STATE_CONSTRAINED_BOTTOM);
#endif
#undef C
        }
    }
    debug("\n");
    if (new_states & TOPLEVEL_STATE_RESIZING) {
        if (width) window->wl.user_requested_content_size.width = width;
        if (height) window->wl.user_requested_content_size.height = height;
        if (!(window->wl.current.toplevel_states & TOPLEVEL_STATE_RESIZING)) report_live_resize(window, true);
    }
    if (width != 0 && height != 0)
    {
        if (!(new_states & TOPLEVEL_STATE_DOCKED))
        {
            if (window->numer != GLFW_DONT_CARE && window->denom != GLFW_DONT_CARE)
            {
                aspectRatio = (float)width / (float)height;
                targetRatio = (float)window->numer / (float)window->denom;
                if (aspectRatio < targetRatio)
                    height = (int32_t)((float)width / targetRatio);
                else if (aspectRatio > targetRatio)
                    width = (int32_t)((float)height * targetRatio);
            }
        }
    }

    window->wl.pending.toplevel_states = new_states;
    window->wl.pending.width = width;
    window->wl.pending.height = height;
    window->wl.pending_state |= PENDING_STATE_TOPLEVEL;
}

static void xdgToplevelHandleClose(void* data,
                                   struct xdg_toplevel* toplevel UNUSED)
{
    _GLFWwindow* window = data;
    window->wl.window_fully_created = true;
    _glfwInputWindowCloseRequest(window);
}

#if defined(XDG_TOPLEVEL_WM_CAPABILITIES_SINCE_VERSION)
static void
xdg_toplevel_wm_capabilities(void *data, struct xdg_toplevel *xdg_toplevel UNUSED, struct wl_array *caps) {
    _GLFWwindow *window = data;
#define c (window->wl.wm_capabilities)
    memset(&c, 0, sizeof(c));

    enum xdg_toplevel_wm_capabilities *cap;
    wl_array_for_each(cap, caps) {
        switch (*cap) {
        case XDG_TOPLEVEL_WM_CAPABILITIES_MAXIMIZE: c.maximize = true; break;
        case XDG_TOPLEVEL_WM_CAPABILITIES_MINIMIZE: c.minimize = true; break;
        case XDG_TOPLEVEL_WM_CAPABILITIES_WINDOW_MENU: c.window_menu = true; break;
        case XDG_TOPLEVEL_WM_CAPABILITIES_FULLSCREEN: c.fullscreen = true; break;
        }
    }
    debug("Compositor top-level capabilities: maximize=%d minimize=%d window_menu=%d fullscreen=%d\n",
            c.maximize, c.minimize, c.window_menu, c.fullscreen);
#undef c
}
#endif

static void
xdg_toplevel_configure_bounds(void *data, struct xdg_toplevel *xdg_toplevel UNUSED, int32_t width, int32_t height) {
    _GLFWwindow *window = data;
    window->wl.xdg.top_level_bounds.width = width;
    window->wl.xdg.top_level_bounds.height = height;
    debug("Compositor set top-level bounds of: %dx%d for window %llu\n", width, height, window->id);
}

static const struct xdg_toplevel_listener xdgToplevelListener = {
    .configure = xdgToplevelHandleConfigure,
    .close = xdgToplevelHandleClose,
#ifdef XDG_TOPLEVEL_WM_CAPABILITIES_SINCE_VERSION
    .configure_bounds = xdg_toplevel_configure_bounds,
    .wm_capabilities = xdg_toplevel_wm_capabilities,
#endif
};

static void
update_fully_created_on_configure(_GLFWwindow *window) {
    // See fractional_scale_preferred_scale() for logic
    if (!window->wl.window_fully_created) {
        window->wl.window_fully_created = window->wl.once.fractional_scale_received;
        if (window->wl.window_fully_created) debug("Marked window as fully created in configure event\n");
    }
}

static void
apply_xdg_configure_changes(_GLFWwindow *window) {
    bool suspended_changed = false;
    if (window->wl.pending_state & PENDING_STATE_TOPLEVEL) {
        uint32_t new_states = window->wl.pending.toplevel_states;
        int width = window->wl.pending.width;
        int height = window->wl.pending.height;
        if (!window->wl.once.surface_configured) {
            window->swaps_disallowed = false;
            wait_for_swap_to_commit(window);
            window->wl.once.surface_configured = true;
            update_fully_created_on_configure(window);
        }

#ifdef XDG_TOPLEVEL_STATE_SUSPENDED_SINCE_VERSION
        suspended_changed = ((new_states & TOPLEVEL_STATE_SUSPENDED) != (window->wl.current.toplevel_states & TOPLEVEL_STATE_SUSPENDED));
#endif

        if (new_states != window->wl.current.toplevel_states ||
                width != window->wl.current.width ||
                height != window->wl.current.height) {

            bool live_resize_done = !(new_states & TOPLEVEL_STATE_RESIZING) && (window->wl.current.toplevel_states & TOPLEVEL_STATE_RESIZING);
            window->wl.current.toplevel_states = new_states;
            window->wl.current.width = width;
            window->wl.current.height = height;
            if (live_resize_done) report_live_resize(window, false);
        }
    }

    if (window->wl.pending_state & PENDING_STATE_DECORATION) {
        uint32_t mode = window->wl.pending.decoration_mode;
        bool has_server_side_decorations = (mode == ZXDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
        window->wl.decorations.serverSide = has_server_side_decorations;
        window->wl.current.decoration_mode = mode;
    }

    if (window->wl.pending_state) {
        int width = window->wl.pending.width, height = window->wl.pending.height;
        csd_set_window_geometry(window, &width, &height);
        bool resized = dispatchChangesAfterConfigure(window, width, height);
        csd_set_visible(window, csd_should_window_be_decorated(window));
        debug("Final window %llu content size: %dx%d resized: %d\n", window->id, width, height, resized);
    }

    inform_compositor_of_window_geometry(window, "configure");
    commit_window_surface_if_safe(window);
    window->wl.pending_state = 0;
#ifdef XDG_TOPLEVEL_STATE_SUSPENDED_SINCE_VERSION
    if (suspended_changed) {
        _glfwInputWindowOcclusion(window, window->wl.current.toplevel_states & TOPLEVEL_STATE_SUSPENDED);
    }
#endif
}

typedef union pixel {
    struct {
        uint8_t blue, green, red, alpha;
    };
    uint32_t value;
} pixel;

static struct wl_buffer*
create_single_color_buffer(int width, int height, pixel color) {
    // convert to pre-multiplied alpha as that's what wayland wants
    if (width == 1 && height == 1 && _glfw.wl.wp_single_pixel_buffer_manager_v1) {
#define C(x) (uint32_t)(((double)((uint64_t)color.alpha * color.x * UINT32_MAX)) / (255 * 255))
        struct wl_buffer *ans = wp_single_pixel_buffer_manager_v1_create_u32_rgba_buffer(
            _glfw.wl.wp_single_pixel_buffer_manager_v1, C(red), C(green), C(blue), (uint32_t)((color.alpha / 255.) * UINT32_MAX));
#undef C
        if (!ans) _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: failed to create single pixel buffer");
        return ans;
    }
    float alpha = color.alpha / 255.f;
    color.red = (uint8_t)(alpha * color.red); color.green = (uint8_t)(alpha * color.green); color.blue = (uint8_t)(alpha * color.blue);
    int shm_format = color.alpha == 0xff ? WL_SHM_FORMAT_XRGB8888 : WL_SHM_FORMAT_ARGB8888;
    const size_t size = 4 * width * height;
    int fd = createAnonymousFile(size);
    if (fd < 0) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: failed to create anonymous file");
        return NULL;
    }
    uint32_t *shm_data = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (color.value) for (size_t i = 0; i < size/4; i++) shm_data[i] = color.value;
    else memset(shm_data, 0, size);
    if (!shm_data) {
        close(fd);
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: failed to mmap anonymous file");
        return NULL;
    }
    struct wl_shm_pool *pool = wl_shm_create_pool(_glfw.wl.shm, fd, size);
    if (!pool) {
        close(fd); munmap(shm_data, size);
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: failed to create wl_shm_pool of size: %zu", size);
        return NULL;
    }
    struct wl_buffer *buffer = wl_shm_pool_create_buffer(pool, 0, width, height, width * 4, shm_format);
    wl_shm_pool_destroy(pool); munmap(shm_data, size); close(fd);
    if (!buffer) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: failed to create wl_buffer of size: %zu", size);
        return NULL;
    }
    return buffer;
}

static bool
attach_temp_buffer_during_window_creation(_GLFWwindow *window) {
    pixel color;
    color.value = _glfw.hints.window.wl.bgcolor;
    if (!window->wl.transparent) color.alpha = 0xff;
    else if (color.alpha == 0) color.value = 0;  // fully transparent blends best with black and we can use memset

    if (window->wl.temp_buffer_used_during_window_creation) {
        wl_buffer_destroy(window->wl.temp_buffer_used_during_window_creation);
        window->wl.temp_buffer_used_during_window_creation = NULL;
    }
    int width, height;
    _glfwPlatformGetFramebufferSize(window, &width, &height);

    if (window->wl.wp_viewport) {
        window->wl.temp_buffer_used_during_window_creation = create_single_color_buffer(1, 1, color);
        wl_surface_set_buffer_scale(window->wl.surface, 1);
        wp_viewport_set_destination(window->wl.wp_viewport, window->wl.width, window->wl.height);
    } else {
        window->wl.temp_buffer_used_during_window_creation = create_single_color_buffer(width, height, color);
        wl_surface_set_buffer_scale(window->wl.surface, window->wl.fractional_scale ? 1: _glfwWaylandIntegerWindowScale(window));
    }
    if (!window->wl.temp_buffer_used_during_window_creation) return false;
    wl_surface_attach(window->wl.surface, window->wl.temp_buffer_used_during_window_creation, 0, 0);
    debug("Attached temp buffer during window %llu creation of size: %dx%d and rgba(%u, %u, %u, %u)\n", window->id, width, height, color.red, color.green, color.blue, color.alpha);
    commit_window_surface(window);
    return true;
}

static void
loop_till_window_fully_created(_GLFWwindow *window) {
    if (!window->wl.window_fully_created) {
        GLFWwindow *ctx = glfwGetCurrentContext();
        debug("Waiting for compositor to send fractional scale for window %llu\n", window->id);
        monotonic_t start = monotonic();
        while (!window->wl.window_fully_created && monotonic() - start < ms_to_monotonic_t(300)) {
            if (wl_display_roundtrip(_glfw.wl.display) == -1) {
                window->wl.window_fully_created = true;
            }
        }
        window->wl.window_fully_created = true;
        // If other OS windows were resized when this window is shown, the ctx might have been changed by
        // user code, restore it to whatever it was at the start.
        if (glfwGetCurrentContext() != ctx) glfwMakeContextCurrent(ctx);
    }
}

static void
xdgSurfaceHandleConfigure(void* data, struct xdg_surface* surface, uint32_t serial) {
    // The poorly documented pattern Wayland requires is:
    // 1) ack the configure,
    // 2) set the window geometry
    // 3) attach a new buffer of the correct size to the surface
    // 4) only then commit the surface.
    // buffer is attached only by eglSwapBuffers,
    // so we set a flag to not commit the surface till the next swapbuffers. Note that
    // wl_egl_window_resize() does not actually resize the buffer until the next draw call
    // or buffer state query.
    _GLFWwindow* window = data;
    xdg_surface_ack_configure(surface, serial);
    debug("XDG surface configure event received and acknowledged for window %llu\n", window->id);
    apply_xdg_configure_changes(window);
    if (!window->wl.window_fully_created) {
        if (!attach_temp_buffer_during_window_creation(window)) window->wl.window_fully_created = true;
    }
}

static const struct xdg_surface_listener xdgSurfaceListener = {
    xdgSurfaceHandleConfigure
};

static void
setXdgDecorations(_GLFWwindow* window)
{
    if (window->wl.xdg.decoration) {
        window->wl.decorations.serverSide = true;
        zxdg_toplevel_decoration_v1_set_mode(window->wl.xdg.decoration, window->decorated ? ZXDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE: ZXDG_TOPLEVEL_DECORATION_V1_MODE_CLIENT_SIDE);
    } else {
        window->wl.decorations.serverSide = false;
        csd_set_visible(window, csd_should_window_be_decorated(window));
    }
}

void _glfwPlatformSetWindowDecorated(_GLFWwindow* window, bool enabled UNUSED) {
    setXdgDecorations(window);
    inform_compositor_of_window_geometry(window, "SetWindowDecorated");
    commit_window_surface_if_safe(window);
}


static struct wl_output*
find_output_by_name(const char* name) {
    if (!name || !name[0]) return NULL;
    for (int i = 0; i < _glfw.monitorCount; i++) {
        _GLFWmonitor *m = _glfw.monitors[i];
        if (strcmp(m->name, name) == 0) return m->wl.output;
    }
    return NULL;
}

static enum zwlr_layer_shell_v1_layer
get_layer_shell_layer(const _GLFWwindow *window) {
    enum zwlr_layer_shell_v1_layer which_layer = ZWLR_LAYER_SHELL_V1_LAYER_BACKGROUND; // Default to background
    switch (window->wl.layer_shell.config.type) {
        case GLFW_LAYER_SHELL_BACKGROUND: case GLFW_LAYER_SHELL_NONE: break;
        case GLFW_LAYER_SHELL_PANEL: which_layer = ZWLR_LAYER_SHELL_V1_LAYER_BOTTOM; break;
        case GLFW_LAYER_SHELL_TOP: which_layer = ZWLR_LAYER_SHELL_V1_LAYER_TOP; break;
        case GLFW_LAYER_SHELL_OVERLAY: which_layer = ZWLR_LAYER_SHELL_V1_LAYER_OVERLAY; break;
    }
    return which_layer;
}

static void
layer_set_properties(const _GLFWwindow *window, bool during_creation, uint32_t width, uint32_t height) {
#define config window->wl.layer_shell.config
    enum zwlr_layer_surface_v1_anchor which_anchor = ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT | ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT;
    int exclusive_zone = config.requested_exclusive_zone;
    enum zwlr_layer_surface_v1_keyboard_interactivity focus_policy = ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE;
    switch(config.focus_policy) {
        case GLFW_FOCUS_NOT_ALLOWED: focus_policy = ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_NONE; break;
        case GLFW_FOCUS_EXCLUSIVE: focus_policy = ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_EXCLUSIVE; break;
        case GLFW_FOCUS_ON_DEMAND: focus_policy = ZWLR_LAYER_SURFACE_V1_KEYBOARD_INTERACTIVITY_ON_DEMAND; break;
    }
    int panel_width = 0, panel_height = 0;
    switch (config.type) {
        case GLFW_LAYER_SHELL_NONE: break;
        case GLFW_LAYER_SHELL_BACKGROUND: exclusive_zone = -1; break;
        case GLFW_LAYER_SHELL_TOP:
        case GLFW_LAYER_SHELL_OVERLAY:
        case GLFW_LAYER_SHELL_PANEL:
            switch (config.edge) {
                case GLFW_EDGE_TOP:
                    which_anchor = ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT | ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT;
                    panel_height = height;
                    if (!config.override_exclusive_zone) exclusive_zone = height;
                    break;
                case GLFW_EDGE_BOTTOM:
                    which_anchor = ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT | ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT;
                    panel_height = height;
                    if (!config.override_exclusive_zone) exclusive_zone = height;
                    break;
                case GLFW_EDGE_LEFT:
                    which_anchor = ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT | ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM;
                    panel_width = width;
                    if (!config.override_exclusive_zone) exclusive_zone = width;
                    break;
                case GLFW_EDGE_RIGHT:
                    which_anchor = ZWLR_LAYER_SURFACE_V1_ANCHOR_RIGHT | ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_BOTTOM;
                    panel_width = width;
                    if (!config.override_exclusive_zone) exclusive_zone = width;
                    break;
                case GLFW_EDGE_CENTER:
                    break;
                case GLFW_EDGE_CENTER_SIZED:
                    panel_width = width; panel_height = height;
                    break;
                case GLFW_EDGE_NONE:
                    which_anchor = ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT | ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP;
                    panel_width = width; panel_height = height;
                    break;
            }
    }
#define surface window->wl.layer_shell.zwlr_layer_surface_v1
    zwlr_layer_surface_v1_set_size(surface, panel_width, panel_height);
    debug("Compositor will be informed that layer size: %dx%d viewport: %dx%d at next surface commit\n", panel_width, panel_height, width, height);
    zwlr_layer_surface_v1_set_anchor(surface, which_anchor);
    zwlr_layer_surface_v1_set_exclusive_zone(surface, exclusive_zone);
    zwlr_layer_surface_v1_set_margin(surface, config.requested_top_margin, config.requested_right_margin, config.requested_bottom_margin, config.requested_left_margin);
    if (!during_creation) zwlr_layer_surface_v1_set_layer(surface, get_layer_shell_layer(window));
    zwlr_layer_surface_v1_set_keyboard_interactivity(surface, focus_policy);
#undef surface
#undef config
}

static void
calculate_layer_size(_GLFWwindow *window, uint32_t *width, uint32_t *height) {
    const GLFWLayerShellConfig *config = &window->wl.layer_shell.config;
    GLFWvidmode m = {0};
    if (window->wl.monitorsCount) _glfwPlatformGetVideoMode(window->wl.monitors[0], &m);
    int monitor_width = m.width, monitor_height = m.height;
    const int y_margin = config->requested_bottom_margin + config->requested_top_margin, x_margin = config->requested_left_margin + config->requested_right_margin;
    monitor_width = monitor_width > x_margin ? monitor_width - x_margin : 0;
    monitor_height = monitor_height > y_margin ? monitor_height - y_margin : 0;
    float xscale = (float)config->expected.xscale, yscale = (float)config->expected.yscale;
    if (window->wl.window_fully_created) _glfwPlatformGetWindowContentScale(window, &xscale, &yscale);
    unsigned cell_width, cell_height; double left_edge_spacing, top_edge_spacing, right_edge_spacing, bottom_edge_spacing;
    config->size_callback((GLFWwindow*)window, xscale, yscale, &cell_width, &cell_height, &left_edge_spacing, &top_edge_spacing, &right_edge_spacing, &bottom_edge_spacing);
    double spacing_x = left_edge_spacing + right_edge_spacing;
    double spacing_y = top_edge_spacing + bottom_edge_spacing;
    if (config->type == GLFW_LAYER_SHELL_BACKGROUND) {
        if (!*width) *width = monitor_width;
        if (!*height) *height = monitor_height;
        return;
    }
    const unsigned xsz = config->x_size_in_pixels ? (unsigned)(config->x_size_in_pixels * xscale) : (cell_width * config->x_size_in_cells);
    const unsigned ysz = config->y_size_in_pixels ? (unsigned)(config->y_size_in_pixels * yscale) : (cell_height * config->y_size_in_cells);
    debug("Calculating layer shell window size at scale: %f cell_size: %u %u sz: %u %u\n", xscale, cell_width, cell_height, xsz, ysz);
    if (config->edge == GLFW_EDGE_LEFT || config->edge == GLFW_EDGE_RIGHT) {
        if (!*height) *height = monitor_height;
        double spacing = spacing_x;
        spacing += xsz / xscale;
        *width = (uint32_t)(1. + spacing);
    } else if (config->edge == GLFW_EDGE_TOP || config->edge == GLFW_EDGE_BOTTOM) {
        if (!*width) *width = monitor_width;
        double spacing = spacing_y;
        spacing += ysz / yscale;
        *height = (uint32_t)(1. + spacing);
    } else if (config->edge == GLFW_EDGE_CENTER) {
        if (!*width) *width = monitor_width;
        if (!*height) *height = monitor_height;
    } else {
        spacing_x += xsz / xscale;
        spacing_y += ysz / yscale;
        *width = (uint32_t)(1. + spacing_x);
        *height = (uint32_t)(1. + spacing_y);
    }

}

static void
layer_surface_handle_configure(void* data, struct zwlr_layer_surface_v1* surface, uint32_t serial, uint32_t width, uint32_t height) {
    debug("Layer shell configure event: width: %u height: %u\n", width, height);
    _GLFWwindow* window = data;
    if (!window->wl.once.surface_configured) {
        window->swaps_disallowed = false;
        wait_for_swap_to_commit(window);
        window->wl.once.surface_configured = true;
        update_fully_created_on_configure(window);
    }
    calculate_layer_size(window, &width, &height);
    zwlr_layer_surface_v1_ack_configure(surface, serial);
    if ((int)width != window->wl.width || (int)height != window->wl.height) {
        debug("Layer shell size changed to %ux%u in layer_surface_handle_configure\n", width, height);
        _glfwInputWindowSize(window, width, height);
        window->wl.width = width; window->wl.height = height;
        resizeFramebuffer(window);
        _glfwInputWindowDamage(window);
        layer_set_properties(window, false, window->wl.width, window->wl.height);
        if (window->wl.wp_viewport) wp_viewport_set_destination(window->wl.wp_viewport, window->wl.width, window->wl.height);
    }
    commit_window_surface_if_safe(window);
    if (!window->wl.window_fully_created) {
        if (!attach_temp_buffer_during_window_creation(window)) window->wl.window_fully_created = true;
    }
}

static void
layer_surface_handle_close_requested(void* data, struct zwlr_layer_surface_v1* surface UNUSED) {
    _GLFWwindow* window = data;
    window->wl.window_fully_created = true;
    _glfwInputWindowCloseRequest(window);
}

static const struct zwlr_layer_surface_v1_listener zwlr_layer_surface_v1_listener = {
    .configure=layer_surface_handle_configure,
    .closed=layer_surface_handle_close_requested,
};

static bool
create_layer_shell_surface(_GLFWwindow *window) {
    if (!_glfw.wl.zwlr_layer_shell_v1) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: wlr-layer-shell protocol unsupported by compositor");
        return false;
    }
    window->decorated = false;  // shell windows must not have decorations
    struct wl_output *wl_output = find_output_by_name(window->wl.layer_shell.config.output_name);
#define ls window->wl.layer_shell.zwlr_layer_surface_v1
    ls = zwlr_layer_shell_v1_get_layer_surface(
            _glfw.wl.zwlr_layer_shell_v1, window->wl.surface, wl_output, get_layer_shell_layer(window), window->wl.appId[0] ? window->wl.appId : "kitty");
    if (!ls) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: layer-surface creation failed");
        return false;
    }
    zwlr_layer_surface_v1_add_listener(ls, &zwlr_layer_surface_v1_listener, window);
    layer_set_properties(window, true, window->wl.width, window->wl.height);
    if (window->wl.wp_viewport) wp_viewport_set_destination(window->wl.wp_viewport, window->wl.width, window->wl.height);
    commit_window_surface(window);
    wl_display_roundtrip(_glfw.wl.display);
    window->wl.created = true;
#undef ls
    return true;
}

static bool
create_window_desktop_surface(_GLFWwindow* window)
{
    if (is_layer_shell(window)) return create_layer_shell_surface(window);

    window->wl.xdg.surface = xdg_wm_base_get_xdg_surface(_glfw.wl.wmBase,
                                                         window->wl.surface);
    if (!window->wl.xdg.surface)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: xdg-surface creation failed");
        return false;
    }

    xdg_surface_add_listener(window->wl.xdg.surface,
                             &xdgSurfaceListener,
                             window);

    window->wl.xdg.toplevel = xdg_surface_get_toplevel(window->wl.xdg.surface);
    if (!window->wl.xdg.toplevel)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: xdg-toplevel creation failed");
        return false;
    }

#ifdef XDG_TOPLEVEL_WM_CAPABILITIES_SINCE_VERSION
    if (_glfw.wl.xdg_wm_base_version < XDG_TOPLEVEL_WM_CAPABILITIES_SINCE_VERSION) {
        window->wl.wm_capabilities.maximize = true; window->wl.wm_capabilities.minimize = true; window->wl.wm_capabilities.fullscreen = true;
        window->wl.wm_capabilities.window_menu = true;
    }
#endif
    xdg_toplevel_add_listener(window->wl.xdg.toplevel, &xdgToplevelListener, window);
    if (_glfw.wl.decorationManager) {
        window->wl.xdg.decoration = zxdg_decoration_manager_v1_get_toplevel_decoration(
                _glfw.wl.decorationManager, window->wl.xdg.toplevel);
        zxdg_toplevel_decoration_v1_add_listener(window->wl.xdg.decoration, &xdgDecorationListener, window);
    }

    if (window->wl.appId[0])
        xdg_toplevel_set_app_id(window->wl.xdg.toplevel, window->wl.appId);
    if (window->wl.windowTag[0] && _glfw.wl.xdg_toplevel_tag_manager_v1)
        xdg_toplevel_tag_manager_v1_set_toplevel_tag(_glfw.wl.xdg_toplevel_tag_manager_v1, window->wl.xdg.toplevel, window->wl.windowTag);

    if (window->wl.title)
        xdg_toplevel_set_title(window->wl.xdg.toplevel, window->wl.title);

    if (window->minwidth != GLFW_DONT_CARE && window->minheight != GLFW_DONT_CARE)
        xdg_toplevel_set_min_size(window->wl.xdg.toplevel,
                                  window->minwidth, window->minheight);
    if (window->maxwidth != GLFW_DONT_CARE && window->maxheight != GLFW_DONT_CARE)
        xdg_toplevel_set_max_size(window->wl.xdg.toplevel,
                                  window->maxwidth, window->maxheight);

    if (window->monitor) {
        if (window->wl.wm_capabilities.fullscreen)
            xdg_toplevel_set_fullscreen(window->wl.xdg.toplevel, window->monitor->wl.output);
        else
            _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland compositor does not support fullscreen");
    } else {
        if (window->wl.maximize_on_first_show) {
            window->wl.maximize_on_first_show = false;
            xdg_toplevel_set_maximized(window->wl.xdg.toplevel);
        }
        setXdgDecorations(window);
    }

    commit_window_surface(window);
    wl_display_roundtrip(_glfw.wl.display);
    window->wl.created = true;

    return true;
}

static void incrementCursorImage(_GLFWwindow* window)
{
    if (window && window->wl.decorations.focus == CENTRAL_WINDOW && window->cursorMode != GLFW_CURSOR_HIDDEN) {
        _GLFWcursor* cursor = window->wl.currentCursor;
        if (cursor && cursor->wl.cursor && cursor->wl.cursor->image_count)
        {
            cursor->wl.currentImage += 1;
            cursor->wl.currentImage %= cursor->wl.cursor->image_count;
            setCursorImage(window, false);
            toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, cursor->wl.cursor->image_count > 1);
            return;
        }
    }
    toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, 1);
}

void
animateCursorImage(id_type timer_id UNUSED, void *data UNUSED) {
    incrementCursorImage(_glfw.wl.pointerFocus);
}

static void
abortOnFatalError(int last_error) {
    static bool abort_called = false;
    if (!abort_called) {
        abort_called = true;
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: fatal display error: %s", strerror(last_error));
        if (_glfw.callbacks.application_close) _glfw.callbacks.application_close(1);
        else {
            _GLFWwindow* window = _glfw.windowListHead;
            while (window)
            {
                _glfwInputWindowCloseRequest(window);
                window = window->next;
            }
        }
    }
    // ensure the tick callback is called
    _glfw.wl.eventLoopData.wakeup_data_read = true;
}

static void
wayland_read_events(int poll_result, int events, void *data UNUSED) {
    EVDBG("wayland_read_events poll_result: %d events: %d", poll_result, events);
    if (poll_result > 0 && events) wl_display_read_events(_glfw.wl.display);
    else wl_display_cancel_read(_glfw.wl.display);
}

static void handleEvents(monotonic_t timeout)
{
    struct wl_display* display = _glfw.wl.display;
    errno = 0;
    EVDBG("starting handleEvents(%.2f)", monotonic_t_to_s_double(timeout));

    while (wl_display_prepare_read(display) != 0) {
        if (wl_display_dispatch_pending(display) == -1) {
            abortOnFatalError(errno);
            return;
        }
    }

    // If an error different from EAGAIN happens, we have likely been
    // disconnected from the Wayland session, try to handle that the best we
    // can.
    errno = 0;
    if (wl_display_flush(display) < 0 && errno != EAGAIN)
    {
        wl_display_cancel_read(display);
        abortOnFatalError(errno);
        return;
    }

    // we pass in wayland_read_events to ensure that the above wl_display_prepare_read call
    // is followed by either wl_display_cancel_read or wl_display_read_events
    // before any events/timers are dispatched. This allows other wayland functions
    // to be called in the event/timer handlers without causing a deadlock
    bool display_read_ok = pollForEvents(&_glfw.wl.eventLoopData, timeout, wayland_read_events);
    EVDBG("display_read_ok: %d", display_read_ok);
    if (display_read_ok) {
        int num = wl_display_dispatch_pending(display);
        (void)num;
        EVDBG("dispatched %d Wayland events", num);
    }
    glfw_ibus_dispatch(&_glfw.wl.xkb.ibus);
    glfw_dbus_session_bus_dispatch();
    EVDBG("other dispatch done");
    if (_glfw.wl.eventLoopData.wakeup_fd_ready) check_for_wakeup_events(&_glfw.wl.eventLoopData);
}

static struct wl_cursor*
try_cursor_names(struct wl_cursor_theme* theme, int arg_count, ...) {
    struct wl_cursor* ans = NULL;
    va_list ap;
    va_start(ap, arg_count);
    for (int i = 0; i < arg_count && !ans; i++) {
        const char *name = va_arg(ap, const char *);
        ans = wl_cursor_theme_get_cursor(theme, name);
    }
    va_end(ap);
    return ans;
}

struct wl_cursor* _glfwLoadCursor(GLFWCursorShape shape, struct wl_cursor_theme* theme)
{
    static bool warnings[GLFW_INVALID_CURSOR] = {0};
    if (!theme) return NULL;
#define NUMARGS(...)  (sizeof((const char*[]){__VA_ARGS__})/sizeof(const char*))
#define C(name, ...) case name: { \
    ans = try_cursor_names(theme, NUMARGS(__VA_ARGS__), __VA_ARGS__); \
    if (!ans && !warnings[name]) {\
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: Could not find standard cursor: %s", #name); \
        warnings[name] = true; \
    } \
    break; }

    struct wl_cursor* ans = NULL;
    switch (shape)
    {
        /* start glfw to xc mapping (auto generated by gen-key-constants.py do not edit) */
        C(GLFW_DEFAULT_CURSOR, "default", "left_ptr");
        C(GLFW_TEXT_CURSOR, "text", "xterm", "ibeam");
        C(GLFW_POINTER_CURSOR, "pointing_hand", "pointer", "hand2", "hand");
        C(GLFW_HELP_CURSOR, "help", "question_arrow", "whats_this");
        C(GLFW_WAIT_CURSOR, "wait", "clock", "watch");
        C(GLFW_PROGRESS_CURSOR, "progress", "half-busy", "left_ptr_watch");
        C(GLFW_CROSSHAIR_CURSOR, "crosshair", "tcross");
        C(GLFW_CELL_CURSOR, "cell", "plus", "cross");
        C(GLFW_VERTICAL_TEXT_CURSOR, "vertical-text");
        C(GLFW_MOVE_CURSOR, "move", "fleur", "pointer-move");
        C(GLFW_E_RESIZE_CURSOR, "e-resize", "right_side");
        C(GLFW_NE_RESIZE_CURSOR, "ne-resize", "top_right_corner");
        C(GLFW_NW_RESIZE_CURSOR, "nw-resize", "top_left_corner");
        C(GLFW_N_RESIZE_CURSOR, "n-resize", "top_side");
        C(GLFW_SE_RESIZE_CURSOR, "se-resize", "bottom_right_corner");
        C(GLFW_SW_RESIZE_CURSOR, "sw-resize", "bottom_left_corner");
        C(GLFW_S_RESIZE_CURSOR, "s-resize", "bottom_side");
        C(GLFW_W_RESIZE_CURSOR, "w-resize", "left_side");
        C(GLFW_EW_RESIZE_CURSOR, "ew-resize", "sb_h_double_arrow", "split_h");
        C(GLFW_NS_RESIZE_CURSOR, "ns-resize", "sb_v_double_arrow", "split_v");
        C(GLFW_NESW_RESIZE_CURSOR, "nesw-resize", "size_bdiag", "size-bdiag");
        C(GLFW_NWSE_RESIZE_CURSOR, "nwse-resize", "size_fdiag", "size-fdiag");
        C(GLFW_ZOOM_IN_CURSOR, "zoom-in", "zoom_in");
        C(GLFW_ZOOM_OUT_CURSOR, "zoom-out", "zoom_out");
        C(GLFW_ALIAS_CURSOR, "dnd-link");
        C(GLFW_COPY_CURSOR, "dnd-copy");
        C(GLFW_NOT_ALLOWED_CURSOR, "not-allowed", "forbidden", "crossed_circle");
        C(GLFW_NO_DROP_CURSOR, "no-drop", "dnd-no-drop");
        C(GLFW_GRAB_CURSOR, "grab", "openhand", "hand1");
        C(GLFW_GRABBING_CURSOR, "grabbing", "closedhand", "dnd-none");
/* end glfw to xc mapping */
        case GLFW_INVALID_CURSOR:
            break;
    }
    return ans;
#undef NUMARGS
#undef C
}

//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

static bool
attach_opengl_context_to_window(_GLFWwindow *window, const _GLFWctxconfig *ctxconfig, const _GLFWfbconfig *fbconfig) {
    if (ctxconfig->source == GLFW_EGL_CONTEXT_API ||
        ctxconfig->source == GLFW_NATIVE_CONTEXT_API)
    {
        if (!_glfwInitEGL())
            return false;
        if (!_glfwCreateContextEGL(window, ctxconfig, fbconfig))
            return false;
    }
    else if (ctxconfig->source == GLFW_OSMESA_CONTEXT_API)
    {
        if (!_glfwInitOSMesa())
            return false;
        if (!_glfwCreateContextOSMesa(window, ctxconfig, fbconfig))
            return false;
    }
    return true;
}

int _glfwPlatformCreateWindow(
    _GLFWwindow* window, const _GLFWwndconfig* wndconfig, const _GLFWctxconfig* ctxconfig, const _GLFWfbconfig* fbconfig,
    const GLFWLayerShellConfig *lsc
) {
    window->wl.layer_shell.config = lsc ? *lsc : (GLFWLayerShellConfig){0};
    csd_initialize_metrics(window);
    window->wl.transparent = fbconfig->transparent;
    strncpy(window->wl.appId, wndconfig->wl.appId, sizeof(window->wl.appId));
    window->swaps_disallowed = true;

    if (!createSurface(window, wndconfig)) return false;
    if (wndconfig->title) window->wl.title = _glfw_strdup(wndconfig->title);
    if (wndconfig->maximized) window->wl.maximize_on_first_show = true;
    if (wndconfig->visible) {
        if (!create_window_desktop_surface(window)) return false;
        window->wl.visible = true;
    } else {
        window->wl.visible = false;
        window->wl.xdg.surface = NULL;
        window->wl.xdg.toplevel = NULL;
        window->wl.layer_shell.zwlr_layer_surface_v1 = NULL;
    }


    window->wl.currentCursor = NULL;
    // Don't set window->wl.cursorTheme to NULL here.

    window->wl.monitors = calloc(1, sizeof(_GLFWmonitor*));
    window->wl.monitorsCount = 0;
    window->wl.monitorsSize = 1;
    // looping till window fully created attaches a single pixel buffer to the window,
    // this cannot be done once a OpenGL context is created for the window. So first loop
    // and only then create the OpenGL context.
    if (window->wl.visible) loop_till_window_fully_created(window);
    debug("Creating OpenGL context and attaching it to window\n");
    if (ctxconfig->client != GLFW_NO_API) attach_opengl_context_to_window(window, ctxconfig, fbconfig);
    return true;
}

void _glfwPlatformDestroyWindow(_GLFWwindow* window)
{
    if (window == _glfw.wl.pointerFocus)
    {
        _glfw.wl.pointerFocus = NULL;
        _glfwInputCursorEnter(window, false);
    }
    if (window->id == _glfw.wl.keyboardFocusId)
    {
        _glfw.wl.keyboardFocusId = 0;
        _glfwInputWindowFocus(window, false);
    }
    if (window->id == _glfw.wl.keyRepeatInfo.keyboardFocusId) {
        _glfw.wl.keyRepeatInfo.keyboardFocusId = 0;
    }
    if (window->wl.keyboard_shortcuts_inhibitor)
        zwp_keyboard_shortcuts_inhibitor_v1_destroy(window->wl.keyboard_shortcuts_inhibitor);

    if (window->wl.temp_buffer_used_during_window_creation)
        wl_buffer_destroy(window->wl.temp_buffer_used_during_window_creation);

    if (window->wl.wp_fractional_scale_v1)
        wp_fractional_scale_v1_destroy(window->wl.wp_fractional_scale_v1);
    if (window->wl.wp_viewport)
        wp_viewport_destroy(window->wl.wp_viewport);
    if (window->wl.org_kde_kwin_blur)
        org_kde_kwin_blur_release(window->wl.org_kde_kwin_blur);

    if (window->context.destroy)
        window->context.destroy(window);

    csd_free_all_resources(window);
    if (window->wl.xdg.decoration)
        zxdg_toplevel_decoration_v1_destroy(window->wl.xdg.decoration);

    if (window->wl.native)
        wl_egl_window_destroy(window->wl.native);

    if (window->wl.xdg.toplevel)
        xdg_toplevel_destroy(window->wl.xdg.toplevel);

    if (window->wl.xdg.surface)
        xdg_surface_destroy(window->wl.xdg.surface);

    if (window->wl.layer_shell.zwlr_layer_surface_v1)
        zwlr_layer_surface_v1_destroy(window->wl.layer_shell.zwlr_layer_surface_v1);

    if (window->wl.surface)
        wl_surface_destroy(window->wl.surface);

    free(window->wl.title);
    free(window->wl.monitors);
    if (window->wl.frameCallbackData.current_wl_callback)
        wl_callback_destroy(window->wl.frameCallbackData.current_wl_callback);
}

void _glfwPlatformSetWindowTitle(_GLFWwindow* window, const char* title)
{
    if (window->wl.title) {
        if (title && strcmp(title, window->wl.title) == 0) return;
        free(window->wl.title);
    } else if (!title) return;
    // Wayland cannot handle requests larger than ~8200 bytes. Sending
    // one causes an abort(). Since titles this large are meaningless anyway
    // ensure they do not happen.
    window->wl.title = utf_8_strndup(title, 2048);
    if (window->wl.xdg.toplevel) {
        xdg_toplevel_set_title(window->wl.xdg.toplevel, window->wl.title);
        csd_change_title(window);
        commit_window_surface_if_safe(window);
    }
}

void
_glfwPlatformSetWindowIcon(_GLFWwindow* window, int count, const GLFWimage* images) {
    if (!_glfw.wl.xdg_toplevel_icon_manager_v1) {
        static bool warned_once = false;
        if (!warned_once) {
            _glfwInputError(GLFW_FEATURE_UNAVAILABLE, "Wayland: The compositor does not support changing window icons");
            warned_once = true;
        }
        return;
    }
    if (!count) {
        xdg_toplevel_icon_manager_v1_set_icon(_glfw.wl.xdg_toplevel_icon_manager_v1, window->wl.xdg.toplevel, NULL);
        return;
    }
    struct wl_buffer* *buffers = malloc(sizeof(struct wl_buffer*) * count);
    if (!buffers) return;
    size_t total_data_size = 0;
    for (int i = 0; i < count; i++) total_data_size += images[i].width * images[i].height * 4;
    int fd = createAnonymousFile(total_data_size);
    if (fd < 0) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: Creating a buffer file for %ld B failed: %s", (long)total_data_size, strerror(errno));
        free(buffers);
        return;
    }
    unsigned char *data = mmap(NULL, total_data_size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (data == MAP_FAILED) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: mmap failed: %s", strerror(errno));
        free(buffers);
        close(fd);
        return;
    }
    struct wl_shm_pool* pool = wl_shm_create_pool(_glfw.wl.shm, fd, total_data_size);
    struct xdg_toplevel_icon_v1 *icon = xdg_toplevel_icon_manager_v1_create_icon(_glfw.wl.xdg_toplevel_icon_manager_v1);
    size_t pos = 0;
    for (int i = 0; i < count; i++) {
        const size_t sz = images[i].width * images[i].height * 4;
        convert_glfw_image_to_wayland_image(images + i, data + pos);
        buffers[i] = wl_shm_pool_create_buffer(
                pool, pos, images[i].width, images[i].height, images[i].width * 4, WL_SHM_FORMAT_ARGB8888);
        xdg_toplevel_icon_v1_add_buffer(icon, buffers[i], 1);
        pos += sz;
    }
    xdg_toplevel_icon_manager_v1_set_icon(_glfw.wl.xdg_toplevel_icon_manager_v1, window->wl.xdg.toplevel, icon);
    xdg_toplevel_icon_v1_destroy(icon);
    for (int i = 0; i < count; i++) wl_buffer_destroy(buffers[i]);
    free(buffers);
    wl_shm_pool_destroy(pool);
    munmap(data, total_data_size);
    close(fd);
}

void _glfwPlatformGetWindowPos(_GLFWwindow* window UNUSED, int* xpos UNUSED, int* ypos UNUSED)
{
    // A Wayland client is not aware of its position, so just warn and leave it
    // as (0, 0)
    static bool warned_once = false;
    if (!warned_once) {
        _glfwInputError(GLFW_FEATURE_UNAVAILABLE,
                        "Wayland: The platform does not provide the window position");
        warned_once = true;
    }
}

void _glfwPlatformSetWindowPos(_GLFWwindow* window UNUSED, int xpos UNUSED, int ypos UNUSED)
{
    // A Wayland client can not set its position, so just warn

    _glfwInputError(GLFW_FEATURE_UNAVAILABLE,
                    "Wayland: The platform does not support setting the window position");
}

void _glfwPlatformGetWindowSize(_GLFWwindow* window, int* width, int* height)
{
    if (width)
        *width = window->wl.width;
    if (height)
        *height = window->wl.height;
}

void _glfwPlatformSetWindowSize(_GLFWwindow* window, int width, int height)
{
    if (is_layer_shell(window)) {
        _glfwInputError(GLFW_FEATURE_UNAVAILABLE,
                        "Wayland: Resizing of layer shell surfaces is not supported");
        return;
    }
    if (width != window->wl.width || height != window->wl.height) {
        window->wl.user_requested_content_size.width = width;
        window->wl.user_requested_content_size.height = height;
        int32_t w = 0, h = 0;
        csd_set_window_geometry(window, &w, &h);
        window->wl.width = w; window->wl.height = h;
        resizeFramebuffer(window);
        csd_set_visible(window, csd_should_window_be_decorated(window));  // resizes the csd iff the window currently has csd
        commit_window_surface_if_safe(window);
        inform_compositor_of_window_geometry(window, "SetWindowSize");
    }
}

void _glfwPlatformSetWindowSizeLimits(_GLFWwindow* window,
                                      int minwidth, int minheight,
                                      int maxwidth, int maxheight)
{
    if (window->wl.xdg.toplevel)
    {
        if (minwidth == GLFW_DONT_CARE || minheight == GLFW_DONT_CARE)
            minwidth = minheight = 0;
        if (maxwidth == GLFW_DONT_CARE || maxheight == GLFW_DONT_CARE)
            maxwidth = maxheight = 0;
        xdg_toplevel_set_min_size(window->wl.xdg.toplevel, minwidth, minheight);
        xdg_toplevel_set_max_size(window->wl.xdg.toplevel, maxwidth, maxheight);
        commit_window_surface_if_safe(window);
    }
}

void _glfwPlatformSetWindowAspectRatio(_GLFWwindow* window UNUSED,
                                       int numer UNUSED, int denom UNUSED)
{
    // TODO: find out how to trigger a resize.
    // The actual limits are checked in the xdg_toplevel::configure handler.
    _glfwInputError(GLFW_FEATURE_UNIMPLEMENTED,
                    "Wayland: Window aspect ratio not yet implemented");
}

void _glfwPlatformSetWindowSizeIncrements(_GLFWwindow* window UNUSED,
                                          int widthincr UNUSED, int heightincr UNUSED)
{
    // TODO: find out how to trigger a resize.
    // The actual limits are checked in the xdg_toplevel::configure handler.
}

void _glfwPlatformGetFramebufferSize(_GLFWwindow* window,
                                     int* width, int* height)
{
    _glfwPlatformGetWindowSize(window, width, height);
    double fscale = _glfwWaylandWindowScale(window);
    if (width)
        *width = (int)round(*width * fscale);
    if (height)
        *height = (int)round(*height * fscale);
}

void _glfwPlatformGetWindowFrameSize(_GLFWwindow* window,
                                     int* left, int* top,
                                     int* right, int* bottom)
{
    if (window->decorated && !window->monitor && !window->wl.decorations.serverSide)
    {
        if (top)
            *top = window->wl.decorations.metrics.top - window->wl.decorations.metrics.visible_titlebar_height;
        if (left)
            *left = window->wl.decorations.metrics.width;
        if (right)
            *right = window->wl.decorations.metrics.width;
        if (bottom)
            *bottom = window->wl.decorations.metrics.width;
    }
}

void _glfwPlatformGetWindowContentScale(_GLFWwindow* window,
                                        float* xscale, float* yscale)
{
    float fscale = (float)_glfwWaylandWindowScale(window);
    if (xscale)
        *xscale = fscale;
    if (yscale)
        *yscale = fscale;
}

monotonic_t _glfwPlatformGetDoubleClickInterval(_GLFWwindow* window UNUSED)
{
    return ms_to_monotonic_t(500ll);
}

void _glfwPlatformIconifyWindow(_GLFWwindow* window)
{
    if (window->wl.xdg.toplevel) {
        if (window->wl.wm_capabilities.minimize) xdg_toplevel_set_minimized(window->wl.xdg.toplevel);
        else _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland compositor does not support minimizing windows");
    }
}

void _glfwPlatformRestoreWindow(_GLFWwindow* window)
{
    if (window->wl.xdg.toplevel)
    {
        if (window->monitor)
            xdg_toplevel_unset_fullscreen(window->wl.xdg.toplevel);
        if (window->wl.current.toplevel_states & TOPLEVEL_STATE_MAXIMIZED)
            xdg_toplevel_unset_maximized(window->wl.xdg.toplevel);
        // There is no way to unset minimized, or even to know if we are
        // minimized, so there is nothing to do in this case.
    }
    _glfwInputWindowMonitor(window, NULL);
}

void _glfwPlatformMaximizeWindow(_GLFWwindow* window)
{
    if (window->wl.xdg.toplevel) {
        if (window->wl.wm_capabilities.maximize) xdg_toplevel_set_maximized(window->wl.xdg.toplevel);
        else _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland compositor does not support maximizing windows");
    }
}

void _glfwPlatformShowWindow(_GLFWwindow* window)
{
    if (!window->wl.visible) {
        if (!window->wl.created) {
            create_window_desktop_surface(window);
            window->wl.visible = true;
        } else {
            // workaround for kwin layer shell bug: https://bugs.kde.org/show_bug.cgi?id=503121
            if (is_layer_shell(window)) layer_set_properties(window, false, window->wl.width, window->wl.height);
            window->wl.visible = true;
            commit_window_surface(window);
        }
        debug("Window %llu mapped waiting for configure event from compositor\n", window->id);
    }
}

void _glfwPlatformHideWindow(_GLFWwindow* window)
{
    if (!window->wl.visible) return;
    wl_surface_attach(window->wl.surface, NULL, 0, 0);
    window->wl.once.surface_configured = false;
    window->swaps_disallowed = true;
    window->wl.visible = false;
    commit_window_surface(window);
    debug("Window %llu unmapped\n", window->id);
}

bool
_glfwPlatformSetLayerShellConfig(_GLFWwindow* window, const GLFWLayerShellConfig *value) {
    if (!is_layer_shell(window)) return false;
    if (value) window->wl.layer_shell.config = *value;
    uint32_t width, height;
    calculate_layer_size(window, &width, &height);
    layer_set_properties(window, false, width, height);
    commit_window_surface(window);
    return true;
}

static void
request_attention(GLFWwindow *window, const char *token, void *data UNUSED) {
    if (window && token && token[0] && _glfw.wl.xdg_activation_v1) xdg_activation_v1_activate(_glfw.wl.xdg_activation_v1, token, ((_GLFWwindow*)window)->wl.surface);
}

static bool
has_activation_in_flight(_GLFWwindow* window, GLFWactivationcallback callback) {
    for (size_t i = 0; i < _glfw.wl.activation_requests.sz; i++) {
        glfw_wl_xdg_activation_request *r = _glfw.wl.activation_requests.array + i;
        if (r->window_id == window->id && r->callback == callback) return true;
    }
    return false;
}

void _glfwPlatformRequestWindowAttention(_GLFWwindow* window) {
    if (!has_activation_in_flight(window, request_attention)) get_activation_token(window, 0, request_attention, NULL);
}

int _glfwPlatformWindowBell(_GLFWwindow* window UNUSED)
{
    // TODO: Use an actual Wayland API to implement this when one becomes available
    return false;
}

static void
focus_window(GLFWwindow *window, const char *token, void *data UNUSED) {
    if (!window) return;
    if (token && token[0] && _glfw.wl.xdg_activation_v1) xdg_activation_v1_activate(_glfw.wl.xdg_activation_v1, token, ((_GLFWwindow*)window)->wl.surface);
    else {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: Window focus request via xdg-activation protocol was denied or is unsupported by the compositor. Use a better compositor.");
    }
}

void _glfwPlatformFocusWindow(_GLFWwindow* window UNUSED)
{
    // Attempt to focus the window by using the activation protocol, whether it works
    // is entirely compositor dependent and as we all know Wayland and its ecosystem is
    // the product of morons.
    if (_glfw.wl.input_serial && !has_activation_in_flight(window, focus_window)) get_activation_token(window, _glfw.wl.input_serial, focus_window, NULL);
}

void _glfwPlatformSetWindowMonitor(_GLFWwindow* window,
                                   _GLFWmonitor* monitor,
                                   int xpos UNUSED, int ypos UNUSED,
                                   int width UNUSED, int height UNUSED,
                                   int refreshRate UNUSED)
{
    setFullscreen(window, monitor, monitor != NULL);
    _glfwInputWindowMonitor(window, monitor);
}

int _glfwPlatformWindowFocused(_GLFWwindow* window)
{
    return _glfw.wl.keyboardFocusId == (window ? window->id : 0);
}

int _glfwPlatformWindowOccluded(_GLFWwindow* window UNUSED)
{
#ifdef XDG_TOPLEVEL_STATE_SUSPENDED_SINCE_VERSION
    return (window->wl.current.toplevel_states & TOPLEVEL_STATE_SUSPENDED) != 0;
#endif
    return false;
}

int _glfwPlatformWindowIconified(_GLFWwindow* window UNUSED)
{
    // xdg-shell doesn’t give any way to request whether a surface is
    // iconified.
    return false;
}

int _glfwPlatformWindowVisible(_GLFWwindow* window)
{
    return window->wl.visible;
}

int _glfwPlatformWindowMaximized(_GLFWwindow* window)
{
    return window->wl.current.toplevel_states & TOPLEVEL_STATE_MAXIMIZED;
}

int _glfwPlatformWindowHovered(_GLFWwindow* window)
{
    return window->wl.hovered;
}

int _glfwPlatformFramebufferTransparent(_GLFWwindow* window)
{
    return window->wl.transparent;
}

void _glfwPlatformSetWindowResizable(_GLFWwindow* window UNUSED, bool enabled UNUSED)
{
    // TODO
    _glfwInputError(GLFW_FEATURE_UNIMPLEMENTED,
                    "Wayland: Window attribute setting not implemented yet");
}

void _glfwPlatformSetWindowFloating(_GLFWwindow* window UNUSED, bool enabled UNUSED)
{
    // TODO
    _glfwInputError(GLFW_FEATURE_UNIMPLEMENTED,
                    "Wayland: Window attribute setting not implemented yet");
}

void _glfwPlatformSetWindowMousePassthrough(_GLFWwindow* window, bool enabled)
{
    if (enabled)
    {
        struct wl_region* region = wl_compositor_create_region(_glfw.wl.compositor);
        wl_surface_set_input_region(window->wl.surface, region);
        wl_region_destroy(region);
    }
    else
        wl_surface_set_input_region(window->wl.surface, 0);
    commit_window_surface_if_safe(window);
}

float _glfwPlatformGetWindowOpacity(_GLFWwindow* window UNUSED)
{
    return 1.f;
}

void _glfwPlatformSetWindowOpacity(_GLFWwindow* window UNUSED, float opacity UNUSED)
{
    _glfwInputError(GLFW_FEATURE_UNAVAILABLE,
                    "Wayland: The platform does not support setting the window opacity");
}

void _glfwPlatformSetRawMouseMotion(_GLFWwindow *window UNUSED, bool enabled UNUSED)
{
    // This is handled in relativePointerHandleRelativeMotion
}

bool _glfwPlatformRawMouseMotionSupported(void)
{
    return true;
}

void _glfwPlatformPollEvents(void)
{
    wl_display_dispatch_pending(_glfw.wl.display);
    handleEvents(0);
}

void _glfwPlatformWaitEvents(void)
{
    monotonic_t timeout = wl_display_dispatch_pending(_glfw.wl.display) > 0 ? 0 : -1;
    handleEvents(timeout);
}

void _glfwPlatformWaitEventsTimeout(monotonic_t timeout)
{
    if (wl_display_dispatch_pending(_glfw.wl.display) > 0) timeout = 0;
    handleEvents(timeout);
}

void _glfwPlatformPostEmptyEvent(void)
{
    wakeupEventLoop(&_glfw.wl.eventLoopData);
}

void _glfwPlatformGetCursorPos(_GLFWwindow* window, double* xpos, double* ypos)
{
    if (xpos)
        *xpos = window->wl.cursorPosX;
    if (ypos)
        *ypos = window->wl.cursorPosY;
}

static bool isPointerLocked(_GLFWwindow* window);

void _glfwPlatformSetCursorPos(_GLFWwindow* window, double x, double y)
{
    if (isPointerLocked(window))
    {
        zwp_locked_pointer_v1_set_cursor_position_hint(
            window->wl.pointerLock.lockedPointer,
            wl_fixed_from_double(x), wl_fixed_from_double(y));
        commit_window_surface_if_safe(window);
    }
}

void _glfwPlatformSetCursorMode(_GLFWwindow* window, int mode UNUSED)
{
    _glfwPlatformSetCursor(window, window->wl.currentCursor);
}

const char* _glfwPlatformGetNativeKeyName(int native_key)
{
    return glfw_xkb_keysym_name(native_key);
}

int _glfwPlatformGetNativeKeyForKey(uint32_t key)
{
    return glfw_xkb_sym_for_key(key);
}

int _glfwPlatformCreateCursor(_GLFWcursor* cursor,
                              const GLFWimage* image,
                              int xhot, int yhot, int count UNUSED)
{
    cursor->wl.buffer = createShmBuffer(image, false, true);
    if (!cursor->wl.buffer)
        return false;

    cursor->wl.width = image->width;
    cursor->wl.height = image->height;
    cursor->wl.xhot = xhot;
    cursor->wl.yhot = yhot;
    cursor->wl.scale = -1;
    cursor->wl.shape = GLFW_INVALID_CURSOR;
    return true;
}

int _glfwPlatformCreateStandardCursor(_GLFWcursor* cursor, GLFWCursorShape shape)
{
    // Don't actually load the cursor at this point,
    // because there's not enough info to be properly HiDPI aware.
    cursor->wl.cursor = NULL;
    cursor->wl.currentImage = 0;
    cursor->wl.scale = 0;
    cursor->wl.shape = shape;
    return true;
}

void _glfwPlatformDestroyCursor(_GLFWcursor* cursor)
{
    // If it's a standard cursor we don't need to do anything here
    if (cursor->wl.cursor)
        return;

    if (cursor->wl.buffer)
        wl_buffer_destroy(cursor->wl.buffer);
}

static void relativePointerHandleRelativeMotion(void* data,
                                                struct zwp_relative_pointer_v1* pointer UNUSED,
                                                uint32_t timeHi UNUSED,
                                                uint32_t timeLo UNUSED,
                                                wl_fixed_t dx,
                                                wl_fixed_t dy,
                                                wl_fixed_t dxUnaccel,
                                                wl_fixed_t dyUnaccel)
{
    _GLFWwindow* window = data;
    double xpos = window->virtualCursorPosX;
    double ypos = window->virtualCursorPosY;

    if (window->cursorMode != GLFW_CURSOR_DISABLED)
        return;

    if (window->rawMouseMotion)
    {
        xpos += wl_fixed_to_double(dxUnaccel);
        ypos += wl_fixed_to_double(dyUnaccel);
    }
    else
    {
        xpos += wl_fixed_to_double(dx);
        ypos += wl_fixed_to_double(dy);
    }

    _glfwInputCursorPos(window, xpos, ypos);
}

static const struct zwp_relative_pointer_v1_listener relativePointerListener = {
    relativePointerHandleRelativeMotion
};

static void lockedPointerHandleLocked(void* data UNUSED,
                                      struct zwp_locked_pointer_v1* lockedPointer UNUSED)
{
}

static void unlockPointer(_GLFWwindow* window)
{
    struct zwp_relative_pointer_v1* relativePointer =
        window->wl.pointerLock.relativePointer;
    struct zwp_locked_pointer_v1* lockedPointer =
        window->wl.pointerLock.lockedPointer;

    zwp_relative_pointer_v1_destroy(relativePointer);
    zwp_locked_pointer_v1_destroy(lockedPointer);

    window->wl.pointerLock.relativePointer = NULL;
    window->wl.pointerLock.lockedPointer = NULL;
}

static void lockPointer(_GLFWwindow* window UNUSED);

static void lockedPointerHandleUnlocked(void* data UNUSED,
                                        struct zwp_locked_pointer_v1* lockedPointer UNUSED)
{
}

static const struct zwp_locked_pointer_v1_listener lockedPointerListener = {
    lockedPointerHandleLocked,
    lockedPointerHandleUnlocked
};

static void lockPointer(_GLFWwindow* window)
{
    struct zwp_relative_pointer_v1* relativePointer;
    struct zwp_locked_pointer_v1* lockedPointer;

    if (!_glfw.wl.relativePointerManager)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: no relative pointer manager");
        return;
    }

    relativePointer =
        zwp_relative_pointer_manager_v1_get_relative_pointer(
            _glfw.wl.relativePointerManager,
            _glfw.wl.pointer);
    zwp_relative_pointer_v1_add_listener(relativePointer,
                                         &relativePointerListener,
                                         window);

    lockedPointer =
        zwp_pointer_constraints_v1_lock_pointer(
            _glfw.wl.pointerConstraints,
            window->wl.surface,
            _glfw.wl.pointer,
            NULL,
            ZWP_POINTER_CONSTRAINTS_V1_LIFETIME_PERSISTENT);
    zwp_locked_pointer_v1_add_listener(lockedPointer,
                                       &lockedPointerListener,
                                       window);

    window->wl.pointerLock.relativePointer = relativePointer;
    window->wl.pointerLock.lockedPointer = lockedPointer;

    set_cursor_surface(NULL, 0, 0, "lockPointer");
}

static bool isPointerLocked(_GLFWwindow* window)
{
    return window->wl.pointerLock.lockedPointer != NULL;
}

void _glfwPlatformSetCursor(_GLFWwindow* window, _GLFWcursor* cursor)
{
    if (!_glfw.wl.pointer)
        return;

    window->wl.currentCursor = cursor;

    // If we're not in the correct window just save the cursor
    // the next time the pointer enters the window the cursor will change
    if (window != _glfw.wl.pointerFocus || window->wl.decorations.focus != CENTRAL_WINDOW)
        return;

    // Unlock possible pointer lock if no longer disabled.
    if (window->cursorMode != GLFW_CURSOR_DISABLED && isPointerLocked(window))
        unlockPointer(window);

    if (window->cursorMode == GLFW_CURSOR_NORMAL)
    {
        setCursorImage(window, false);
    }
    else if (window->cursorMode == GLFW_CURSOR_DISABLED)
    {
        if (!isPointerLocked(window))
            lockPointer(window);
    }
    else if (window->cursorMode == GLFW_CURSOR_HIDDEN)
    {
        set_cursor_surface(NULL, 0, 0, "_glfwPlatformSetCursor");
    }
}

static bool
write_all(int fd, const char *data, size_t sz) {
    monotonic_t start = glfwGetTime();
    size_t pos = 0;
    while (pos < sz && glfwGetTime() - start < s_to_monotonic_t(2ll)) {
        ssize_t ret = write(fd, data + pos, sz - pos);
        if (ret < 0) {
            if (errno == EAGAIN || errno == EINTR) continue;
            _glfwInputError(GLFW_PLATFORM_ERROR,
                "Wayland: Could not copy writing to destination fd failed with error: %s", strerror(errno));
            return false;
        }
        if (ret > 0) {
            start = glfwGetTime();
            pos += ret;
        }
    }
    return pos >= sz;
}

static void
send_clipboard_data(const _GLFWClipboardData *cd, const char *mime, int fd) {
    if (strcmp(mime, "text/plain;charset=utf-8") == 0 || strcmp(mime, "UTF8_STRING") == 0 || strcmp(mime, "TEXT") == 0 || strcmp(mime, "STRING") == 0) mime = "text/plain";
    GLFWDataChunk chunk = cd->get_data(mime, NULL, cd->ctype);
    void *iter = chunk.iter;
    if (!iter) return;
    bool keep_going = true;
    while (keep_going) {
        chunk = cd->get_data(mime, iter, cd->ctype);
        if (!chunk.sz) break;
        if (!write_all(fd, chunk.data, chunk.sz)) keep_going = false;
        if (chunk.free) chunk.free((void*)chunk.free_data);
    }
    cd->get_data(NULL, iter, cd->ctype);
}

static void _glfwSendClipboardText(void *data UNUSED, struct wl_data_source *data_source UNUSED, const char *mime_type, int fd) {
    send_clipboard_data(&_glfw.clipboard, mime_type, fd);
    close(fd);
}

static void _glfwSendPrimarySelectionText(void *data UNUSED, struct zwp_primary_selection_source_v1 *primary_selection_source UNUSED,
        const char *mime_type, int fd) {
    send_clipboard_data(&_glfw.primary, mime_type, fd);
    close(fd);
}

static void
read_offer(int data_pipe, GLFWclipboardwritedatafun write_data, void *object) {
    wl_display_flush(_glfw.wl.display);
    struct pollfd fds;
    fds.fd = data_pipe;
    fds.events = POLLIN;
    monotonic_t start = glfwGetTime();
#define bail(...) { \
    _glfwInputError(GLFW_PLATFORM_ERROR, __VA_ARGS__); \
    close(data_pipe); \
    return; \
}

    char buf[8192];

    while (glfwGetTime() - start < s_to_monotonic_t(2ll)) {
        int ret = poll(&fds, 1, 2000);
        if (ret == -1) {
            if (errno == EINTR) continue;
            bail("Wayland: Failed to poll clipboard data from pipe with error: %s", strerror(errno));
        }
        if (!ret) {
            bail("Wayland: Failed to read clipboard data from pipe (timed out)");
        }
        ret = read(data_pipe, buf, sizeof(buf));
        if (ret == -1) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) continue;
            bail("Wayland: Failed to read clipboard data from pipe with error: %s", strerror(errno));
        }
        if (ret == 0) { close(data_pipe); return; }
        if (!write_data(object, buf, ret)) bail("Wayland: call to write_data() failed with data from data offer");
        start = glfwGetTime();
    }
    bail("Wayland: Failed to read clipboard data from pipe (timed out)");
#undef bail
}


typedef struct chunked_writer {
    char *buf; size_t sz, cap;
} chunked_writer;

static bool
write_chunk(void *object, const char *data, size_t sz) {
    chunked_writer *cw = object;
    if (cw->cap < cw->sz + sz) {
        cw->cap = MAX(cw->cap * 2, cw->sz + 8*sz);
        cw->buf = realloc(cw->buf, cw->cap * sizeof(cw->buf[0]));
    }
    memcpy(cw->buf + cw->sz, data, sz);
    cw->sz += sz;
    return true;
}


static char*
read_offer_string(int data_pipe, size_t *sz) {
    chunked_writer cw = {0};
    read_offer(data_pipe, write_chunk, &cw);
    if (cw.buf) {
        *sz = cw.sz;
        return cw.buf;
    }
    *sz = 0;
    return NULL;
}

static void
read_clipboard_data_offer(struct wl_data_offer *data_offer, const char *mime, GLFWclipboardwritedatafun write_data, void *object) {
    int pipefd[2];
    if (pipe2(pipefd, O_CLOEXEC) != 0) return;
    wl_data_offer_receive(data_offer, mime, pipefd[1]);
    close(pipefd[1]);
    read_offer(pipefd[0], write_data, object);
}

static void
read_primary_selection_offer(struct zwp_primary_selection_offer_v1 *primary_selection_offer, const char *mime, GLFWclipboardwritedatafun write_data, void *object) {
    int pipefd[2];
    if (pipe2(pipefd, O_CLOEXEC) != 0) return;
    zwp_primary_selection_offer_v1_receive(primary_selection_offer, mime, pipefd[1]);
    close(pipefd[1]);
    read_offer(pipefd[0], write_data, object);
}

static char* read_data_offer(struct wl_data_offer *data_offer, const char *mime, size_t *sz) {
    int pipefd[2];
    if (pipe2(pipefd, O_CLOEXEC) != 0) return NULL;
    wl_data_offer_receive(data_offer, mime, pipefd[1]);
    close(pipefd[1]);
    return read_offer_string(pipefd[0], sz);
}

static void data_source_canceled(void *data UNUSED, struct wl_data_source *wl_data_source) {
    if (_glfw.wl.dataSourceForClipboard == wl_data_source) {
        _glfw.wl.dataSourceForClipboard = NULL;
        _glfw_free_clipboard_data(&_glfw.clipboard);
        _glfwInputClipboardLost(GLFW_CLIPBOARD);
    }
    wl_data_source_destroy(wl_data_source);
}

static void primary_selection_source_canceled(void *data UNUSED, struct zwp_primary_selection_source_v1 *primary_selection_source) {
    if (_glfw.wl.dataSourceForPrimarySelection == primary_selection_source) {
        _glfw.wl.dataSourceForPrimarySelection = NULL;
        _glfw_free_clipboard_data(&_glfw.primary);
        _glfwInputClipboardLost(GLFW_PRIMARY_SELECTION);
    }
    zwp_primary_selection_source_v1_destroy(primary_selection_source);
}

// KWin aborts if we don't define these even though they are not used for copy/paste
static void dummy_data_source_target(void* data UNUSED, struct wl_data_source* wl_data_source UNUSED, const char* mime_type UNUSED) {
}

static void dummy_data_source_action(void* data UNUSED, struct wl_data_source* wl_data_source UNUSED, uint dnd_action UNUSED) {
}

static const struct wl_data_source_listener data_source_listener = {
    .send = _glfwSendClipboardText,
    .cancelled = data_source_canceled,
    .target = dummy_data_source_target,
    .action = dummy_data_source_action,
};

static const struct zwp_primary_selection_source_v1_listener primary_selection_source_listener = {
    .send = _glfwSendPrimarySelectionText,
    .cancelled = primary_selection_source_canceled,
};

void
destroy_data_offer(_GLFWWaylandDataOffer *offer) {
    if (offer->id) {
        if (offer->is_primary) zwp_primary_selection_offer_v1_destroy(offer->id);
        else wl_data_offer_destroy(offer->id);
    }
    if (offer->mimes) {
        for (size_t i = 0; i < offer->mimes_count; i++) free((char*)offer->mimes[i]);
        free(offer->mimes);
    }
    memset(offer, 0, sizeof(_GLFWWaylandDataOffer));
}

static void prune_unclaimed_data_offers(void) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id && !_glfw.wl.dataOffers[i].offer_type) {
            destroy_data_offer(&_glfw.wl.dataOffers[i]);
        }
    }
}

static void mark_selection_offer(void *data UNUSED, struct wl_data_device *data_device UNUSED, struct wl_data_offer *data_offer)
{
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == data_offer) {
            _glfw.wl.dataOffers[i].offer_type = CLIPBOARD;
        } else if (_glfw.wl.dataOffers[i].offer_type == CLIPBOARD) {
            _glfw.wl.dataOffers[i].offer_type = EXPIRED;  // previous selection offer
        }
    }
    prune_unclaimed_data_offers();
}

static void mark_primary_selection_offer(void *data UNUSED, struct zwp_primary_selection_device_v1* primary_selection_device UNUSED,
        struct zwp_primary_selection_offer_v1 *primary_selection_offer) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == primary_selection_offer) {
            _glfw.wl.dataOffers[i].offer_type = PRIMARY_SELECTION;
        } else if (_glfw.wl.dataOffers[i].offer_type == PRIMARY_SELECTION) {
            _glfw.wl.dataOffers[i].offer_type = EXPIRED;  // previous selection offer
        }
    }
    prune_unclaimed_data_offers();
}

static void
set_offer_mimetype(_GLFWWaylandDataOffer* offer, const char* mime) {
    if (strcmp(mime, clipboard_mime()) == 0) {
        offer->is_self_offer = true;
    }
    if (!offer->mimes || offer->mimes_count >= offer->mimes_capacity - 1) {
        offer->mimes = realloc(offer->mimes, sizeof(char*) * (offer->mimes_capacity + 64));
        if (offer->mimes) offer->mimes_capacity += 64;
        else return;
    }
    offer->mimes[offer->mimes_count++] = _glfw_strdup(mime);
}

static void handle_offer_mimetype(void *data UNUSED, struct wl_data_offer* id, const char *mime) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == id) {
            set_offer_mimetype(&_glfw.wl.dataOffers[i], mime);
            break;
        }
    }
}

static void handle_primary_selection_offer_mimetype(void *data UNUSED, struct zwp_primary_selection_offer_v1* id, const char *mime) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == id) {
            set_offer_mimetype((_GLFWWaylandDataOffer*)&_glfw.wl.dataOffers[i], mime);
            break;
        }
    }
}

static void data_offer_source_actions(void *data UNUSED, struct wl_data_offer* id, uint32_t actions) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == id) {
            _glfw.wl.dataOffers[i].source_actions = actions;
            break;
        }
    }
}

static void data_offer_action(void *data UNUSED, struct wl_data_offer* id, uint32_t action) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == id) {
            _glfw.wl.dataOffers[i].dnd_action = action;
            break;
        }
    }
}


static const struct wl_data_offer_listener data_offer_listener = {
    .offer = handle_offer_mimetype,
    .source_actions = data_offer_source_actions,
    .action = data_offer_action,
};

static const struct zwp_primary_selection_offer_v1_listener primary_selection_offer_listener = {
    .offer = handle_primary_selection_offer_mimetype,
};

static size_t
handle_data_offer_generic(void *id, bool is_primary) {
    size_t smallest_idx = SIZE_MAX, pos = 0;
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].idx && _glfw.wl.dataOffers[i].idx < smallest_idx) {
            smallest_idx = _glfw.wl.dataOffers[i].idx;
            pos = i;
        }
        if (_glfw.wl.dataOffers[i].id == NULL) {
            pos = i;
            goto end;
        }
    }
    if (_glfw.wl.dataOffers[pos].id) destroy_data_offer(&_glfw.wl.dataOffers[pos]);
end:
    _glfw.wl.dataOffers[pos].id = id;
    _glfw.wl.dataOffers[pos].is_primary = is_primary;
    _glfw.wl.dataOffers[pos].idx = ++_glfw.wl.dataOffersCounter;
    return pos;
}

static void handle_data_offer(void *data UNUSED, struct wl_data_device *wl_data_device UNUSED, struct wl_data_offer *id) {
    handle_data_offer_generic(id, false);
    wl_data_offer_add_listener(id, &data_offer_listener, NULL);
}

static void handle_primary_selection_offer(void *data UNUSED, struct zwp_primary_selection_device_v1 *zwp_primary_selection_device_v1 UNUSED, struct zwp_primary_selection_offer_v1 *id) {
    handle_data_offer_generic(id, true);
    zwp_primary_selection_offer_v1_add_listener(id, &primary_selection_offer_listener, NULL);
}

static void drag_enter(void *data UNUSED, struct wl_data_device *wl_data_device UNUSED, uint32_t serial, struct wl_surface *surface, wl_fixed_t x UNUSED, wl_fixed_t y UNUSED, struct wl_data_offer *id) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        _GLFWWaylandDataOffer *d = _glfw.wl.dataOffers + i;
        if (d->id == id) {
            d->offer_type = DRAG_AND_DROP;
            d->surface = surface;
            _GLFWwindow* window = _glfw.windowListHead;
            int format_priority = 0;
            while (window)
            {
                if (window->wl.surface == surface) {
                    for (size_t j = 0; j < d->mimes_count; j++) {
                        int prio = _glfwInputDrop(window, d->mimes[j], NULL, 0);
                        if (prio > format_priority) d->mime_for_drop = d->mimes[j];
                    }
                    break;
                }
                window = window->next;
            }
            wl_data_offer_accept(id, serial, d->mime_for_drop);
        } else if (_glfw.wl.dataOffers[i].offer_type == DRAG_AND_DROP) {
            _glfw.wl.dataOffers[i].offer_type = EXPIRED;  // previous drag offer
        }
    }
    prune_unclaimed_data_offers();
}

static void drag_leave(void *data UNUSED, struct wl_data_device *wl_data_device UNUSED) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].offer_type == DRAG_AND_DROP) {
            destroy_data_offer(&_glfw.wl.dataOffers[i]);
        }
    }
}

static void drop(void *data UNUSED, struct wl_data_device *wl_data_device UNUSED) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].offer_type == DRAG_AND_DROP && _glfw.wl.dataOffers[i].mime_for_drop) {
            size_t sz = 0;
            char *d = read_data_offer(_glfw.wl.dataOffers[i].id, _glfw.wl.dataOffers[i].mime_for_drop, &sz);
            if (d) {
                // We dont do finish as this requires version 3 for wl_data_device_manager
                // which then requires more work with calling set_actions for drag and drop to function
                // wl_data_offer_finish(_glfw.wl.dataOffers[i].id);

                _GLFWwindow* window = _glfw.windowListHead;
                while (window)
                {
                    if (window->wl.surface == _glfw.wl.dataOffers[i].surface) {
                        _glfwInputDrop(window, _glfw.wl.dataOffers[i].mime_for_drop, d, sz);
                        break;
                    }
                    window = window->next;
                }

                free(d);
            }
            destroy_data_offer(&_glfw.wl.dataOffers[i]);
            break;
        }
    }
}

static void motion(void *data UNUSED, struct wl_data_device *wl_data_device UNUSED, uint32_t time UNUSED, wl_fixed_t x UNUSED, wl_fixed_t y UNUSED) {
}

static const struct wl_data_device_listener data_device_listener = {
    .data_offer = handle_data_offer,
    .selection = mark_selection_offer,
    .enter = drag_enter,
    .motion = motion,
    .drop = drop,
    .leave = drag_leave,
};

static const struct zwp_primary_selection_device_v1_listener primary_selection_device_listener = {
    .data_offer = handle_primary_selection_offer,
    .selection = mark_primary_selection_offer,
};


void _glfwSetupWaylandDataDevice(void) {
    _glfw.wl.dataDevice = wl_data_device_manager_get_data_device(_glfw.wl.dataDeviceManager, _glfw.wl.seat);
    if (_glfw.wl.dataDevice) wl_data_device_add_listener(_glfw.wl.dataDevice, &data_device_listener, NULL);
}

void _glfwSetupWaylandPrimarySelectionDevice(void) {
    _glfw.wl.primarySelectionDevice = zwp_primary_selection_device_manager_v1_get_device(_glfw.wl.primarySelectionDeviceManager, _glfw.wl.seat);
    if (_glfw.wl.primarySelectionDevice) zwp_primary_selection_device_v1_add_listener(_glfw.wl.primarySelectionDevice, &primary_selection_device_listener, NULL);
}

static bool _glfwEnsureDataDevice(void) {
    if (!_glfw.wl.dataDeviceManager)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Cannot use clipboard, data device manager is not ready");
        return false;
    }

    if (!_glfw.wl.dataDevice)
    {
        if (!_glfw.wl.seat)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland: Cannot use clipboard, seat is not ready");
            return false;
        }
        if (!_glfw.wl.dataDevice)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland: Cannot use clipboard, failed to create data device");
            return false;
        }
    }
    return true;
}

typedef void(*add_offer_func)(void*, const char *mime);


void
_glfwPlatformSetClipboard(GLFWClipboardType t) {
    _GLFWClipboardData *cd = NULL;
    void *data_source;
    add_offer_func f;
    if (t == GLFW_CLIPBOARD) {
        if (!_glfwEnsureDataDevice()) return;
        cd = &_glfw.clipboard;
        f = (add_offer_func)wl_data_source_offer;
        if (_glfw.wl.dataSourceForClipboard) wl_data_source_destroy(_glfw.wl.dataSourceForClipboard);
        _glfw.wl.dataSourceForClipboard = wl_data_device_manager_create_data_source(_glfw.wl.dataDeviceManager);
        if (!_glfw.wl.dataSourceForClipboard)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland: Cannot copy failed to create data source");
            return;
        }
        wl_data_source_add_listener(_glfw.wl.dataSourceForClipboard, &data_source_listener, NULL);
        data_source = _glfw.wl.dataSourceForClipboard;
    } else {
        if (!_glfw.wl.primarySelectionDevice) {
            static bool warned_about_primary_selection_device = false;
            if (!warned_about_primary_selection_device) {
                _glfwInputError(GLFW_PLATFORM_ERROR,
                                "Wayland: Cannot copy no primary selection device available");
                warned_about_primary_selection_device = true;
            }
            return;
        }
        cd = &_glfw.primary;
        f = (add_offer_func)zwp_primary_selection_source_v1_offer;
        if (_glfw.wl.dataSourceForPrimarySelection) zwp_primary_selection_source_v1_destroy(_glfw.wl.dataSourceForPrimarySelection);
        _glfw.wl.dataSourceForPrimarySelection = zwp_primary_selection_device_manager_v1_create_source(_glfw.wl.primarySelectionDeviceManager);
        if (!_glfw.wl.dataSourceForPrimarySelection)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland: Cannot copy failed to create primary selection source");
            return;
        }
        zwp_primary_selection_source_v1_add_listener(_glfw.wl.dataSourceForPrimarySelection, &primary_selection_source_listener, NULL);
        data_source = _glfw.wl.dataSourceForPrimarySelection;
    }
    f(data_source, clipboard_mime());
    for (size_t i = 0; i < cd->num_mime_types; i++) {
        if (strcmp(cd->mime_types[i], "text/plain") == 0) {
            f(data_source, "TEXT");
            f(data_source, "STRING");
            f(data_source, "UTF8_STRING");
            f(data_source, "text/plain;charset=utf-8");
        }
        f(data_source, cd->mime_types[i]);
    }
    if (t == GLFW_CLIPBOARD) {
        // According to some interpretations of the Wayland spec only the application that has keyboard focus can set the clipboard.
        // Hurray for the Wayland nanny state!
        //
        // However in wl-roots based compositors, using the serial from the keyboard enter event doesn't work. No clue what
        // the correct serial to use here is. Given this Wayland there probably isn't one. What a joke.
        // Bug report: https://github.com/kovidgoyal/kitty/issues/6890
        // Ironically one of the contributors to wl_roots claims the keyboard enter serial is the correct one to use:
        // https://emersion.fr/blog/2020/wayland-clipboard-drag-and-drop/
        // The Wayland spec itself says "serial number of the event that triggered this request"
        // https://wayland.freedesktop.org/docs/html/apa.html#protocol-spec-wl_data_device
        // So who the fuck knows. Just use the latest received serial and ask anybody that uses Wayland
        // to get their head examined.
        wl_data_device_set_selection(_glfw.wl.dataDevice, _glfw.wl.dataSourceForClipboard, _glfw.wl.serial);
    } else {
        // According to the Wayland spec we can only set the primary selection in response to a pointer button event
        // Hurray for the Wayland nanny state!
        zwp_primary_selection_device_v1_set_selection(
                _glfw.wl.primarySelectionDevice, _glfw.wl.dataSourceForPrimarySelection, _glfw.wl.pointer_serial);
    }
}

static bool
offer_has_mime(const _GLFWWaylandDataOffer *d, const char *mime) {
    for (unsigned i = 0; i < d->mimes_count; i++) {
        if (strcmp(d->mimes[i], mime) == 0) return true;
    }
    return false;
}

static const char*
plain_text_mime_for_offer(const _GLFWWaylandDataOffer *d) {
#define A(x) if (offer_has_mime(d, x)) return x;
    A("text/plain;charset=utf-8");
    A("text/plain");
    A("UTF8_STRING");
    A("STRING");
    A("TEXT");
#undef A
    return NULL;
}

void
_glfwPlatformGetClipboard(GLFWClipboardType clipboard_type, const char* mime_type, GLFWclipboardwritedatafun write_data, void *object) {
    _GLFWWaylandOfferType offer_type = clipboard_type == GLFW_PRIMARY_SELECTION ? PRIMARY_SELECTION : CLIPBOARD;
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        _GLFWWaylandDataOffer *d = _glfw.wl.dataOffers + i;
        if (d->id && d->offer_type == offer_type) {
            if (d->is_self_offer) {
                write_data(object, NULL, 1);
                return;
            }
            if (mime_type == NULL) {
                bool ok = true;
                for (size_t o = 0; o < d->mimes_count; o++) {
                    const char *q = d->mimes[o];
                    if (strchr(d->mimes[0], '/')) {
                        if (strcmp(q, clipboard_mime()) == 0) continue;
                        if (strcmp(q, "text/plain;charset=utf-8") == 0) q = "text/plain";
                    } else {
                        if (strcmp(q, "UTF8_STRING") == 0 || strcmp(q, "STRING") == 0 || strcmp(q, "TEXT") == 0) q = "text/plain";
                    }
                    if (ok) ok = write_data(object, q, strlen(q));
                }
                return;
            }
            if (strcmp(mime_type, "text/plain") == 0) {
                mime_type = plain_text_mime_for_offer(d);
                if (!mime_type) return;
            }
            if (d->is_primary) {
                read_primary_selection_offer(d->id, mime_type, write_data, object);
            } else {
                read_clipboard_data_offer(d->id, mime_type, write_data, object);
            }
            break;
        }
    }
}

EGLenum _glfwPlatformGetEGLPlatform(EGLint** attribs UNUSED)
{
    if (_glfw.egl.EXT_platform_base && _glfw.egl.EXT_platform_wayland)
        return EGL_PLATFORM_WAYLAND_EXT;
    else
        return 0;
}

EGLNativeDisplayType _glfwPlatformGetEGLNativeDisplay(void)
{
    return _glfw.wl.display;
}

EGLNativeWindowType _glfwPlatformGetEGLNativeWindow(_GLFWwindow* window)
{
    return window->wl.native;
}

void _glfwPlatformGetRequiredInstanceExtensions(char** extensions)
{
    if (!_glfw.vk.KHR_surface || !_glfw.vk.KHR_wayland_surface)
        return;

    extensions[0] = "VK_KHR_surface";
    extensions[1] = "VK_KHR_wayland_surface";
}

int _glfwPlatformGetPhysicalDevicePresentationSupport(VkInstance instance,
                                                      VkPhysicalDevice device,
                                                      uint32_t queuefamily)
{
    PFN_vkGetPhysicalDeviceWaylandPresentationSupportKHR
        vkGetPhysicalDeviceWaylandPresentationSupportKHR =
        (PFN_vkGetPhysicalDeviceWaylandPresentationSupportKHR)
        vkGetInstanceProcAddr(instance, "vkGetPhysicalDeviceWaylandPresentationSupportKHR");
    if (!vkGetPhysicalDeviceWaylandPresentationSupportKHR)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE,
                        "Wayland: Vulkan instance missing VK_KHR_wayland_surface extension");
        return VK_NULL_HANDLE;
    }

    return vkGetPhysicalDeviceWaylandPresentationSupportKHR(device,
                                                            queuefamily,
                                                            _glfw.wl.display);
}

VkResult _glfwPlatformCreateWindowSurface(VkInstance instance,
                                          _GLFWwindow* window,
                                          const VkAllocationCallbacks* allocator,
                                          VkSurfaceKHR* surface)
{
    VkResult err;
    VkWaylandSurfaceCreateInfoKHR sci;
    PFN_vkCreateWaylandSurfaceKHR vkCreateWaylandSurfaceKHR;

    vkCreateWaylandSurfaceKHR = (PFN_vkCreateWaylandSurfaceKHR)
        vkGetInstanceProcAddr(instance, "vkCreateWaylandSurfaceKHR");
    if (!vkCreateWaylandSurfaceKHR)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE,
                        "Wayland: Vulkan instance missing VK_KHR_wayland_surface extension");
        return VK_ERROR_EXTENSION_NOT_PRESENT;
    }

    memset(&sci, 0, sizeof(sci));
    sci.sType = VK_STRUCTURE_TYPE_WAYLAND_SURFACE_CREATE_INFO_KHR;
    sci.display = _glfw.wl.display;
    sci.surface = window->wl.surface;

    err = vkCreateWaylandSurfaceKHR(instance, &sci, allocator, surface);
    if (err)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to create Vulkan surface: %s",
                        _glfwGetVulkanResultString(err));
    }

    return err;
}

static void
frame_handle_redraw(void *data, struct wl_callback *callback, uint32_t time UNUSED) {
    _GLFWwindow* window = (_GLFWwindow*) data;
    if (callback == window->wl.frameCallbackData.current_wl_callback) {
        window->wl.frameCallbackData.callback(window->wl.frameCallbackData.id);
        window->wl.frameCallbackData.current_wl_callback = NULL;
    }
    wl_callback_destroy(callback);
}

void
_glfwPlatformChangeCursorTheme(void) {
    glfw_wlc_destroy();
    _GLFWwindow *w = _glfw.windowListHead;
    while (w) {
        setCursorImage(w, true);
        w = w->next;
    }

}

int
_glfwPlatformSetWindowBlur(_GLFWwindow *window, int blur_radius) {
    if (!window->wl.transparent) return 0;
    bool has_blur = window->wl.has_blur;
    bool new_has_blur = blur_radius > 0;
    if (new_has_blur != has_blur) {
        window->wl.has_blur = new_has_blur;
        update_regions(window);
    }
    return has_blur ? 1 : 0;
}

bool
_glfwPlatformGrabKeyboard(bool grab) {
    if (!_glfw.wl.keyboard_shortcuts_inhibit_manager) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "The Wayland compositor does not implement inhibit-keyboard-shortcuts, cannot grab keyboard");
        return false;
    }
    for (_GLFWwindow* window = _glfw.windowListHead; window; window = window->next) inhibit_shortcuts_for(window, grab);
    return true;
}

//////////////////////////////////////////////////////////////////////////
//////                        GLFW native API                       //////
//////////////////////////////////////////////////////////////////////////

GLFWAPI struct wl_display* glfwGetWaylandDisplay(void)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    return _glfw.wl.display;
}

GLFWAPI struct wl_surface* glfwGetWaylandWindow(GLFWwindow* handle)
{
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    return window->wl.surface;
}

GLFWAPI void glfwWaylandActivateWindow(GLFWwindow* handle, const char *activation_token) {
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT();
    if (activation_token && activation_token[0] && _glfw.wl.xdg_activation_v1) xdg_activation_v1_activate(_glfw.wl.xdg_activation_v1, activation_token, window->wl.surface);
}

GLFWAPI void glfwWaylandRunWithActivationToken(GLFWwindow *handle, GLFWactivationcallback cb, void *cb_data) {
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT();
    get_activation_token(window, _glfw.wl.input_serial, cb, cb_data);
}

GLFWAPI int glfwGetNativeKeyForName(const char* keyName, bool caseSensitive) {
    return glfw_xkb_keysym_from_name(keyName, caseSensitive);
}

GLFWAPI void glfwRequestWaylandFrameEvent(GLFWwindow *handle, unsigned long long id, void(*callback)(unsigned long long id)) {
    _GLFWwindow* window = (_GLFWwindow*) handle;
    static const struct wl_callback_listener frame_listener = { .done = frame_handle_redraw };
    if (window->wl.frameCallbackData.current_wl_callback) wl_callback_destroy(window->wl.frameCallbackData.current_wl_callback);
    if (window->wl.waiting_for_swap_to_commit) {
        callback(id);
        window->wl.frameCallbackData.id = 0;
        window->wl.frameCallbackData.callback = NULL;
        window->wl.frameCallbackData.current_wl_callback = NULL;
    } else {
        window->wl.frameCallbackData.id = id;
        window->wl.frameCallbackData.callback = callback;
        window->wl.frameCallbackData.current_wl_callback = wl_surface_frame(window->wl.surface);
        if (window->wl.frameCallbackData.current_wl_callback) {
            wl_callback_add_listener(window->wl.frameCallbackData.current_wl_callback, &frame_listener, window);
            commit_window_surface_if_safe(window);
        }
    }
}

GLFWAPI unsigned long long glfwDBusUserNotify(const GLFWDBUSNotificationData *n, GLFWDBusnotificationcreatedfun callback, void *data) {
    return glfw_dbus_send_user_notification(n, callback, data);
}

GLFWAPI void glfwDBusSetUserNotificationHandler(GLFWDBusnotificationactivatedfun handler) {
    glfw_dbus_set_user_notification_activated_handler(handler);
}

GLFWAPI bool glfwWaylandSetTitlebarColor(GLFWwindow *handle, uint32_t color, bool use_system_color) {
    _GLFWwindow* window = (_GLFWwindow*) handle;
    if (!window->wl.decorations.serverSide) {
        csd_set_titlebar_color(window, color, use_system_color);
        return true;
    }
    return false;
}

GLFWAPI void glfwWaylandRedrawCSDWindowTitle(GLFWwindow *handle) {
    _GLFWwindow* window = (_GLFWwindow*) handle;
    if (csd_change_title(window)) commit_window_surface_if_safe(window);
}

const GLFWLayerShellConfig*
_glfwPlatformGetLayerShellConfig(_GLFWwindow *window) {
    return &window->wl.layer_shell.config;
}

GLFWAPI bool glfwIsLayerShellSupported(void) { return _glfw.wl.zwlr_layer_shell_v1 != NULL; }

GLFWAPI bool glfwWaylandIsWindowFullyCreated(GLFWwindow *handle) { return handle != NULL && ((_GLFWwindow*)handle)->wl.window_fully_created; }

void
_glfwPlatformInputColorScheme(GLFWColorScheme appearance UNUSED) {
    _GLFWwindow* window = _glfw.windowListHead;
    while (window) {
        glfwWaylandRedrawCSDWindowTitle((GLFWwindow*)window);
        window = window->next;
    }
}

GLFWAPI bool glfwWaylandBeep(GLFWwindow *handle) {
    if (!_glfw.wl.xdg_system_bell_v1) return false;
    _GLFWwindow *window = (_GLFWwindow*)handle;
    xdg_system_bell_v1_ring(_glfw.wl.xdg_system_bell_v1, window ? window->wl.surface : NULL);
    return true;
}

