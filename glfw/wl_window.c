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
#include "memfd.h"
#include "linux_notify.h"
#include "wl_client_side_decorations.h"
#include "../kitty/monotonic.h"

#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>
#include <sys/mman.h>

#define debug(...) if (_glfw.hints.init.debugRendering) fprintf(stderr, __VA_ARGS__);

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

static struct wl_buffer* createShmBuffer(const GLFWimage* image, bool is_opaque, bool init_data)
{
    struct wl_shm_pool* pool;
    struct wl_buffer* buffer;
    int stride = image->width * 4;
    int length = image->width * image->height * 4;
    void* data;
    int fd, i;

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
    if (init_data) {
        unsigned char* source = (unsigned char*) image->pixels;
        unsigned char* target = data;
        for (i = 0;  i < image->width * image->height;  i++, source += 4)
        {
            unsigned int alpha = source[3];

            *target++ = (unsigned char) ((source[2] * alpha) / 255);
            *target++ = (unsigned char) ((source[1] * alpha) / 255);
            *target++ = (unsigned char) ((source[0] * alpha) / 255);
            *target++ = (unsigned char) alpha;
        }
    }

    buffer =
        wl_shm_pool_create_buffer(pool, 0,
                                  image->width,
                                  image->height,
                                  stride, is_opaque ? WL_SHM_FORMAT_XRGB8888 : WL_SHM_FORMAT_ARGB8888);
    munmap(data, length);
    wl_shm_pool_destroy(pool);

    return buffer;
}

static void
setCursorImage(_GLFWwindow* window, bool on_theme_change) {
    _GLFWcursorWayland defaultCursor = {.shape = GLFW_ARROW_CURSOR};
    _GLFWcursorWayland* cursorWayland = window->cursor ? &window->cursor->wl : &defaultCursor;
    struct wl_cursor_image* image = NULL;
    struct wl_buffer* buffer = NULL;
    struct wl_surface* surface = _glfw.wl.cursorSurface;
    const int scale = window->wl.scale;

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
        if (!cursorWayland->cursor || !cursorWayland->cursor->image_count)
            return;
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

    debug("Calling wl_pointer_set_cursor in setCursorImage with surface: %p\n", (void*)surface);
    wl_pointer_set_cursor(_glfw.wl.pointer, _glfw.wl.serial,
                          surface,
                          cursorWayland->xhot / scale,
                          cursorWayland->yhot / scale);
    wl_surface_set_buffer_scale(surface, scale);
    wl_surface_attach(surface, buffer, 0, 0);
    wl_surface_damage(surface, 0, 0,
                      cursorWayland->width, cursorWayland->height);
    wl_surface_commit(surface);
}


static bool checkScaleChange(_GLFWwindow* window)
{
    int scale = 1;
    int i;
    int monitorScale;

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
        if (m && m->wl.scale > scale) scale = m->wl.scale;
    }

    // Only change the framebuffer size if the scale changed.
    if (scale != window->wl.scale)
    {
        window->wl.scale = scale;
        wl_surface_set_buffer_scale(window->wl.surface, scale);
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
commit_window_surface_if_safe(_GLFWwindow *window) {
    // we only commit if the buffer attached to the surface is the correct size,
    // which means that at least one frame is drawn after resizeFramebuffer()
    if (!window->wl.waiting_for_swap_to_commit) {
        wl_surface_commit(window->wl.surface);
    }
}

// Makes the surface considered as XRGB instead of ARGB.
static void setOpaqueRegion(_GLFWwindow* window, bool commit_surface)
{
    struct wl_region* region;

    region = wl_compositor_create_region(_glfw.wl.compositor);
    if (!region)
        return;

    wl_region_add(region, 0, 0, window->wl.width, window->wl.height);
    wl_surface_set_opaque_region(window->wl.surface, region);
    if (commit_surface) commit_window_surface_if_safe(window);
    wl_region_destroy(region);
}


static void
resizeFramebuffer(_GLFWwindow* window) {
    int scale = window->wl.scale;
    int scaledWidth = window->wl.width * scale;
    int scaledHeight = window->wl.height * scale;
    debug("Resizing framebuffer to: %dx%d at scale: %d\n", window->wl.width, window->wl.height, scale);
    wl_egl_window_resize(window->wl.native, scaledWidth, scaledHeight, 0, 0);
    if (!window->wl.transparent) setOpaqueRegion(window, false);
    window->wl.waiting_for_swap_to_commit = true;
    _glfwInputFramebufferSize(window, scaledWidth, scaledHeight);
}

void
_glfwWaylandAfterBufferSwap(_GLFWwindow* window) {
    if (window->wl.waiting_for_swap_to_commit) {
        debug("Waiting for swap to commit: swap has happened\n");
        window->wl.waiting_for_swap_to_commit = false;
        // this is not really needed, since I think eglSwapBuffers() calls wl_surface_commit()
        // but lets be safe. See https://gitlab.freedesktop.org/mesa/mesa/-/blob/main/src/egl/drivers/dri2/platform_wayland.c#L1510
        wl_surface_commit(window->wl.surface);
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
        debug("Scale changed to %d in dispatchChangesAfterConfigure\n", window->wl.scale);
        if (!size_changed) resizeFramebuffer(window);
        _glfwInputWindowContentScale(window, window->wl.scale, window->wl.scale);
    }

    _glfwInputWindowDamage(window);

    return size_changed || scale_changed;
}

static void
inform_compositor_of_window_geometry(_GLFWwindow *window, const char *event) {
#define geometry window->wl.decorations.geometry
    debug("Setting window geometry in %s event: x=%d y=%d %dx%d\n", event, geometry.x, geometry.y, geometry.width, geometry.height);
    xdg_surface_set_window_geometry(window->wl.xdg.surface, geometry.x, geometry.y, geometry.width, geometry.height);
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
    debug("XDG decoration configure event received: has_server_side_decorations: %d\n", (mode == ZXDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE));
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
        debug("Scale changed to %d in surface enter event\n", window->wl.scale);
        resizeFramebuffer(window);
        _glfwInputWindowContentScale(window, window->wl.scale, window->wl.scale);
        ensure_csd_resources(window);
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
        debug("Scale changed to %d in surface leave event\n", window->wl.scale);
        resizeFramebuffer(window);
        _glfwInputWindowContentScale(window, window->wl.scale, window->wl.scale);
        ensure_csd_resources(window);
    }
}

static const struct wl_surface_listener surfaceListener = {
    surfaceHandleEnter,
    surfaceHandleLeave
};

static void setIdleInhibitor(_GLFWwindow* window, bool enable)
{
    if (enable && !window->wl.idleInhibitor && _glfw.wl.idleInhibitManager)
    {
        window->wl.idleInhibitor =
            zwp_idle_inhibit_manager_v1_create_inhibitor(
                _glfw.wl.idleInhibitManager, window->wl.surface);
        if (!window->wl.idleInhibitor)
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland: Idle inhibitor creation failed");
    }
    else if (!enable && window->wl.idleInhibitor)
    {
        zwp_idle_inhibitor_v1_destroy(window->wl.idleInhibitor);
        window->wl.idleInhibitor = NULL;
    }
}

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

    debug("Creating window at size: %dx%d and scale %d\n", wndconfig->width, wndconfig->height, scale);
    window->wl.native = wl_egl_window_create(window->wl.surface, wndconfig->width * scale, wndconfig->height * scale);
    if (!window->wl.native)
        return false;

    window->wl.width = wndconfig->width;
    window->wl.height = wndconfig->height;
    window->wl.user_requested_content_size.width = wndconfig->width;
    window->wl.user_requested_content_size.height = wndconfig->height;

    window->wl.scale = scale;

    if (!window->wl.transparent)
        setOpaqueRegion(window, false);

    wl_surface_set_buffer_scale(window->wl.surface, scale);
    return true;
}

static void setFullscreen(_GLFWwindow* window, _GLFWmonitor* monitor, bool on)
{
    if (window->wl.xdg.toplevel)
    {
        if (on) {
            xdg_toplevel_set_fullscreen(
                window->wl.xdg.toplevel,
                monitor ? monitor->wl.output : NULL);
            if (!window->wl.decorations.serverSide) free_csd_surfaces(window);
        } else {
            xdg_toplevel_unset_fullscreen(window->wl.xdg.toplevel);
            ensure_csd_resources(window);
        }
    }
    setIdleInhibitor(window, on);
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
    debug("top-level configure event: size: %dx%d states: ", width, height);

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
#undef C
        }
    }
    debug("\n");
    if (new_states & TOPLEVEL_STATE_RESIZING) {
        if (width) window->wl.user_requested_content_size.width = width;
        if (height) window->wl.user_requested_content_size.height = height;
        if (!(window->wl.current.toplevel_states & TOPLEVEL_STATE_RESIZING)) _glfwInputLiveResize(window, true);
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
    _glfwInputWindowCloseRequest(window);
}

static const struct xdg_toplevel_listener xdgToplevelListener = {
    xdgToplevelHandleConfigure,
    xdgToplevelHandleClose
};

static void xdgSurfaceHandleConfigure(void* data,
                                      struct xdg_surface* surface,
                                      uint32_t serial)
{
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
    if (window->wl.pending_state & PENDING_STATE_TOPLEVEL) {
        uint32_t new_states = window->wl.pending.toplevel_states;
        int width = window->wl.pending.width;
        int height = window->wl.pending.height;
        if (!window->wl.surface_configured_once) {
            window->swaps_disallowed = false;
            window->wl.waiting_for_swap_to_commit = true;
            window->wl.surface_configured_once = true;
        }

        if (new_states != window->wl.current.toplevel_states ||
                width != window->wl.current.width ||
                height != window->wl.current.height) {

            bool live_resize_done = !(new_states & TOPLEVEL_STATE_RESIZING) && (window->wl.current.toplevel_states & TOPLEVEL_STATE_RESIZING);
            window->wl.current.toplevel_states = new_states;
            window->wl.current.width = width;
            window->wl.current.height = height;
            _glfwInputWindowFocus(window, window->wl.current.toplevel_states & TOPLEVEL_STATE_ACTIVATED);
            if (live_resize_done) _glfwInputLiveResize(window, false);
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
        set_csd_window_geometry(window, &width, &height);
        bool resized = dispatchChangesAfterConfigure(window, width, height);
        if (window->wl.decorations.serverSide || window->monitor || window->wl.current.toplevel_states & TOPLEVEL_STATE_FULLSCREEN) {
            free_csd_surfaces(window);
        } else {
            ensure_csd_resources(window);
        }
        debug("final window content size: %dx%d resized: %d\n", width, height, resized);
    }

    inform_compositor_of_window_geometry(window, "configure");
    commit_window_surface_if_safe(window);
    window->wl.pending_state = 0;
}

static const struct xdg_surface_listener xdgSurfaceListener = {
    xdgSurfaceHandleConfigure
};

static void
setXdgDecorations(_GLFWwindow* window)
{
    if (_glfw.wl.decorationManager)
    {
        window->wl.decorations.serverSide = true;
        window->wl.xdg.decoration =
            zxdg_decoration_manager_v1_get_toplevel_decoration(
                _glfw.wl.decorationManager, window->wl.xdg.toplevel);
        zxdg_toplevel_decoration_v1_add_listener(window->wl.xdg.decoration,
                                                 &xdgDecorationListener,
                                                 window);
        zxdg_toplevel_decoration_v1_set_mode(
            window->wl.xdg.decoration,
            ZXDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
    }
    else
    {
        window->wl.decorations.serverSide = false;
        ensure_csd_resources(window);
    }
}

static bool
createXdgSurface(_GLFWwindow* window)
{
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

    xdg_toplevel_add_listener(window->wl.xdg.toplevel,
                              &xdgToplevelListener,
                              window);

    if (window->wl.title)
        xdg_toplevel_set_title(window->wl.xdg.toplevel, window->wl.title);

    if (window->minwidth != GLFW_DONT_CARE && window->minheight != GLFW_DONT_CARE)
        xdg_toplevel_set_min_size(window->wl.xdg.toplevel,
                                  window->minwidth, window->minheight);
    if (window->maxwidth != GLFW_DONT_CARE && window->maxheight != GLFW_DONT_CARE)
        xdg_toplevel_set_max_size(window->wl.xdg.toplevel,
                                  window->maxwidth, window->maxheight);

    if (window->monitor)
    {
        xdg_toplevel_set_fullscreen(window->wl.xdg.toplevel,
                                    window->monitor->wl.output);
        setIdleInhibitor(window, true);
    }
    else if (window->wl.maximize_on_first_show)
    {
        window->wl.maximize_on_first_show = false;
        xdg_toplevel_set_maximized(window->wl.xdg.toplevel);
        setIdleInhibitor(window, false);
        setXdgDecorations(window);
    }
    else
    {
        setIdleInhibitor(window, false);
        setXdgDecorations(window);
    }
    if (strlen(window->wl.appId))
        xdg_toplevel_set_app_id(window->wl.xdg.toplevel, window->wl.appId);

    wl_surface_commit(window->wl.surface);
    wl_display_roundtrip(_glfw.wl.display);

    return true;
}

static void incrementCursorImage(_GLFWwindow* window)
{
    if (window && window->wl.decorations.focus == CENTRAL_WINDOW && window->cursorMode != GLFW_CURSOR_HIDDEN) {
        _GLFWcursor* cursor = window->wl.currentCursor;
        if (cursor && cursor->wl.cursor)
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
        C(GLFW_ARROW_CURSOR, "left_ptr", "arrow", "default")
        C(GLFW_IBEAM_CURSOR, "xterm", "ibeam", "text")
        C(GLFW_CROSSHAIR_CURSOR, "crosshair", "cross")
        C(GLFW_HAND_CURSOR, "hand2", "grab", "grabbing", "closedhand")
        C(GLFW_HRESIZE_CURSOR, "sb_h_double_arrow", "h_double_arrow", "col-resize")
        C(GLFW_VRESIZE_CURSOR, "sb_v_double_arrow", "v_double_arrow", "row-resize")
        C(GLFW_NW_RESIZE_CURSOR, "top_left_corner", "nw-resize")
        C(GLFW_NE_RESIZE_CURSOR, "top_right_corner", "ne-resize")
        C(GLFW_SW_RESIZE_CURSOR, "bottom_left_corner", "sw-resize")
        C(GLFW_SE_RESIZE_CURSOR, "bottom_right_corner", "se-resize")
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

int _glfwPlatformCreateWindow(_GLFWwindow* window,
                              const _GLFWwndconfig* wndconfig,
                              const _GLFWctxconfig* ctxconfig,
                              const _GLFWfbconfig* fbconfig)
{
    initialize_csd_metrics(window);
    window->wl.transparent = fbconfig->transparent;
    strncpy(window->wl.appId, wndconfig->wl.appId, sizeof(window->wl.appId));
    window->swaps_disallowed = true;

    if (!createSurface(window, wndconfig))
        return false;

    if (ctxconfig->client != GLFW_NO_API)
    {
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
    }

    if (wndconfig->title)
        window->wl.title = _glfw_strdup(wndconfig->title);
    if (wndconfig->maximized)
        window->wl.maximize_on_first_show = true;

    if (wndconfig->visible)
    {
        if (!createXdgSurface(window))
            return false;

        window->wl.visible = true;
    }
    else
    {
        window->wl.xdg.surface = NULL;
        window->wl.xdg.toplevel = NULL;
        window->wl.visible = false;
    }

    window->wl.currentCursor = NULL;
    // Don't set window->wl.cursorTheme to NULL here.

    window->wl.monitors = calloc(1, sizeof(_GLFWmonitor*));
    window->wl.monitorsCount = 0;
    window->wl.monitorsSize = 1;

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

    if (window->wl.idleInhibitor)
        zwp_idle_inhibitor_v1_destroy(window->wl.idleInhibitor);

    if (window->context.destroy)
        window->context.destroy(window);

    free_all_csd_resources(window);
    if (window->wl.xdg.decoration)
        zxdg_toplevel_decoration_v1_destroy(window->wl.xdg.decoration);

    if (window->wl.native)
        wl_egl_window_destroy(window->wl.native);

    if (window->wl.xdg.toplevel)
        xdg_toplevel_destroy(window->wl.xdg.toplevel);

    if (window->wl.xdg.surface)
        xdg_surface_destroy(window->wl.xdg.surface);

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
    if (window->wl.xdg.toplevel) xdg_toplevel_set_title(window->wl.xdg.toplevel, window->wl.title);
    change_csd_title(window);
}

void _glfwPlatformSetWindowIcon(_GLFWwindow* window UNUSED,
                                int count UNUSED, const GLFWimage* images UNUSED)
{
    _glfwInputError(GLFW_FEATURE_UNAVAILABLE,
                    "Wayland: The platform does not support setting the window icon");
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
    if (width != window->wl.width || height != window->wl.height) {
        window->wl.user_requested_content_size.width = width;
        window->wl.user_requested_content_size.height = height;
        int32_t w = 0, h = 0;
        set_csd_window_geometry(window, &w, &h);
        window->wl.width = w; window->wl.height = h;
        resizeFramebuffer(window);
        ensure_csd_resources(window);
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
    if (width)
        *width *= window->wl.scale;
    if (height)
        *height *= window->wl.scale;
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
    if (xscale)
        *xscale = (float) window->wl.scale;
    if (yscale)
        *yscale = (float) window->wl.scale;
}

monotonic_t _glfwPlatformGetDoubleClickInterval(_GLFWwindow* window UNUSED)
{
    return ms_to_monotonic_t(500ll);
}

void _glfwPlatformIconifyWindow(_GLFWwindow* window)
{
    if (window->wl.xdg.toplevel)
        xdg_toplevel_set_minimized(window->wl.xdg.toplevel);
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
    if (window->wl.xdg.toplevel)
    {
        xdg_toplevel_set_maximized(window->wl.xdg.toplevel);
    }
}

void _glfwPlatformShowWindow(_GLFWwindow* window)
{
    if (!window->wl.visible)
    {
        createXdgSurface(window);
        window->wl.visible = true;
    }
}

void _glfwPlatformHideWindow(_GLFWwindow* window)
{
    if (window->wl.xdg.toplevel)
    {
        xdg_toplevel_destroy(window->wl.xdg.toplevel);
        xdg_surface_destroy(window->wl.xdg.surface);
        window->wl.xdg.toplevel = NULL;
        window->wl.xdg.surface = NULL;
        window->wl.surface_configured_once = false;
        window->swaps_disallowed = true;
    }
    window->wl.visible = false;
}

static void
request_attention(GLFWwindow *window, const char *token, void *data UNUSED) {
    if (window && token && token[0]) xdg_activation_v1_activate(_glfw.wl.xdg_activation_v1, token, ((_GLFWwindow*)window)->wl.surface);
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
    if (token && token[0]) xdg_activation_v1_activate(_glfw.wl.xdg_activation_v1, token, ((_GLFWwindow*)window)->wl.surface);
    else {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: Window focus request via xdg-activation protocol was denied by the compositor. Use a better compositor.");
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
    return _glfw.wl.keyboardFocusId = window ? window->id : 0;
}

int _glfwPlatformWindowOccluded(_GLFWwindow* window UNUSED)
{
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

void _glfwPlatformSetWindowDecorated(_GLFWwindow* window, bool enabled)
{
    if (!window->monitor)
    {
        if (enabled)
            ensure_csd_resources(window);
        else
            free_csd_surfaces(window);
    }
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

    debug("Calling wl_pointer_set_cursor in lockPointer with surface: %p\n", NULL);
    wl_pointer_set_cursor(_glfw.wl.pointer, _glfw.wl.serial,
                          NULL, 0, 0);
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
        debug("Calling wl_pointer_set_cursor in _glfwPlatformSetCursor with surface: %p\n", NULL);
        wl_pointer_set_cursor(_glfw.wl.pointer, _glfw.wl.serial, NULL, 0, 0);
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
    }
    wl_data_source_destroy(wl_data_source);
}

static void primary_selection_source_canceled(void *data UNUSED, struct zwp_primary_selection_source_v1 *primary_selection_source) {
    if (_glfw.wl.dataSourceForPrimarySelection == primary_selection_source) {
        _glfw.wl.dataSourceForPrimarySelection = NULL;
        _glfw_free_clipboard_data(&_glfw.primary);
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


static void
clipboard_copy_callback_done(void *data, struct wl_callback *callback, uint32_t serial) {
    if (_glfw.wl.dataDevice && data == (void*)_glfw.wl.dataSourceForClipboard) {
        wl_data_device_set_selection(_glfw.wl.dataDevice, data, serial);
    }
    wl_callback_destroy(callback);
}

static void
primary_selection_copy_callback_done(void *data, struct wl_callback *callback, uint32_t serial) {
    if (_glfw.wl.primarySelectionDevice && data == (void*)_glfw.wl.dataSourceForPrimarySelection) {
        zwp_primary_selection_device_v1_set_selection(_glfw.wl.primarySelectionDevice, data, serial);
    }
    wl_callback_destroy(callback);
}

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
    struct wl_callback *callback = wl_display_sync(_glfw.wl.display);
    if (t == GLFW_CLIPBOARD) {
        static const struct wl_callback_listener clipboard_copy_callback_listener = {.done = clipboard_copy_callback_done};
        wl_callback_add_listener(callback, &clipboard_copy_callback_listener, _glfw.wl.dataSourceForClipboard);
    } else {
        static const struct wl_callback_listener primary_selection_copy_callback_listener = {.done = primary_selection_copy_callback_done};
        wl_callback_add_listener(callback, &primary_selection_copy_callback_listener, _glfw.wl.dataSourceForPrimarySelection);
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
    if (activation_token && activation_token[0]) xdg_activation_v1_activate(_glfw.wl.xdg_activation_v1, activation_token, window->wl.surface);
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

GLFWAPI unsigned long long glfwDBusUserNotify(const char *app_name, const char* icon, const char *summary, const char *body, const char *action_name, int32_t timeout, GLFWDBusnotificationcreatedfun callback, void *data) {
    return glfw_dbus_send_user_notification(app_name, icon, summary, body, action_name, timeout, callback, data);
}

GLFWAPI void glfwDBusSetUserNotificationHandler(GLFWDBusnotificationactivatedfun handler) {
    glfw_dbus_set_user_notification_activated_handler(handler);
}

GLFWAPI bool glfwWaylandSetTitlebarColor(GLFWwindow *handle, uint32_t color, bool use_system_color) {
    _GLFWwindow* window = (_GLFWwindow*) handle;
    if (!window->wl.decorations.serverSide) {
        set_titlebar_color(window, color, use_system_color);
        return true;
    }
    return false;
}
