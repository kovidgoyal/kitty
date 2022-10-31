//========================================================================
// GLFW 3.4 EGL - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2002-2006 Marcus Geelnard
// Copyright (c) 2006-2019 Camilla Löwy <elmindreda@glfw.org>
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

#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <assert.h>


// Return a description of the specified EGL error
//
static const char* getEGLErrorString(EGLint error)
{
    switch (error)
    {
        case EGL_SUCCESS:
            return "Success";
        case EGL_NOT_INITIALIZED:
            return "EGL is not or could not be initialized";
        case EGL_BAD_ACCESS:
            return "EGL cannot access a requested resource";
        case EGL_BAD_ALLOC:
            return "EGL failed to allocate resources for the requested operation";
        case EGL_BAD_ATTRIBUTE:
            return "An unrecognized attribute or attribute value was passed in the attribute list";
        case EGL_BAD_CONTEXT:
            return "An EGLContext argument does not name a valid EGL rendering context";
        case EGL_BAD_CONFIG:
            return "An EGLConfig argument does not name a valid EGL frame buffer configuration";
        case EGL_BAD_CURRENT_SURFACE:
            return "The current surface of the calling thread is a window, pixel buffer or pixmap that is no longer valid";
        case EGL_BAD_DISPLAY:
            return "An EGLDisplay argument does not name a valid EGL display connection";
        case EGL_BAD_SURFACE:
            return "An EGLSurface argument does not name a valid surface configured for GL rendering";
        case EGL_BAD_MATCH:
            return "Arguments are inconsistent";
        case EGL_BAD_PARAMETER:
            return "One or more argument values are invalid";
        case EGL_BAD_NATIVE_PIXMAP:
            return "A NativePixmapType argument does not refer to a valid native pixmap";
        case EGL_BAD_NATIVE_WINDOW:
            return "A NativeWindowType argument does not refer to a valid native window";
        case EGL_CONTEXT_LOST:
            return "The application must destroy all contexts and reinitialise";
        default:
            return "ERROR: UNKNOWN EGL ERROR";
    }
}

#ifdef _GLFW_X11
// Returns the specified attribute of the specified EGLConfig
//
static int getEGLConfigAttrib(EGLConfig config, int attrib)
{
    int value;
    eglGetConfigAttrib(_glfw.egl.display, config, attrib, &value);
    return value;
}
#endif

// Return the EGLConfig most closely matching the specified hints
//
static bool chooseEGLConfig(const _GLFWctxconfig* ctxconfig,
                                const _GLFWfbconfig* desired,
                                EGLConfig* result)
{
    EGLConfig configs[512];
    int i = 0, nativeCount = 0, ans_idx = 0;
    EGLint attributes[64];
#define ATTR(k, v) { attributes[i++] = k; attributes[i++] = v; }
    ATTR(EGL_COLOR_BUFFER_TYPE, EGL_RGB_BUFFER);
    ATTR(EGL_SURFACE_TYPE, EGL_WINDOW_BIT);
    if (ctxconfig->client == GLFW_OPENGL_ES_API) {
        if (ctxconfig->major == 1) ATTR(EGL_RENDERABLE_TYPE, EGL_OPENGL_ES_BIT)
        else ATTR(EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT);
    }
    else if (ctxconfig->client == GLFW_OPENGL_API) ATTR(EGL_RENDERABLE_TYPE, EGL_OPENGL_BIT);
    if (desired->samples > 0) ATTR(EGL_SAMPLES, desired->samples);
    if (desired->depthBits > 0) ATTR(EGL_DEPTH_SIZE, desired->depthBits);
    if (desired->stencilBits > 0) ATTR(EGL_STENCIL_SIZE, desired->stencilBits);
    if (desired->redBits > 0) ATTR(EGL_RED_SIZE, desired->redBits);
    if (desired->greenBits > 0) ATTR(EGL_GREEN_SIZE, desired->greenBits);
    if (desired->blueBits > 0) ATTR(EGL_BLUE_SIZE, desired->blueBits);
    if (desired->alphaBits > 0) ATTR(EGL_ALPHA_SIZE, desired->alphaBits);
    ATTR(EGL_NONE, EGL_NONE);
#undef ATTR
    if (!eglChooseConfig(_glfw.egl.display, attributes, configs, sizeof(configs)/sizeof(configs[0]), &nativeCount)) {
        _glfwInputError(GLFW_API_UNAVAILABLE, "EGL: eglChooseConfig failed");
        return false;
    }

    if (!nativeCount)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE, "EGL: No EGLConfigs returned");
        return false;
    }


    for (i = 0;  i < nativeCount;  i++)
    {

#if defined(_GLFW_X11)
        {
            const EGLConfig n = configs[i];
            XVisualInfo vi = {0};

            // Only consider EGLConfigs with associated Visuals
            vi.visualid = getEGLConfigAttrib(n, EGL_NATIVE_VISUAL_ID);
            if (!vi.visualid)
                continue;

            if (desired->transparent)
            {
                int count;
                XVisualInfo* vis =
                    XGetVisualInfo(_glfw.x11.display, VisualIDMask, &vi, &count);
                if (vis)
                {
                    bool transparent = _glfwIsVisualTransparentX11(vis[0].visual);
                    XFree(vis);
                    if (!transparent) continue;
                }
            }
        }
#endif // _GLFW_X11
        ans_idx = i;
        break;
    }
    *result = configs[ans_idx];
    return true;
}

static void makeContextCurrentEGL(_GLFWwindow* window)
{
    if (window)
    {
        if (!eglMakeCurrent(_glfw.egl.display,
                            window->context.egl.surface,
                            window->context.egl.surface,
                            window->context.egl.handle))
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "EGL: Failed to make context current: %s",
                            getEGLErrorString(eglGetError()));
            return;
        }
    }
    else
    {
        if (!eglMakeCurrent(_glfw.egl.display,
                            EGL_NO_SURFACE,
                            EGL_NO_SURFACE,
                            EGL_NO_CONTEXT))
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "EGL: Failed to clear current context: %s",
                            getEGLErrorString(eglGetError()));
            return;
        }
    }

    _glfwPlatformSetTls(&_glfw.contextSlot, window);
}

static void swapBuffersEGL(_GLFWwindow* window)
{
    if (window != _glfwPlatformGetTls(&_glfw.contextSlot))
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "EGL: The context must be current on the calling thread when swapping buffers");
        return;
    }

    eglSwapBuffers(_glfw.egl.display, window->context.egl.surface);
}

static void swapIntervalEGL(int interval)
{
    eglSwapInterval(_glfw.egl.display, interval);
}

static int extensionSupportedEGL(const char* extension)
{
    const char* extensions = eglQueryString(_glfw.egl.display, EGL_EXTENSIONS);
    if (extensions)
    {
        if (_glfwStringInExtensionString(extension, extensions))
            return true;
    }

    return false;
}

static GLFWglproc getProcAddressEGL(const char* procname)
{
    _GLFWwindow* window = _glfwPlatformGetTls(&_glfw.contextSlot);

    if (window->context.egl.client)
    {
        GLFWglproc proc = NULL;
        glfw_dlsym(proc, window->context.egl.client, procname);
        if (proc)
            return proc;
    }

    return eglGetProcAddress(procname);
}

static void destroyContextEGL(_GLFWwindow* window)
{
#if defined(_GLFW_X11)
    // NOTE: Do not unload libGL.so.1 while the X11 display is still open,
    //       as it will make XCloseDisplay segfault
    if (window->context.client != GLFW_OPENGL_API)
#endif // _GLFW_X11
    {
        if (window->context.egl.client)
        {
            _glfw_dlclose(window->context.egl.client);
            window->context.egl.client = NULL;
        }
    }

    if (window->context.egl.surface)
    {
        eglDestroySurface(_glfw.egl.display, window->context.egl.surface);
        window->context.egl.surface = EGL_NO_SURFACE;
    }

    if (window->context.egl.handle)
    {
        eglDestroyContext(_glfw.egl.display, window->context.egl.handle);
        window->context.egl.handle = EGL_NO_CONTEXT;
    }
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

// Initialize EGL
//
bool _glfwInitEGL(void)
{
    int i;
    EGLint* attribs = NULL;
    const char* extensions;
    const char* sonames[] =
    {
#if defined(_GLFW_EGL_LIBRARY)
        _GLFW_EGL_LIBRARY,
#elif defined(_GLFW_WIN32)
        "libEGL.dll",
        "EGL.dll",
#elif defined(_GLFW_COCOA)
        "libEGL.dylib",
#elif defined(__CYGWIN__)
        "libEGL-1.so",
#else
        "libEGL.so.1",
#endif
        NULL
    };

    if (_glfw.egl.handle)
        return true;

    for (i = 0;  sonames[i];  i++)
    {
        _glfw.egl.handle = _glfw_dlopen(sonames[i]);
        if (_glfw.egl.handle)
            break;
    }

    if (!_glfw.egl.handle)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE, "EGL: Library not found");
        return false;
    }

    _glfw.egl.prefix = (strncmp(sonames[i], "lib", 3) == 0);

    glfw_dlsym(_glfw.egl.GetConfigAttrib, _glfw.egl.handle, "eglGetConfigAttrib");
    glfw_dlsym(_glfw.egl.GetConfigs, _glfw.egl.handle, "eglGetConfigs");
    glfw_dlsym(_glfw.egl.ChooseConfig, _glfw.egl.handle, "eglChooseConfig");
    glfw_dlsym(_glfw.egl.GetDisplay, _glfw.egl.handle, "eglGetDisplay");
    glfw_dlsym(_glfw.egl.GetError, _glfw.egl.handle, "eglGetError");
    glfw_dlsym(_glfw.egl.Initialize, _glfw.egl.handle, "eglInitialize");
    glfw_dlsym(_glfw.egl.Terminate, _glfw.egl.handle, "eglTerminate");
    glfw_dlsym(_glfw.egl.BindAPI, _glfw.egl.handle, "eglBindAPI");
    glfw_dlsym(_glfw.egl.CreateContext, _glfw.egl.handle, "eglCreateContext");
    glfw_dlsym(_glfw.egl.DestroySurface, _glfw.egl.handle, "eglDestroySurface");
    glfw_dlsym(_glfw.egl.DestroyContext, _glfw.egl.handle, "eglDestroyContext");
    glfw_dlsym(_glfw.egl.CreateWindowSurface, _glfw.egl.handle, "eglCreateWindowSurface");
    glfw_dlsym(_glfw.egl.MakeCurrent, _glfw.egl.handle, "eglMakeCurrent");
    glfw_dlsym(_glfw.egl.SwapBuffers, _glfw.egl.handle, "eglSwapBuffers");
    glfw_dlsym(_glfw.egl.SwapInterval, _glfw.egl.handle, "eglSwapInterval");
    glfw_dlsym(_glfw.egl.QueryString, _glfw.egl.handle, "eglQueryString");
    glfw_dlsym(_glfw.egl.QuerySurface, _glfw.egl.handle, "eglQuerySurface");
    glfw_dlsym(_glfw.egl.GetProcAddress, _glfw.egl.handle, "eglGetProcAddress");

    if (!_glfw.egl.GetConfigAttrib ||
        !_glfw.egl.GetConfigs ||
        !_glfw.egl.ChooseConfig ||
        !_glfw.egl.GetDisplay ||
        !_glfw.egl.GetError ||
        !_glfw.egl.Initialize ||
        !_glfw.egl.Terminate ||
        !_glfw.egl.BindAPI ||
        !_glfw.egl.CreateContext ||
        !_glfw.egl.DestroySurface ||
        !_glfw.egl.DestroyContext ||
        !_glfw.egl.CreateWindowSurface ||
        !_glfw.egl.MakeCurrent ||
        !_glfw.egl.SwapBuffers ||
        !_glfw.egl.SwapInterval ||
        !_glfw.egl.QueryString ||
        !_glfw.egl.GetProcAddress)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "EGL: Failed to load required entry points");

        _glfwTerminateEGL();
        return false;
    }

    extensions = eglQueryString(EGL_NO_DISPLAY, EGL_EXTENSIONS);
    if (extensions && eglGetError() == EGL_SUCCESS)
        _glfw.egl.EXT_client_extensions = true;

    if (_glfw.egl.EXT_client_extensions)
    {
        _glfw.egl.EXT_platform_base =
            _glfwStringInExtensionString("EGL_EXT_platform_base", extensions);
        _glfw.egl.EXT_platform_x11 =
            _glfwStringInExtensionString("EGL_EXT_platform_x11", extensions);
        _glfw.egl.EXT_platform_wayland =
            _glfwStringInExtensionString("EGL_EXT_platform_wayland", extensions);
        _glfw.egl.ANGLE_platform_angle =
            _glfwStringInExtensionString("EGL_ANGLE_platform_angle", extensions);
        _glfw.egl.ANGLE_platform_angle_opengl =
            _glfwStringInExtensionString("EGL_ANGLE_platform_angle_opengl", extensions);
        _glfw.egl.ANGLE_platform_angle_d3d =
            _glfwStringInExtensionString("EGL_ANGLE_platform_angle_d3d", extensions);
        _glfw.egl.ANGLE_platform_angle_vulkan =
            _glfwStringInExtensionString("EGL_ANGLE_platform_angle_vulkan", extensions);
        _glfw.egl.ANGLE_platform_angle_metal =
            _glfwStringInExtensionString("EGL_ANGLE_platform_angle_metal", extensions);
    }

    if (_glfw.egl.EXT_platform_base)
    {
        _glfw.egl.GetPlatformDisplayEXT = (PFNEGLGETPLATFORMDISPLAYEXTPROC)
            eglGetProcAddress("eglGetPlatformDisplayEXT");
        _glfw.egl.CreatePlatformWindowSurfaceEXT = (PFNEGLCREATEPLATFORMWINDOWSURFACEEXTPROC)
            eglGetProcAddress("eglCreatePlatformWindowSurfaceEXT");
    }

    _glfw.egl.platform = _glfwPlatformGetEGLPlatform(&attribs);
    if (_glfw.egl.platform)
    {
        _glfw.egl.display =
            eglGetPlatformDisplayEXT(_glfw.egl.platform,
                                     _glfwPlatformGetEGLNativeDisplay(),
                                     attribs);
    }
    else
        _glfw.egl.display = eglGetDisplay(_glfwPlatformGetEGLNativeDisplay());

    free(attribs);

    if (_glfw.egl.display == EGL_NO_DISPLAY)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE,
                        "EGL: Failed to get EGL display: %s",
                        getEGLErrorString(eglGetError()));

        _glfwTerminateEGL();
        return false;
    }

    if (!eglInitialize(_glfw.egl.display, &_glfw.egl.major, &_glfw.egl.minor))
    {
        _glfwInputError(GLFW_API_UNAVAILABLE,
                        "EGL: Failed to initialize EGL: %s",
                        getEGLErrorString(eglGetError()));

        _glfwTerminateEGL();
        return false;
    }

    _glfw.egl.KHR_create_context =
        extensionSupportedEGL("EGL_KHR_create_context");
    _glfw.egl.KHR_create_context_no_error =
        extensionSupportedEGL("EGL_KHR_create_context_no_error");
    _glfw.egl.KHR_gl_colorspace =
        extensionSupportedEGL("EGL_KHR_gl_colorspace");
    _glfw.egl.KHR_get_all_proc_addresses =
        extensionSupportedEGL("EGL_KHR_get_all_proc_addresses");
    _glfw.egl.KHR_context_flush_control =
        extensionSupportedEGL("EGL_KHR_context_flush_control");
    _glfw.egl.EXT_present_opaque =
        extensionSupportedEGL("EGL_EXT_present_opaque");

    return true;
}

// Terminate EGL
//
void _glfwTerminateEGL(void)
{
    if (_glfw.egl.display)
    {
        eglTerminate(_glfw.egl.display);
        _glfw.egl.display = EGL_NO_DISPLAY;
    }

    if (_glfw.egl.handle)
    {
        _glfw_dlclose(_glfw.egl.handle);
        _glfw.egl.handle = NULL;
    }
}

#define setAttrib(a, v) \
{ \
    assert(((size_t) index + 1) < sizeof(attribs) / sizeof(attribs[0])); \
    attribs[index++] = a; \
    attribs[index++] = v; \
}

// Create the OpenGL or OpenGL ES context
//
bool _glfwCreateContextEGL(_GLFWwindow* window,
                               const _GLFWctxconfig* ctxconfig,
                               const _GLFWfbconfig* fbconfig)
{
    EGLint attribs[40];
    EGLConfig config;
    EGLContext share = NULL;
    EGLNativeWindowType native;
    int index = 0;

    if (!_glfw.egl.display)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE, "EGL: API not available");
        return false;
    }

    if (ctxconfig->share)
        share = ctxconfig->share->context.egl.handle;

    if (!chooseEGLConfig(ctxconfig, fbconfig, &config))
    {
        _glfwInputError(GLFW_FORMAT_UNAVAILABLE,
                        "EGL: Failed to find a suitable EGLConfig");
        return false;
    }

    if (ctxconfig->client == GLFW_OPENGL_ES_API)
    {
        if (!eglBindAPI(EGL_OPENGL_ES_API))
        {
            _glfwInputError(GLFW_API_UNAVAILABLE,
                            "EGL: Failed to bind OpenGL ES: %s",
                            getEGLErrorString(eglGetError()));
            return false;
        }
    }
    else
    {
        if (!eglBindAPI(EGL_OPENGL_API))
        {
            _glfwInputError(GLFW_API_UNAVAILABLE,
                            "EGL: Failed to bind OpenGL: %s",
                            getEGLErrorString(eglGetError()));
            return false;
        }
    }

    if (_glfw.egl.KHR_create_context)
    {
        int mask = 0, flags = 0;

        if (ctxconfig->client == GLFW_OPENGL_API)
        {
            if (ctxconfig->forward)
                flags |= EGL_CONTEXT_OPENGL_FORWARD_COMPATIBLE_BIT_KHR;

            if (ctxconfig->profile == GLFW_OPENGL_CORE_PROFILE)
                mask |= EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT_KHR;
            else if (ctxconfig->profile == GLFW_OPENGL_COMPAT_PROFILE)
                mask |= EGL_CONTEXT_OPENGL_COMPATIBILITY_PROFILE_BIT_KHR;
        }

        if (ctxconfig->debug)
            flags |= EGL_CONTEXT_OPENGL_DEBUG_BIT_KHR;

        if (ctxconfig->robustness)
        {
            if (ctxconfig->robustness == GLFW_NO_RESET_NOTIFICATION)
            {
                setAttrib(EGL_CONTEXT_OPENGL_RESET_NOTIFICATION_STRATEGY_KHR,
                          EGL_NO_RESET_NOTIFICATION_KHR);
            }
            else if (ctxconfig->robustness == GLFW_LOSE_CONTEXT_ON_RESET)
            {
                setAttrib(EGL_CONTEXT_OPENGL_RESET_NOTIFICATION_STRATEGY_KHR,
                          EGL_LOSE_CONTEXT_ON_RESET_KHR);
            }

            flags |= EGL_CONTEXT_OPENGL_ROBUST_ACCESS_BIT_KHR;
        }

        if (ctxconfig->noerror)
        {
            if (_glfw.egl.KHR_create_context_no_error)
                setAttrib(EGL_CONTEXT_OPENGL_NO_ERROR_KHR, true);
        }

        if (ctxconfig->major != 1 || ctxconfig->minor != 0)
        {
            setAttrib(EGL_CONTEXT_MAJOR_VERSION_KHR, ctxconfig->major);
            setAttrib(EGL_CONTEXT_MINOR_VERSION_KHR, ctxconfig->minor);
        }

        if (mask)
            setAttrib(EGL_CONTEXT_OPENGL_PROFILE_MASK_KHR, mask);

        if (flags)
            setAttrib(EGL_CONTEXT_FLAGS_KHR, flags);
    }
    else
    {
        if (ctxconfig->client == GLFW_OPENGL_ES_API)
            setAttrib(EGL_CONTEXT_CLIENT_VERSION, ctxconfig->major);
    }

    if (_glfw.egl.KHR_context_flush_control)
    {
        if (ctxconfig->release == GLFW_RELEASE_BEHAVIOR_NONE)
        {
            setAttrib(EGL_CONTEXT_RELEASE_BEHAVIOR_KHR,
                      EGL_CONTEXT_RELEASE_BEHAVIOR_NONE_KHR);
        }
        else if (ctxconfig->release == GLFW_RELEASE_BEHAVIOR_FLUSH)
        {
            setAttrib(EGL_CONTEXT_RELEASE_BEHAVIOR_KHR,
                      EGL_CONTEXT_RELEASE_BEHAVIOR_FLUSH_KHR);
        }
    }

    setAttrib(EGL_NONE, EGL_NONE);

    window->context.egl.handle = eglCreateContext(_glfw.egl.display,
                                                  config, share, attribs);

    if (window->context.egl.handle == EGL_NO_CONTEXT)
    {
        _glfwInputError(GLFW_VERSION_UNAVAILABLE,
                        "EGL: Failed to create context: %s",
                        getEGLErrorString(eglGetError()));
        return false;
    }

    // Set up attributes for surface creation
    index = 0;

    if (fbconfig->sRGB)
    {
        if (_glfw.egl.KHR_gl_colorspace)
            setAttrib(EGL_GL_COLORSPACE_KHR, EGL_GL_COLORSPACE_SRGB_KHR);
    }
    // Disabled because it prevents transparency from working on NVIDIA drivers under Wayland
    // https://github.com/kovidgoyal/kitty/issues/5479
    // We anyway dont use the alpha bits for anything.
    /* if (_glfw.egl.EXT_present_opaque) */
    /*     setAttrib(EGL_PRESENT_OPAQUE_EXT, !fbconfig->transparent); */

    setAttrib(EGL_NONE, EGL_NONE);

    native = _glfwPlatformGetEGLNativeWindow(window);
    // HACK: ANGLE does not implement eglCreatePlatformWindowSurfaceEXT
    //       despite reporting EGL_EXT_platform_base
    if (_glfw.egl.platform && _glfw.egl.platform != EGL_PLATFORM_ANGLE_ANGLE)
    {
        window->context.egl.surface =
            eglCreatePlatformWindowSurfaceEXT(_glfw.egl.display, config, native, attribs);
    }
    else
    {
        window->context.egl.surface =
            eglCreateWindowSurface(_glfw.egl.display, config, native, attribs);
    }

    if (window->context.egl.surface == EGL_NO_SURFACE)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "EGL: Failed to create window surface: %s",
                        getEGLErrorString(eglGetError()));
        return false;
    }

    window->context.egl.config = config;

    EGLint a = EGL_MIN_SWAP_INTERVAL;
    if (!eglGetConfigAttrib(_glfw.egl.display, config, a, &a)) {
        _glfwInputError(GLFW_VERSION_UNAVAILABLE, "EGL: could not check for non-blocking buffer swap with error: %s", getEGLErrorString(eglGetError()));
    } else {
        if (a > 0) {
            _glfwInputError(GLFW_VERSION_UNAVAILABLE, "EGL: non-blocking swap buffers not available, minimum swap interval is: %d", a);
        }
    }

    // Load the appropriate client library
    if (!_glfw.egl.KHR_get_all_proc_addresses)
    {
        int i;
        const char** sonames;
        const char* es1sonames[] =
        {
#if defined(_GLFW_GLESV1_LIBRARY)
            _GLFW_GLESV1_LIBRARY,
#elif defined(_GLFW_WIN32)
            "GLESv1_CM.dll",
            "libGLES_CM.dll",
#elif defined(_GLFW_COCOA)
            "libGLESv1_CM.dylib",
#else
            "libGLESv1_CM.so.1",
            "libGLES_CM.so.1",
#endif
            NULL
        };
        const char* es2sonames[] =
        {
#if defined(_GLFW_GLESV2_LIBRARY)
            _GLFW_GLESV2_LIBRARY,
#elif defined(_GLFW_WIN32)
            "GLESv2.dll",
            "libGLESv2.dll",
#elif defined(_GLFW_COCOA)
            "libGLESv2.dylib",
#elif defined(__CYGWIN__)
            "libGLESv2-2.so",
#else
            "libGLESv2.so.2",
#endif
            NULL
        };
        const char* glsonames[] =
        {
#if defined(_GLFW_OPENGL_LIBRARY)
            _GLFW_OPENGL_LIBRARY,
#elif defined(_GLFW_WIN32)
#elif defined(_GLFW_COCOA)
#else
            "libGL.so.1",
#endif
            NULL
        };

        if (ctxconfig->client == GLFW_OPENGL_ES_API)
        {
            if (ctxconfig->major == 1)
                sonames = es1sonames;
            else
                sonames = es2sonames;
        }
        else
            sonames = glsonames;

        for (i = 0;  sonames[i];  i++)
        {
            // HACK: Match presence of lib prefix to increase chance of finding
            //       a matching pair in the jungle that is Win32 EGL/GLES
            if (_glfw.egl.prefix != (strncmp(sonames[i], "lib", 3) == 0))
                continue;

            window->context.egl.client = _glfw_dlopen(sonames[i]);
            if (window->context.egl.client)
                break;
        }

        if (!window->context.egl.client)
        {
            _glfwInputError(GLFW_API_UNAVAILABLE,
                            "EGL: Failed to load client library");
            return false;
        }
    }

    window->context.makeCurrent = makeContextCurrentEGL;
    window->context.swapBuffers = swapBuffersEGL;
    window->context.swapInterval = swapIntervalEGL;
    window->context.extensionSupported = extensionSupportedEGL;
    window->context.getProcAddress = getProcAddressEGL;
    window->context.destroy = destroyContextEGL;

    return true;
}

#undef setAttrib

// Returns the Visual and depth of the chosen EGLConfig
//
#if defined(_GLFW_X11)
bool _glfwChooseVisualEGL(const _GLFWwndconfig* wndconfig UNUSED,
                              const _GLFWctxconfig* ctxconfig,
                              const _GLFWfbconfig* fbconfig,
                              Visual** visual, int* depth)
{
    XVisualInfo* result;
    XVisualInfo desired;
    EGLConfig native;
    EGLint visualID = 0, count = 0;
    const long vimask = VisualScreenMask | VisualIDMask;

    if (!chooseEGLConfig(ctxconfig, fbconfig, &native))
    {
        _glfwInputError(GLFW_FORMAT_UNAVAILABLE,
                        "EGL: Failed to find a suitable EGLConfig");
        return false;
    }

    eglGetConfigAttrib(_glfw.egl.display, native,
                       EGL_NATIVE_VISUAL_ID, &visualID);

    desired.screen = _glfw.x11.screen;
    desired.visualid = visualID;

    result = XGetVisualInfo(_glfw.x11.display, vimask, &desired, &count);
    if (!result)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "EGL: Failed to retrieve Visual for EGLConfig");
        return false;
    }

    *visual = result->visual;
    *depth = result->depth;

    XFree(result);
    return true;
}
#endif // _GLFW_X11


//////////////////////////////////////////////////////////////////////////
//////                        GLFW native API                       //////
//////////////////////////////////////////////////////////////////////////

GLFWAPI EGLDisplay glfwGetEGLDisplay(void)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(EGL_NO_DISPLAY);
    return _glfw.egl.display;
}

GLFWAPI EGLContext glfwGetEGLContext(GLFWwindow* handle)
{
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(EGL_NO_CONTEXT);

    if (window->context.client == GLFW_NO_API)
    {
        _glfwInputError(GLFW_NO_WINDOW_CONTEXT, NULL);
        return EGL_NO_CONTEXT;
    }

    return window->context.egl.handle;
}

GLFWAPI EGLSurface glfwGetEGLSurface(GLFWwindow* handle)
{
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(EGL_NO_SURFACE);

    if (window->context.client == GLFW_NO_API)
    {
        _glfwInputError(GLFW_NO_WINDOW_CONTEXT, NULL);
        return EGL_NO_SURFACE;
    }

    return window->context.egl.surface;
}
