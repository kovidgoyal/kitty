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
#include "wl_text_input.h"
#include "wayland-text-input-unstable-v3-client-protocol.h"

#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <wayland-client.h>
#include <stdio.h>
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

#define debug debug_rendering

static int min(int n1, int n2)
{
    return n1 < n2 ? n1 : n2;
}

#define x window->wl.allCursorPosX
#define y window->wl.allCursorPosY

static _GLFWwindow*
get_window_from_surface(struct wl_surface* surface) {
    if (!surface) return NULL;
    _GLFWwindow *ans = wl_surface_get_user_data(surface);
    if (ans) {
        const _GLFWwindow *w = _glfw.windowListHead;
        while (w) {
            if (w == ans) return ans;
            w = w->next;
        }
    }
    return NULL;
}

static void
pointerHandleEnter(
        void* data UNUSED, struct wl_pointer* pointer UNUSED, uint32_t serial, struct wl_surface* surface,
        wl_fixed_t sx, wl_fixed_t sy
) {
    _GLFWwindow* window = get_window_from_surface(surface);
    if (!window) return;
    _glfw.wl.serial = serial; _glfw.wl.input_serial = serial; _glfw.wl.pointer_serial = serial; _glfw.wl.pointer_enter_serial = serial;
    _glfw.wl.pointerFocus = window;
    window->wl.allCursorPosX = wl_fixed_to_double(sx);
    window->wl.allCursorPosY = wl_fixed_to_double(sy);
    if (surface != window->wl.surface) {
        csd_handle_pointer_event(window, -2, -2, surface);
    } else {
        window->wl.decorations.focus = CENTRAL_WINDOW;
        window->wl.hovered = true;
        window->wl.cursorPosX = x;
        window->wl.cursorPosY = y;

        _glfwPlatformSetCursor(window, window->wl.currentCursor);
        _glfwInputCursorEnter(window, true);
    }
}

static void
pointerHandleLeave(void* data UNUSED, struct wl_pointer* pointer UNUSED, uint32_t serial, struct wl_surface* surface) {
    _GLFWwindow* window = _glfw.wl.pointerFocus;
    if (!window) return;
    _glfw.wl.serial = serial;
    _glfw.wl.pointerFocus = NULL;
    if (window->wl.surface == surface) {
        window->wl.hovered = false;
        _glfwInputCursorEnter(window, false);
        _glfw.wl.cursorPreviousShape = GLFW_INVALID_CURSOR;
    } else csd_handle_pointer_event(window, -3, -3, surface);
}

static void
pointerHandleMotion(void* data UNUSED, struct wl_pointer* pointer UNUSED, uint32_t time UNUSED, wl_fixed_t sx, wl_fixed_t sy) {
    _GLFWwindow* window = _glfw.wl.pointerFocus;
    if (!window || window->cursorMode == GLFW_CURSOR_DISABLED) return;
    window->wl.allCursorPosX = wl_fixed_to_double(sx);
    window->wl.allCursorPosY = wl_fixed_to_double(sy);
    if (window->wl.decorations.focus != CENTRAL_WINDOW) {
        csd_handle_pointer_event(window, -1, -1, NULL);
    } else {
        window->wl.cursorPosX = x;
        window->wl.cursorPosY = y;
        _glfwInputCursorPos(window, x, y);
        _glfw.wl.cursorPreviousShape = GLFW_INVALID_CURSOR;
    }
}

static void pointerHandleButton(void* data UNUSED,
                                struct wl_pointer* pointer UNUSED,
                                uint32_t serial,
                                uint32_t time UNUSED,
                                uint32_t button,
                                uint32_t state)
{
    _glfw.wl.serial = serial; _glfw.wl.input_serial = serial; _glfw.wl.pointer_serial = serial;

    _GLFWwindow* window = _glfw.wl.pointerFocus;
    if (!window) return;
    if (window->wl.decorations.focus != CENTRAL_WINDOW) {
        csd_handle_pointer_event(window, button, state, NULL);
        return;
    }
    /* Makes left, right and middle 0, 1 and 2. Overall order follows evdev
     * codes. */
    int glfwButton = button - BTN_LEFT;
    _glfwInputMouseClick(
            window, glfwButton, state == WL_POINTER_BUTTON_STATE_PRESSED ? GLFW_PRESS : GLFW_RELEASE, _glfw.wl.xkb.states.modifiers);
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
    if (!window || window->wl.decorations.focus != CENTRAL_WINDOW) return;

    assert(axis == WL_POINTER_AXIS_HORIZONTAL_SCROLL ||
           axis == WL_POINTER_AXIS_VERTICAL_SCROLL);

    if (axis == WL_POINTER_AXIS_HORIZONTAL_SCROLL) {
        if (window->wl.axis_discrete_count.x) {
            window->wl.axis_discrete_count.x--;
            return;
        }
        x = -wl_fixed_to_double(value) * _glfwWaylandWindowScale(window);
    }
    else if (axis == WL_POINTER_AXIS_VERTICAL_SCROLL) {
        if (window->wl.axis_discrete_count.y) {
            window->wl.axis_discrete_count.y--;
            return;
        }
        y = -wl_fixed_to_double(value) * _glfwWaylandWindowScale(window);
    }

    _glfwInputScroll(window, x, y, 1, _glfw.wl.xkb.states.modifiers);
}

static void pointerHandleFrame(void* data UNUSED,
                               struct wl_pointer* pointer UNUSED)
{
    _GLFWwindow* window = _glfw.wl.pointerFocus;
    if (!window || window->wl.decorations.focus != CENTRAL_WINDOW) return;
    window->wl.axis_discrete_count.x = 0;
    window->wl.axis_discrete_count.y = 0;
}

static void pointerHandleAxisSource(void* data UNUSED,
                                    struct wl_pointer* pointer UNUSED,
                                    uint32_t source UNUSED)
{
}

static void pointerHandleAxisStop(void *data UNUSED,
                  struct wl_pointer *wl_pointer UNUSED,
                  uint32_t time UNUSED,
                  uint32_t axis UNUSED)
{
}


static void pointerHandleAxisDiscrete(void *data UNUSED,
                  struct wl_pointer *wl_pointer UNUSED,
                  uint32_t axis,
                  int32_t discrete)
{
    _GLFWwindow* window = _glfw.wl.pointerFocus;
    double x = 0.0, y = 0.0;
    if (!window || window->wl.decorations.focus != CENTRAL_WINDOW) return;

    assert(axis == WL_POINTER_AXIS_HORIZONTAL_SCROLL ||
           axis == WL_POINTER_AXIS_VERTICAL_SCROLL);

    if (axis == WL_POINTER_AXIS_HORIZONTAL_SCROLL) {
        x = -discrete;
        window->wl.axis_discrete_count.x++;
    }
    else if (axis == WL_POINTER_AXIS_VERTICAL_SCROLL) {
        y = -discrete;
        window->wl.axis_discrete_count.y++;
    }

    _glfwInputScroll(window, x, y, 0, _glfw.wl.xkb.states.modifiers);
}

static const struct wl_pointer_listener pointerListener = {
    pointerHandleEnter,
    pointerHandleLeave,
    pointerHandleMotion,
    pointerHandleButton,
    pointerHandleAxis,
    pointerHandleFrame,
    pointerHandleAxisSource,
    pointerHandleAxisStop,
    pointerHandleAxisDiscrete,
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
        _glfwInputError(GLFW_PLATFORM_ERROR, "Unknown keymap format: %u", format);
        close(fd);
        return;
    }

    mapStr = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (mapStr == MAP_FAILED) {
        close(fd);
        _glfwInputError(GLFW_PLATFORM_ERROR, "Mapping of keymap file descriptor failed: %u", format);
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
    _GLFWwindow* window = get_window_from_surface(surface);
    if (!window) return;

    _glfw.wl.serial = serial; _glfw.wl.input_serial = serial; _glfw.wl.keyboard_enter_serial = serial;
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

    _glfw.wl.serial = serial; _glfw.wl.input_serial = serial;
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
    _glfw.wl.serial = serial; _glfw.wl.input_serial = serial;
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
        if (_glfw.wl.wp_cursor_shape_manager_v1) {
            if (_glfw.wl.wp_cursor_shape_device_v1) wp_cursor_shape_device_v1_destroy(_glfw.wl.wp_cursor_shape_device_v1);
            _glfw.wl.wp_cursor_shape_device_v1 = NULL;
            _glfw.wl.wp_cursor_shape_device_v1 = wp_cursor_shape_manager_v1_get_pointer(_glfw.wl.wp_cursor_shape_manager_v1, _glfw.wl.pointer);
        }
    }
    else if (!(caps & WL_SEAT_CAPABILITY_POINTER) && _glfw.wl.pointer)
    {
        if (_glfw.wl.wp_cursor_shape_device_v1) wp_cursor_shape_device_v1_destroy(_glfw.wl.wp_cursor_shape_device_v1);
        _glfw.wl.wp_cursor_shape_device_v1 = NULL;
        wl_pointer_destroy(_glfw.wl.pointer);
        _glfw.wl.pointer = NULL;
        if (_glfw.wl.cursorAnimationTimer) toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, 0);
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
        _glfw.wl.keyboardFocusId = 0;
        if (_glfw.wl.keyRepeatInfo.keyRepeatTimer) toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, 0);
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
#define is(x) strcmp(interface, x##_interface.name) == 0
    if (is(wl_compositor))
    {
#ifdef WL_SURFACE_PREFERRED_BUFFER_SCALE_SINCE_VERSION
        _glfw.wl.compositorVersion = min(WL_SURFACE_PREFERRED_BUFFER_SCALE_SINCE_VERSION, version);
        _glfw.wl.has_preferred_buffer_scale = _glfw.wl.compositorVersion >= WL_SURFACE_PREFERRED_BUFFER_SCALE_SINCE_VERSION;
#else
        _glfw.wl.compositorVersion = min(3, version);
#endif
        _glfw.wl.compositor = wl_registry_bind(registry, name, &wl_compositor_interface, _glfw.wl.compositorVersion);
    }
    else if (is(wl_subcompositor))
    {
        _glfw.wl.subcompositor =
            wl_registry_bind(registry, name, &wl_subcompositor_interface, 1);
    }
    else if (is(wl_shm))
    {
        _glfw.wl.shm =
            wl_registry_bind(registry, name, &wl_shm_interface, 1);
    }
    else if (is(wl_output))
    {
        _glfwAddOutputWayland(name, version);
    }
    else if (is(wl_seat))
    {
        if (!_glfw.wl.seat)
        {
            _glfw.wl.seatVersion = min(5, version);
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
        }
    }
    else if (is(xdg_wm_base))
    {
        _glfw.wl.xdg_wm_base_version = 1;
#ifdef XDG_TOPLEVEL_WM_CAPABILITIES_SINCE_VERSION
        _glfw.wl.xdg_wm_base_version = min(XDG_TOPLEVEL_WM_CAPABILITIES_SINCE_VERSION, version);
#endif
        _glfw.wl.wmBase = wl_registry_bind(registry, name, &xdg_wm_base_interface, _glfw.wl.xdg_wm_base_version);
        xdg_wm_base_add_listener(_glfw.wl.wmBase, &wmBaseListener, NULL);
    }
    else if (is(zxdg_decoration_manager_v1))
    {
        _glfw.wl.decorationManager =
        wl_registry_bind(registry, name,
            &zxdg_decoration_manager_v1_interface, 1);
    }
    else if (is(zwp_relative_pointer_manager_v1))
    {
        _glfw.wl.relativePointerManager =
            wl_registry_bind(registry, name,
                             &zwp_relative_pointer_manager_v1_interface,
                             1);
    }
    else if (is(zwp_pointer_constraints_v1))
    {
        _glfw.wl.pointerConstraints =
            wl_registry_bind(registry, name,
                             &zwp_pointer_constraints_v1_interface,
                             1);
    }
    else if (is(zwp_text_input_manager_v3))
    {
        _glfwWaylandBindTextInput(registry, name);
    }
    else if (is(wl_data_device_manager))
    {
        _glfw.wl.dataDeviceManager =
            wl_registry_bind(registry, name,
                             &wl_data_device_manager_interface,
                             1);
        if (_glfw.wl.seat && _glfw.wl.dataDeviceManager && !_glfw.wl.dataDevice) {
            _glfwSetupWaylandDataDevice();
        }
    }
    else if (is(zwp_primary_selection_device_manager_v1))
    {
        _glfw.wl.primarySelectionDeviceManager =
            wl_registry_bind(registry, name,
                             &zwp_primary_selection_device_manager_v1_interface,
                             1);
        if (_glfw.wl.seat && _glfw.wl.primarySelectionDeviceManager && !_glfw.wl.primarySelectionDevice) {
            _glfwSetupWaylandPrimarySelectionDevice();
        }
    }
    else if (is(wp_single_pixel_buffer_manager_v1)) {
        _glfw.wl.wp_single_pixel_buffer_manager_v1 = wl_registry_bind(registry, name, &wp_single_pixel_buffer_manager_v1_interface, 1);
    }
    else if (is(xdg_activation_v1)) {
        _glfw.wl.xdg_activation_v1 = wl_registry_bind(registry, name, &xdg_activation_v1_interface, 1);
    }
    else if (is(wp_cursor_shape_manager_v1)) {
        _glfw.wl.wp_cursor_shape_manager_v1 = wl_registry_bind(registry, name, &wp_cursor_shape_manager_v1_interface, 1);
    }
    else if (is(wp_fractional_scale_manager_v1)) {
        _glfw.wl.wp_fractional_scale_manager_v1 = wl_registry_bind(registry, name, &wp_fractional_scale_manager_v1_interface, 1);
    }
    else if (is(wp_viewporter)) {
        _glfw.wl.wp_viewporter = wl_registry_bind(registry, name, &wp_viewporter_interface, 1);
    }
    else if (is(org_kde_kwin_blur_manager)) {
        _glfw.wl.org_kde_kwin_blur_manager = wl_registry_bind(registry, name, &org_kde_kwin_blur_manager_interface, 1);
    }
    else if (is(zwlr_layer_shell_v1)) {
        if (version >= 4) {
            _glfw.wl.zwlr_layer_shell_v1_version = version;
            _glfw.wl.zwlr_layer_shell_v1 = wl_registry_bind(registry, name, &zwlr_layer_shell_v1_interface, version);
        }
    }
#undef is
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


GLFWAPI GLFWColorScheme glfwGetCurrentSystemColorTheme(void) {
    return glfw_current_system_color_theme();
}

GLFWAPI pid_t glfwWaylandCompositorPID(void) {
    if (!_glfw.wl.display) return -1;
    int fd = wl_display_get_fd(_glfw.wl.display);
    if (fd < 0) return -1;
    struct ucred ucred;
    socklen_t len = sizeof(struct ucred);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &ucred, &len) == -1) {
        perror("getsockopt failed");
        return -1;
    }
    return ucred.pid;
}

//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

static const char*
get_compositor_missing_capabilities(void) {
#define C(title, x) if (!_glfw.wl.x) p += snprintf(buf, sizeof(buf) - (p - buf), "%s", #title);
    static char buf[256];
    char *p = buf;
    *p = 0;
    C(viewporter, wp_viewporter); C(fractional_scale, wp_fractional_scale_manager_v1);
    C(blur, org_kde_kwin_blur_manager); C(server_side_decorations, decorationManager);
    C(cursor_shape, wp_cursor_shape_manager_v1); C(layer_shell, zwlr_layer_shell_v1);
    C(single_pixel_buffer, wp_single_pixel_buffer_manager_v1); C(preferred_scale, has_preferred_buffer_scale);
#undef C
    return buf;
}

GLFWAPI const char* glfwWaylandMissingCapabilities(void) { return get_compositor_missing_capabilities(); }

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
    _glfwWaylandInitTextInput();

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
    if (_glfw.hints.init.debugRendering) {
        const char *mc = get_compositor_missing_capabilities();
        if (mc && mc[0]) debug("Compositor missing capabilities: %s\n", mc);
    }

    return true;
}

void _glfwPlatformTerminate(void)
{
    if (_glfw.wl.activation_requests.array) {
        for (size_t i=0; i < _glfw.wl.activation_requests.sz; i++) {
            glfw_wl_xdg_activation_request *r = _glfw.wl.activation_requests.array + i;
            if (r->callback) r->callback(NULL, NULL, r->callback_data);
            xdg_activation_token_v1_destroy(r->token);
        }
        free(_glfw.wl.activation_requests.array);
    }
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
    if (_glfw.wl.dataSourceForClipboard)
        wl_data_source_destroy(_glfw.wl.dataSourceForClipboard);
    if (_glfw.wl.dataSourceForPrimarySelection)
        zwp_primary_selection_source_v1_destroy(_glfw.wl.dataSourceForPrimarySelection);
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
    if (_glfw.wl.xdg_activation_v1)
        xdg_activation_v1_destroy(_glfw.wl.xdg_activation_v1);
    if (_glfw.wl.wp_single_pixel_buffer_manager_v1)
        wp_single_pixel_buffer_manager_v1_destroy(_glfw.wl.wp_single_pixel_buffer_manager_v1);
    if (_glfw.wl.wp_cursor_shape_manager_v1)
        wp_cursor_shape_manager_v1_destroy(_glfw.wl.wp_cursor_shape_manager_v1);
    if (_glfw.wl.wp_viewporter)
        wp_viewporter_destroy(_glfw.wl.wp_viewporter);
    if (_glfw.wl.wp_fractional_scale_manager_v1)
        wp_fractional_scale_manager_v1_destroy(_glfw.wl.wp_fractional_scale_manager_v1);
    if (_glfw.wl.org_kde_kwin_blur_manager)
        org_kde_kwin_blur_manager_destroy(_glfw.wl.org_kde_kwin_blur_manager);
    if (_glfw.wl.zwlr_layer_shell_v1)
        zwlr_layer_shell_v1_destroy(_glfw.wl.zwlr_layer_shell_v1);

    if (_glfw.wl.registry)
        wl_registry_destroy(_glfw.wl.registry);
    if (_glfw.wl.display)
    {
        wl_display_flush(_glfw.wl.display);
        wl_display_disconnect(_glfw.wl.display);
    }
    finalizePollData(&_glfw.wl.eventLoopData);
}

#define GLFW_LOOP_BACKEND wl
#include "main_loop.h"

const char* _glfwPlatformGetVersionString(void)
{
    (void)keep_going;
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
