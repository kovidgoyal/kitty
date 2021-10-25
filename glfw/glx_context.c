//========================================================================
// GLFW 3.4 GLX - www.glfw.org
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
// It is fine to use C99 in this file because it will not be built with VS
//========================================================================

#include "internal.h"

#include <string.h>
#include <stdlib.h>
#include <assert.h>

#ifndef GLXBadProfileARB
 #define GLXBadProfileARB 13
#endif


// Returns the specified attribute of the specified GLXFBConfig
//
static int getGLXFBConfigAttrib(GLXFBConfig fbconfig, int attrib)
{
    int value;
    glXGetFBConfigAttrib(_glfw.x11.display, fbconfig, attrib, &value);
    return value;
}

static GLXFBConfig*
choose_fb_config(const _GLFWfbconfig* desired, bool trust_window_bit, int *nelements, bool use_best_color_depth) {
    int attrib_list[64];
    int pos = 0;
#define ATTR(x, y) { attrib_list[pos++] = x; attrib_list[pos++] = y; }

    ATTR(GLX_DOUBLEBUFFER, desired->doublebuffer ? True : False);
    if (desired->stereo > 0) ATTR(GLX_STEREO, desired->stereo ? True : False);
    if (desired->auxBuffers > 0) ATTR(GLX_AUX_BUFFERS, desired->auxBuffers);
    if (_glfw.glx.ARB_multisample && desired->samples > 0) ATTR(GLX_SAMPLES, desired->samples);
    if (desired->depthBits != GLFW_DONT_CARE) ATTR(GLX_DEPTH_SIZE, desired->depthBits);
    if (desired->stencilBits != GLFW_DONT_CARE) ATTR(GLX_STENCIL_SIZE, desired->stencilBits);
    if (use_best_color_depth) {
        // we just ask for the highest available R+G+B+A color depth. This hopefully
        // works with 10bit (r=10, g=10, b=19, a=2) visuals
        ATTR(GLX_RED_SIZE, 1); ATTR(GLX_GREEN_SIZE, 1); ATTR(GLX_BLUE_SIZE, 1); ATTR(GLX_ALPHA_SIZE, 1);
    } else {
        if (desired->redBits != GLFW_DONT_CARE) ATTR(GLX_RED_SIZE, desired->redBits);
        if (desired->greenBits != GLFW_DONT_CARE) ATTR(GLX_GREEN_SIZE, desired->greenBits);
        if (desired->blueBits != GLFW_DONT_CARE) ATTR(GLX_BLUE_SIZE, desired->blueBits);
        if (desired->alphaBits != GLFW_DONT_CARE) ATTR(GLX_ALPHA_SIZE, desired->alphaBits);
    }
    if (desired->accumRedBits != GLFW_DONT_CARE) ATTR(GLX_ACCUM_RED_SIZE, desired->accumRedBits);
    if (desired->accumGreenBits != GLFW_DONT_CARE) ATTR(GLX_ACCUM_GREEN_SIZE, desired->accumGreenBits);
    if (desired->accumBlueBits != GLFW_DONT_CARE) ATTR(GLX_ACCUM_BLUE_SIZE, desired->accumBlueBits);
    if (desired->accumAlphaBits != GLFW_DONT_CARE) ATTR(GLX_ACCUM_ALPHA_SIZE, desired->accumAlphaBits);
    if (!trust_window_bit) ATTR(GLX_DRAWABLE_TYPE, 0);
    ATTR(None, None);
    return glXChooseFBConfig(_glfw.x11.display, _glfw.x11.screen, attrib_list, nelements);
#undef ATTR
}


// Return the GLXFBConfig most closely matching the specified hints
//
static bool chooseGLXFBConfig(const _GLFWfbconfig* desired,
                                  GLXFBConfig* result)
{
    GLXFBConfig* nativeConfigs;
    int i, nativeCount, ans_idx = 0;
    const char* vendor;
    bool trustWindowBit = true;
    static _GLFWfbconfig prev_desired  = {0};
    static GLXFBConfig prev_result = 0;
    if (prev_result != 0 && memcmp(&prev_desired, desired, sizeof(_GLFWfbconfig)) == 0) {
        *result = prev_result;
        return true;
    }
    prev_desired = *desired;

    // HACK: This is a (hopefully temporary) workaround for Chromium
    //       (VirtualBox GL) not setting the window bit on any GLXFBConfigs
    vendor = glXGetClientString(_glfw.x11.display, GLX_VENDOR);
    if (vendor && strcmp(vendor, "Chromium") == 0)
        trustWindowBit = false;
    nativeConfigs = choose_fb_config(desired, trustWindowBit, &nativeCount, false);
    if (!nativeConfigs || !nativeCount)
    {
        nativeConfigs = choose_fb_config(desired, trustWindowBit, &nativeCount, true);

        if (!nativeConfigs || !nativeCount) {
            _glfwInputError(GLFW_API_UNAVAILABLE, "GLX: No GLXFBConfigs returned");
            return false;
        }
    }
    for (i = 0;  i < nativeCount;  i++)
    {
        const GLXFBConfig n = nativeConfigs[i];
        bool transparency_matches = true, srgb_matches = true;
        if (desired->transparent) {
            transparency_matches = false;
            XVisualInfo* vi = glXGetVisualFromFBConfig(_glfw.x11.display, n);
            if (vi && _glfwIsVisualTransparentX11(vi->visual)) transparency_matches = true;
        }

        if (desired->sRGB && (_glfw.glx.ARB_framebuffer_sRGB || _glfw.glx.EXT_framebuffer_sRGB)) {
            srgb_matches = getGLXFBConfigAttrib(n, GLX_FRAMEBUFFER_SRGB_CAPABLE_ARB) ? true : false;
        }

        if (transparency_matches && srgb_matches) {
            ans_idx = i; break;
        }

    }

    *result = nativeConfigs[ans_idx];
    prev_result = nativeConfigs[ans_idx];

    XFree(nativeConfigs);

    return true;
}

// Create the OpenGL context using legacy API
//
static GLXContext createLegacyContextGLX(_GLFWwindow* window UNUSED,
                                         GLXFBConfig fbconfig,
                                         GLXContext share)
{
    return glXCreateNewContext(_glfw.x11.display,
                               fbconfig,
                               GLX_RGBA_TYPE,
                               share,
                               True);
}

static void makeContextCurrentGLX(_GLFWwindow* window)
{
    if (window)
    {
        if (!glXMakeCurrent(_glfw.x11.display,
                            window->context.glx.window,
                            window->context.glx.handle))
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "GLX: Failed to make context current");
            return;
        }
    }
    else
    {
        if (!glXMakeCurrent(_glfw.x11.display, None, NULL))
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "GLX: Failed to clear current context");
            return;
        }
    }

    _glfwPlatformSetTls(&_glfw.contextSlot, window);
}

static void swapBuffersGLX(_GLFWwindow* window)
{
    glXSwapBuffers(_glfw.x11.display, window->context.glx.window);
}

static void swapIntervalGLX(int interval)
{
    _GLFWwindow* window = _glfwPlatformGetTls(&_glfw.contextSlot);

    if (_glfw.glx.EXT_swap_control)
    {
        _glfw.glx.SwapIntervalEXT(_glfw.x11.display,
                                  window->context.glx.window,
                                  interval);
    }
    else if (_glfw.glx.MESA_swap_control)
        _glfw.glx.SwapIntervalMESA(interval);
    else if (_glfw.glx.SGI_swap_control)
    {
        if (interval > 0)
            _glfw.glx.SwapIntervalSGI(interval);
    }
}

static int extensionSupportedGLX(const char* extension)
{
    const char* extensions =
        glXQueryExtensionsString(_glfw.x11.display, _glfw.x11.screen);
    if (extensions)
    {
        if (_glfwStringInExtensionString(extension, extensions))
            return true;
    }

    return false;
}

static GLFWglproc getProcAddressGLX(const char* procname)
{
    if (_glfw.glx.GetProcAddress)
        return _glfw.glx.GetProcAddress((const GLubyte*) procname);
    else if (_glfw.glx.GetProcAddressARB)
        return _glfw.glx.GetProcAddressARB((const GLubyte*) procname);
    else {
        GLFWglproc ans = NULL;
        glfw_dlsym(ans, _glfw.glx.handle, procname);
        return ans;
    }
}

static void destroyContextGLX(_GLFWwindow* window)
{
    if (window->context.glx.window)
    {
        glXDestroyWindow(_glfw.x11.display, window->context.glx.window);
        window->context.glx.window = None;
    }

    if (window->context.glx.handle)
    {
        glXDestroyContext(_glfw.x11.display, window->context.glx.handle);
        window->context.glx.handle = NULL;
    }
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

// Initialize GLX
//
bool _glfwInitGLX(void)
{
    int i;
    const char* sonames[] =
    {
#if defined(_GLFW_GLX_LIBRARY)
        _GLFW_GLX_LIBRARY,
#elif defined(__CYGWIN__)
        "libGL-1.so",
#else
        "libGL.so.1",
        "libGL.so",
#endif
        NULL
    };

    if (_glfw.glx.handle)
        return true;

    for (i = 0;  sonames[i];  i++)
    {
        _glfw.glx.handle = _glfw_dlopen(sonames[i]);
        if (_glfw.glx.handle)
            break;
    }

    if (!_glfw.glx.handle)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE, "GLX: Failed to load GLX");
        return false;
    }

    glfw_dlsym(_glfw.glx.GetFBConfigs, _glfw.glx.handle, "glXGetFBConfigs");
    glfw_dlsym(_glfw.glx.GetFBConfigAttrib, _glfw.glx.handle, "glXGetFBConfigAttrib");
    glfw_dlsym(_glfw.glx.ChooseFBConfig, _glfw.glx.handle, "glXChooseFBConfig");
    glfw_dlsym(_glfw.glx.GetClientString, _glfw.glx.handle, "glXGetClientString");
    glfw_dlsym(_glfw.glx.QueryExtension, _glfw.glx.handle, "glXQueryExtension");
    glfw_dlsym(_glfw.glx.QueryVersion, _glfw.glx.handle, "glXQueryVersion");
    glfw_dlsym(_glfw.glx.DestroyContext, _glfw.glx.handle, "glXDestroyContext");
    glfw_dlsym(_glfw.glx.MakeCurrent, _glfw.glx.handle, "glXMakeCurrent");
    glfw_dlsym(_glfw.glx.SwapBuffers, _glfw.glx.handle, "glXSwapBuffers");
    glfw_dlsym(_glfw.glx.QueryExtensionsString, _glfw.glx.handle, "glXQueryExtensionsString");
    glfw_dlsym(_glfw.glx.CreateNewContext, _glfw.glx.handle, "glXCreateNewContext");
    glfw_dlsym(_glfw.glx.CreateWindow, _glfw.glx.handle, "glXCreateWindow");
    glfw_dlsym(_glfw.glx.DestroyWindow, _glfw.glx.handle, "glXDestroyWindow");
    glfw_dlsym(_glfw.glx.GetProcAddress, _glfw.glx.handle, "glXGetProcAddress");
    glfw_dlsym(_glfw.glx.GetProcAddressARB, _glfw.glx.handle, "glXGetProcAddressARB");
    glfw_dlsym(_glfw.glx.GetVisualFromFBConfig, _glfw.glx.handle, "glXGetVisualFromFBConfig");

    if (!_glfw.glx.GetFBConfigs ||
        !_glfw.glx.GetFBConfigAttrib ||
        !_glfw.glx.GetClientString ||
        !_glfw.glx.QueryExtension ||
        !_glfw.glx.QueryVersion ||
        !_glfw.glx.DestroyContext ||
        !_glfw.glx.MakeCurrent ||
        !_glfw.glx.SwapBuffers ||
        !_glfw.glx.QueryExtensionsString ||
        !_glfw.glx.CreateNewContext ||
        !_glfw.glx.CreateWindow ||
        !_glfw.glx.DestroyWindow ||
        !_glfw.glx.GetProcAddress ||
        !_glfw.glx.GetProcAddressARB ||
        !_glfw.glx.GetVisualFromFBConfig)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "GLX: Failed to load required entry points");
        return false;
    }

    if (!glXQueryExtension(_glfw.x11.display,
                           &_glfw.glx.errorBase,
                           &_glfw.glx.eventBase))
    {
        _glfwInputError(GLFW_API_UNAVAILABLE, "GLX: GLX extension not found");
        return false;
    }

    if (!glXQueryVersion(_glfw.x11.display, &_glfw.glx.major, &_glfw.glx.minor))
    {
        _glfwInputError(GLFW_API_UNAVAILABLE,
                        "GLX: Failed to query GLX version");
        return false;
    }

    if (_glfw.glx.major == 1 && _glfw.glx.minor < 3)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE,
                        "GLX: GLX version 1.3 is required");
        return false;
    }

    if (extensionSupportedGLX("GLX_EXT_swap_control"))
    {
        _glfw.glx.SwapIntervalEXT = (PFNGLXSWAPINTERVALEXTPROC)
            getProcAddressGLX("glXSwapIntervalEXT");

        if (_glfw.glx.SwapIntervalEXT)
            _glfw.glx.EXT_swap_control = true;
    }

    if (extensionSupportedGLX("GLX_SGI_swap_control"))
    {
        _glfw.glx.SwapIntervalSGI = (PFNGLXSWAPINTERVALSGIPROC)
            getProcAddressGLX("glXSwapIntervalSGI");

        if (_glfw.glx.SwapIntervalSGI)
            _glfw.glx.SGI_swap_control = true;
    }

    if (extensionSupportedGLX("GLX_MESA_swap_control"))
    {
        _glfw.glx.SwapIntervalMESA = (PFNGLXSWAPINTERVALMESAPROC)
            getProcAddressGLX("glXSwapIntervalMESA");

        if (_glfw.glx.SwapIntervalMESA)
            _glfw.glx.MESA_swap_control = true;
    }

    if (extensionSupportedGLX("GLX_ARB_multisample"))
        _glfw.glx.ARB_multisample = true;

    if (extensionSupportedGLX("GLX_ARB_framebuffer_sRGB"))
        _glfw.glx.ARB_framebuffer_sRGB = true;

    if (extensionSupportedGLX("GLX_EXT_framebuffer_sRGB"))
        _glfw.glx.EXT_framebuffer_sRGB = true;

    if (extensionSupportedGLX("GLX_ARB_create_context"))
    {
        _glfw.glx.CreateContextAttribsARB = (PFNGLXCREATECONTEXTATTRIBSARBPROC)
            getProcAddressGLX("glXCreateContextAttribsARB");

        if (_glfw.glx.CreateContextAttribsARB)
            _glfw.glx.ARB_create_context = true;
    }

    if (extensionSupportedGLX("GLX_ARB_create_context_robustness"))
        _glfw.glx.ARB_create_context_robustness = true;

    if (extensionSupportedGLX("GLX_ARB_create_context_profile"))
        _glfw.glx.ARB_create_context_profile = true;

    if (extensionSupportedGLX("GLX_EXT_create_context_es2_profile"))
        _glfw.glx.EXT_create_context_es2_profile = true;

    if (extensionSupportedGLX("GLX_ARB_create_context_no_error"))
        _glfw.glx.ARB_create_context_no_error = true;

    if (extensionSupportedGLX("GLX_ARB_context_flush_control"))
        _glfw.glx.ARB_context_flush_control = true;

    return true;
}

// Terminate GLX
//
void _glfwTerminateGLX(void)
{
    // NOTE: This function must not call any X11 functions, as it is called
    //       after XCloseDisplay (see _glfwPlatformTerminate for details)

    if (_glfw.glx.handle)
    {
        _glfw_dlclose(_glfw.glx.handle);
        _glfw.glx.handle = NULL;
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
bool _glfwCreateContextGLX(_GLFWwindow* window,
                               const _GLFWctxconfig* ctxconfig,
                               const _GLFWfbconfig* fbconfig)
{
    int attribs[40];
    GLXFBConfig native = NULL;
    GLXContext share = NULL;

    if (ctxconfig->share)
        share = ctxconfig->share->context.glx.handle;

    if (!chooseGLXFBConfig(fbconfig, &native))
    {
        _glfwInputError(GLFW_FORMAT_UNAVAILABLE,
                        "GLX: Failed to find a suitable GLXFBConfig");
        return false;
    }

    if (ctxconfig->client == GLFW_OPENGL_ES_API)
    {
        if (!_glfw.glx.ARB_create_context ||
            !_glfw.glx.ARB_create_context_profile ||
            !_glfw.glx.EXT_create_context_es2_profile)
        {
            _glfwInputError(GLFW_API_UNAVAILABLE,
                            "GLX: OpenGL ES requested but GLX_EXT_create_context_es2_profile is unavailable");
            return false;
        }
    }

    if (ctxconfig->forward)
    {
        if (!_glfw.glx.ARB_create_context)
        {
            _glfwInputError(GLFW_VERSION_UNAVAILABLE,
                            "GLX: Forward compatibility requested but GLX_ARB_create_context_profile is unavailable");
            return false;
        }
    }

    if (ctxconfig->profile)
    {
        if (!_glfw.glx.ARB_create_context ||
            !_glfw.glx.ARB_create_context_profile)
        {
            _glfwInputError(GLFW_VERSION_UNAVAILABLE,
                            "GLX: An OpenGL profile requested but GLX_ARB_create_context_profile is unavailable");
            return false;
        }
    }

    _glfwGrabErrorHandlerX11();

    if (_glfw.glx.ARB_create_context)
    {
        int index = 0, mask = 0, flags = 0;

        if (ctxconfig->client == GLFW_OPENGL_API)
        {
            if (ctxconfig->forward)
                flags |= GLX_CONTEXT_FORWARD_COMPATIBLE_BIT_ARB;

            if (ctxconfig->profile == GLFW_OPENGL_CORE_PROFILE)
                mask |= GLX_CONTEXT_CORE_PROFILE_BIT_ARB;
            else if (ctxconfig->profile == GLFW_OPENGL_COMPAT_PROFILE)
                mask |= GLX_CONTEXT_COMPATIBILITY_PROFILE_BIT_ARB;
        }
        else
            mask |= GLX_CONTEXT_ES2_PROFILE_BIT_EXT;

        if (ctxconfig->debug)
            flags |= GLX_CONTEXT_DEBUG_BIT_ARB;

        if (ctxconfig->robustness)
        {
            if (_glfw.glx.ARB_create_context_robustness)
            {
                if (ctxconfig->robustness == GLFW_NO_RESET_NOTIFICATION)
                {
                    setAttrib(GLX_CONTEXT_RESET_NOTIFICATION_STRATEGY_ARB,
                              GLX_NO_RESET_NOTIFICATION_ARB);
                }
                else if (ctxconfig->robustness == GLFW_LOSE_CONTEXT_ON_RESET)
                {
                    setAttrib(GLX_CONTEXT_RESET_NOTIFICATION_STRATEGY_ARB,
                              GLX_LOSE_CONTEXT_ON_RESET_ARB);
                }

                flags |= GLX_CONTEXT_ROBUST_ACCESS_BIT_ARB;
            }
        }

        if (ctxconfig->release)
        {
            if (_glfw.glx.ARB_context_flush_control)
            {
                if (ctxconfig->release == GLFW_RELEASE_BEHAVIOR_NONE)
                {
                    setAttrib(GLX_CONTEXT_RELEASE_BEHAVIOR_ARB,
                              GLX_CONTEXT_RELEASE_BEHAVIOR_NONE_ARB);
                }
                else if (ctxconfig->release == GLFW_RELEASE_BEHAVIOR_FLUSH)
                {
                    setAttrib(GLX_CONTEXT_RELEASE_BEHAVIOR_ARB,
                              GLX_CONTEXT_RELEASE_BEHAVIOR_FLUSH_ARB);
                }
            }
        }

        if (ctxconfig->noerror)
        {
            if (_glfw.glx.ARB_create_context_no_error)
                setAttrib(GLX_CONTEXT_OPENGL_NO_ERROR_ARB, true);
        }

        // NOTE: Only request an explicitly versioned context when necessary, as
        //       explicitly requesting version 1.0 does not always return the
        //       highest version supported by the driver
        if (ctxconfig->major != 1 || ctxconfig->minor != 0)
        {
            setAttrib(GLX_CONTEXT_MAJOR_VERSION_ARB, ctxconfig->major);
            setAttrib(GLX_CONTEXT_MINOR_VERSION_ARB, ctxconfig->minor);
        }

        if (mask)
            setAttrib(GLX_CONTEXT_PROFILE_MASK_ARB, mask);

        if (flags)
            setAttrib(GLX_CONTEXT_FLAGS_ARB, flags);

        setAttrib(None, None);

        window->context.glx.handle =
            _glfw.glx.CreateContextAttribsARB(_glfw.x11.display,
                                              native,
                                              share,
                                              True,
                                              attribs);

        // HACK: This is a fallback for broken versions of the Mesa
        //       implementation of GLX_ARB_create_context_profile that fail
        //       default 1.0 context creation with a GLXBadProfileARB error in
        //       violation of the extension spec
        if (!window->context.glx.handle)
        {
            if (_glfw.x11.errorCode == _glfw.glx.errorBase + GLXBadProfileARB &&
                ctxconfig->client == GLFW_OPENGL_API &&
                ctxconfig->profile == GLFW_OPENGL_ANY_PROFILE &&
                ctxconfig->forward == false)
            {
                window->context.glx.handle =
                    createLegacyContextGLX(window, native, share);
            }
        }
    }
    else
    {
        window->context.glx.handle =
            createLegacyContextGLX(window, native, share);
    }

    _glfwReleaseErrorHandlerX11();

    if (!window->context.glx.handle)
    {
        _glfwInputErrorX11(GLFW_VERSION_UNAVAILABLE, "GLX: Failed to create context");
        return false;
    }

    window->context.glx.window =
        glXCreateWindow(_glfw.x11.display, native, window->x11.handle, NULL);
    if (!window->context.glx.window)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR, "GLX: Failed to create window");
        return false;
    }

    window->context.makeCurrent = makeContextCurrentGLX;
    window->context.swapBuffers = swapBuffersGLX;
    window->context.swapInterval = swapIntervalGLX;
    window->context.extensionSupported = extensionSupportedGLX;
    window->context.getProcAddress = getProcAddressGLX;
    window->context.destroy = destroyContextGLX;

    return true;
}

#undef setAttrib

// Returns the Visual and depth of the chosen GLXFBConfig
//
bool _glfwChooseVisualGLX(const _GLFWwndconfig* wndconfig UNUSED,
                              const _GLFWctxconfig* ctxconfig UNUSED,
                              const _GLFWfbconfig* fbconfig,
                              Visual** visual, int* depth)
{
    GLXFBConfig native;
    XVisualInfo* result;

    if (!chooseGLXFBConfig(fbconfig, &native))
    {
        _glfwInputError(GLFW_FORMAT_UNAVAILABLE,
                        "GLX: Failed to find a suitable GLXFBConfig");
        return false;
    }

    result = glXGetVisualFromFBConfig(_glfw.x11.display, native);
    if (!result)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "GLX: Failed to retrieve Visual for GLXFBConfig");
        return false;
    }

    *visual = result->visual;
    *depth  = result->depth;

    XFree(result);
    return true;
}


//////////////////////////////////////////////////////////////////////////
//////                        GLFW native API                       //////
//////////////////////////////////////////////////////////////////////////

GLFWAPI GLXContext glfwGetGLXContext(GLFWwindow* handle)
{
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);

    if (window->context.client == GLFW_NO_API)
    {
        _glfwInputError(GLFW_NO_WINDOW_CONTEXT, NULL);
        return NULL;
    }

    return window->context.glx.handle;
}

GLFWAPI GLXWindow glfwGetGLXWindow(GLFWwindow* handle)
{
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(None);

    if (window->context.client == GLFW_NO_API)
    {
        _glfwInputError(GLFW_NO_WINDOW_CONTEXT, NULL);
        return None;
    }

    return window->context.glx.window;
}
