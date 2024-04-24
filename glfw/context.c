//========================================================================
// GLFW 3.4 - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2002-2006 Marcus Geelnard
// Copyright (c) 2006-2016 Camilla Löwy <elmindreda@glfw.org>
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
// Please use C89 style variable declarations in this file because VS 2010
//========================================================================

#include "internal.h"

#include <assert.h>
#include <stdio.h>
#include <string.h>
#include <stdio.h>


//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

// Checks whether the desired context attributes are valid
//
// This function checks things like whether the specified client API version
// exists and whether all relevant options have supported and non-conflicting
// values
//
bool _glfwIsValidContextConfig(const _GLFWctxconfig* ctxconfig)
{
    if (ctxconfig->share)
    {
        if (ctxconfig->client == GLFW_NO_API ||
            ctxconfig->share->context.client == GLFW_NO_API)
        {
            _glfwInputError(GLFW_NO_WINDOW_CONTEXT, NULL);
            return false;
        }
    }

    if (ctxconfig->source != GLFW_NATIVE_CONTEXT_API &&
        ctxconfig->source != GLFW_EGL_CONTEXT_API &&
        ctxconfig->source != GLFW_OSMESA_CONTEXT_API)
    {
        _glfwInputError(GLFW_INVALID_ENUM,
                        "Invalid context creation API 0x%08X",
                        ctxconfig->source);
        return false;
    }

    if (ctxconfig->client != GLFW_NO_API &&
        ctxconfig->client != GLFW_OPENGL_API &&
        ctxconfig->client != GLFW_OPENGL_ES_API)
    {
        _glfwInputError(GLFW_INVALID_ENUM,
                        "Invalid client API 0x%08X",
                        ctxconfig->client);
        return false;
    }

    if (ctxconfig->client == GLFW_OPENGL_API)
    {
        if ((ctxconfig->major < 1 || ctxconfig->minor < 0) ||
            (ctxconfig->major == 1 && ctxconfig->minor > 5) ||
            (ctxconfig->major == 2 && ctxconfig->minor > 1) ||
            (ctxconfig->major == 3 && ctxconfig->minor > 3))
        {
            // OpenGL 1.0 is the smallest valid version
            // OpenGL 1.x series ended with version 1.5
            // OpenGL 2.x series ended with version 2.1
            // OpenGL 3.x series ended with version 3.3
            // For now, let everything else through

            _glfwInputError(GLFW_INVALID_VALUE,
                            "Invalid OpenGL version %i.%i",
                            ctxconfig->major, ctxconfig->minor);
            return false;
        }

        if (ctxconfig->profile)
        {
            if (ctxconfig->profile != GLFW_OPENGL_CORE_PROFILE &&
                ctxconfig->profile != GLFW_OPENGL_COMPAT_PROFILE)
            {
                _glfwInputError(GLFW_INVALID_ENUM,
                                "Invalid OpenGL profile 0x%08X",
                                ctxconfig->profile);
                return false;
            }

            if (ctxconfig->major <= 2 ||
                (ctxconfig->major == 3 && ctxconfig->minor < 2))
            {
                // Desktop OpenGL context profiles are only defined for version 3.2
                // and above

                _glfwInputError(GLFW_INVALID_VALUE,
                                "Context profiles are only defined for OpenGL version 3.2 and above");
                return false;
            }
        }

        if (ctxconfig->forward && ctxconfig->major <= 2)
        {
            // Forward-compatible contexts are only defined for OpenGL version 3.0 and above
            _glfwInputError(GLFW_INVALID_VALUE,
                            "Forward-compatibility is only defined for OpenGL version 3.0 and above");
            return false;
        }
    }
    else if (ctxconfig->client == GLFW_OPENGL_ES_API)
    {
        if (ctxconfig->major < 1 || ctxconfig->minor < 0 ||
            (ctxconfig->major == 1 && ctxconfig->minor > 1) ||
            (ctxconfig->major == 2 && ctxconfig->minor > 0))
        {
            // OpenGL ES 1.0 is the smallest valid version
            // OpenGL ES 1.x series ended with version 1.1
            // OpenGL ES 2.x series ended with version 2.0
            // For now, let everything else through

            _glfwInputError(GLFW_INVALID_VALUE,
                            "Invalid OpenGL ES version %i.%i",
                            ctxconfig->major, ctxconfig->minor);
            return false;
        }
    }

    if (ctxconfig->robustness)
    {
        if (ctxconfig->robustness != GLFW_NO_RESET_NOTIFICATION &&
            ctxconfig->robustness != GLFW_LOSE_CONTEXT_ON_RESET)
        {
            _glfwInputError(GLFW_INVALID_ENUM,
                            "Invalid context robustness mode 0x%08X",
                            ctxconfig->robustness);
            return false;
        }
    }

    if (ctxconfig->release)
    {
        if (ctxconfig->release != GLFW_RELEASE_BEHAVIOR_NONE &&
            ctxconfig->release != GLFW_RELEASE_BEHAVIOR_FLUSH)
        {
            _glfwInputError(GLFW_INVALID_ENUM,
                            "Invalid context release behavior 0x%08X",
                            ctxconfig->release);
            return false;
        }
    }

    return true;
}

// Retrieves the attributes of the current context
//
bool _glfwRefreshContextAttribs(_GLFWwindow* window,
                                    const _GLFWctxconfig* ctxconfig)
{
    int i;
    _GLFWwindow* previous;
    const char* version;
    const char* prefixes[] =
    {
        "OpenGL ES-CM ",
        "OpenGL ES-CL ",
        "OpenGL ES ",
        NULL
    };

    window->context.source = ctxconfig->source;
    window->context.client = GLFW_OPENGL_API;

    previous = _glfwPlatformGetTls(&_glfw.contextSlot);
    glfwMakeContextCurrent((GLFWwindow*) window);

    window->context.GetIntegerv = (PFNGLGETINTEGERVPROC)
        window->context.getProcAddress("glGetIntegerv");
    window->context.GetString = (PFNGLGETSTRINGPROC)
        window->context.getProcAddress("glGetString");
    if (!window->context.GetIntegerv || !window->context.GetString)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Entry point retrieval is broken");
        glfwMakeContextCurrent((GLFWwindow*) previous);
        return false;
    }

    version = (const char*) window->context.GetString(GL_VERSION);
    if (!version)
    {
        if (ctxconfig->client == GLFW_OPENGL_API)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "OpenGL version string retrieval is broken");
        }
        else
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "OpenGL ES version string retrieval is broken");
        }

        glfwMakeContextCurrent((GLFWwindow*) previous);
        return false;
    }

    for (i = 0;  prefixes[i];  i++)
    {
        const size_t length = strlen(prefixes[i]);

        if (strncmp(version, prefixes[i], length) == 0)
        {
            version += length;
            window->context.client = GLFW_OPENGL_ES_API;
            break;
        }
    }

    if (sscanf(version, "%d.%d.%d",
                &window->context.major,
                &window->context.minor,
                &window->context.revision) < 1)
    {
        if (window->context.client == GLFW_OPENGL_API)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "No version found in OpenGL version string");
        }
        else
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "No version found in OpenGL ES version string");
        }

        glfwMakeContextCurrent((GLFWwindow*) previous);
        return false;
    }

    if (window->context.major < ctxconfig->major ||
        (window->context.major == ctxconfig->major &&
         window->context.minor < ctxconfig->minor))
    {
        // The desired OpenGL version is greater than the actual version
        // This only happens if the machine lacks {GLX|WGL}_ARB_create_context
        // /and/ the user has requested an OpenGL version greater than 1.0

        // For API consistency, we emulate the behavior of the
        // {GLX|WGL}_ARB_create_context extension and fail here

        if (window->context.client == GLFW_OPENGL_API)
        {
            _glfwInputError(GLFW_VERSION_UNAVAILABLE,
                            "Requested OpenGL version %i.%i, got version %i.%i",
                            ctxconfig->major, ctxconfig->minor,
                            window->context.major, window->context.minor);
        }
        else
        {
            _glfwInputError(GLFW_VERSION_UNAVAILABLE,
                            "Requested OpenGL ES version %i.%i, got version %i.%i",
                            ctxconfig->major, ctxconfig->minor,
                            window->context.major, window->context.minor);
        }

        glfwMakeContextCurrent((GLFWwindow*) previous);
        return false;
    }

    if (window->context.major >= 3)
    {
        // OpenGL 3.0+ uses a different function for extension string retrieval
        // We cache it here instead of in glfwExtensionSupported mostly to alert
        // users as early as possible that their build may be broken

        window->context.GetStringi = (PFNGLGETSTRINGIPROC)
            window->context.getProcAddress("glGetStringi");
        if (!window->context.GetStringi)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Entry point retrieval is broken");
            glfwMakeContextCurrent((GLFWwindow*) previous);
            return false;
        }
    }

    if (window->context.client == GLFW_OPENGL_API)
    {
        // Read back context flags (OpenGL 3.0 and above)
        if (window->context.major >= 3)
        {
            GLint flags;
            window->context.GetIntegerv(GL_CONTEXT_FLAGS, &flags);

            if (flags & GL_CONTEXT_FLAG_FORWARD_COMPATIBLE_BIT)
                window->context.forward = true;

            if (flags & GL_CONTEXT_FLAG_DEBUG_BIT)
                window->context.debug = true;
            else if (glfwExtensionSupported("GL_ARB_debug_output") &&
                     ctxconfig->debug)
            {
                // HACK: This is a workaround for older drivers (pre KHR_debug)
                //       not setting the debug bit in the context flags for
                //       debug contexts
                window->context.debug = true;
            }

            if (flags & GL_CONTEXT_FLAG_NO_ERROR_BIT_KHR)
                window->context.noerror = true;
        }

        // Read back OpenGL context profile (OpenGL 3.2 and above)
        if (window->context.major >= 4 ||
            (window->context.major == 3 && window->context.minor >= 2))
        {
            GLint mask;
            window->context.GetIntegerv(GL_CONTEXT_PROFILE_MASK, &mask);

            if (mask & GL_CONTEXT_COMPATIBILITY_PROFILE_BIT)
                window->context.profile = GLFW_OPENGL_COMPAT_PROFILE;
            else if (mask & GL_CONTEXT_CORE_PROFILE_BIT)
                window->context.profile = GLFW_OPENGL_CORE_PROFILE;
            else if (glfwExtensionSupported("GL_ARB_compatibility"))
            {
                // HACK: This is a workaround for the compatibility profile bit
                //       not being set in the context flags if an OpenGL 3.2+
                //       context was created without having requested a specific
                //       version
                window->context.profile = GLFW_OPENGL_COMPAT_PROFILE;
            }
        }

        // Read back robustness strategy
        if (glfwExtensionSupported("GL_ARB_robustness"))
        {
            // NOTE: We avoid using the context flags for detection, as they are
            //       only present from 3.0 while the extension applies from 1.1

            GLint strategy;
            window->context.GetIntegerv(GL_RESET_NOTIFICATION_STRATEGY_ARB,
                                        &strategy);

            if (strategy == GL_LOSE_CONTEXT_ON_RESET_ARB)
                window->context.robustness = GLFW_LOSE_CONTEXT_ON_RESET;
            else if (strategy == GL_NO_RESET_NOTIFICATION_ARB)
                window->context.robustness = GLFW_NO_RESET_NOTIFICATION;
        }
    }
    else
    {
        // Read back robustness strategy
        if (glfwExtensionSupported("GL_EXT_robustness"))
        {
            // NOTE: The values of these constants match those of the OpenGL ARB
            //       one, so we can reuse them here

            GLint strategy;
            window->context.GetIntegerv(GL_RESET_NOTIFICATION_STRATEGY_ARB,
                                        &strategy);

            if (strategy == GL_LOSE_CONTEXT_ON_RESET_ARB)
                window->context.robustness = GLFW_LOSE_CONTEXT_ON_RESET;
            else if (strategy == GL_NO_RESET_NOTIFICATION_ARB)
                window->context.robustness = GLFW_NO_RESET_NOTIFICATION;
        }
    }

    if (glfwExtensionSupported("GL_KHR_context_flush_control"))
    {
        GLint behavior;
        window->context.GetIntegerv(GL_CONTEXT_RELEASE_BEHAVIOR, &behavior);

        if (behavior == GL_NONE)
            window->context.release = GLFW_RELEASE_BEHAVIOR_NONE;
        else if (behavior == GL_CONTEXT_RELEASE_BEHAVIOR_FLUSH)
            window->context.release = GLFW_RELEASE_BEHAVIOR_FLUSH;
    }

    glfwMakeContextCurrent((GLFWwindow*) previous);
    return true;
}

// Searches an extension string for the specified extension
//
bool _glfwStringInExtensionString(const char* string, const char* extensions)
{
    const char* start = extensions;

    for (;;)
    {
        const char* where;
        const char* terminator;

        where = strstr(start, string);
        if (!where)
            return false;

        terminator = where + strlen(string);
        if (where == start || *(where - 1) == ' ')
        {
            if (*terminator == ' ' || *terminator == '\0')
                break;
        }

        start = terminator;
    }

    return true;
}


//////////////////////////////////////////////////////////////////////////
//////                        GLFW public API                       //////
//////////////////////////////////////////////////////////////////////////

GLFWAPI void glfwMakeContextCurrent(GLFWwindow* handle)
{
    _GLFW_REQUIRE_INIT();

    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFWwindow* previous = _glfwPlatformGetTls(&_glfw.contextSlot);

    if (window && window->context.client == GLFW_NO_API)
    {
        _glfwInputError(GLFW_NO_WINDOW_CONTEXT,
                        "Cannot make current with a window that has no OpenGL or OpenGL ES context");
        return;
    }

    if (previous)
    {
        if (!window || window->context.source != previous->context.source)
            previous->context.makeCurrent(NULL);
    }

    if (window)
        window->context.makeCurrent(window);
}

GLFWAPI GLFWwindow* glfwGetCurrentContext(void)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    return _glfwPlatformGetTls(&_glfw.contextSlot);
}

GLFWAPI void glfwSwapBuffers(GLFWwindow* handle)
{
    _GLFWwindow* window = (_GLFWwindow*) handle;
    assert(window != NULL);

    _GLFW_REQUIRE_INIT();

    if (window->context.client == GLFW_NO_API)
    {
        _glfwInputError(GLFW_NO_WINDOW_CONTEXT,
                        "Cannot swap buffers of a window that has no OpenGL or OpenGL ES context");
        return;
    }

    window->context.swapBuffers(window);
#ifdef _GLFW_WAYLAND
    _glfwWaylandAfterBufferSwap(window);
#endif
}

GLFWAPI void glfwSwapInterval(int interval)
{
    _GLFWwindow* window;

    _GLFW_REQUIRE_INIT();

    window = _glfwPlatformGetTls(&_glfw.contextSlot);
    if (!window)
    {
        _glfwInputError(GLFW_NO_CURRENT_CONTEXT,
                        "Cannot set swap interval without a current OpenGL or OpenGL ES context");
        return;
    }

    window->context.swapInterval(interval);
}

GLFWAPI int glfwExtensionSupported(const char* extension)
{
    _GLFWwindow* window;
    assert(extension != NULL);

    _GLFW_REQUIRE_INIT_OR_RETURN(false);

    window = _glfwPlatformGetTls(&_glfw.contextSlot);
    if (!window)
    {
        _glfwInputError(GLFW_NO_CURRENT_CONTEXT,
                        "Cannot query extension without a current OpenGL or OpenGL ES context");
        return false;
    }

    if (*extension == '\0')
    {
        _glfwInputError(GLFW_INVALID_VALUE, "Extension name cannot be an empty string");
        return false;
    }

    if (window->context.major >= 3)
    {
        int i;
        GLint count;

        // Check if extension is in the modern OpenGL extensions string list

        window->context.GetIntegerv(GL_NUM_EXTENSIONS, &count);

        for (i = 0;  i < count;  i++)
        {
            const char* en = (const char*)
                window->context.GetStringi(GL_EXTENSIONS, i);
            if (!en)
            {
                _glfwInputError(GLFW_PLATFORM_ERROR,
                                "Extension string retrieval is broken");
                return false;
            }

            if (strcmp(en, extension) == 0)
                return true;
        }
    }
    else
    {
        // Check if extension is in the old style OpenGL extensions string

        const char* extensions = (const char*)
            window->context.GetString(GL_EXTENSIONS);
        if (!extensions)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Extension string retrieval is broken");
            return false;
        }

        if (_glfwStringInExtensionString(extension, extensions))
            return true;
    }

    // Check if extension is in the platform-specific string
    return window->context.extensionSupported(extension);
}

GLFWAPI GLFWglproc glfwGetProcAddress(const char* procname)
{
    _GLFWwindow* window;
    assert(procname != NULL);

    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);

    window = _glfwPlatformGetTls(&_glfw.contextSlot);
    if (!window)
    {
        _glfwInputError(GLFW_NO_CURRENT_CONTEXT,
                        "Cannot query entry point without a current OpenGL or OpenGL ES context");
        return NULL;
    }

    return window->context.getProcAddress(procname);
}
