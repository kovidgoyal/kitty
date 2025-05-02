//========================================================================
// GLFW 3.4 X11 - www.glfw.org
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

#define _GNU_SOURCE
#include "internal.h"
#include "backend_utils.h"
#include "linux_desktop_settings.h"

#include <X11/Xresource.h>

#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <stdio.h>
#include <locale.h>
#include <fcntl.h>
#include <unistd.h>


// Return the atom ID only if it is listed in the specified array
//
static Atom getAtomIfSupported(Atom* supportedAtoms,
                               unsigned long atomCount,
                               const Atom atom)
{
    for (unsigned long i = 0;  i < atomCount;  i++) {
        if (supportedAtoms[i] == atom) return atom;
    }
    return None;
}

// Check whether the running window manager is EWMH-compliant
//
static void detectEWMH(void)
{
    // First we read the _NET_SUPPORTING_WM_CHECK property on the root window

    Window* windowFromRoot = NULL;
    if (!_glfwGetWindowPropertyX11(_glfw.x11.root,
                                   _glfw.x11.NET_SUPPORTING_WM_CHECK,
                                   XA_WINDOW,
                                   (unsigned char**) &windowFromRoot))
    {
        return;
    }

    _glfwGrabErrorHandlerX11();

    // If it exists, it should be the XID of a top-level window
    // Then we look for the same property on that window

    Window* windowFromChild = NULL;
    if (!_glfwGetWindowPropertyX11(*windowFromRoot,
                                   _glfw.x11.NET_SUPPORTING_WM_CHECK,
                                   XA_WINDOW,
                                   (unsigned char**) &windowFromChild))
    {
        XFree(windowFromRoot);
        return;
    }

    _glfwReleaseErrorHandlerX11();

    // If the property exists, it should contain the XID of the window

    if (*windowFromRoot != *windowFromChild)
    {
        XFree(windowFromRoot);
        XFree(windowFromChild);
        return;
    }

    XFree(windowFromRoot);
    XFree(windowFromChild);

    // We are now fairly sure that an EWMH-compliant WM is currently running
    // We can now start querying the WM about what features it supports by
    // looking in the _NET_SUPPORTED property on the root window
    // It should contain a list of supported EWMH protocol and state atoms

    Atom* supportedAtoms = NULL;
    const unsigned long atomCount =
        _glfwGetWindowPropertyX11(_glfw.x11.root,
                                  _glfw.x11.NET_SUPPORTED,
                                  XA_ATOM,
                                  (unsigned char**) &supportedAtoms);
    if (!supportedAtoms)
        return;

    // See which of the atoms we support that are supported by the WM

#define ALL_ATOMS  \
    S(NET_WM_STATE) S(NET_WM_STATE_ABOVE) S(NET_WM_STATE_BELOW) S(NET_WM_STATE_FULLSCREEN) \
    S(NET_WM_STATE_MAXIMIZED_VERT) S(NET_WM_STATE_MAXIMIZED_HORZ) S(NET_WM_STATE_DEMANDS_ATTENTION) \
    S(NET_WM_STATE_SKIP_TASKBAR) S(NET_WM_STATE_SKIP_PAGER) S(NET_WM_STATE_STICKY) \
\
    S(NET_WM_FULLSCREEN_MONITORS) S(NET_WM_STRUT_PARTIAL) \
\
    S(NET_WM_WINDOW_TYPE) S(NET_WM_WINDOW_TYPE_NORMAL) S(NET_WM_WINDOW_TYPE_DOCK) S(NET_WM_WINDOW_TYPE_DESKTOP) \
    S(NET_WM_WINDOW_TYPE_UTILITY) S(NET_WM_WINDOW_TYPE_SPLASH) S(NET_WM_WINDOW_TYPE_DIALOG) S(NET_WM_WINDOW_TYPE_MENU) \
    S(NET_WM_WINDOW_TYPE_NOTIFICATION) \
\
    S(NET_WORKAREA) S(NET_CURRENT_DESKTOP) S(NET_ACTIVE_WINDOW) S(NET_FRAME_EXTENTS) S(NET_REQUEST_FRAME_EXTENTS) \
\
    S(NET_WM_ALLOWED_ACTIONS) S(NET_WM_ACTION_MOVE) S(NET_WM_ACTION_RESIZE) S(NET_WM_ACTION_MINIMIZE) \
    S(NET_WM_ACTION_SHADE) S(NET_WM_ACTION_STICK) S(NET_WM_ACTION_MAXIMIZE_HORZ) S(NET_WM_ACTION_MAXIMIZE_VERT) \
    S(NET_WM_ACTION_FULLSCREEN) S(NET_WM_ACTION_CHANGE_DESKTOP) S(NET_WM_ACTION_CLOSE) S(NET_WM_ACTION_ABOVE) \
    S(NET_WM_ACTION_BELOW) S(NET_WM_ACTION_ABOVE_BELOW)

    static const char* atom_names[40] = {
#define S(x) "_" #x,
        ALL_ATOMS
    };
#undef S
    Atom atoms[arraysz(atom_names)];
    XInternAtoms(_glfw.x11.display, (char**)atom_names, arraysz(atom_names), False, atoms);
    unsigned i = 0;
#define S(name) _glfw.x11.name = getAtomIfSupported(supportedAtoms, atomCount, atoms[i++]);
    ALL_ATOMS
#undef S
#undef ALL_ATOMS
    XFree(supportedAtoms);
}

// Look for and initialize supported X11 extensions
//
static bool initExtensions(void)
{
    _glfw.x11.vidmode.handle = _glfw_dlopen("libXxf86vm.so.1");
    if (_glfw.x11.vidmode.handle)
    {
        glfw_dlsym(_glfw.x11.vidmode.QueryExtension, _glfw.x11.vidmode.handle, "XF86VidModeQueryExtension");
        glfw_dlsym(_glfw.x11.vidmode.GetGammaRamp, _glfw.x11.vidmode.handle, "XF86VidModeGetGammaRamp");
        glfw_dlsym(_glfw.x11.vidmode.SetGammaRamp, _glfw.x11.vidmode.handle, "XF86VidModeSetGammaRamp");
        glfw_dlsym(_glfw.x11.vidmode.GetGammaRampSize, _glfw.x11.vidmode.handle, "XF86VidModeGetGammaRampSize");

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
        glfw_dlsym(_glfw.x11.xi.QueryVersion, _glfw.x11.xi.handle, "XIQueryVersion");
        glfw_dlsym(_glfw.x11.xi.SelectEvents, _glfw.x11.xi.handle, "XISelectEvents");

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
                _glfw.x11.xi.available = true;
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
        glfw_dlsym(_glfw.x11.randr.AllocGamma, _glfw.x11.randr.handle, "XRRAllocGamma");
        glfw_dlsym(_glfw.x11.randr.FreeGamma, _glfw.x11.randr.handle, "XRRFreeGamma");
        glfw_dlsym(_glfw.x11.randr.FreeCrtcInfo, _glfw.x11.randr.handle, "XRRFreeCrtcInfo");
        glfw_dlsym(_glfw.x11.randr.FreeGamma, _glfw.x11.randr.handle, "XRRFreeGamma");
        glfw_dlsym(_glfw.x11.randr.FreeOutputInfo, _glfw.x11.randr.handle, "XRRFreeOutputInfo");
        glfw_dlsym(_glfw.x11.randr.FreeScreenResources, _glfw.x11.randr.handle, "XRRFreeScreenResources");
        glfw_dlsym(_glfw.x11.randr.GetCrtcGamma, _glfw.x11.randr.handle, "XRRGetCrtcGamma");
        glfw_dlsym(_glfw.x11.randr.GetCrtcGammaSize, _glfw.x11.randr.handle, "XRRGetCrtcGammaSize");
        glfw_dlsym(_glfw.x11.randr.GetCrtcInfo, _glfw.x11.randr.handle, "XRRGetCrtcInfo");
        glfw_dlsym(_glfw.x11.randr.GetOutputInfo, _glfw.x11.randr.handle, "XRRGetOutputInfo");
        glfw_dlsym(_glfw.x11.randr.GetOutputPrimary, _glfw.x11.randr.handle, "XRRGetOutputPrimary");
        glfw_dlsym(_glfw.x11.randr.GetScreenResourcesCurrent, _glfw.x11.randr.handle, "XRRGetScreenResourcesCurrent");
        glfw_dlsym(_glfw.x11.randr.QueryExtension, _glfw.x11.randr.handle, "XRRQueryExtension");
        glfw_dlsym(_glfw.x11.randr.QueryVersion, _glfw.x11.randr.handle, "XRRQueryVersion");
        glfw_dlsym(_glfw.x11.randr.SelectInput, _glfw.x11.randr.handle, "XRRSelectInput");
        glfw_dlsym(_glfw.x11.randr.SetCrtcConfig, _glfw.x11.randr.handle, "XRRSetCrtcConfig");
        glfw_dlsym(_glfw.x11.randr.SetCrtcGamma, _glfw.x11.randr.handle, "XRRSetCrtcGamma");
        glfw_dlsym(_glfw.x11.randr.UpdateConfiguration, _glfw.x11.randr.handle, "XRRUpdateConfiguration");

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
                    _glfw.x11.randr.available = true;
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
            _glfw.x11.randr.gammaBroken = true;
        }

        if (!sr->ncrtc)
        {
            // A system without CRTCs is likely a system with broken RandR
            // Disable the RandR monitor path and fall back to core functions
            _glfw.x11.randr.monitorBroken = true;
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
        glfw_dlsym(_glfw.x11.xcursor.ImageCreate, _glfw.x11.xcursor.handle, "XcursorImageCreate");
        glfw_dlsym(_glfw.x11.xcursor.ImageDestroy, _glfw.x11.xcursor.handle, "XcursorImageDestroy");
        glfw_dlsym(_glfw.x11.xcursor.ImageLoadCursor, _glfw.x11.xcursor.handle, "XcursorImageLoadCursor");
    }

#if defined(__CYGWIN__)
    _glfw.x11.xinerama.handle = _glfw_dlopen("libXinerama-1.so");
#else
    _glfw.x11.xinerama.handle = _glfw_dlopen("libXinerama.so.1");
#endif
    if (_glfw.x11.xinerama.handle)
    {
        glfw_dlsym(_glfw.x11.xinerama.IsActive, _glfw.x11.xinerama.handle, "XineramaIsActive");
        glfw_dlsym(_glfw.x11.xinerama.QueryExtension, _glfw.x11.xinerama.handle, "XineramaQueryExtension");
        glfw_dlsym(_glfw.x11.xinerama.QueryScreens, _glfw.x11.xinerama.handle, "XineramaQueryScreens");

        if (XineramaQueryExtension(_glfw.x11.display,
                                   &_glfw.x11.xinerama.major,
                                   &_glfw.x11.xinerama.minor))
        {
            if (XineramaIsActive(_glfw.x11.display))
                _glfw.x11.xinerama.available = true;
        }
    }

#if defined(__CYGWIN__)
    _glfw.x11.xrender.handle = _glfw_dlopen("libXrender-1.so");
#else
    _glfw.x11.xrender.handle = _glfw_dlopen("libXrender.so.1");
#endif
    if (_glfw.x11.xrender.handle)
    {
        glfw_dlsym(_glfw.x11.xrender.QueryExtension, _glfw.x11.xrender.handle, "XRenderQueryExtension");
        glfw_dlsym(_glfw.x11.xrender.QueryVersion, _glfw.x11.xrender.handle, "XRenderQueryVersion");
        glfw_dlsym(_glfw.x11.xrender.FindVisualFormat, _glfw.x11.xrender.handle, "XRenderFindVisualFormat");

        if (XRenderQueryExtension(_glfw.x11.display,
                                  &_glfw.x11.xrender.errorBase,
                                  &_glfw.x11.xrender.eventBase))
        {
            if (XRenderQueryVersion(_glfw.x11.display,
                                    &_glfw.x11.xrender.major,
                                    &_glfw.x11.xrender.minor))
            {
                _glfw.x11.xrender.available = true;
            }
        }
    }

#if defined(__CYGWIN__)
    _glfw.x11.xshape.handle = _glfw_dlopen("libXext-6.so");
#else
    _glfw.x11.xshape.handle = _glfw_dlopen("libXext.so.6");
#endif
    if (_glfw.x11.xshape.handle)
    {
        glfw_dlsym(_glfw.x11.xshape.QueryExtension, _glfw.x11.xshape.handle, "XShapeQueryExtension");
        glfw_dlsym(_glfw.x11.xshape.ShapeCombineRegion, _glfw.x11.xshape.handle, "XShapeCombineRegion");
        glfw_dlsym(_glfw.x11.xshape.QueryVersion, _glfw.x11.xshape.handle, "XShapeQueryVersion");

        if (XShapeQueryExtension(_glfw.x11.display,
            &_glfw.x11.xshape.errorBase,
            &_glfw.x11.xshape.eventBase))
        {
            if (XShapeQueryVersion(_glfw.x11.display,
                &_glfw.x11.xshape.major,
                &_glfw.x11.xshape.minor))
            {
                _glfw.x11.xshape.available = true;
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
        return false;
    }
    Bool supported;
    if (XkbSetDetectableAutoRepeat(_glfw.x11.display, True, &supported))
    {
        if (supported)
            _glfw.x11.xkb.detectable = true;
    }

    if (!glfw_xkb_set_x11_events_mask()) return false;
    if (!glfw_xkb_create_context(&_glfw.x11.xkb)) return false;
    if (!glfw_xkb_update_x11_keyboard_id(&_glfw.x11.xkb)) return false;
    if (!glfw_xkb_compile_keymap(&_glfw.x11.xkb, NULL)) return false;

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

    // ICCCM, EWMH and Motif window property atoms
    // These can be set safely even without WM support
    // The EWMH atoms that require WM support are handled in detectEWMH
    _glfw.x11.WM_PROTOCOLS =
        XInternAtom(_glfw.x11.display, "WM_PROTOCOLS", False);
    _glfw.x11.WM_STATE =
        XInternAtom(_glfw.x11.display, "WM_STATE", False);
    _glfw.x11.WM_DELETE_WINDOW =
        XInternAtom(_glfw.x11.display, "WM_DELETE_WINDOW", False);
    _glfw.x11.NET_SUPPORTED =
        XInternAtom(_glfw.x11.display, "_NET_SUPPORTED", False);
    _glfw.x11.NET_SUPPORTING_WM_CHECK =
        XInternAtom(_glfw.x11.display, "_NET_SUPPORTING_WM_CHECK", False);
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

    // Detect whether an EWMH-conformant window manager is running
    detectEWMH();

    return true;
}

// Retrieve system content scale via folklore heuristics
//
void _glfwGetSystemContentScaleX11(float* xscale, float* yscale, bool bypass_cache)
{
    // Start by assuming the default X11 DPI
    // NOTE: Some desktop environments (KDE) may remove the Xft.dpi field when it
    //       would be set to 96, so assume that is the case if we cannot find it
    float xdpi = 96.f, ydpi = 96.f;

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
                    xdpi = ydpi = (float)atof(value.addr);
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
    if (_glfw.x11.display != display)
        return 0;

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

GLFWAPI GLFWColorScheme glfwGetCurrentSystemColorTheme(bool query_if_unintialized) {
    return glfw_current_system_color_theme(query_if_unintialized);
}

void _glfwPlatformInputColorScheme(GLFWColorScheme appearance UNUSED) { }

int _glfwPlatformInit(bool *supports_window_occlusion)
{
    *supports_window_occlusion = false;
    XInitThreads();
    XrmInitialize();

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

        return false;
    }

    if (!initPollData(&_glfw.x11.eventLoopData, ConnectionNumber(_glfw.x11.display))) {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "X11: Failed to initialize event loop data");
    }
    glfw_dbus_init(&_glfw.x11.dbus, &_glfw.x11.eventLoopData);
    glfw_initialize_desktop_settings();  // needed for color scheme change notification

    _glfw.x11.screen = DefaultScreen(_glfw.x11.display);
    _glfw.x11.root = RootWindow(_glfw.x11.display, _glfw.x11.screen);
    _glfw.x11.context = XUniqueContext();
    _glfw.x11.RESOURCE_MANAGER = XInternAtom(_glfw.x11.display, "RESOURCE_MANAGER", True);
    _glfw.x11._KDE_NET_WM_BLUR_BEHIND_REGION = None;
    XSelectInput(_glfw.x11.display, _glfw.x11.root, PropertyChangeMask);

    _glfwGetSystemContentScaleX11(&_glfw.x11.contentScaleX, &_glfw.x11.contentScaleY, false);

    if (!initExtensions())
        return false;

    _glfw.x11.helperWindowHandle = createHelperWindow();
    _glfw.x11.hiddenCursorHandle = createHiddenCursor();

    _glfwPollMonitorsX11();
    return true;
}

void _glfwPlatformTerminate(void)
{
    removeAllTimers(&_glfw.x11.eventLoopData);
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
    if (_glfw.x11.mime_atoms.array) {
        for (size_t i = 0; i < _glfw.x11.mime_atoms.sz; i++) {
            free((void*)_glfw.x11.mime_atoms.array[i].mime);
        }
        free(_glfw.x11.mime_atoms.array);
    }
    if (_glfw.x11.clipboard_atoms.array) { free(_glfw.x11.clipboard_atoms.array); }
    if (_glfw.x11.primary_atoms.array) { free(_glfw.x11.primary_atoms.array); }

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

    finalizePollData(&_glfw.x11.eventLoopData);
}

const char* _glfwPlatformGetVersionString(void)
{
    return _GLFW_VERSION_NUMBER " X11 GLX EGL OSMesa"
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

#include "main_loop.h"
