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

#include "internal.h"

#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <assert.h>


static void outputHandleGeometry(void* data,
                                 struct wl_output* output UNUSED,
                                 int32_t x,
                                 int32_t y,
                                 int32_t physicalWidth,
                                 int32_t physicalHeight,
                                 int32_t subpixel UNUSED,
                                 const char* make UNUSED,
                                 const char* model UNUSED,
                                 int32_t transform)
{
    struct _GLFWmonitor *monitor = data;
    monitor->wl.x = x;
    monitor->wl.y = y;
    monitor->widthMM = physicalWidth;
    monitor->heightMM = physicalHeight;
    monitor->wl.transform = transform;
}

static void outputHandleMode(void* data,
                             struct wl_output* output UNUSED,
                             uint32_t flags,
                             int32_t width,
                             int32_t height,
                             int32_t refresh)
{
    struct _GLFWmonitor *monitor = data;
    GLFWvidmode mode;

    mode.width = width;
    mode.height = height;
    mode.redBits = 8;
    mode.greenBits = 8;
    mode.blueBits = 8;
    mode.refreshRate = (int) round(refresh / 1000.0);

    monitor->modeCount++;
    monitor->modes =
        realloc(monitor->modes, monitor->modeCount * sizeof(GLFWvidmode));
    monitor->modes[monitor->modeCount - 1] = mode;

    if (flags & WL_OUTPUT_MODE_CURRENT)
        monitor->wl.currentMode = monitor->modeCount - 1;
}

static void outputHandleDone(void* data, struct wl_output* output UNUSED)
{
    struct _GLFWmonitor *monitor = data;
    for (int i = 0; i < _glfw.monitorCount; i++) {
        if (_glfw.monitors[i] == monitor) return;
    }
    _glfwInputMonitor(monitor, GLFW_CONNECTED, _GLFW_INSERT_LAST);
}

static void outputHandleScale(void* data,
                              struct wl_output* output UNUSED,
                              int32_t factor)
{
    struct _GLFWmonitor *monitor = data;
    if (factor > 0 && factor < 24)
        monitor->wl.scale = factor;
}

static void outputHandleName(void* data,
                              struct wl_output* output UNUSED,
                              const char* name) {
    struct _GLFWmonitor *monitor = data;
    if (name) {
        if (monitor->name) free((void*)monitor->name);
        monitor->name = _glfw_strdup(name);
    }
}

static void outputHandleDescription(void* data,
                              struct wl_output* output UNUSED,
                              const char* description) {
    struct _GLFWmonitor *monitor = data;
    if (description) {
        if (monitor->description) free((void*)monitor->description);
        monitor->description = _glfw_strdup(description);
    }
}

static const struct wl_output_listener outputListener = {
    outputHandleGeometry,
    outputHandleMode,
    outputHandleDone,
    outputHandleScale,
    outputHandleName,
    outputHandleDescription,
};


static void xdgOutputHandleLogicalPosition(void *data,
                                            struct zxdg_output_v1 *xdg_output UNUSED,
                                            int32_t x,
                                            int32_t y)
{
    struct _GLFWmonitor *monitor = data;
    monitor->wl.x = x;
    monitor->wl.y = y;
    monitor->wl.xdg_position_received = true;
}

static void xdgOutputHandleLogicalSize(void *data,
                                        struct zxdg_output_v1 *xdg_output UNUSED,
                                        int32_t width,
                                        int32_t height)
{
    struct _GLFWmonitor *monitor = data;
    monitor->wl.xdg_logical_width = width;
    monitor->wl.xdg_logical_height = height;
    monitor->wl.xdg_size_received = true;
}

static void computeXdgFractionalScale(struct _GLFWmonitor *monitor)
{
    if (monitor->wl.xdg_logical_width <= 0 || monitor->wl.xdg_logical_height <= 0) return;
    if (monitor->modeCount == 0 || monitor->wl.currentMode < 0) return;
    GLFWvidmode *mode = &monitor->modes[monitor->wl.currentMode];
    if (mode->width <= 0 || mode->height <= 0) return;

    // For 90° and 270° rotations the compositor maps physical width↔height,
    // so use the swapped axis when dividing by the logical size.
    int phys_w = mode->width, phys_h = mode->height;
    int32_t t = monitor->wl.transform;
    if (t == WL_OUTPUT_TRANSFORM_90 || t == WL_OUTPUT_TRANSFORM_270 ||
        t == WL_OUTPUT_TRANSFORM_FLIPPED_90 || t == WL_OUTPUT_TRANSFORM_FLIPPED_270)
    {
        int tmp = phys_w; phys_w = phys_h; phys_h = tmp;
    }

    double sx = (double)phys_w / monitor->wl.xdg_logical_width;
    double sy = (double)phys_h / monitor->wl.xdg_logical_height;
    // Use the average in case of minor rounding differences between axes.
    monitor->wl.fractional_scale = (sx + sy) * 0.5;
}

static void xdgOutputHandleDone(void *data,
                                 struct zxdg_output_v1 *xdg_output UNUSED)
{
    struct _GLFWmonitor *monitor = data;
    computeXdgFractionalScale(monitor);
}

static void xdgOutputHandleName(void *data,
                                 struct zxdg_output_v1 *xdg_output UNUSED,
                                 const char *name)
{
    // wl_output already provides the name; skip to avoid duplicate frees.
    (void)data; (void)name;
}

static void xdgOutputHandleDescription(void *data,
                                        struct zxdg_output_v1 *xdg_output UNUSED,
                                        const char *description)
{
    (void)data; (void)description;
}

static const struct zxdg_output_v1_listener xdgOutputListener = {
    xdgOutputHandleLogicalPosition,
    xdgOutputHandleLogicalSize,
    xdgOutputHandleDone,
    xdgOutputHandleName,
    xdgOutputHandleDescription,
};


//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

void _glfwCreateXdgOutputWayland(_GLFWmonitor* monitor)
{
    if (!_glfw.wl.xdg_output_manager || monitor->wl.xdg_output) return;
    monitor->wl.xdg_output = zxdg_output_manager_v1_get_xdg_output(
        _glfw.wl.xdg_output_manager, monitor->wl.output);
    if (monitor->wl.xdg_output)
        zxdg_output_v1_add_listener(monitor->wl.xdg_output, &xdgOutputListener, monitor);
}

void _glfwAddOutputWayland(uint32_t name, uint32_t version)
{
    _GLFWmonitor *monitor;
    struct wl_output *output;

    if (version < 2)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Unsupported output interface version");
        return;
    }

    // The actual name of this output will be set in the handlers.
    monitor = _glfwAllocMonitor("unnamed", 0, 0);

    output = wl_registry_bind(_glfw.wl.registry,
                              name,
                              &wl_output_interface,
                              MIN(version, (unsigned)WL_OUTPUT_NAME_SINCE_VERSION));
    if (!output)
    {
        _glfwFreeMonitor(monitor);
        return;
    }

    monitor->wl.scale = 1;
    monitor->wl.output = output;
    monitor->wl.name = name;

    wl_output_add_listener(output, &outputListener, monitor);
    _glfwCreateXdgOutputWayland(monitor);
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

void _glfwPlatformFreeMonitor(_GLFWmonitor* monitor)
{
    if (monitor->wl.xdg_output)
        zxdg_output_v1_destroy(monitor->wl.xdg_output);
    if (monitor->wl.output)
        wl_output_destroy(monitor->wl.output);
}

void _glfwPlatformGetMonitorPos(_GLFWmonitor* monitor, int* xpos, int* ypos)
{
    if (xpos)
        *xpos = monitor->wl.x;
    if (ypos)
        *ypos = monitor->wl.y;
}

void _glfwPlatformGetMonitorContentScale(_GLFWmonitor* monitor,
                                         float* xscale, float* yscale)
{
    float scale = monitor->wl.fractional_scale > 0.0
                  ? (float)monitor->wl.fractional_scale
                  : (float)monitor->wl.scale;
    if (xscale) *xscale = scale;
    if (yscale) *yscale = scale;
}

void _glfwPlatformGetMonitorWorkarea(_GLFWmonitor* monitor,
                                     int* xpos, int* ypos,
                                     int* width, int* height)
{
    if (xpos)
        *xpos = monitor->wl.x;
    if (ypos)
        *ypos = monitor->wl.y;
    if (width)
        *width = monitor->modes[monitor->wl.currentMode].width;
    if (height)
        *height = monitor->modes[monitor->wl.currentMode].height;
}

GLFWvidmode* _glfwPlatformGetVideoModes(_GLFWmonitor* monitor, int* found)
{
    *found = monitor->modeCount;
    return monitor->modes;
}

bool _glfwPlatformGetVideoMode(_GLFWmonitor* monitor, GLFWvidmode* mode)
{
    if (monitor->modeCount > monitor->wl.currentMode) {
        *mode = monitor->modes[monitor->wl.currentMode];
        return true;
    }
    return false;
}

bool _glfwPlatformGetGammaRamp(_GLFWmonitor* monitor UNUSED, GLFWgammaramp* ramp UNUSED)
{
    _glfwInputError(GLFW_FEATURE_UNAVAILABLE,
                    "Wayland: Gamma ramp access is not available");
    return false;
}

void _glfwPlatformSetGammaRamp(_GLFWmonitor* monitor UNUSED,
                               const GLFWgammaramp* ramp UNUSED)
{
    _glfwInputError(GLFW_FEATURE_UNAVAILABLE,
                    "Wayland: Gamma ramp access is not available");
}


//////////////////////////////////////////////////////////////////////////
//////                        GLFW native API                       //////
//////////////////////////////////////////////////////////////////////////

GLFWAPI struct wl_output* glfwGetWaylandMonitor(GLFWmonitor* handle)
{
    _GLFWmonitor* monitor = (_GLFWmonitor*) handle;
    assert(monitor != NULL);

    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    return monitor->wl.output;
}

GLFWAPI double glfwGetWaylandCurrentMonitorFractionalScale(void)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(1.0);
    if (!_glfw.wl.xdg_output_manager || _glfw.monitorCount == 0)
        return 1.0;

    // Use the monitor of the currently focused window, then the most recently
    // focused window, then fall back to the primary monitor.
    _GLFWmonitor *monitor = NULL;
    GLFWid focus_ids[2] = { _glfw.wl.keyboardFocusId, _glfw.wl.lastKeyboardFocusId };
    for (int i = 0; i < 2 && !monitor; i++) {
        if (!focus_ids[i]) continue;
        _GLFWwindow *window = _glfwWindowForId(focus_ids[i]);
        if (window && window->wl.monitorsCount > 0)
            monitor = window->wl.monitors[0];
    }
    if (!monitor) {
        // No focused window to key off of (typically the first window at
        // startup). Prefer the output at the logical origin (0, 0): the
        // compositor's top-left/primary output is a better guess for where a
        // new window will be placed than registry order. Fall back to the
        // first output if no output reports position (0, 0).
        //
        // xdg_output geometry arrives asynchronously and x/y remain zero until
        // it does, so wait for every monitor's logical geometry before trusting
        // the reported positions (otherwise an as-yet-unpositioned output would
        // spuriously match (0, 0)).
        for (int i = 0; i < _glfw.monitorCount; i++) {
            _GLFWmonitor *m = _glfw.monitors[i];
            while (m->wl.xdg_output &&
                   !(m->wl.xdg_size_received && m->wl.xdg_position_received)) {
                if (wl_display_roundtrip(_glfw.wl.display) < 0) break;
            }
        }
        for (int i = 0; i < _glfw.monitorCount; i++) {
            _GLFWmonitor *m = _glfw.monitors[i];
            if (m->wl.xdg_output && m->wl.xdg_size_received &&
                m->wl.xdg_position_received &&
                m->wl.x == 0 && m->wl.y == 0) { monitor = m; break; }
        }
        if (!monitor)
            monitor = _glfw.monitors[0];
    }

    if (!monitor->wl.xdg_output)
        return monitor->wl.scale > 0 ? (double)monitor->wl.scale : 1.0;

    // Block until the compositor has delivered xdg_output logical size and position.
    while (!(monitor->wl.xdg_size_received && monitor->wl.xdg_position_received))
    {
        if (wl_display_roundtrip(_glfw.wl.display) < 0) break;
    }

    if (monitor->wl.fractional_scale <= 0.0)
        computeXdgFractionalScale(monitor);

    return monitor->wl.fractional_scale > 0.0
           ? monitor->wl.fractional_scale
           : (monitor->wl.scale > 0 ? (double)monitor->wl.scale : 1.0);
}
