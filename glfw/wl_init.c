//========================================================================
// GLFW 3.3 Wayland - www.glfw.org
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

#define _GNU_SOURCE
#include "internal.h"
#include "backend_utils.h"

#include <assert.h>
#include <errno.h>
#include <limits.h>
#include <linux/input.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>
#include <fcntl.h>
#include <wayland-client.h>


static inline int min(int n1, int n2)
{
    return n1 < n2 ? n1 : n2;
}

static _GLFWwindow* findWindowFromDecorationSurface(struct wl_surface* surface, int* which)
{
    int focus;
    _GLFWwindow* window = _glfw.windowListHead;
    if (!which)
        which = &focus;
    while (window)
    {
        if (surface == window->wl.decorations.top.surface)
        {
            *which = topDecoration;
            break;
        }
        if (surface == window->wl.decorations.left.surface)
        {
            *which = leftDecoration;
            break;
        }
        if (surface == window->wl.decorations.right.surface)
        {
            *which = rightDecoration;
            break;
        }
        if (surface == window->wl.decorations.bottom.surface)
        {
            *which = bottomDecoration;
            break;
        }
        window = window->next;
    }
    return window;
}

static void pointerHandleEnter(void* data,
                               struct wl_pointer* pointer,
                               uint32_t serial,
                               struct wl_surface* surface,
                               wl_fixed_t sx,
                               wl_fixed_t sy)
{
    // Happens in the case we just destroyed the surface.
    if (!surface)
        return;

    int focus = 0;
    _GLFWwindow* window = wl_surface_get_user_data(surface);
    if (!window)
    {
        window = findWindowFromDecorationSurface(surface, &focus);
        if (!window)
            return;
    }

    window->wl.decorations.focus = focus;
    _glfw.wl.pointerSerial = serial;
    _glfw.wl.pointerFocus = window;

    window->wl.hovered = GLFW_TRUE;

    _glfwPlatformSetCursor(window, window->wl.currentCursor);
    _glfwInputCursorEnter(window, GLFW_TRUE);
}

static void pointerHandleLeave(void* data,
                               struct wl_pointer* pointer,
                               uint32_t serial,
                               struct wl_surface* surface)
{
    _GLFWwindow* window = _glfw.wl.pointerFocus;

    if (!window)
        return;

    window->wl.hovered = GLFW_FALSE;

    _glfw.wl.pointerSerial = serial;
    _glfw.wl.pointerFocus = NULL;
    _glfwInputCursorEnter(window, GLFW_FALSE);
}

static void setCursor(GLFWCursorShape shape)
{
    struct wl_buffer* buffer;
    struct wl_cursor* cursor;
    struct wl_cursor_image* image;
    struct wl_surface* surface = _glfw.wl.cursorSurface;

    cursor = _glfwLoadCursor(shape);
    if (!cursor) return;
    // TODO: handle animated cursors too.
    image = cursor->images[0];

    if (!image)
        return;

    buffer = wl_cursor_image_get_buffer(image);
    if (!buffer)
        return;
    wl_pointer_set_cursor(_glfw.wl.pointer, _glfw.wl.pointerSerial,
                          surface,
                          image->hotspot_x,
                          image->hotspot_y);
    wl_surface_attach(surface, buffer, 0, 0);
    wl_surface_damage(surface, 0, 0,
                      image->width, image->height);
    wl_surface_commit(surface);
}

static void pointerHandleMotion(void* data,
                                struct wl_pointer* pointer,
                                uint32_t time,
                                wl_fixed_t sx,
                                wl_fixed_t sy)
{
    _GLFWwindow* window = _glfw.wl.pointerFocus;
    GLFWCursorShape cursorShape = GLFW_ARROW_CURSOR;

    if (!window)
        return;

    if (window->cursorMode == GLFW_CURSOR_DISABLED)
        return;
    else
    {
        window->wl.cursorPosX = wl_fixed_to_double(sx);
        window->wl.cursorPosY = wl_fixed_to_double(sy);
    }

    switch (window->wl.decorations.focus)
    {
        case mainWindow:
            _glfwInputCursorPos(window,
                                wl_fixed_to_double(sx),
                                wl_fixed_to_double(sy));
            return;
        case topDecoration:
            if (window->wl.cursorPosY < _GLFW_DECORATION_WIDTH)
                cursorShape = GLFW_VRESIZE_CURSOR;
            else
                cursorShape = GLFW_ARROW_CURSOR;
            break;
        case leftDecoration:
            if (window->wl.cursorPosY < _GLFW_DECORATION_WIDTH)
                cursorShape = GLFW_NW_RESIZE_CURSOR;
            else
                cursorShape = GLFW_HRESIZE_CURSOR;
            break;
        case rightDecoration:
            if (window->wl.cursorPosY < _GLFW_DECORATION_WIDTH)
                cursorShape = GLFW_NE_RESIZE_CURSOR;
            else
                cursorShape = GLFW_HRESIZE_CURSOR;
            break;
        case bottomDecoration:
            if (window->wl.cursorPosX < _GLFW_DECORATION_WIDTH)
                cursorShape = GLFW_SW_RESIZE_CURSOR;
            else if (window->wl.cursorPosX > window->wl.width + _GLFW_DECORATION_WIDTH)
                cursorShape = GLFW_SE_RESIZE_CURSOR;
            else
                cursorShape = GLFW_VRESIZE_CURSOR;
            break;
        default:
            assert(0);
    }
    setCursor(cursorShape);
}

static void pointerHandleButton(void* data,
                                struct wl_pointer* pointer,
                                uint32_t serial,
                                uint32_t time,
                                uint32_t button,
                                uint32_t state)
{
    _GLFWwindow* window = _glfw.wl.pointerFocus;
    int glfwButton;

    // Both xdg-shell and wl_shell use the same values.
    uint32_t edges = WL_SHELL_SURFACE_RESIZE_NONE;

    if (!window)
        return;
    if (button == BTN_LEFT)
    {
        switch (window->wl.decorations.focus)
        {
            case mainWindow:
                break;
            case topDecoration:
                if (window->wl.cursorPosY < _GLFW_DECORATION_WIDTH)
                    edges = WL_SHELL_SURFACE_RESIZE_TOP;
                else
                {
                    if (window->wl.xdg.toplevel)
                        xdg_toplevel_move(window->wl.xdg.toplevel, _glfw.wl.seat, serial);
                    else
                        wl_shell_surface_move(window->wl.shellSurface, _glfw.wl.seat, serial);
                }
                break;
            case leftDecoration:
                if (window->wl.cursorPosY < _GLFW_DECORATION_WIDTH)
                    edges = WL_SHELL_SURFACE_RESIZE_TOP_LEFT;
                else
                    edges = WL_SHELL_SURFACE_RESIZE_LEFT;
                break;
            case rightDecoration:
                if (window->wl.cursorPosY < _GLFW_DECORATION_WIDTH)
                    edges = WL_SHELL_SURFACE_RESIZE_TOP_RIGHT;
                else
                    edges = WL_SHELL_SURFACE_RESIZE_RIGHT;
                break;
            case bottomDecoration:
                if (window->wl.cursorPosX < _GLFW_DECORATION_WIDTH)
                    edges = WL_SHELL_SURFACE_RESIZE_BOTTOM_LEFT;
                else if (window->wl.cursorPosX > window->wl.width + _GLFW_DECORATION_WIDTH)
                    edges = WL_SHELL_SURFACE_RESIZE_BOTTOM_RIGHT;
                else
                    edges = WL_SHELL_SURFACE_RESIZE_BOTTOM;
                break;
            default:
                assert(0);
        }
        if (edges != WL_SHELL_SURFACE_RESIZE_NONE)
        {
            if (window->wl.xdg.toplevel)
                xdg_toplevel_resize(window->wl.xdg.toplevel, _glfw.wl.seat,
                                    serial, edges);
            else
                wl_shell_surface_resize(window->wl.shellSurface, _glfw.wl.seat,
                                        serial, edges);
        }
    }
    else if (button == BTN_RIGHT)
    {
        if (window->wl.decorations.focus != mainWindow && window->wl.xdg.toplevel)
        {
            xdg_toplevel_show_window_menu(window->wl.xdg.toplevel,
                                          _glfw.wl.seat, serial,
                                          window->wl.cursorPosX,
                                          window->wl.cursorPosY);
            return;
        }
    }

    // Don’t pass the button to the user if it was related to a decoration.
    if (window->wl.decorations.focus != mainWindow)
        return;

    _glfw.wl.pointerSerial = serial;

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

static void pointerHandleAxis(void* data,
                              struct wl_pointer* pointer,
                              uint32_t time,
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
        x = wl_fixed_to_double(value) * -1;
    else if (axis == WL_POINTER_AXIS_VERTICAL_SCROLL)
        y = wl_fixed_to_double(value) * -1;

    _glfwInputScroll(window, x, y, 1);
}

static const struct wl_pointer_listener pointerListener = {
    pointerHandleEnter,
    pointerHandleLeave,
    pointerHandleMotion,
    pointerHandleButton,
    pointerHandleAxis,
};

static void keyboardHandleKeymap(void* data,
                                 struct wl_keyboard* keyboard,
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

static void keyboardHandleEnter(void* data,
                                struct wl_keyboard* keyboard,
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

    _glfw.wl.keyboardFocus = window;
    _glfwInputWindowFocus(window, GLFW_TRUE);
}

static void keyboardHandleLeave(void* data,
                                struct wl_keyboard* keyboard,
                                uint32_t serial,
                                struct wl_surface* surface)
{
    _GLFWwindow* window = _glfw.wl.keyboardFocus;

    if (!window)
        return;

    _glfw.wl.keyboardFocus = NULL;
    _glfwInputWindowFocus(window, GLFW_FALSE);
}

static void
dispatchPendingKeyRepeats(id_type timer_id, void *data) {
    if (_glfw.wl.keyRepeatInfo.keyboardFocus != _glfw.wl.keyboardFocus || _glfw.wl.keyboardRepeatRate == 0) return;
    glfw_xkb_handle_key_event(_glfw.wl.keyRepeatInfo.keyboardFocus, &_glfw.wl.xkb, _glfw.wl.keyRepeatInfo.key, GLFW_REPEAT);
    changeTimerInterval(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, (1.0 / (double)_glfw.wl.keyboardRepeatRate));
    toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, 1);
}


static void keyboardHandleKey(void* data,
                              struct wl_keyboard* keyboard,
                              uint32_t serial,
                              uint32_t time,
                              uint32_t key,
                              uint32_t state)
{
    _GLFWwindow* window = _glfw.wl.keyboardFocus;
    if (!window)
        return;
    int action = state == WL_KEYBOARD_KEY_STATE_PRESSED ? GLFW_PRESS : GLFW_RELEASE;
    glfw_xkb_handle_key_event(window, &_glfw.wl.xkb, key, action);
    GLFWbool repeatable = GLFW_FALSE;

    if (action == GLFW_PRESS && _glfw.wl.keyboardRepeatRate > 0 && glfw_xkb_should_repeat(&_glfw.wl.xkb, key))
    {
        _glfw.wl.keyRepeatInfo.key = key;
        repeatable = GLFW_TRUE;
        _glfw.wl.keyRepeatInfo.keyboardFocus = window;
    }
    if (repeatable) {
        changeTimerInterval(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, (double)(_glfw.wl.keyboardRepeatDelay) / 1000.0);
    }
    toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.keyRepeatInfo.keyRepeatTimer, repeatable ? 1 : 0);
}

static void keyboardHandleModifiers(void* data,
                                    struct wl_keyboard* keyboard,
                                    uint32_t serial,
                                    uint32_t modsDepressed,
                                    uint32_t modsLatched,
                                    uint32_t modsLocked,
                                    uint32_t group)
{
    glfw_xkb_update_modifiers(&_glfw.wl.xkb, modsDepressed, modsLatched, modsLocked, 0, 0, group);
}

static void keyboardHandleRepeatInfo(void* data,
                                     struct wl_keyboard* keyboard,
                                     int32_t rate,
                                     int32_t delay)
{
    if (keyboard != _glfw.wl.keyboard)
        return;

    _glfw.wl.keyboardRepeatRate = rate;
    _glfw.wl.keyboardRepeatDelay = delay;
}

static const struct wl_keyboard_listener keyboardListener = {
    keyboardHandleKeymap,
    keyboardHandleEnter,
    keyboardHandleLeave,
    keyboardHandleKey,
    keyboardHandleModifiers,
    keyboardHandleRepeatInfo,
};

static void seatHandleCapabilities(void* data,
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

static void seatHandleName(void* data,
                           struct wl_seat* seat,
                           const char* name)
{
}

static const struct wl_seat_listener seatListener = {
    seatHandleCapabilities,
    seatHandleName,
};

static void wmBaseHandlePing(void* data,
                             struct xdg_wm_base* wmBase,
                             uint32_t serial)
{
    xdg_wm_base_pong(wmBase, serial);
}

static const struct xdg_wm_base_listener wmBaseListener = {
    wmBaseHandlePing
};

static void registryHandleGlobal(void* data,
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
    else if (strcmp(interface, "wl_shell") == 0)
    {
        _glfw.wl.shell =
            wl_registry_bind(registry, name, &wl_shell_interface, 1);
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
    else if (strcmp(interface, "wp_viewporter") == 0)
    {
        _glfw.wl.viewporter =
            wl_registry_bind(registry, name, &wp_viewporter_interface, 1);
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
    else if (strcmp(interface, "zwp_primary_selection_device_manager_v1") == 0 ||
        strcmp(interface, "gtk_primary_selection_device_manager") == 0)
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

static void registryHandleGlobalRemove(void *data,
                                       struct wl_registry *registry,
                                       uint32_t name)
{
    int i;
    _GLFWmonitor* monitor;

    for (i = 0; i < _glfw.monitorCount; ++i)
    {
        monitor = _glfw.monitors[i];
        if (monitor->wl.name == name)
        {
            _glfwInputMonitor(monitor, GLFW_DISCONNECTED, 0);
            return;
        }
    }
}


static const struct wl_registry_listener registryListener = {
    registryHandleGlobal,
    registryHandleGlobalRemove
};


//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

int _glfwPlatformInit(void)
{
    if (pipe2(_glfw.wl.eventLoopData.wakeupFds, O_CLOEXEC | O_NONBLOCK) != 0)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                "Wayland: failed to create self pipe");
        return GLFW_FALSE;
    }

    _glfw.wl.cursor.handle = _glfw_dlopen("libwayland-cursor.so.0");
    if (!_glfw.wl.cursor.handle)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to open libwayland-cursor");
        return GLFW_FALSE;
    }

    _glfw.wl.cursor.theme_load = (PFN_wl_cursor_theme_load)
        _glfw_dlsym(_glfw.wl.cursor.handle, "wl_cursor_theme_load");
    _glfw.wl.cursor.theme_destroy = (PFN_wl_cursor_theme_destroy)
        _glfw_dlsym(_glfw.wl.cursor.handle, "wl_cursor_theme_destroy");
    _glfw.wl.cursor.theme_get_cursor = (PFN_wl_cursor_theme_get_cursor)
        _glfw_dlsym(_glfw.wl.cursor.handle, "wl_cursor_theme_get_cursor");
    _glfw.wl.cursor.image_get_buffer = (PFN_wl_cursor_image_get_buffer)
        _glfw_dlsym(_glfw.wl.cursor.handle, "wl_cursor_image_get_buffer");

    _glfw.wl.egl.handle = _glfw_dlopen("libwayland-egl.so.1");
    if (!_glfw.wl.egl.handle)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to open libwayland-egl");
        return GLFW_FALSE;
    }

    _glfw.wl.egl.window_create = (PFN_wl_egl_window_create)
        _glfw_dlsym(_glfw.wl.egl.handle, "wl_egl_window_create");
    _glfw.wl.egl.window_destroy = (PFN_wl_egl_window_destroy)
        _glfw_dlsym(_glfw.wl.egl.handle, "wl_egl_window_destroy");
    _glfw.wl.egl.window_resize = (PFN_wl_egl_window_resize)
        _glfw_dlsym(_glfw.wl.egl.handle, "wl_egl_window_resize");

    _glfw.wl.display = wl_display_connect(NULL);
    if (!_glfw.wl.display)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to connect to display");
        return GLFW_FALSE;
    }
    initPollData(&_glfw.wl.eventLoopData, _glfw.wl.eventLoopData.wakeupFds[0], wl_display_get_fd(_glfw.wl.display));
    glfw_dbus_init(&_glfw.wl.dbus, &_glfw.wl.eventLoopData);
    _glfw.wl.keyRepeatInfo.keyRepeatTimer = addTimer(&_glfw.wl.eventLoopData, "wayland-key-repeat", 0.5, 0, true, dispatchPendingKeyRepeats, NULL, NULL);
    _glfw.wl.cursorAnimationTimer = addTimer(&_glfw.wl.eventLoopData, "wayland-cursor-animation", 0.5, 0, true, animateCursorImage, NULL, NULL);

    _glfw.wl.registry = wl_display_get_registry(_glfw.wl.display);
    wl_registry_add_listener(_glfw.wl.registry, &registryListener, NULL);

    if (!glfw_xkb_create_context(&_glfw.wl.xkb)) return GLFW_FALSE;

    // Sync so we got all registry objects
    wl_display_roundtrip(_glfw.wl.display);

    // Sync so we got all initial output events
    wl_display_roundtrip(_glfw.wl.display);

#ifdef __linux__
    if (_glfw.hints.init.enableJoysticks) {
        if (!_glfwInitJoysticksLinux())
            return GLFW_FALSE;
    }
#endif

    _glfwInitTimerPOSIX();

    if (_glfw.wl.shm)
    {
        const char *cursorTheme = getenv("XCURSOR_THEME"), *cursorSizeStr = getenv("XCURSOR_SIZE");
        char *cursorSizeEnd;
        int cursorSize = 32;
        if (cursorSizeStr)
        {
            errno = 0;
            long cursorSizeLong = strtol(cursorSizeStr, &cursorSizeEnd, 10);
            if (!*cursorSizeEnd && !errno && cursorSizeLong > 0 && cursorSizeLong <= INT_MAX)
                cursorSize = (int)cursorSizeLong;
        }
        _glfw.wl.cursorTheme = wl_cursor_theme_load(cursorTheme, cursorSize, _glfw.wl.shm);
        if (!_glfw.wl.cursorTheme)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland: Unable to load default cursor theme");
            return GLFW_FALSE;
        }
        _glfw.wl.cursorSurface =
            wl_compositor_create_surface(_glfw.wl.compositor);
    }

    return GLFW_TRUE;
}

void _glfwPlatformTerminate(void)
{
#ifdef __linux__
    _glfwTerminateJoysticksLinux();
#endif
    _glfwTerminateEGL();
    if (_glfw.wl.egl.handle)
    {
        _glfw_dlclose(_glfw.wl.egl.handle);
        _glfw.wl.egl.handle = NULL;
    }

    glfw_xkb_release(&_glfw.wl.xkb);
    glfw_dbus_terminate(&_glfw.wl.dbus);

    if (_glfw.wl.cursorTheme)
        wl_cursor_theme_destroy(_glfw.wl.cursorTheme);
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
    if (_glfw.wl.shell)
        wl_shell_destroy(_glfw.wl.shell);
    if (_glfw.wl.viewporter)
        wp_viewporter_destroy(_glfw.wl.viewporter);
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
    if (_glfw.wl.idleInhibitManager)
        zwp_idle_inhibit_manager_v1_destroy(_glfw.wl.idleInhibitManager);
    if (_glfw.wl.dataSourceForClipboard)
        wl_data_source_destroy(_glfw.wl.dataSourceForClipboard);
    for (size_t doi=0; doi < arraysz(_glfw.wl.dataOffers); doi++) {
        if (_glfw.wl.dataOffers[doi].id) {
            wl_data_offer_destroy(_glfw.wl.dataOffers[doi].id);
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
    closeFds(_glfw.wl.eventLoopData.wakeupFds, sizeof(_glfw.wl.eventLoopData.wakeupFds)/sizeof(_glfw.wl.eventLoopData.wakeupFds[0]));
    free(_glfw.wl.clipboardString); _glfw.wl.clipboardString = NULL;
    free(_glfw.wl.primarySelectionString); _glfw.wl.primarySelectionString = NULL;
    free(_glfw.wl.pasteString); _glfw.wl.pasteString = NULL;

}

const char* _glfwPlatformGetVersionString(void)
{
    return _GLFW_VERSION_NUMBER " Wayland EGL"
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
