//========================================================================
// GLFW 3.4 - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2016 Google Inc.
// Copyright (c) 2016-2019 Camilla Löwy <elmindreda@glfw.org>
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
#include "../kitty/monotonic.h"

#include <stdlib.h>

static void applySizeLimits(_GLFWwindow* window, int* width, int* height)
{
    if (window->numer != GLFW_DONT_CARE && window->denom != GLFW_DONT_CARE)
    {
        const float ratio = (float) window->numer / (float) window->denom;
        *height = (int) (*width / ratio);
    }

    if (window->minwidth != GLFW_DONT_CARE && *width < window->minwidth)
        *width = window->minwidth;
    else if (window->maxwidth != GLFW_DONT_CARE && *width > window->maxwidth)
        *width = window->maxwidth;

    if (window->minheight != GLFW_DONT_CARE && *height < window->minheight)
        *height = window->minheight;
    else if (window->maxheight != GLFW_DONT_CARE && *height > window->maxheight)
        *height = window->maxheight;
}

static void fitToMonitor(_GLFWwindow* window)
{
    GLFWvidmode mode;
    _glfwPlatformGetVideoMode(window->monitor, &mode);
    _glfwPlatformGetMonitorPos(window->monitor,
                               &window->null.xpos,
                               &window->null.ypos);
    window->null.width = mode.width;
    window->null.height = mode.height;
}

static void acquireMonitor(_GLFWwindow* window)
{
    _glfwInputMonitorWindow(window->monitor, window);
}

static void releaseMonitor(_GLFWwindow* window)
{
    if (window->monitor->window != window)
        return;

    _glfwInputMonitorWindow(window->monitor, NULL);
}

static int createNativeWindow(_GLFWwindow* window,
                              const _GLFWwndconfig* wndconfig,
                              const _GLFWfbconfig* fbconfig)
{
    if (window->monitor)
        fitToMonitor(window);
    else
    {
        window->null.xpos = 17;
        window->null.ypos = 17;
        window->null.width = wndconfig->width;
        window->null.height = wndconfig->height;
    }

    window->null.visible = wndconfig->visible;
    window->null.decorated = wndconfig->decorated;
    window->null.maximized = wndconfig->maximized;
    window->null.floating = wndconfig->floating;
    window->null.transparent = fbconfig->transparent;
    window->null.opacity = 1.f;

    return true;
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

int _glfwPlatformCreateWindow(_GLFWwindow* window,
                              const _GLFWwndconfig* wndconfig,
                              const _GLFWctxconfig* ctxconfig,
                              const _GLFWfbconfig* fbconfig)
{
    if (!createNativeWindow(window, wndconfig, fbconfig))
        return false;

    if (ctxconfig->client != GLFW_NO_API)
    {
        if (ctxconfig->source == GLFW_NATIVE_CONTEXT_API ||
            ctxconfig->source == GLFW_OSMESA_CONTEXT_API)
        {
            if (!_glfwInitOSMesa())
                return false;
            if (!_glfwCreateContextOSMesa(window, ctxconfig, fbconfig))
                return false;
        }
        else
        {
            _glfwInputError(GLFW_API_UNAVAILABLE, "Null: EGL not available");
            return false;
        }
    }

    if (window->monitor)
    {
        _glfwPlatformShowWindow(window);
        _glfwPlatformFocusWindow(window);
        acquireMonitor(window);
    }

    return true;
}

void _glfwPlatformDestroyWindow(_GLFWwindow* window)
{
    if (window->monitor)
        releaseMonitor(window);

    if (_glfw.null.focusedWindow == window)
        _glfw.null.focusedWindow = NULL;

    if (window->context.destroy)
        window->context.destroy(window);
}

void _glfwPlatformSetWindowTitle(_GLFWwindow* window UNUSED, const char* title UNUSED)
{
}

void _glfwPlatformSetWindowIcon(_GLFWwindow* window UNUSED, int count UNUSED,
                                const GLFWimage* images UNUSED)
{
}

void _glfwPlatformSetWindowMonitor(_GLFWwindow* window,
                                   _GLFWmonitor* monitor,
                                   int xpos, int ypos,
                                   int width, int height,
                                   int refreshRate UNUSED)
{
    if (window->monitor == monitor)
    {
        if (!monitor)
        {
            _glfwPlatformSetWindowPos(window, xpos, ypos);
            _glfwPlatformSetWindowSize(window, width, height);
        }

        return;
    }

    if (window->monitor)
        releaseMonitor(window);

    _glfwInputWindowMonitor(window, monitor);

    if (window->monitor)
    {
        window->null.visible = true;
        acquireMonitor(window);
        fitToMonitor(window);
    }
    else
    {
        _glfwPlatformSetWindowPos(window, xpos, ypos);
        _glfwPlatformSetWindowSize(window, width, height);
    }
}

void _glfwPlatformGetWindowPos(_GLFWwindow* window, int* xpos, int* ypos)
{
    if (xpos)
        *xpos = window->null.xpos;
    if (ypos)
        *ypos = window->null.ypos;
}

void _glfwPlatformSetWindowPos(_GLFWwindow* window, int xpos, int ypos)
{
    if (window->monitor)
        return;

    if (window->null.xpos != xpos || window->null.ypos != ypos)
    {
        window->null.xpos = xpos;
        window->null.ypos = ypos;
        _glfwInputWindowPos(window, xpos, ypos);
    }
}

void _glfwPlatformGetWindowSize(_GLFWwindow* window, int* width, int* height)
{
    if (width)
        *width = window->null.width;
    if (height)
        *height = window->null.height;
}

void _glfwPlatformSetWindowSize(_GLFWwindow* window, int width, int height)
{
    if (window->monitor)
        return;

    if (window->null.width != width || window->null.height != height)
    {
        window->null.width = width;
        window->null.height = height;
        _glfwInputWindowSize(window, width, height);
        _glfwInputFramebufferSize(window, width, height);
    }
}

void _glfwPlatformSetWindowSizeLimits(_GLFWwindow* window,
                                      int minwidth UNUSED, int minheight UNUSED,
                                      int maxwidth UNUSED, int maxheight UNUSED)
{
    int width = window->null.width;
    int height = window->null.height;
    applySizeLimits(window, &width, &height);
    _glfwPlatformSetWindowSize(window, width, height);
}

void _glfwPlatformSetWindowAspectRatio(_GLFWwindow* window, int n UNUSED, int d UNUSED)
{
    int width = window->null.width;
    int height = window->null.height;
    applySizeLimits(window, &width, &height);
    _glfwPlatformSetWindowSize(window, width, height);
}

void _glfwPlatformSetWindowSizeIncrements(_GLFWwindow* window UNUSED, int widthincr UNUSED, int heightincr UNUSED)
{
}

void _glfwPlatformGetFramebufferSize(_GLFWwindow* window, int* width, int* height)
{
    if (width)
        *width = window->null.width;
    if (height)
        *height = window->null.height;
}

void _glfwPlatformGetWindowFrameSize(_GLFWwindow* window,
                                     int* left, int* top,
                                     int* right, int* bottom)
{
    if (window->null.decorated && !window->monitor)
    {
        if (left)
            *left = 1;
        if (top)
            *top = 10;
        if (right)
            *right = 1;
        if (bottom)
            *bottom = 1;
    }
    else
    {
        if (left)
            *left = 0;
        if (top)
            *top = 0;
        if (right)
            *right = 0;
        if (bottom)
            *bottom = 0;
    }
}

void _glfwPlatformGetWindowContentScale(_GLFWwindow* window UNUSED,
                                        float* xscale, float* yscale)
{
    if (xscale)
        *xscale = 1.f;
    if (yscale)
        *yscale = 1.f;
}

monotonic_t _glfwPlatformGetDoubleClickInterval(_GLFWwindow* window UNUSED)
{
    return ms_to_monotonic_t(500ll);
}

void _glfwPlatformIconifyWindow(_GLFWwindow* window)
{
    if (_glfw.null.focusedWindow == window)
    {
        _glfw.null.focusedWindow = NULL;
        _glfwInputWindowFocus(window, false);
    }

    if (!window->null.iconified)
    {
        window->null.iconified = true;
        _glfwInputWindowIconify(window, true);

        if (window->monitor)
            releaseMonitor(window);
    }
}

void _glfwPlatformRestoreWindow(_GLFWwindow* window)
{
    if (window->null.iconified)
    {
        window->null.iconified = false;
        _glfwInputWindowIconify(window, false);

        if (window->monitor)
            acquireMonitor(window);
    }
    else if (window->null.maximized)
    {
        window->null.maximized = false;
        _glfwInputWindowMaximize(window, false);
    }
}

void _glfwPlatformMaximizeWindow(_GLFWwindow* window)
{
    if (!window->null.maximized)
    {
        window->null.maximized = true;
        _glfwInputWindowMaximize(window, true);
    }
}

int _glfwPlatformWindowMaximized(_GLFWwindow* window)
{
    return window->null.maximized;
}

int _glfwPlatformWindowHovered(_GLFWwindow* window)
{
    return _glfw.null.xcursor >= window->null.xpos &&
           _glfw.null.ycursor >= window->null.ypos &&
           _glfw.null.xcursor <= window->null.xpos + window->null.width - 1 &&
           _glfw.null.ycursor <= window->null.ypos + window->null.height - 1;
}

int _glfwPlatformFramebufferTransparent(_GLFWwindow* window)
{
    return window->null.transparent;
}

void _glfwPlatformSetWindowResizable(_GLFWwindow* window, bool enabled)
{
    window->null.resizable = enabled;
}

void _glfwPlatformSetWindowDecorated(_GLFWwindow* window, bool enabled)
{
    window->null.decorated = enabled;
}

void _glfwPlatformSetWindowFloating(_GLFWwindow* window, bool enabled)
{
    window->null.floating = enabled;
}

void _glfwPlatformSetWindowMousePassthrough(_GLFWwindow* window UNUSED, bool enabled UNUSED)
{
}

float _glfwPlatformGetWindowOpacity(_GLFWwindow* window)
{
    return window->null.opacity;
}

void _glfwPlatformSetWindowOpacity(_GLFWwindow* window, float opacity)
{
    window->null.opacity = opacity;
}

void _glfwPlatformSetRawMouseMotion(_GLFWwindow *window UNUSED, bool enabled UNUSED)
{
}

bool _glfwPlatformRawMouseMotionSupported(void)
{
    return true;
}

void _glfwPlatformShowWindow(_GLFWwindow* window)
{
    window->null.visible = true;
}

void _glfwPlatformRequestWindowAttention(_GLFWwindow* window UNUSED)
{
}

int _glfwPlatformWindowBell(_GLFWwindow* window UNUSED)
{
    return false;
}

void _glfwPlatformHideWindow(_GLFWwindow* window)
{
    if (_glfw.null.focusedWindow == window)
    {
        _glfw.null.focusedWindow = NULL;
        _glfwInputWindowFocus(window, false);
    }

    window->null.visible = false;
}

void _glfwPlatformFocusWindow(_GLFWwindow* window)
{
    if (_glfw.null.focusedWindow == window)
        return;

    if (!window->null.visible)
        return;

    _GLFWwindow* previous = _glfw.null.focusedWindow;
    _glfw.null.focusedWindow = window;

    if (previous)
    {
        _glfwInputWindowFocus(previous, false);
        if (previous->monitor && previous->autoIconify)
            _glfwPlatformIconifyWindow(previous);
    }

    _glfwInputWindowFocus(window, true);
}

int _glfwPlatformWindowFocused(_GLFWwindow* window)
{
    return _glfw.null.focusedWindow == window;
}

int _glfwPlatformWindowOccluded(_GLFWwindow* window UNUSED)
{
    return false;
}

int _glfwPlatformWindowIconified(_GLFWwindow* window)
{
    return window->null.iconified;
}

int _glfwPlatformWindowVisible(_GLFWwindow* window)
{
    return window->null.visible;
}

void _glfwPlatformPollEvents(void)
{
}

void _glfwPlatformWaitEvents(void)
{
}

void _glfwPlatformWaitEventsTimeout(monotonic_t timeout UNUSED)
{
}

void _glfwPlatformPostEmptyEvent(void)
{
}

void _glfwPlatformGetCursorPos(_GLFWwindow* window, double* xpos, double* ypos)
{
    if (xpos)
        *xpos = _glfw.null.xcursor - window->null.xpos;
    if (ypos)
        *ypos = _glfw.null.ycursor - window->null.ypos;
}

void _glfwPlatformSetCursorPos(_GLFWwindow* window, double x, double y)
{
    _glfw.null.xcursor = window->null.xpos + (int) x;
    _glfw.null.ycursor = window->null.ypos + (int) y;
}

void _glfwPlatformSetCursorMode(_GLFWwindow* window UNUSED, int mode UNUSED)
{
}

int _glfwPlatformCreateCursor(_GLFWcursor* cursor UNUSED,
                              const GLFWimage* image UNUSED,
                              int xhot UNUSED, int yhot UNUSED, int count UNUSED)
{
    return true;
}

int _glfwPlatformCreateStandardCursor(_GLFWcursor* cursor UNUSED, int shape UNUSED)
{
    return true;
}

void _glfwPlatformDestroyCursor(_GLFWcursor* cursor UNUSED)
{
}

void _glfwPlatformSetCursor(_GLFWwindow* window UNUSED, _GLFWcursor* cursor UNUSED)
{
}

void _glfwPlatformSetClipboardString(const char* string)
{
    char* copy = _glfw_strdup(string);
    free(_glfw.null.clipboardString);
    _glfw.null.clipboardString = copy;
}

const char* _glfwPlatformGetClipboardString(void)
{
    return _glfw.null.clipboardString;
}

const char* _glfwPlatformGetNativeKeyName(int native_key)
{
    switch (scancode)
    {
        case GLFW_KEY_APOSTROPHE:
            return "'";
        case GLFW_KEY_COMMA:
            return ",";
        case GLFW_KEY_MINUS:
        case GLFW_KEY_KP_SUBTRACT:
            return "-";
        case GLFW_KEY_PERIOD:
        case GLFW_KEY_KP_DECIMAL:
            return ".";
        case GLFW_KEY_SLASH:
        case GLFW_KEY_KP_DIVIDE:
            return "/";
        case GLFW_KEY_SEMICOLON:
            return ";";
        case GLFW_KEY_EQUAL:
        case GLFW_KEY_KP_EQUAL:
            return "=";
        case GLFW_KEY_LEFT_BRACKET:
            return "[";
        case GLFW_KEY_RIGHT_BRACKET:
            return "]";
        case GLFW_KEY_KP_MULTIPLY:
            return "*";
        case GLFW_KEY_KP_ADD:
            return "+";
        case GLFW_KEY_BACKSLASH:
        case GLFW_KEY_WORLD_1:
        case GLFW_KEY_WORLD_2:
            return "\\";
        case GLFW_KEY_0:
        case GLFW_KEY_KP_0:
            return "0";
        case GLFW_KEY_1:
        case GLFW_KEY_KP_1:
            return "1";
        case GLFW_KEY_2:
        case GLFW_KEY_KP_2:
            return "2";
        case GLFW_KEY_3:
        case GLFW_KEY_KP_3:
            return "3";
        case GLFW_KEY_4:
        case GLFW_KEY_KP_4:
            return "4";
        case GLFW_KEY_5:
        case GLFW_KEY_KP_5:
            return "5";
        case GLFW_KEY_6:
        case GLFW_KEY_KP_6:
            return "6";
        case GLFW_KEY_7:
        case GLFW_KEY_KP_7:
            return "7";
        case GLFW_KEY_8:
        case GLFW_KEY_KP_8:
            return "8";
        case GLFW_KEY_9:
        case GLFW_KEY_KP_9:
            return "9";
        case GLFW_KEY_A:
            return "a";
        case GLFW_KEY_B:
            return "b";
        case GLFW_KEY_C:
            return "c";
        case GLFW_KEY_D:
            return "d";
        case GLFW_KEY_E:
            return "e";
        case GLFW_KEY_F:
            return "f";
        case GLFW_KEY_G:
            return "g";
        case GLFW_KEY_H:
            return "h";
        case GLFW_KEY_I:
            return "i";
        case GLFW_KEY_J:
            return "j";
        case GLFW_KEY_K:
            return "k";
        case GLFW_KEY_L:
            return "l";
        case GLFW_KEY_M:
            return "m";
        case GLFW_KEY_N:
            return "n";
        case GLFW_KEY_O:
            return "o";
        case GLFW_KEY_P:
            return "p";
        case GLFW_KEY_Q:
            return "q";
        case GLFW_KEY_R:
            return "r";
        case GLFW_KEY_S:
            return "s";
        case GLFW_KEY_T:
            return "t";
        case GLFW_KEY_U:
            return "u";
        case GLFW_KEY_V:
            return "v";
        case GLFW_KEY_W:
            return "w";
        case GLFW_KEY_X:
            return "x";
        case GLFW_KEY_Y:
            return "y";
        case GLFW_KEY_Z:
            return "z";
    }

    return NULL;
}

int _glfwPlatformGetNativeKeyForKey(int key)
{
    return key;
}

void _glfwPlatformGetRequiredInstanceExtensions(char** extensions UNUSED)
{
}

int _glfwPlatformGetPhysicalDevicePresentationSupport(VkInstance instance UNUSED,
                                                      VkPhysicalDevice device UNUSED,
                                                      uint32_t queuefamily UNUSED)
{
    return false;
}

VkResult _glfwPlatformCreateWindowSurface(VkInstance instance UNUSED,
                                          _GLFWwindow* window UNUSED,
                                          const VkAllocationCallbacks* allocator UNUSED,
                                          VkSurfaceKHR* surface UNUSED)
{
    // This seems like the most appropriate error to return here
    return VK_ERROR_EXTENSION_NOT_PRESENT;
}

