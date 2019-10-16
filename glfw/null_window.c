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


static int createNativeWindow(_GLFWwindow* window,
                              const _GLFWwndconfig* wndconfig)
{
    window->null.width = wndconfig->width;
    window->null.height = wndconfig->height;

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
    if (!createNativeWindow(window, wndconfig))
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

    return true;
}

void _glfwPlatformDestroyWindow(_GLFWwindow* window)
{
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

void _glfwPlatformSetWindowMonitor(_GLFWwindow* window UNUSED,
                                   _GLFWmonitor* monitor UNUSED,
                                   int xpos UNUSED, int ypos UNUSED,
                                   int width UNUSED, int height UNUSED,
                                   int refreshRate UNUSED)
{
}

void _glfwPlatformGetWindowPos(_GLFWwindow* window UNUSED, int* xpos UNUSED, int* ypos UNUSED)
{
}

void _glfwPlatformSetWindowPos(_GLFWwindow* window UNUSED, int xpos UNUSED, int ypos UNUSED)
{
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
    window->null.width = width;
    window->null.height = height;
}

void _glfwPlatformSetWindowSizeLimits(_GLFWwindow* window UNUSED,
                                      int minwidth UNUSED, int minheight UNUSED,
                                      int maxwidth UNUSED, int maxheight UNUSED)
{
}

void _glfwPlatformSetWindowAspectRatio(_GLFWwindow* window UNUSED, int n UNUSED, int d UNUSED)
{
}

void _glfwPlatformGetFramebufferSize(_GLFWwindow* window, int* width, int* height)
{
    if (width)
        *width = window->null.width;
    if (height)
        *height = window->null.height;
}

void _glfwPlatformGetWindowFrameSize(_GLFWwindow* window UNUSED,
                                     int* left UNUSED, int* top UNUSED,
                                     int* right UNUSED, int* bottom UNUSED)
{
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

void _glfwPlatformIconifyWindow(_GLFWwindow* window UNUSED)
{
}

void _glfwPlatformRestoreWindow(_GLFWwindow* window UNUSED)
{
}

void _glfwPlatformMaximizeWindow(_GLFWwindow* window UNUSED)
{
}

int _glfwPlatformWindowMaximized(_GLFWwindow* window UNUSED)
{
    return false;
}

int _glfwPlatformWindowHovered(_GLFWwindow* window UNUSED)
{
    return false;
}

int _glfwPlatformFramebufferTransparent(_GLFWwindow* window UNUSED)
{
    return false;
}

void _glfwPlatformSetWindowResizable(_GLFWwindow* window UNUSED, bool enabled UNUSED)
{
}

void _glfwPlatformSetWindowDecorated(_GLFWwindow* window UNUSED, bool enabled UNUSED)
{
}

void _glfwPlatformSetWindowFloating(_GLFWwindow* window UNUSED, bool enabled UNUSED)
{
}

float _glfwPlatformGetWindowOpacity(_GLFWwindow* window UNUSED)
{
    return 1.f;
}

void _glfwPlatformSetWindowOpacity(_GLFWwindow* window UNUSED, float opacity UNUSED)
{
}

void _glfwPlatformShowWindow(_GLFWwindow* window UNUSED)
{
}


void _glfwPlatformRequestWindowAttention(_GLFWwindow* window UNUSED)
{
}

int _glfwPlatformWindowBell(_GLFWwindow* window UNUSED)
{
    return false;
}

void _glfwPlatformUnhideWindow(_GLFWwindow* window UNUSED)
{
}

void _glfwPlatformHideWindow(_GLFWwindow* window UNUSED)
{
}

void _glfwPlatformFocusWindow(_GLFWwindow* window UNUSED)
{
}

int _glfwPlatformWindowFocused(_GLFWwindow* window UNUSED)
{
    return false;
}

int _glfwPlatformWindowOccluded(_GLFWwindow* window UNUSED)
{
    return false;
}

int _glfwPlatformWindowIconified(_GLFWwindow* window UNUSED)
{
    return false;
}

int _glfwPlatformWindowVisible(_GLFWwindow* window UNUSED)
{
    return false;
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

void _glfwPlatformGetCursorPos(_GLFWwindow* window UNUSED, double* xpos UNUSED, double* ypos UNUSED)
{
}

void _glfwPlatformSetCursorPos(_GLFWwindow* window UNUSED, double x UNUSED, double y UNUSED)
{
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

void _glfwPlatformSetClipboardString(const char* string UNUSED)
{
}

const char* _glfwPlatformGetClipboardString(void)
{
    return NULL;
}

const char* _glfwPlatformGetNativeKeyName(int native_key UNUSED)
{
    return "";
}

int _glfwPlatformGetNativeKeyForKey(int key UNUSED)
{
    return -1;
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
    return VK_ERROR_INITIALIZATION_FAILED;
}

