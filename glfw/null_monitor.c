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


//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

void _glfwPlatformFreeMonitor(_GLFWmonitor* monitor UNUSED)
{
}

void _glfwPlatformGetMonitorPos(_GLFWmonitor* monitor UNUSED, int* xpos UNUSED, int* ypos UNUSED)
{
}

void _glfwPlatformGetMonitorContentScale(_GLFWmonitor* monitor UNUSED,
                                         float* xscale, float* yscale)
{
    if (xscale)
        *xscale = 1.f;
    if (yscale)
        *yscale = 1.f;
}

void _glfwPlatformGetMonitorWorkarea(_GLFWmonitor* monitor UNUSED,
                                     int* xpos UNUSED, int* ypos UNUSED,
                                     int* width UNUSED, int* height UNUSED)
{
}

GLFWvidmode* _glfwPlatformGetVideoModes(_GLFWmonitor* monitor UNUSED, int* found UNUSED)
{
    return NULL;
}

void _glfwPlatformGetVideoMode(_GLFWmonitor* monitor UNUSED, GLFWvidmode* mode UNUSED)
{
}

bool _glfwPlatformGetGammaRamp(_GLFWmonitor* monitor UNUSED, GLFWgammaramp* ramp UNUSED)
{
    return false;
}

void _glfwPlatformSetGammaRamp(_GLFWmonitor* monitor UNUSED, const GLFWgammaramp* ramp UNUSED)
{
}

