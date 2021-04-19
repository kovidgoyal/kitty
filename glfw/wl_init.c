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
#include "wl_client_side_decorations.h"
#include "linux_desktop_settings.h"
#include "../kitty/monotonic.h"

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include <wayland-client.h>
// Needed for the BTN_* defines
#ifdef __has_include
#if __has_include(<linux/input.h>)
#include <linux/input.h>
#elif __has_include(<dev/evdev/input.h>)
#include <dev/evdev/input.h>
#endif
#else
#include <linux/input.h>
#endif


static inline int min(int n1, int n2)
{
    return n1 < n2 ? n1 : n2;
}

static _GLFWwindow*
findWindowFromDecorationSurface(struct wl_surface* surface, _GLFWdecorationSideWayland* which)
{
    _GLFWdecorationSideWayland focus;
    if (!which) which = &focus;
    _GLFWwindow* window = _glfw.windowListHead;
#define q(edge, result) if (surface == window->wl.decorations.edge.surface) { *which = result; break; }
    while (window) {
        q(top, TOP_DECORATION);
        q(left, LEFT_DECORATION);
        q(right, RIGHT_DECORATION);
        q(bottom, BOTTOM_DECORATION);
        window = window->next;
    }
#undef q
    return window;
}

static void pointerHandleEnter(void* data UNUSED,
                               struct wl_pointer* pointer UNUSED,
                               uint32_t serial,
                               struct wl_surface* surface,
                               wl_fixed_t sx UNUSED,
                               wl_fixed_t sy UNUSED)
{
    // Happens in the case we just destroyed the surface.
    if (!surface)
        return;

    _GLFWdecorationSideWayland focus = CENTRAL_WINDOW;
    _GLFWwindow* window = wl_surface_get_user_data(surface);
    if (!window)
    {
        window = findWindowFromDecorationSurface(surface, &focus);
        if (!window)
            return;
    }

    window->wl.decorations.focus = focus;
    _glfw.wl.serial = serial;
    _glfw.wl.pointerFocus = window;

    window->wl.hovered = true;

    _glfwPlatformSetCursor(window, window->wl.currentCursor);
    _glfwInputCursorEnter(window, true);
}

static void pointerHandleLeave(void* data UNUSED,
                               struct wl_pointer* pointer UNUSED,
                               uint32_t serial,
                               struct wl_surface* surface UNUSED)
{
    _GLFWwindow* window = _glfw.wl.pointerFocus;

    if (!window)
        return;

    window->wl.hovered = false;

    _glfw.wl.serial = serial;
    _glfw.wl.pointerFocus = NULL;
    _glfwInputCursorEnter(window, false);
    _glfw.wl.cursorPreviousShape = GLFW_INVALID_CURSOR;
}

static void setCursor(GLFWCursorShape shape, _GLFWwindow* window)
{
    struct wl_buffer* buffer;
    struct wl_cursor* cursor;
    struct wl_cursor_image* image;
    struct wl_surface* surface = _glfw.wl.cursorSurface;
    const int scale = window->wl.scale;

    struct wl_cursor_theme *theme = glfw_wlc_theme_for_scale(scale);
    if (!theme) return;
    cursor = _glfwLoadCursor(shape, theme);
    if (!cursor) return;
    // TODO: handle animated cursors too.
    image = cursor->images[0];

    if (!image)
        return;

    buffer = wl_cursor_image_get_buffer(image);
    if (!buffer)
        return;
    wl_pointer_set_cursor(_glfw.wl.pointer, _glfw.wl.serial,
                          surface,
                          image->hotspot_x / scale,
                          image->hotspot_y / scale);
    wl_surface_set_buffer_scale(surface, scale);
    wl_surface_attach(surface, buffer, 0, 0);
    wl_surface_damage(surface, 0, 0,
                      image->width, image->height);
    wl_surface_commit(surface);
    _glfw.wl.cursorPreviousShape = shape;
}

#define x window->wl.allCursorPosX
#define y window->wl.allCursorPosY
static void pointerHandleMotion(void* data UNUSED,
                                struct wl_pointer* pointer UNUSED,
                                uint32_t time UNUSED,
                                wl_fixed_t sx,
                                wl_fixed_t sy)
{
    _GLFWwindow* window = _glfw.wl.pointerFocus;
    GLFWCursorShape cursorShape = GLFW_ARROW_CURSOR;

    if (!window)
        return;

    if (window->cursorMode == GLFW_CURSOR_DISABLED)
        return;
    window->wl.allCursorPosX = wl_fixed_to_double(sx);
    window->wl.allCursorPosY = wl_fixed_to_double(sy);

    switch (window->wl.decorations.focus)
    {
        case CENTRAL_WINDOW:
            window->wl.cursorPosX = x;
            window->wl.cursorPosY = y;
            _glfwInputCursorPos(window, x, y);
            _glfw.wl.cursorPreviousShape = GLFW_INVALID_CURSOR;
            return;
        case TOP_DECORATION:
            if (y < window->wl.decorations.metrics.width)
                cursorShape = GLFW_VRESIZE_CURSOR;
            else
                cursorShape = GLFW_ARROW_CURSOR;
            break;
        case LEFT_DECORATION:
            if (y < window->wl.decorations.metrics.width)
                cursorShape = GLFW_NW_RESIZE_CURSOR;
            else
                cursorShape = GLFW_HRESIZE_CURSOR;
            break;
        case RIGHT_DECORATION:
            if (y < window->wl.decorations.metrics.width)
                cursorShape = GLFW_NE_RESIZE_CURSOR;
            else
                cursorShape = GLFW_HRESIZE_CURSOR;
            break;
        case BOTTOM_DECORATION:
            if (x < window->wl.decorations.metrics.width)
                cursorShape = GLFW_SW_RESIZE_CURSOR;
            else if (x > window->wl.width + window->wl.decorations.metrics.width)
                cursorShape = GLFW_SE_RESIZE_CURSOR;
            else
                cursorShape = GLFW_VRESIZE_CURSOR;
            break;
        default:
            assert(0);
    }
    if (_glfw.wl.cursorPreviousShape != cursorShape)
        setCursor(cursorShape, window);
}

static void pointerHandleButton(void* data UNUSED,
                                struct wl_pointer* pointer UNUSED,
                                uint32_t serial,
                                uint32_t time UNUSED,
                                uint32_t button,
                                uint32_t state)
{
    _GLFWwindow* window = _glfw.wl.pointerFocus;
    int glfwButton;
    uint32_t edges = XDG_TOPLEVEL_RESIZE_EDGE_NONE;

    if (!window)
        return;
    if (button == BTN_LEFT)
    {
        switch (window->wl.decorations.focus)
        {
            case CENTRAL_WINDOW:
                break;
            case TOP_DECORATION:
                if (state == WL_POINTER_BUTTON_STATE_PRESSED) {
                    monotonic_t last_click_at = window->wl.decorations.last_click_on_top_decoration_at;
                    window->wl.decorations.last_click_on_top_decoration_at = monotonic();
                    if (window->wl.decorations.last_click_on_top_decoration_at - last_click_at <= _glfwPlatformGetDoubleClickInterval(window)) {
                        window->wl.decorations.last_click_on_top_decoration_at = 0;
                        if (window->wl.toplevel_states & TOPLEVEL_STATE_MAXIMIZED)
                            xdg_toplevel_unset_maximized(window->wl.xdg.toplevel);
                        else
                            xdg_toplevel_set_maximized(window->wl.xdg.toplevel);
                        return;
                    }
                }
                if (y < window->wl.decorations.metrics.width)
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_TOP;
                else
                {
                    if (window->wl.xdg.toplevel)
                        xdg_toplevel_move(window->wl.xdg.toplevel, _glfw.wl.seat, serial);
                }

                break;
            case LEFT_DECORATION:
                if (y < window->wl.decorations.metrics.width)
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_TOP_LEFT;
                else
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_LEFT;
                break;
            case RIGHT_DECORATION:
                if (y < window->wl.decorations.metrics.width)
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_TOP_RIGHT;
                else
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_RIGHT;
                break;
            case BOTTOM_DECORATION:
                if (x < window->wl.decorations.metrics.width)
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_BOTTOM_LEFT;
                else if (x > window->wl.width + window->wl.decorations.metrics.width)
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_BOTTOM_RIGHT;
                else
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_BOTTOM;
                break;
            default:
                assert(0);
        }
        if (edges != XDG_TOPLEVEL_RESIZE_EDGE_NONE)
        {
            xdg_toplevel_resize(window->wl.xdg.toplevel, _glfw.wl.seat,
                                serial, edges);
        }
    }
    else if (button == BTN_RIGHT)
    {
        if (window->wl.decorations.focus != CENTRAL_WINDOW && window->wl.xdg.toplevel)
        {
            xdg_toplevel_show_window_menu(window->wl.xdg.toplevel, _glfw.wl.seat, serial, (int32_t)x, (int32_t)y - window->wl.decorations.metrics.top);
            return;
        }
    }

    // Don’t pass the button to the user if it was related to a decoration.
    if (window->wl.decorations.focus != CENTRAL_WINDOW)
        return;

    _glfw.wl.serial = serial;

    /* Makes left, right and middle 0, 1 and 2. Overall order follows evdev
     * codes. */
    glfwButton = button - BTN_LEFT;

    _glfwInputMouseClick(window,
                         glfwButton,
                         state == WL_POINTER_BUTTON_STATE_PRESSED
                                ? GLFW_PRESS
                                : GLFW_RELEASE,
                         _glfw.wl.xkb.states.modifiers);
}
#undef x
#undef y

static void pointerHandleAxis(void* data UNUSED,
                              struct wl_pointer* pointer UNUSED,
                              uint32_t time UNUSED,
                              uint32_t axis,
                              wl_fixed_t value)
{
    _GLFWwindow* window = _glfw.wl.pointerFocus;
    double x = 0.0, y = 0.0;
    if (!window)
        return;

    assert(axis == WL_POINTER_AXIS_HORIZONTAL_SCROLL ||
           axis == WL_POINTER_AXIS_VERTICAL_SCROLL);

    if (axis == WL_POINTER_AXIS_HORIZONTAL_SCROLL)
        x = -wl_fixed_to_double(value);
    else if (axis == WL_POINTER_AXIS_VERTICAL_SCROLL)
        y = -wl_fixed_to_double(value);

    _glfwInputScroll(window, x, y, 1, _glfw.wl.xkb.states.modifiers);
}

static const struct wl_pointer_listener pointerListener = {
    pointerHandleEnter,
    pointerHandleLeave,
    pointerHandleMotion,
    pointerHandleButton,
    pointerHandleAxis,
};

static void keyboardHandleKeymap(void* data UNUSED,
                                 struct wl_keyboard* keyboard UNUSED,
                                 uint32_t format,
                                 int fd,
                                 uint32_t size)
{
    char* mapStr;

    if (format != WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1)
    {
        close(fd);
        return;
    }

    mapStr = mmap(NULL, size, PROT_READ, MAP_SHARED, fd, 0);
    if (mapStr == MAP_FAILED) {
        close(fd);
        return;
    }
    glfw_xkb_compile_keymap(&_glfw.wl.xkb, mapStr);
    munmap(mapStr, size);
    close(fd);

}

static void keyboardHandleEnter(void* data UNUSED,
                                struct wl_keyboard* keyboard UNUSED,
                                uint32_t serial,
                                struct wl_surface* surface,
                                struct wl_array* keys)
{
    // Happens in the case we just destroyed the surface.
    if (!surface)
        return;

    _GLFWwindow* window = wl_surface_get_user_data(surface);
    if (!window)
    {
        window = findWindowFromDecorationSurface(surface, NULL);
        if (!window)
            return;
    }

    _glfw.wl.serial = serial;
    _glfw.wl.keyboardFocusId = window->id;
    _glfwInputWindowFocus(window, true);
    uint32_t* key;
    if (keys && _glfw.wl.keyRepeatInfo.key) {
        wl_array_for_each(key, keys) {
            if (*key == _glfw.wl.keyRepeatInfo.key) {
                toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, 1);
                break;
            }
        }
    }
}

static void keyboardHandleLeave(void* data UNUSED,
                                struct wl_keyboard* keyboard UNUSED,
                                uint32_t serial,
                                struct wl_surface* surface UNUSED)
{
    _GLFWwindow* window = _glfwWindowForId(_glfw.wl.keyboardFocusId);

    if (!window)
        return;

    _glfw.wl.serial = serial;
    _glfw.wl.keyboardFocusId = 0;
    _glfwInputWindowFocus(window, false);
    toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, 0);
}

static void
dispatchPendingKeyRepeats(id_type timer_id UNUSED, void *data UNUSED) {
    if (_glfw.wl.keyRepeatInfo.keyboardFocusId != _glfw.wl.keyboardFocusId || _glfw.wl.keyboardRepeatRate == 0) return;
    _GLFWwindow* window = _glfwWindowForId(_glfw.wl.keyboardFocusId);
    if (!window) return;
    glfw_xkb_handle_key_event(window, &_glfw.wl.xkb, _glfw.wl.keyRepeatInfo.key, GLFW_REPEAT);
    changeTimerInterval(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, (s_to_monotonic_t(1ll) / (monotonic_t)_glfw.wl.keyboardRepeatRate));
    toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, 1);
}


static void keyboardHandleKey(void* data UNUSED,
                              struct wl_keyboard* keyboard UNUSED,
                              uint32_t serial,
                              uint32_t time UNUSED,
                              uint32_t key,
                              uint32_t state)
{
    _GLFWwindow* window = _glfwWindowForId(_glfw.wl.keyboardFocusId);
    if (!window)
        return;
    int action = state == WL_KEYBOARD_KEY_STATE_PRESSED ? GLFW_PRESS : GLFW_RELEASE;

    _glfw.wl.serial = serial;
    glfw_xkb_handle_key_event(window, &_glfw.wl.xkb, key, action);

    if (action == GLFW_PRESS && _glfw.wl.keyboardRepeatRate > 0 && glfw_xkb_should_repeat(&_glfw.wl.xkb, key))
    {
        _glfw.wl.keyRepeatInfo.key = key;
        _glfw.wl.keyRepeatInfo.keyboardFocusId = window->id;
        changeTimerInterval(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, _glfw.wl.keyboardRepeatDelay);
        toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, 1);
    } else if (action == GLFW_RELEASE && key == _glfw.wl.keyRepeatInfo.key) {
        _glfw.wl.keyRepeatInfo.key = 0;
        toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, 0);
    }
}

static void keyboardHandleModifiers(void* data UNUSED,
                                    struct wl_keyboard* keyboard UNUSED,
                                    uint32_t serial,
                                    uint32_t modsDepressed,
                                    uint32_t modsLatched,
                                    uint32_t modsLocked,
                                    uint32_t group)
{
    _glfw.wl.serial = serial;
    glfw_xkb_update_modifiers(&_glfw.wl.xkb, modsDepressed, modsLatched, modsLocked, 0, 0, group);
}

static void keyboardHandleRepeatInfo(void* data UNUSED,
                                     struct wl_keyboard* keyboard,
                                     int32_t rate,
                                     int32_t delay)
{
    if (keyboard != _glfw.wl.keyboard)
        return;

    _glfw.wl.keyboardRepeatRate = rate;
    _glfw.wl.keyboardRepeatDelay = ms_to_monotonic_t(delay);
}

static const struct wl_keyboard_listener keyboardListener = {
    keyboardHandleKeymap,
    keyboardHandleEnter,
    keyboardHandleLeave,
    keyboardHandleKey,
    keyboardHandleModifiers,
    keyboardHandleRepeatInfo,
};

static void seatHandleCapabilities(void* data UNUSED,
                                   struct wl_seat* seat,
                                   enum wl_seat_capability caps)
{
    if ((caps & WL_SEAT_CAPABILITY_POINTER) && !_glfw.wl.pointer)
    {
        _glfw.wl.pointer = wl_seat_get_pointer(seat);
        wl_pointer_add_listener(_glfw.wl.pointer, &pointerListener, NULL);
    }
    else if (!(caps & WL_SEAT_CAPABILITY_POINTER) && _glfw.wl.pointer)
    {
        wl_pointer_destroy(_glfw.wl.pointer);
        _glfw.wl.pointer = NULL;
    }

    if ((caps & WL_SEAT_CAPABILITY_KEYBOARD) && !_glfw.wl.keyboard)
    {
        _glfw.wl.keyboard = wl_seat_get_keyboard(seat);
        wl_keyboard_add_listener(_glfw.wl.keyboard, &keyboardListener, NULL);
    }
    else if (!(caps & WL_SEAT_CAPABILITY_KEYBOARD) && _glfw.wl.keyboard)
    {
        wl_keyboard_destroy(_glfw.wl.keyboard);
        _glfw.wl.keyboard = NULL;
    }
}

static void seatHandleName(void* data UNUSED,
                           struct wl_seat* seat UNUSED,
                           const char* name UNUSED)
{
}

static const struct wl_seat_listener seatListener = {
    seatHandleCapabilities,
    seatHandleName,
};

static void wmBaseHandlePing(void* data UNUSED,
                             struct xdg_wm_base* wmBase,
                             uint32_t serial)
{
    xdg_wm_base_pong(wmBase, serial);
}

static const struct xdg_wm_base_listener wmBaseListener = {
    wmBaseHandlePing
};

static void registryHandleGlobal(void* data UNUSED,
                                 struct wl_registry* registry,
                                 uint32_t name,
                                 const char* interface,
                                 uint32_t version)
{
    if (strcmp(interface, "wl_compositor") == 0)
    {
        _glfw.wl.compositorVersion = min(3, version);
        _glfw.wl.compositor =
            wl_registry_bind(registry, name, &wl_compositor_interface,
                             _glfw.wl.compositorVersion);
    }
    else if (strcmp(interface, "wl_subcompositor") == 0)
    {
        _glfw.wl.subcompositor =
            wl_registry_bind(registry, name, &wl_subcompositor_interface, 1);
    }
    else if (strcmp(interface, "wl_shm") == 0)
    {
        _glfw.wl.shm =
            wl_registry_bind(registry, name, &wl_shm_interface, 1);
    }
    else if (strcmp(interface, "wl_output") == 0)
    {
        _glfwAddOutputWayland(name, version);
    }
    else if (strcmp(interface, "wl_seat") == 0)
    {
        if (!_glfw.wl.seat)
        {
            _glfw.wl.seatVersion = min(4, version);
            _glfw.wl.seat =
                wl_registry_bind(registry, name, &wl_seat_interface,
                                 _glfw.wl.seatVersion);
            wl_seat_add_listener(_glfw.wl.seat, &seatListener, NULL);
        }
        if (_glfw.wl.seat) {
            if (_glfw.wl.dataDeviceManager && !_glfw.wl.dataDevice) _glfwSetupWaylandDataDevice();
            if (_glfw.wl.primarySelectionDeviceManager && !_glfw.wl.primarySelectionDevice) {
                _glfwSetupWaylandPrimarySelectionDevice();
            }
            _glfwWaylandInitTextInput();
        }
    }
    else if (strcmp(interface, "xdg_wm_base") == 0)
    {
        _glfw.wl.wmBase =
            wl_registry_bind(registry, name, &xdg_wm_base_interface, 1);
        xdg_wm_base_add_listener(_glfw.wl.wmBase, &wmBaseListener, NULL);
    }
    else if (strcmp(interface, "zxdg_decoration_manager_v1") == 0)
    {
        _glfw.wl.decorationManager =
        wl_registry_bind(registry, name,
            &zxdg_decoration_manager_v1_interface, 1);
    }
    else if (strcmp(interface, "zwp_relative_pointer_manager_v1") == 0)
    {
        _glfw.wl.relativePointerManager =
            wl_registry_bind(registry, name,
                             &zwp_relative_pointer_manager_v1_interface,
                             1);
    }
    else if (strcmp(interface, "zwp_pointer_constraints_v1") == 0)
    {
        _glfw.wl.pointerConstraints =
            wl_registry_bind(registry, name,
                             &zwp_pointer_constraints_v1_interface,
                             1);
    }
    else if (strcmp(interface, GLFW_WAYLAND_TEXT_INPUT_INTERFACE_NAME) == 0)
    {
        _glfwWaylandBindTextInput(registry, name);
        _glfwWaylandInitTextInput();
    }
    else if (strcmp(interface, "zwp_idle_inhibit_manager_v1") == 0)
    {
        _glfw.wl.idleInhibitManager =
            wl_registry_bind(registry, name,
                             &zwp_idle_inhibit_manager_v1_interface,
                             1);
    }
    else if (strcmp(interface, "wl_data_device_manager") == 0)
    {
        _glfw.wl.dataDeviceManager =
            wl_registry_bind(registry, name,
                             &wl_data_device_manager_interface,
                             1);
        if (_glfw.wl.seat && _glfw.wl.dataDeviceManager && !_glfw.wl.dataDevice) {
            _glfwSetupWaylandDataDevice();
        }
    }
    else if (strcmp(interface, "zwp_primary_selection_device_manager_v1") == 0)
    {
        _glfw.wl.primarySelectionDeviceManager =
            wl_registry_bind(registry, name,
                             &zwp_primary_selection_device_manager_v1_interface,
                             1);
        if (_glfw.wl.seat && _glfw.wl.primarySelectionDeviceManager && !_glfw.wl.primarySelectionDevice) {
            _glfwSetupWaylandPrimarySelectionDevice();
        }
    }

}

static void registryHandleGlobalRemove(void *data UNUSED,
                                       struct wl_registry *registry UNUSED,
                                       uint32_t name)
{
    _GLFWmonitor* monitor;

    for (int i = 0; i < _glfw.monitorCount; ++i)
    {
        monitor = _glfw.monitors[i];
        if (monitor->wl.name == name)
        {
            for (_GLFWwindow *window = _glfw.windowListHead;  window;  window = window->next) {
                for (int m = window->wl.monitorsCount - 1; m >= 0; m--) {
                    if (window->wl.monitors[m] == monitor) {
                        remove_i_from_array(window->wl.monitors, m, window->wl.monitorsCount);
                    }
                }
            }
            _glfwInputMonitor(monitor, GLFW_DISCONNECTED, 0);
            return;
        }
    }
}


static const struct wl_registry_listener registryListener = {
    registryHandleGlobal,
    registryHandleGlobalRemove
};



static void registry_handle_global(void* data,
                                 struct wl_registry* registry UNUSED,
                                 uint32_t name UNUSED,
                                 const char* interface,
                                 uint32_t version UNUSED) {
    if (strcmp(interface, "zxdg_decoration_manager_v1") == 0) {
        bool *has_ssd = (bool*)data;
        if (has_ssd) *has_ssd = true;
    }
}

static void registry_handle_global_remove(void *data UNUSED,
                                       struct wl_registry *registry UNUSED,
                                       uint32_t name UNUSED) {}
GLFWAPI const char*
glfwWaylandCheckForServerSideDecorations(void) {
    struct wl_display *display = wl_display_connect(NULL);
    if (!display) return "ERR: Failed to connect to Wayland display";
    static const struct wl_registry_listener rl = {
        registry_handle_global, registry_handle_global_remove
    };
    struct wl_registry *registry = wl_display_get_registry(display);
    bool has_ssd = false;
    wl_registry_add_listener(registry, &rl, &has_ssd);
    wl_display_roundtrip(display);

    wl_registry_destroy(registry);
    wl_display_flush(display);
    wl_display_flush(display);
    return has_ssd ? "YES" : "NO";
}

//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

int _glfwPlatformInit(void)
{
    int i;
    _GLFWmonitor* monitor;

    _glfw.wl.cursor.handle = _glfw_dlopen("libwayland-cursor.so.0");
    if (!_glfw.wl.cursor.handle)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to open libwayland-cursor");
        return false;
    }

    glfw_dlsym(_glfw.wl.cursor.theme_load, _glfw.wl.cursor.handle, "wl_cursor_theme_load");
    glfw_dlsym(_glfw.wl.cursor.theme_destroy, _glfw.wl.cursor.handle, "wl_cursor_theme_destroy");
    glfw_dlsym(_glfw.wl.cursor.theme_get_cursor, _glfw.wl.cursor.handle, "wl_cursor_theme_get_cursor");
    glfw_dlsym(_glfw.wl.cursor.image_get_buffer, _glfw.wl.cursor.handle, "wl_cursor_image_get_buffer");

    _glfw.wl.egl.handle = _glfw_dlopen("libwayland-egl.so.1");
    if (!_glfw.wl.egl.handle)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to open libwayland-egl");
        return false;
    }

    glfw_dlsym(_glfw.wl.egl.window_create, _glfw.wl.egl.handle, "wl_egl_window_create");
    glfw_dlsym(_glfw.wl.egl.window_destroy, _glfw.wl.egl.handle, "wl_egl_window_destroy");
    glfw_dlsym(_glfw.wl.egl.window_resize, _glfw.wl.egl.handle, "wl_egl_window_resize");

    _glfw.wl.display = wl_display_connect(NULL);
    if (!_glfw.wl.display)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to connect to display");
        return false;
    }
    if (!initPollData(&_glfw.wl.eventLoopData, wl_display_get_fd(_glfw.wl.display))) {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to initialize event loop data");
    }
    glfw_dbus_init(&_glfw.wl.dbus, &_glfw.wl.eventLoopData);
    glfw_initialize_desktop_settings();
    _glfw.wl.keyRepeatInfo.keyRepeatTimer = addTimer(&_glfw.wl.eventLoopData, "wayland-key-repeat", ms_to_monotonic_t(500ll), 0, true, dispatchPendingKeyRepeats, NULL, NULL);
    _glfw.wl.cursorAnimationTimer = addTimer(&_glfw.wl.eventLoopData, "wayland-cursor-animation", ms_to_monotonic_t(500ll), 0, true, animateCursorImage, NULL, NULL);

    _glfw.wl.registry = wl_display_get_registry(_glfw.wl.display);
    wl_registry_add_listener(_glfw.wl.registry, &registryListener, NULL);

    if (!glfw_xkb_create_context(&_glfw.wl.xkb)) return false;

    // Sync so we got all registry objects
    wl_display_roundtrip(_glfw.wl.display);

    // Sync so we got all initial output events
    wl_display_roundtrip(_glfw.wl.display);

    for (i = 0; i < _glfw.monitorCount; ++i)
    {
        monitor = _glfw.monitors[i];
        if (monitor->widthMM <= 0 || monitor->heightMM <= 0)
        {
            // If Wayland does not provide a physical size, assume the default 96 DPI
            monitor->widthMM  = (int) (monitor->modes[monitor->wl.currentMode].width * 25.4f / 96.f);
            monitor->heightMM = (int) (monitor->modes[monitor->wl.currentMode].height * 25.4f / 96.f);
        }
    }

    if (!_glfw.wl.wmBase)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to find xdg-shell in your compositor");
        return false;
    }

    if (_glfw.wl.shm)
    {
        _glfw.wl.cursorSurface =
            wl_compositor_create_surface(_glfw.wl.compositor);
    }
    else
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to find Wayland SHM");
        return false;
    }

    return true;
}

void _glfwPlatformTerminate(void)
{
    _glfwTerminateEGL();
    if (_glfw.wl.egl.handle)
    {
        _glfw_dlclose(_glfw.wl.egl.handle);
        _glfw.wl.egl.handle = NULL;
    }

    glfw_xkb_release(&_glfw.wl.xkb);
    glfw_dbus_terminate(&_glfw.wl.dbus);

    glfw_wlc_destroy();
    if (_glfw.wl.cursor.handle)
    {
        _glfw_dlclose(_glfw.wl.cursor.handle);
        _glfw.wl.cursor.handle = NULL;
    }

    if (_glfw.wl.cursorSurface)
        wl_surface_destroy(_glfw.wl.cursorSurface);
    if (_glfw.wl.subcompositor)
        wl_subcompositor_destroy(_glfw.wl.subcompositor);
    if (_glfw.wl.compositor)
        wl_compositor_destroy(_glfw.wl.compositor);
    if (_glfw.wl.shm)
        wl_shm_destroy(_glfw.wl.shm);
    if (_glfw.wl.decorationManager)
        zxdg_decoration_manager_v1_destroy(_glfw.wl.decorationManager);
    if (_glfw.wl.wmBase)
        xdg_wm_base_destroy(_glfw.wl.wmBase);
    if (_glfw.wl.pointer)
        wl_pointer_destroy(_glfw.wl.pointer);
    if (_glfw.wl.keyboard)
        wl_keyboard_destroy(_glfw.wl.keyboard);
    if (_glfw.wl.seat)
        wl_seat_destroy(_glfw.wl.seat);
    if (_glfw.wl.relativePointerManager)
        zwp_relative_pointer_manager_v1_destroy(_glfw.wl.relativePointerManager);
    if (_glfw.wl.pointerConstraints)
        zwp_pointer_constraints_v1_destroy(_glfw.wl.pointerConstraints);
    _glfwWaylandDestroyTextInput();
    if (_glfw.wl.idleInhibitManager)
        zwp_idle_inhibit_manager_v1_destroy(_glfw.wl.idleInhibitManager);
    if (_glfw.wl.dataSourceForClipboard)
        wl_data_source_destroy(_glfw.wl.dataSourceForClipboard);
    for (size_t doi=0; doi < arraysz(_glfw.wl.dataOffers); doi++) {
        if (_glfw.wl.dataOffers[doi].id) {
            destroy_data_offer(&_glfw.wl.dataOffers[doi]);
        }
    }
    if (_glfw.wl.dataDevice)
        wl_data_device_destroy(_glfw.wl.dataDevice);
    if (_glfw.wl.dataDeviceManager)
        wl_data_device_manager_destroy(_glfw.wl.dataDeviceManager);
    if (_glfw.wl.primarySelectionDevice)
        zwp_primary_selection_device_v1_destroy(_glfw.wl.primarySelectionDevice);
    if (_glfw.wl.primarySelectionDeviceManager)
        zwp_primary_selection_device_manager_v1_destroy(_glfw.wl.primarySelectionDeviceManager);
    if (_glfw.wl.registry)
        wl_registry_destroy(_glfw.wl.registry);
    if (_glfw.wl.display)
    {
        wl_display_flush(_glfw.wl.display);
        wl_display_disconnect(_glfw.wl.display);
    }
    finalizePollData(&_glfw.wl.eventLoopData);
    free(_glfw.wl.clipboardString); _glfw.wl.clipboardString = NULL;
    free(_glfw.wl.primarySelectionString); _glfw.wl.primarySelectionString = NULL;
    free(_glfw.wl.pasteString); _glfw.wl.pasteString = NULL;

}

const char* _glfwPlatformGetVersionString(void)
{
    return _GLFW_VERSION_NUMBER " Wayland EGL OSMesa"
#if defined(_POSIX_TIMERS) && defined(_POSIX_MONOTONIC_CLOCK)
        " clock_gettime"
#else
        " gettimeofday"
#endif
        " evdev"
#if defined(_GLFW_BUILD_DLL)
        " shared"
#endif
        ;
}

#define GLFW_LOOP_BACKEND wl
#include "main_loop.h"
