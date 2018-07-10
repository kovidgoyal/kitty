//========================================================================
// GLFW 3.3 X11 - www.glfw.org
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

#define _GNU_SOURCE
#include "internal.h"
#include "backend_utils.h"

#include <X11/Xresource.h>

#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <stdio.h>
#include <locale.h>
#include <fcntl.h>


// Check whether the specified atom is supported
//
static Atom getSupportedAtom(Atom* supportedAtoms,
                             unsigned long atomCount,
                             const char* atomName)
{
    unsigned long i;
    const Atom atom = XInternAtom(_glfw.x11.display, atomName, False);

    for (i = 0;  i < atomCount;  i++)
    {
        if (supportedAtoms[i] == atom)
            return atom;
    }

    return None;
}

// Check whether the running window manager is EWMH-compliant
//
static void detectEWMH(void)
{
    Window* windowFromRoot = NULL;
    Window* windowFromChild = NULL;

    // First we need a couple of atoms
    const Atom supportingWmCheck =
        XInternAtom(_glfw.x11.display, "_NET_SUPPORTING_WM_CHECK", False);
    const Atom wmSupported =
        XInternAtom(_glfw.x11.display, "_NET_SUPPORTED", False);

    // Then we look for the _NET_SUPPORTING_WM_CHECK property of the root window
    if (!_glfwGetWindowPropertyX11(_glfw.x11.root,
                                   supportingWmCheck,
                                   XA_WINDOW,
                                   (unsigned char**) &windowFromRoot))
    {
        return;
    }

    _glfwGrabErrorHandlerX11();

    // It should be the ID of a child window (of the root)
    // Then we look for the same property on the child window
    if (!_glfwGetWindowPropertyX11(*windowFromRoot,
                                   supportingWmCheck,
                                   XA_WINDOW,
                                   (unsigned char**) &windowFromChild))
    {
        XFree(windowFromRoot);
        return;
    }

    _glfwReleaseErrorHandlerX11();

    // It should be the ID of that same child window
    if (*windowFromRoot != *windowFromChild)
    {
        XFree(windowFromRoot);
        XFree(windowFromChild);
        return;
    }

    XFree(windowFromRoot);
    XFree(windowFromChild);

    // We are now fairly sure that an EWMH-compliant window manager is running

    Atom* supportedAtoms;
    unsigned long atomCount;

    // Now we need to check the _NET_SUPPORTED property of the root window
    // It should be a list of supported WM protocol and state atoms
    atomCount = _glfwGetWindowPropertyX11(_glfw.x11.root,
                                          wmSupported,
                                          XA_ATOM,
                                          (unsigned char**) &supportedAtoms);

    // See which of the atoms we support that are supported by the WM
    _glfw.x11.NET_WM_STATE =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_WM_STATE");
    _glfw.x11.NET_WM_STATE_ABOVE =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_WM_STATE_ABOVE");
    _glfw.x11.NET_WM_STATE_FULLSCREEN =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_WM_STATE_FULLSCREEN");
    _glfw.x11.NET_WM_STATE_MAXIMIZED_VERT =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_WM_STATE_MAXIMIZED_VERT");
    _glfw.x11.NET_WM_STATE_MAXIMIZED_HORZ =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_WM_STATE_MAXIMIZED_HORZ");
    _glfw.x11.NET_WM_STATE_DEMANDS_ATTENTION =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_WM_STATE_DEMANDS_ATTENTION");
    _glfw.x11.NET_WM_FULLSCREEN_MONITORS =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_WM_FULLSCREEN_MONITORS");
    _glfw.x11.NET_WM_WINDOW_TYPE =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_WM_WINDOW_TYPE");
    _glfw.x11.NET_WM_WINDOW_TYPE_NORMAL =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_WM_WINDOW_TYPE_NORMAL");
    _glfw.x11.NET_ACTIVE_WINDOW =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_ACTIVE_WINDOW");
    _glfw.x11.NET_FRAME_EXTENTS =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_FRAME_EXTENTS");
    _glfw.x11.NET_REQUEST_FRAME_EXTENTS =
        getSupportedAtom(supportedAtoms, atomCount, "_NET_REQUEST_FRAME_EXTENTS");

    if (supportedAtoms)
        XFree(supportedAtoms);
}

// Look for and initialize supported X11 extensions
//
static GLFWbool initExtensions(void)
{
    _glfw.x11.vidmode.handle = _glfw_dlopen("libXxf86vm.so.1");
    if (_glfw.x11.vidmode.handle)
    {
        _glfw.x11.vidmode.QueryExtension = (PFN_XF86VidModeQueryExtension)
            _glfw_dlsym(_glfw.x11.vidmode.handle, "XF86VidModeQueryExtension");
        _glfw.x11.vidmode.GetGammaRamp = (PFN_XF86VidModeGetGammaRamp)
            _glfw_dlsym(_glfw.x11.vidmode.handle, "XF86VidModeGetGammaRamp");
        _glfw.x11.vidmode.SetGammaRamp = (PFN_XF86VidModeSetGammaRamp)
            _glfw_dlsym(_glfw.x11.vidmode.handle, "XF86VidModeSetGammaRamp");
        _glfw.x11.vidmode.GetGammaRampSize = (PFN_XF86VidModeGetGammaRampSize)
            _glfw_dlsym(_glfw.x11.vidmode.handle, "XF86VidModeGetGammaRampSize");

        _glfw.x11.vidmode.available =
            XF86VidModeQueryExtension(_glfw.x11.display,
                                      &_glfw.x11.vidmode.eventBase,
                                      &_glfw.x11.vidmode.errorBase);
    }

#if defined(__CYGWIN__)
    _glfw.x11.xi.handle = _glfw_dlopen("libXi-6.so");
#else
    _glfw.x11.xi.handle = _glfw_dlopen("libXi.so.6");
#endif
    if (_glfw.x11.xi.handle)
    {
        _glfw.x11.xi.QueryVersion = (PFN_XIQueryVersion)
            _glfw_dlsym(_glfw.x11.xi.handle, "XIQueryVersion");
        _glfw.x11.xi.SelectEvents = (PFN_XISelectEvents)
            _glfw_dlsym(_glfw.x11.xi.handle, "XISelectEvents");

        if (XQueryExtension(_glfw.x11.display,
                            "XInputExtension",
                            &_glfw.x11.xi.majorOpcode,
                            &_glfw.x11.xi.eventBase,
                            &_glfw.x11.xi.errorBase))
        {
            _glfw.x11.xi.major = 2;
            _glfw.x11.xi.minor = 0;

            if (XIQueryVersion(_glfw.x11.display,
                               &_glfw.x11.xi.major,
                               &_glfw.x11.xi.minor) == Success)
            {
                _glfw.x11.xi.available = GLFW_TRUE;
            }
        }
    }

#if defined(__CYGWIN__)
    _glfw.x11.randr.handle = _glfw_dlopen("libXrandr-2.so");
#else
    _glfw.x11.randr.handle = _glfw_dlopen("libXrandr.so.2");
#endif
    if (_glfw.x11.randr.handle)
    {
        _glfw.x11.randr.AllocGamma = (PFN_XRRAllocGamma)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRAllocGamma");
        _glfw.x11.randr.FreeGamma = (PFN_XRRFreeGamma)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRFreeGamma");
        _glfw.x11.randr.FreeCrtcInfo = (PFN_XRRFreeCrtcInfo)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRFreeCrtcInfo");
        _glfw.x11.randr.FreeGamma = (PFN_XRRFreeGamma)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRFreeGamma");
        _glfw.x11.randr.FreeOutputInfo = (PFN_XRRFreeOutputInfo)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRFreeOutputInfo");
        _glfw.x11.randr.FreeScreenResources = (PFN_XRRFreeScreenResources)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRFreeScreenResources");
        _glfw.x11.randr.GetCrtcGamma = (PFN_XRRGetCrtcGamma)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRGetCrtcGamma");
        _glfw.x11.randr.GetCrtcGammaSize = (PFN_XRRGetCrtcGammaSize)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRGetCrtcGammaSize");
        _glfw.x11.randr.GetCrtcInfo = (PFN_XRRGetCrtcInfo)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRGetCrtcInfo");
        _glfw.x11.randr.GetOutputInfo = (PFN_XRRGetOutputInfo)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRGetOutputInfo");
        _glfw.x11.randr.GetOutputPrimary = (PFN_XRRGetOutputPrimary)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRGetOutputPrimary");
        _glfw.x11.randr.GetScreenResourcesCurrent = (PFN_XRRGetScreenResourcesCurrent)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRGetScreenResourcesCurrent");
        _glfw.x11.randr.QueryExtension = (PFN_XRRQueryExtension)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRQueryExtension");
        _glfw.x11.randr.QueryVersion = (PFN_XRRQueryVersion)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRQueryVersion");
        _glfw.x11.randr.SelectInput = (PFN_XRRSelectInput)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRSelectInput");
        _glfw.x11.randr.SetCrtcConfig = (PFN_XRRSetCrtcConfig)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRSetCrtcConfig");
        _glfw.x11.randr.SetCrtcGamma = (PFN_XRRSetCrtcGamma)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRSetCrtcGamma");
        _glfw.x11.randr.UpdateConfiguration = (PFN_XRRUpdateConfiguration)
            _glfw_dlsym(_glfw.x11.randr.handle, "XRRUpdateConfiguration");

        if (XRRQueryExtension(_glfw.x11.display,
                              &_glfw.x11.randr.eventBase,
                              &_glfw.x11.randr.errorBase))
        {
            if (XRRQueryVersion(_glfw.x11.display,
                                &_glfw.x11.randr.major,
                                &_glfw.x11.randr.minor))
            {
                // The GLFW RandR path requires at least version 1.3
                if (_glfw.x11.randr.major > 1 || _glfw.x11.randr.minor >= 3)
                    _glfw.x11.randr.available = GLFW_TRUE;
            }
            else
            {
                _glfwInputError(GLFW_PLATFORM_ERROR,
                                "X11: Failed to query RandR version");
            }
        }
    }

    if (_glfw.x11.randr.available)
    {
        XRRScreenResources* sr = XRRGetScreenResourcesCurrent(_glfw.x11.display,
                                                              _glfw.x11.root);

        if (!sr->ncrtc || !XRRGetCrtcGammaSize(_glfw.x11.display, sr->crtcs[0]))
        {
            // This is likely an older Nvidia driver with broken gamma support
            // Flag it as useless and fall back to xf86vm gamma, if available
            _glfw.x11.randr.gammaBroken = GLFW_TRUE;
        }

        if (!sr->ncrtc)
        {
            // A system without CRTCs is likely a system with broken RandR
            // Disable the RandR monitor path and fall back to core functions
            _glfw.x11.randr.monitorBroken = GLFW_TRUE;
        }

        XRRFreeScreenResources(sr);
    }

    if (_glfw.x11.randr.available && !_glfw.x11.randr.monitorBroken)
    {
        XRRSelectInput(_glfw.x11.display, _glfw.x11.root,
                       RROutputChangeNotifyMask);
    }

#if defined(__CYGWIN__)
    _glfw.x11.xcursor.handle = _glfw_dlopen("libXcursor-1.so");
#else
    _glfw.x11.xcursor.handle = _glfw_dlopen("libXcursor.so.1");
#endif
    if (_glfw.x11.xcursor.handle)
    {
        _glfw.x11.xcursor.ImageCreate = (PFN_XcursorImageCreate)
            _glfw_dlsym(_glfw.x11.xcursor.handle, "XcursorImageCreate");
        _glfw.x11.xcursor.ImageDestroy = (PFN_XcursorImageDestroy)
            _glfw_dlsym(_glfw.x11.xcursor.handle, "XcursorImageDestroy");
        _glfw.x11.xcursor.ImageLoadCursor = (PFN_XcursorImageLoadCursor)
            _glfw_dlsym(_glfw.x11.xcursor.handle, "XcursorImageLoadCursor");
    }

#if defined(__CYGWIN__)
    _glfw.x11.xinerama.handle = _glfw_dlopen("libXinerama-1.so");
#else
    _glfw.x11.xinerama.handle = _glfw_dlopen("libXinerama.so.1");
#endif
    if (_glfw.x11.xinerama.handle)
    {
        _glfw.x11.xinerama.IsActive = (PFN_XineramaIsActive)
            _glfw_dlsym(_glfw.x11.xinerama.handle, "XineramaIsActive");
        _glfw.x11.xinerama.QueryExtension = (PFN_XineramaQueryExtension)
            _glfw_dlsym(_glfw.x11.xinerama.handle, "XineramaQueryExtension");
        _glfw.x11.xinerama.QueryScreens = (PFN_XineramaQueryScreens)
            _glfw_dlsym(_glfw.x11.xinerama.handle, "XineramaQueryScreens");

        if (XineramaQueryExtension(_glfw.x11.display,
                                   &_glfw.x11.xinerama.major,
                                   &_glfw.x11.xinerama.minor))
        {
            if (XineramaIsActive(_glfw.x11.display))
                _glfw.x11.xinerama.available = GLFW_TRUE;
        }
    }

#if defined(__CYGWIN__)
    _glfw.x11.xrender.handle = _glfw_dlopen("libXrender-1.so");
#else
    _glfw.x11.xrender.handle = _glfw_dlopen("libXrender.so.1");
#endif
    if (_glfw.x11.xrender.handle)
    {
        _glfw.x11.xrender.QueryExtension = (PFN_XRenderQueryExtension)
            _glfw_dlsym(_glfw.x11.xrender.handle, "XRenderQueryExtension");
        _glfw.x11.xrender.QueryVersion = (PFN_XRenderQueryVersion)
            _glfw_dlsym(_glfw.x11.xrender.handle, "XRenderQueryVersion");
        _glfw.x11.xrender.FindVisualFormat = (PFN_XRenderFindVisualFormat)
            _glfw_dlsym(_glfw.x11.xrender.handle, "XRenderFindVisualFormat");

        if (XRenderQueryExtension(_glfw.x11.display,
                                  &_glfw.x11.xrender.errorBase,
                                  &_glfw.x11.xrender.eventBase))
        {
            if (XRenderQueryVersion(_glfw.x11.display,
                                    &_glfw.x11.xrender.major,
                                    &_glfw.x11.xrender.minor))
            {
                _glfw.x11.xrender.available = GLFW_TRUE;
            }
        }
    }

    _glfw.x11.xkb.major = 1;
    _glfw.x11.xkb.minor = 0;
    _glfw.x11.xkb.available = XkbQueryExtension(_glfw.x11.display,
            &_glfw.x11.xkb.majorOpcode,
            &_glfw.x11.xkb.eventBase,
            &_glfw.x11.xkb.errorBase,
            &_glfw.x11.xkb.major,
            &_glfw.x11.xkb.minor);

    if (!_glfw.x11.xkb.available)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Failed to load Xkb extension");
        return GLFW_FALSE;
    }
    Bool supported;
    if (XkbSetDetectableAutoRepeat(_glfw.x11.display, True, &supported))
    {
        if (supported)
            _glfw.x11.xkb.detectable = GLFW_TRUE;
    }

    if (!glfw_xkb_set_x11_events_mask()) return GLFW_FALSE;
    if (!glfw_xkb_create_context(&_glfw.x11.xkb)) return GLFW_FALSE;
    if (!glfw_xkb_update_x11_keyboard_id(&_glfw.x11.xkb)) return GLFW_FALSE;
    if (!glfw_xkb_compile_keymap(&_glfw.x11.xkb, NULL)) return GLFW_FALSE;

    // Detect whether an EWMH-conformant window manager is running
    detectEWMH();

    // String format atoms
    _glfw.x11.NULL_ = XInternAtom(_glfw.x11.display, "NULL", False);
    _glfw.x11.UTF8_STRING = XInternAtom(_glfw.x11.display, "UTF8_STRING", False);
    _glfw.x11.ATOM_PAIR = XInternAtom(_glfw.x11.display, "ATOM_PAIR", False);

    // Custom selection property atom
    _glfw.x11.GLFW_SELECTION =
        XInternAtom(_glfw.x11.display, "GLFW_SELECTION", False);

    // ICCCM standard clipboard atoms
    _glfw.x11.TARGETS = XInternAtom(_glfw.x11.display, "TARGETS", False);
    _glfw.x11.MULTIPLE = XInternAtom(_glfw.x11.display, "MULTIPLE", False);
    _glfw.x11.PRIMARY = XInternAtom(_glfw.x11.display, "PRIMARY", False);
    _glfw.x11.INCR = XInternAtom(_glfw.x11.display, "INCR", False);
    _glfw.x11.CLIPBOARD = XInternAtom(_glfw.x11.display, "CLIPBOARD", False);

    // Clipboard manager atoms
    _glfw.x11.CLIPBOARD_MANAGER =
        XInternAtom(_glfw.x11.display, "CLIPBOARD_MANAGER", False);
    _glfw.x11.SAVE_TARGETS =
        XInternAtom(_glfw.x11.display, "SAVE_TARGETS", False);

    // Xdnd (drag and drop) atoms
    _glfw.x11.XdndAware = XInternAtom(_glfw.x11.display, "XdndAware", False);
    _glfw.x11.XdndEnter = XInternAtom(_glfw.x11.display, "XdndEnter", False);
    _glfw.x11.XdndPosition = XInternAtom(_glfw.x11.display, "XdndPosition", False);
    _glfw.x11.XdndStatus = XInternAtom(_glfw.x11.display, "XdndStatus", False);
    _glfw.x11.XdndActionCopy = XInternAtom(_glfw.x11.display, "XdndActionCopy", False);
    _glfw.x11.XdndDrop = XInternAtom(_glfw.x11.display, "XdndDrop", False);
    _glfw.x11.XdndFinished = XInternAtom(_glfw.x11.display, "XdndFinished", False);
    _glfw.x11.XdndSelection = XInternAtom(_glfw.x11.display, "XdndSelection", False);
    _glfw.x11.XdndTypeList = XInternAtom(_glfw.x11.display, "XdndTypeList", False);
    _glfw.x11.text_uri_list = XInternAtom(_glfw.x11.display, "text/uri-list", False);

    // ICCCM, EWMH and Motif window property atoms
    // These can be set safely even without WM support
    // The EWMH atoms that require WM support are handled in detectEWMH
    _glfw.x11.WM_PROTOCOLS =
        XInternAtom(_glfw.x11.display, "WM_PROTOCOLS", False);
    _glfw.x11.WM_STATE =
        XInternAtom(_glfw.x11.display, "WM_STATE", False);
    _glfw.x11.WM_DELETE_WINDOW =
        XInternAtom(_glfw.x11.display, "WM_DELETE_WINDOW", False);
    _glfw.x11.NET_WM_ICON =
        XInternAtom(_glfw.x11.display, "_NET_WM_ICON", False);
    _glfw.x11.NET_WM_PING =
        XInternAtom(_glfw.x11.display, "_NET_WM_PING", False);
    _glfw.x11.NET_WM_PID =
        XInternAtom(_glfw.x11.display, "_NET_WM_PID", False);
    _glfw.x11.NET_WM_NAME =
        XInternAtom(_glfw.x11.display, "_NET_WM_NAME", False);
    _glfw.x11.NET_WM_ICON_NAME =
        XInternAtom(_glfw.x11.display, "_NET_WM_ICON_NAME", False);
    _glfw.x11.NET_WM_BYPASS_COMPOSITOR =
        XInternAtom(_glfw.x11.display, "_NET_WM_BYPASS_COMPOSITOR", False);
    _glfw.x11.NET_WM_WINDOW_OPACITY =
        XInternAtom(_glfw.x11.display, "_NET_WM_WINDOW_OPACITY", False);
    _glfw.x11.MOTIF_WM_HINTS =
        XInternAtom(_glfw.x11.display, "_MOTIF_WM_HINTS", False);

    // The compositing manager selection name contains the screen number
    {
        char name[32];
        snprintf(name, sizeof(name), "_NET_WM_CM_S%u", _glfw.x11.screen);
        _glfw.x11.NET_WM_CM_Sx = XInternAtom(_glfw.x11.display, name, False);
    }

    return GLFW_TRUE;
}

// Retrieve system content scale via folklore heuristics
//
void _glfwGetSystemContentScaleX11(float* xscale, float* yscale, GLFWbool bypass_cache)
{
    // NOTE: Default to the display-wide DPI as we don't currently have a policy
    //       for which monitor a window is considered to be on
    float xdpi = DisplayWidth(_glfw.x11.display, _glfw.x11.screen) *
        25.4f / DisplayWidthMM(_glfw.x11.display, _glfw.x11.screen);
    float ydpi = DisplayHeight(_glfw.x11.display, _glfw.x11.screen) *
        25.4f / DisplayHeightMM(_glfw.x11.display, _glfw.x11.screen);

    // NOTE: Basing the scale on Xft.dpi where available should provide the most
    //       consistent user experience (matches Qt, Gtk, etc), although not
    //       always the most accurate one
    char* rms = NULL;
    char* owned_rms = NULL;

    if (bypass_cache)
    {
        _glfwGetWindowPropertyX11(_glfw.x11.root,
                                  _glfw.x11.RESOURCE_MANAGER,
                                  XA_STRING,
                                  (unsigned char**) &owned_rms);
        rms = owned_rms;
    } else {
        rms = XResourceManagerString(_glfw.x11.display);
    }

    if (rms)
    {
        XrmDatabase db = XrmGetStringDatabase(rms);
        if (db)
        {
            XrmValue value;
            char* type = NULL;

            if (XrmGetResource(db, "Xft.dpi", "Xft.Dpi", &type, &value))
            {
                if (type && strcmp(type, "String") == 0)
                    xdpi = ydpi = atof(value.addr);
            }

            XrmDestroyDatabase(db);
        }
        XFree(owned_rms);
    }

    *xscale = xdpi / 96.f;
    *yscale = ydpi / 96.f;
}

// Create a blank cursor for hidden and disabled cursor modes
//
static Cursor createHiddenCursor(void)
{
    unsigned char pixels[16 * 16 * 4] = { 0 };
    GLFWimage image = { 16, 16, pixels };
    return _glfwCreateCursorX11(&image, 0, 0);
}

// Create a helper window for IPC
//
static Window createHelperWindow(void)
{
    XSetWindowAttributes wa;
    wa.event_mask = PropertyChangeMask;

    return XCreateWindow(_glfw.x11.display, _glfw.x11.root,
                         0, 0, 1, 1, 0, 0,
                         InputOnly,
                         DefaultVisual(_glfw.x11.display, _glfw.x11.screen),
                         CWEventMask, &wa);
}

// X error handler
//
static int errorHandler(Display *display, XErrorEvent* event)
{
    _glfw.x11.errorCode = event->error_code;
    return 0;
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

// Sets the X error handler callback
//
void _glfwGrabErrorHandlerX11(void)
{
    _glfw.x11.errorCode = Success;
    XSetErrorHandler(errorHandler);
}

// Clears the X error handler callback
//
void _glfwReleaseErrorHandlerX11(void)
{
    // Synchronize to make sure all commands are processed
    XSync(_glfw.x11.display, False);
    XSetErrorHandler(NULL);
}

// Reports the specified error, appending information about the last X error
//
void _glfwInputErrorX11(int error, const char* message)
{
    char buffer[_GLFW_MESSAGE_SIZE];
    XGetErrorText(_glfw.x11.display, _glfw.x11.errorCode,
                  buffer, sizeof(buffer));

    _glfwInputError(error, "%s: %s", message, buffer);
}

// Creates a native cursor object from the specified image and hotspot
//
Cursor _glfwCreateCursorX11(const GLFWimage* image, int xhot, int yhot)
{
    int i;
    Cursor cursor;

    if (!_glfw.x11.xcursor.handle)
        return None;

    XcursorImage* native = XcursorImageCreate(image->width, image->height);
    if (native == NULL)
        return None;

    native->xhot = xhot;
    native->yhot = yhot;

    unsigned char* source = (unsigned char*) image->pixels;
    XcursorPixel* target = native->pixels;

    for (i = 0;  i < image->width * image->height;  i++, target++, source += 4)
    {
        unsigned int alpha = source[3];

        *target = (alpha << 24) |
                  ((unsigned char) ((source[0] * alpha) / 255) << 16) |
                  ((unsigned char) ((source[1] * alpha) / 255) <<  8) |
                  ((unsigned char) ((source[2] * alpha) / 255) <<  0);
    }

    cursor = XcursorImageLoadCursor(_glfw.x11.display, native);
    XcursorImageDestroy(native);

    return cursor;
}

//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

int _glfwPlatformInit(void)
{
    XInitThreads();
    XrmInitialize();

    if (pipe2(_glfw.x11.eventLoopData.wakeupFds, O_CLOEXEC | O_NONBLOCK) != 0)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                "X11: failed to create self pipe");
        return GLFW_FALSE;
    }

    _glfw.x11.display = XOpenDisplay(NULL);
    if (!_glfw.x11.display)
    {
        const char* display = getenv("DISPLAY");
        if (display)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "X11: Failed to open display %s", display);
        }
        else
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "X11: The DISPLAY environment variable is missing");
        }

        return GLFW_FALSE;
    }

    initPollData(&_glfw.x11.eventLoopData, _glfw.x11.eventLoopData.wakeupFds[0], ConnectionNumber(_glfw.x11.display));
    glfw_dbus_init(&_glfw.x11.dbus, &_glfw.x11.eventLoopData);

    _glfw.x11.screen = DefaultScreen(_glfw.x11.display);
    _glfw.x11.root = RootWindow(_glfw.x11.display, _glfw.x11.screen);
    _glfw.x11.context = XUniqueContext();
    _glfw.x11.RESOURCE_MANAGER = XInternAtom(_glfw.x11.display, "RESOURCE_MANAGER", True);
    XSelectInput(_glfw.x11.display, _glfw.x11.root, PropertyChangeMask);

    _glfwGetSystemContentScaleX11(&_glfw.x11.contentScaleX, &_glfw.x11.contentScaleY, GLFW_FALSE);

    if (!initExtensions())
        return GLFW_FALSE;

    _glfw.x11.helperWindowHandle = createHelperWindow();
    _glfw.x11.hiddenCursorHandle = createHiddenCursor();

#if defined(__linux__)
    if (!_glfwInitJoysticksLinux())
        return GLFW_FALSE;
    if (_glfw.linjs.inotify > 0)
        addWatch(&_glfw.x11.eventLoopData, "joystick", _glfw.linjs.inotify, POLLIN, 1, NULL, NULL);
#endif

    _glfwInitTimerPOSIX();

    _glfwPollMonitorsX11();
    return GLFW_TRUE;
}

void _glfwPlatformTerminate(void)
{
    if (_glfw.x11.helperWindowHandle)
    {
        if (XGetSelectionOwner(_glfw.x11.display, _glfw.x11.CLIPBOARD) ==
            _glfw.x11.helperWindowHandle)
        {
            _glfwPushSelectionToManagerX11();
        }

        XDestroyWindow(_glfw.x11.display, _glfw.x11.helperWindowHandle);
        _glfw.x11.helperWindowHandle = None;
    }

    if (_glfw.x11.hiddenCursorHandle)
    {
        XFreeCursor(_glfw.x11.display, _glfw.x11.hiddenCursorHandle);
        _glfw.x11.hiddenCursorHandle = (Cursor) 0;
    }

    glfw_xkb_release(&_glfw.x11.xkb);
    glfw_dbus_terminate(&_glfw.x11.dbus);
    free(_glfw.x11.primarySelectionString);
    free(_glfw.x11.clipboardString);

    if (_glfw.x11.display)
    {
        XCloseDisplay(_glfw.x11.display);
        _glfw.x11.display = NULL;
        _glfw.x11.eventLoopData.fds[0].fd = -1;
    }

    if (_glfw.x11.xcursor.handle)
    {
        _glfw_dlclose(_glfw.x11.xcursor.handle);
        _glfw.x11.xcursor.handle = NULL;
    }

    if (_glfw.x11.randr.handle)
    {
        _glfw_dlclose(_glfw.x11.randr.handle);
        _glfw.x11.randr.handle = NULL;
    }

    if (_glfw.x11.xinerama.handle)
    {
        _glfw_dlclose(_glfw.x11.xinerama.handle);
        _glfw.x11.xinerama.handle = NULL;
    }

    if (_glfw.x11.xrender.handle)
    {
        _glfw_dlclose(_glfw.x11.xrender.handle);
        _glfw.x11.xrender.handle = NULL;
    }

    if (_glfw.x11.vidmode.handle)
    {
        _glfw_dlclose(_glfw.x11.vidmode.handle);
        _glfw.x11.vidmode.handle = NULL;
    }

    if (_glfw.x11.xi.handle)
    {
        _glfw_dlclose(_glfw.x11.xi.handle);
        _glfw.x11.xi.handle = NULL;
    }

    // NOTE: These need to be unloaded after XCloseDisplay, as they register
    //       cleanup callbacks that get called by that function
    _glfwTerminateEGL();
    _glfwTerminateGLX();

#if defined(__linux__)
    _glfwTerminateJoysticksLinux();
#endif
    closeFds(_glfw.x11.eventLoopData.wakeupFds, sizeof(_glfw.x11.eventLoopData.wakeupFds)/sizeof(_glfw.x11.eventLoopData.wakeupFds[0]));
}

const char* _glfwPlatformGetVersionString(void)
{
    return _GLFW_VERSION_NUMBER " X11 GLX EGL"
#if defined(_POSIX_TIMERS) && defined(_POSIX_MONOTONIC_CLOCK)
        " clock_gettime"
#else
        " gettimeofday"
#endif
#if defined(__linux__)
        " evdev"
#endif
#if defined(_GLFW_BUILD_DLL)
        " shared"
#endif
        ;
}
