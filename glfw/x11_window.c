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
#include "linux_notify.h"
#include "../kitty/monotonic.h"

#include <X11/cursorfont.h>
#include <X11/Xmd.h>

#include <string.h>
#include <stdio.h>
#include <stdlib.h>
#include <limits.h>
#include <errno.h>

// Action for EWMH client messages
#define _NET_WM_STATE_REMOVE        0
#define _NET_WM_STATE_ADD           1
#define _NET_WM_STATE_TOGGLE        2

// Additional mouse button names for XButtonEvent
#define Button6            6
#define Button7            7

// Motif WM hints flags
#define MWM_HINTS_DECORATIONS   2
#define MWM_DECOR_ALL           1

#define _GLFW_XDND_VERSION 5


// Wait for data to arrive using poll
// This avoids blocking other threads via the per-display Xlib lock that also
// covers GLX functions
//
static unsigned _glfwDispatchX11Events(void);

static void
handleEvents(monotonic_t timeout) {
    EVDBG("starting handleEvents(%.2f)", monotonic_t_to_s_double(timeout));
    int display_read_ok = pollForEvents(&_glfw.x11.eventLoopData, timeout, NULL);
    EVDBG("display_read_ok: %d", display_read_ok);
    if (display_read_ok) {
        unsigned dispatched = _glfwDispatchX11Events();
        (void)dispatched;
        EVDBG("dispatched %u X11 events", dispatched);
    }
    glfw_ibus_dispatch(&_glfw.x11.xkb.ibus);
    glfw_dbus_session_bus_dispatch();
    EVDBG("other dispatch done");
    if (_glfw.x11.eventLoopData.wakeup_fd_ready) check_for_wakeup_events(&_glfw.x11.eventLoopData);
}

static bool
waitForX11Event(monotonic_t timeout) {
    // returns true if there is X11 data waiting to be read, does not run watches and timers
    monotonic_t end_time = glfwGetTime() + timeout;
    while(true) {
        if (timeout >= 0) {
            const int result = pollWithTimeout(_glfw.x11.eventLoopData.fds, 1, timeout);
            if (result > 0) return true;
            timeout = end_time - glfwGetTime();
            if (timeout <= 0) return false;
            if (result < 0 && (errno == EINTR || errno == EAGAIN)) continue;
            return false;
        } else {
            const int result = poll(_glfw.x11.eventLoopData.fds, 1, -1);
            if (result > 0) return true;
            if (result < 0 && (errno == EINTR || errno == EAGAIN)) continue;
            return false;
        }
    }
}

// Waits until a VisibilityNotify event arrives for the specified window or the
// timeout period elapses (ICCCM section 4.2.2)
//
static bool waitForVisibilityNotify(_GLFWwindow* window)
{
    XEvent dummy;

    while (!XCheckTypedWindowEvent(_glfw.x11.display,
                                   window->x11.handle,
                                   VisibilityNotify,
                                   &dummy))
    {
        if (!waitForX11Event(ms_to_monotonic_t(100ll)))
            return false;
    }

    return true;
}

// Returns whether the window is iconified
//
static int getWindowState(_GLFWwindow* window)
{
    int result = WithdrawnState;
    struct {
        CARD32 state;
        Window icon;
    } *state = NULL;

    if (_glfwGetWindowPropertyX11(window->x11.handle,
                                  _glfw.x11.WM_STATE,
                                  _glfw.x11.WM_STATE,
                                  (unsigned char**) &state) >= 2)
    {
        result = state->state;
    }

    if (state)
        XFree(state);

    return result;
}

// Returns whether the event is a selection event
//
static Bool isSelectionEvent(Display* display UNUSED, XEvent* event, XPointer pointer UNUSED)
{
    if (event->xany.window != _glfw.x11.helperWindowHandle)
        return False;

    return event->type == SelectionRequest ||
           event->type == SelectionNotify ||
           event->type == SelectionClear;
}

// Returns whether it is a _NET_FRAME_EXTENTS event for the specified window
//
static Bool isFrameExtentsEvent(Display* display UNUSED, XEvent* event, XPointer pointer)
{
    _GLFWwindow* window = (_GLFWwindow*) pointer;
    return event->type == PropertyNotify &&
           event->xproperty.state == PropertyNewValue &&
           event->xproperty.window == window->x11.handle &&
           event->xproperty.atom == _glfw.x11.NET_FRAME_EXTENTS;
}

// Returns whether it is a property event for the specified selection transfer
//
static Bool isSelPropNewValueNotify(Display* display UNUSED, XEvent* event, XPointer pointer)
{
    XEvent* notification = (XEvent*) pointer;
    return event->type == PropertyNotify &&
           event->xproperty.state == PropertyNewValue &&
           event->xproperty.window == notification->xselection.requestor &&
           event->xproperty.atom == notification->xselection.property;
}

// Translates an X event modifier state mask
//
static int translateState(int state)
{
    int mods = 0;

    /* Need some way to expose hyper and meta without xkbcommon-x11 */
    if (state & ShiftMask)
        mods |= GLFW_MOD_SHIFT;
    if (state & ControlMask)
        mods |= GLFW_MOD_CONTROL;
    if (state & Mod1Mask)
        mods |= GLFW_MOD_ALT;
    if (state & Mod4Mask)
        mods |= GLFW_MOD_SUPER;
    if (state & LockMask)
        mods |= GLFW_MOD_CAPS_LOCK;
    if (state & Mod2Mask)
        mods |= GLFW_MOD_NUM_LOCK;

    return mods;
}

// Sends an EWMH or ICCCM event to the window manager
//
static void sendEventToWM(_GLFWwindow* window, Atom type,
                          long a, long b, long c, long d, long e)
{
    XEvent event = { ClientMessage };
    event.xclient.window = window->x11.handle;
    event.xclient.format = 32; // Data is 32-bit longs
    event.xclient.message_type = type;
    event.xclient.data.l[0] = a;
    event.xclient.data.l[1] = b;
    event.xclient.data.l[2] = c;
    event.xclient.data.l[3] = d;
    event.xclient.data.l[4] = e;

    XSendEvent(_glfw.x11.display, _glfw.x11.root,
               False,
               SubstructureNotifyMask | SubstructureRedirectMask,
               &event);
}

// Updates the normal hints according to the window settings
//
static void
updateNormalHints(_GLFWwindow* window, int width, int height)
{
    XSizeHints* hints = XAllocSizeHints();

    if (!window->monitor)
    {
        if (window->resizable)
        {
            if (window->minwidth != GLFW_DONT_CARE &&
                window->minheight != GLFW_DONT_CARE)
            {
                hints->flags |= PMinSize;
                hints->min_width = window->minwidth;
                hints->min_height = window->minheight;
            }

            if (window->maxwidth != GLFW_DONT_CARE &&
                window->maxheight != GLFW_DONT_CARE)
            {
                hints->flags |= PMaxSize;
                hints->max_width = window->maxwidth;
                hints->max_height = window->maxheight;
            }

            if (window->numer != GLFW_DONT_CARE &&
                window->denom != GLFW_DONT_CARE)
            {
                hints->flags |= PAspect;
                hints->min_aspect.x = hints->max_aspect.x = window->numer;
                hints->min_aspect.y = hints->max_aspect.y = window->denom;
            }

            if (window->widthincr != GLFW_DONT_CARE &&
                window->heightincr != GLFW_DONT_CARE && !window->x11.maximized)
            {
                hints->flags |= PResizeInc;
                hints->width_inc = window->widthincr;
                hints->height_inc = window->heightincr;
            }
        }
        else
        {
            hints->flags |= (PMinSize | PMaxSize);
            hints->min_width  = hints->max_width  = width;
            hints->min_height = hints->max_height = height;
        }
    }

    hints->flags |= PWinGravity;
    hints->win_gravity = StaticGravity;

    XSetWMNormalHints(_glfw.x11.display, window->x11.handle, hints);
    XFree(hints);
}

static bool
is_window_fullscreen(_GLFWwindow* window)
{
    Atom* states;
    unsigned long i;
    bool ans = false;
    if (!_glfw.x11.NET_WM_STATE || !_glfw.x11.NET_WM_STATE_FULLSCREEN)
        return ans;
    const unsigned long count =
        _glfwGetWindowPropertyX11(window->x11.handle,
                                  _glfw.x11.NET_WM_STATE,
                                  XA_ATOM,
                                  (unsigned char**) &states);

    for (i = 0;  i < count;  i++)
    {
        if (states[i] == _glfw.x11.NET_WM_STATE_FULLSCREEN)
        {
            ans = true;
            break;
        }
    }

    if (states)
        XFree(states);

    return ans;
}

static void
set_fullscreen(_GLFWwindow *window, bool on) {
    if (_glfw.x11.NET_WM_STATE && _glfw.x11.NET_WM_STATE_FULLSCREEN) {
        sendEventToWM(window,
                _glfw.x11.NET_WM_STATE,
                on ? _NET_WM_STATE_ADD : _NET_WM_STATE_REMOVE,
                _glfw.x11.NET_WM_STATE_FULLSCREEN,
                0, 1, 0);
        // Enable compositor bypass
        if (!window->x11.transparent)
        {
            if (on) {
                const unsigned long value = 1;

                XChangeProperty(_glfw.x11.display,  window->x11.handle,
                                _glfw.x11.NET_WM_BYPASS_COMPOSITOR, XA_CARDINAL, 32,
                                PropModeReplace, (unsigned char*) &value, 1);
            } else {
                XDeleteProperty(_glfw.x11.display, window->x11.handle,
                                _glfw.x11.NET_WM_BYPASS_COMPOSITOR);
            }
        }

    } else {
        static bool warned = false;
        if (!warned) {
            warned = true;
            _glfwInputErrorX11(GLFW_PLATFORM_ERROR,
                               "X11: Failed to toggle fullscreen, the window manager does not support it");
        }
    }
}

bool
_glfwPlatformIsFullscreen(_GLFWwindow *window, unsigned int flags UNUSED) {
    return is_window_fullscreen(window);
}

bool
_glfwPlatformToggleFullscreen(_GLFWwindow *window, unsigned int flags UNUSED) {
    bool already_fullscreen = is_window_fullscreen(window);
    set_fullscreen(window, !already_fullscreen);
    return !already_fullscreen;
}

// Updates the full screen status of the window
//
static void updateWindowMode(_GLFWwindow* window)
{
    if (window->monitor)
    {
        if (_glfw.x11.xinerama.available &&
            _glfw.x11.NET_WM_FULLSCREEN_MONITORS)
        {
            sendEventToWM(window,
                          _glfw.x11.NET_WM_FULLSCREEN_MONITORS,
                          window->monitor->x11.index,
                          window->monitor->x11.index,
                          window->monitor->x11.index,
                          window->monitor->x11.index,
                          0);
        }

        set_fullscreen(window, true);

    }
    else
    {
        if (_glfw.x11.xinerama.available &&
            _glfw.x11.NET_WM_FULLSCREEN_MONITORS)
        {
            XDeleteProperty(_glfw.x11.display, window->x11.handle,
                            _glfw.x11.NET_WM_FULLSCREEN_MONITORS);
        }

        set_fullscreen(window, false);

    }
}


// Encode a Unicode code point to a UTF-8 stream
// Based on cutef8 by Jeff Bezanson (Public Domain)
//
static size_t encodeUTF8(char* s, unsigned int ch)
{
    size_t count = 0;

    if (ch < 0x80)
        s[count++] = (char) ch;
    else if (ch < 0x800)
    {
        s[count++] = (ch >> 6) | 0xc0;
        s[count++] = (ch & 0x3f) | 0x80;
    }
    else if (ch < 0x10000)
    {
        s[count++] = (ch >> 12) | 0xe0;
        s[count++] = ((ch >> 6) & 0x3f) | 0x80;
        s[count++] = (ch & 0x3f) | 0x80;
    }
    else if (ch < 0x110000)
    {
        s[count++] = (ch >> 18) | 0xf0;
        s[count++] = ((ch >> 12) & 0x3f) | 0x80;
        s[count++] = ((ch >> 6) & 0x3f) | 0x80;
        s[count++] = (ch & 0x3f) | 0x80;
    }

    return count;
}

// Convert the specified Latin-1 string to UTF-8
//
static char* convertLatin1toUTF8(const char* source)
{
    size_t size = 1;
    const char* sp;

    if (source) {
        for (sp = source;  *sp;  sp++)
            size += (*sp & 0x80) ? 2 : 1;
    }

    char* target = calloc(size, 1);
    char* tp = target;

    if (source) {
        for (sp = source;  *sp;  sp++)
            tp += encodeUTF8(tp, *sp);
    }

    return target;
}

// Updates the cursor image according to its cursor mode
//
static void updateCursorImage(_GLFWwindow* window)
{
    if (window->cursorMode == GLFW_CURSOR_NORMAL)
    {
        if (window->cursor)
        {
            XDefineCursor(_glfw.x11.display, window->x11.handle,
                          window->cursor->x11.handle);
        }
        else
            XUndefineCursor(_glfw.x11.display, window->x11.handle);
    }
    else
    {
        XDefineCursor(_glfw.x11.display, window->x11.handle,
                      _glfw.x11.hiddenCursorHandle);
    }
}

// Enable XI2 raw mouse motion events
//
static void enableRawMouseMotion(_GLFWwindow* window UNUSED)
{
    XIEventMask em;
    unsigned char mask[XIMaskLen(XI_RawMotion)] = { 0 };

    em.deviceid = XIAllMasterDevices;
    em.mask_len = sizeof(mask);
    em.mask = mask;
    XISetMask(mask, XI_RawMotion);

    XISelectEvents(_glfw.x11.display, _glfw.x11.root, &em, 1);
}

// Disable XI2 raw mouse motion events
//
static void disableRawMouseMotion(_GLFWwindow* window UNUSED)
{
    XIEventMask em;
    unsigned char mask[] = { 0 };

    em.deviceid = XIAllMasterDevices;
    em.mask_len = sizeof(mask);
    em.mask = mask;

    XISelectEvents(_glfw.x11.display, _glfw.x11.root, &em, 1);
}

// Apply disabled cursor mode to a focused window
//
static void disableCursor(_GLFWwindow* window)
{
    if (window->rawMouseMotion)
        enableRawMouseMotion(window);

    _glfw.x11.disabledCursorWindow = window;
    _glfwPlatformGetCursorPos(window,
                              &_glfw.x11.restoreCursorPosX,
                              &_glfw.x11.restoreCursorPosY);
    updateCursorImage(window);
    _glfwCenterCursorInContentArea(window);
    XGrabPointer(_glfw.x11.display, window->x11.handle, True,
                 ButtonPressMask | ButtonReleaseMask | PointerMotionMask,
                 GrabModeAsync, GrabModeAsync,
                 window->x11.handle,
                 _glfw.x11.hiddenCursorHandle,
                 CurrentTime);
}

// Exit disabled cursor mode for the specified window
//
static void enableCursor(_GLFWwindow* window)
{
    if (window->rawMouseMotion)
        disableRawMouseMotion(window);

    _glfw.x11.disabledCursorWindow = NULL;
    XUngrabPointer(_glfw.x11.display, CurrentTime);
    _glfwPlatformSetCursorPos(window,
                              _glfw.x11.restoreCursorPosX,
                              _glfw.x11.restoreCursorPosY);
    updateCursorImage(window);
}

typedef unsigned long strut_type;

typedef struct WindowGeometry {
    int x, y, width, height;
    bool needs_strut;
    strut_type struts[12];
} WindowGeometry;

#define config (window->x11.layer_shell.config)

static _GLFWmonitor*
find_monitor_by_name(const char* name) {
    if (!name || !name[0]) return (_GLFWmonitor*)glfwGetPrimaryMonitor();;
    for (int i = 0; i < _glfw.monitorCount; i++) {
        _GLFWmonitor *m = _glfw.monitors[i];
        if (strcmp(m->name, name) == 0) return m;
    }
    return (_GLFWmonitor*)glfwGetPrimaryMonitor();;
}


static WindowGeometry
calculate_layer_geometry(_GLFWwindow *window) {
    _GLFWmonitor *monitor = find_monitor_by_name(config.output_name);
    MonitorGeometry mg = _glfwPlatformGetMonitorGeometry((_GLFWmonitor*)glfwGetPrimaryMonitor());
    WindowGeometry ans = {0};
    debug_rendering("Monitor: %s full: %dx%d@%dx%d workarea: %dx%d@%dx%d\n", monitor->name,
            mg.full.width, mg.full.height, mg.full.x, mg.full.y, mg.workarea.width, mg.workarea.height, mg.workarea.x, mg.workarea.y);
    ans.width = mg.full.width; ans.height = mg.full.height;
    ans.x = mg.full.x; ans.y = mg.full.y;
    ans.needs_strut = config.type == GLFW_LAYER_SHELL_PANEL;
    if (config.type == GLFW_LAYER_SHELL_BACKGROUND) {
        ans.x += config.requested_left_margin; ans.y += config.requested_top_margin;
        ans.width -= config.requested_left_margin + config.requested_right_margin;
        ans.height -= config.requested_top_margin + config.requested_bottom_margin;
        return ans;
    }
    float xscale = (float)config.expected.xscale, yscale = (float)config.expected.yscale;
    _glfwPlatformGetWindowContentScale(window, &xscale, &yscale);
    unsigned cell_width, cell_height; double left_edge_spacing, top_edge_spacing, right_edge_spacing, bottom_edge_spacing;
    config.size_callback((GLFWwindow*)window, xscale, yscale, &cell_width, &cell_height, &left_edge_spacing, &top_edge_spacing, &right_edge_spacing, &bottom_edge_spacing);
    double spacing_x = left_edge_spacing + right_edge_spacing;
    double spacing_y = top_edge_spacing + bottom_edge_spacing;
    double xsz = config.x_size_in_pixels ? (unsigned)(config.x_size_in_pixels * xscale) : (cell_width * config.x_size_in_cells);
    double ysz = config.y_size_in_pixels ? (unsigned)(config.y_size_in_pixels * yscale) : (cell_height * config.y_size_in_cells);
    ans.width = (int)(1. + spacing_x + xsz); ans.height = (int)(1. + spacing_y + ysz);
    GeometryRect m = config.type == GLFW_LAYER_SHELL_TOP || config.type == GLFW_LAYER_SHELL_OVERLAY ? mg.workarea : mg.full;
    static const struct {
        unsigned left, right, top, bottom, left_start_y, left_end_y, right_start_y, right_end_y, top_start_x, top_end_x, bottom_start_x, bottom_end_x;
    } s = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11};

    switch (config.edge) {
        case GLFW_EDGE_LEFT:
            ans.x = m.x + config.requested_left_margin;
            ans.y = m.y + config.requested_top_margin;
            ans.height = m.height - config.requested_bottom_margin - config.requested_top_margin;
            ans.struts[s.left] = ans.width; ans.struts[s.left_end_y] = ans.height;
            break;
        case GLFW_EDGE_RIGHT:
            ans.x = m.x + m.width - config.requested_right_margin - ans.width;
            ans.y = m.y + config.requested_top_margin;
            ans.height = m.height - config.requested_bottom_margin - config.requested_top_margin;
            ans.struts[s.right] = ans.width; ans.struts[s.right_end_y] = ans.height;
            break;
        case GLFW_EDGE_TOP:
            ans.x = m.x + config.requested_left_margin;
            ans.y = m.y + config.requested_top_margin;
            ans.width = m.width - config.requested_right_margin - config.requested_left_margin;
            ans.struts[s.top] = ans.height; ans.struts[s.top_end_x] = ans.width;
            break;
        case GLFW_EDGE_BOTTOM:
            ans.x = m.x + config.requested_left_margin;
            ans.y = m.height - config.requested_bottom_margin - ans.height;
            ans.width = m.width - config.requested_right_margin - config.requested_left_margin;
            ans.struts[s.bottom] = ans.height; ans.struts[s.bottom_end_x] = ans.width;
            break;
        case GLFW_EDGE_CENTER_SIZED:
            ans.needs_strut = false;
            ans.x = (m.width - ans.width) / 2;
            ans.y = (m.height - ans.height) / 2;
            break;
        default:
            ans.needs_strut = false;
            ans.x = m.x + config.requested_left_margin;
            ans.y = m.y + config.requested_top_margin;
            ans.height = m.height - config.requested_bottom_margin - config.requested_top_margin;
            ans.width = m.width - config.requested_right_margin - config.requested_left_margin;
            break;
    }
    debug_rendering("Calculating layer geometry at scale: %f cell size: (%u, %u) -> %dx%d@%dx%d needs_strut: %d\n",
            xscale, cell_width, cell_height, ans.width, ans.height, ans.x, ans.y, ans.needs_strut)
    return ans;
}

GLFWAPI bool glfwIsLayerShellSupported(void) { return _glfw.x11.NET_WM_WINDOW_TYPE != 0 && _glfw.x11.NET_WM_STATE != 0; }


static bool
update_wm_hints(_GLFWwindow *window, const WindowGeometry *wg, const _GLFWwndconfig *wndconfig) {
    XWMHints* hints = XAllocWMHints();
    bool is_layer_shell = window->x11.layer_shell.is_active;
    bool ok = false;
    if (hints) {
        ok = true;
        hints->flags = StateHint | InputHint;
        hints->initial_state = NormalState;
        hints->input = true;
        if (is_layer_shell && config.focus_policy == GLFW_FOCUS_NOT_ALLOWED) hints->input = false;
        XSetWMHints(_glfw.x11.display, window->x11.handle, hints);
        XFree(hints);
    } else _glfwInputError(GLFW_OUT_OF_MEMORY, "X11: Failed to allocate WM hints");
    if (_glfw.x11.NET_WM_WINDOW_TYPE) {
        Atom type = 0;
        if (is_layer_shell) {
            const char *name = NULL;
#define S(which) type = _glfw.x11.which; name = #which
            switch (config.type) {
                case GLFW_LAYER_SHELL_BACKGROUND: S(NET_WM_WINDOW_TYPE_DESKTOP); break;
                case GLFW_LAYER_SHELL_PANEL: S(NET_WM_WINDOW_TYPE_DOCK); break;
                default: S(NET_WM_WINDOW_TYPE_NORMAL); break;
            }
#undef S
            if (!type) {
                _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Window manager does not support _%s", name);
                ok = false;
            }
        } else if (_glfw.x11.NET_WM_WINDOW_TYPE_NORMAL) type = _glfw.x11.NET_WM_WINDOW_TYPE_NORMAL;
        if (type) XChangeProperty(
            _glfw.x11.display,  window->x11.handle, _glfw.x11.NET_WM_WINDOW_TYPE, XA_ATOM, 32, PropModeReplace, (unsigned char*) &type, 1);
    } else if (is_layer_shell) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Window manager does not support _NET_WM_WINDOW_TYPE");
        ok = false;
    }
    if (is_layer_shell) {
        if (_glfw.x11.NET_WM_STRUT_PARTIAL) {
            XChangeProperty(
                _glfw.x11.display, window->x11.handle, _glfw.x11.NET_WM_STRUT_PARTIAL, XA_CARDINAL, 32, PropModeReplace,
                (unsigned char*)(wg->needs_strut ? wg->struts : (strut_type[12]){0}), 12);
        } else if (wg->needs_strut) {
            _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Window manager does not support _NET_WM_STRUT_PARTIAL");
            ok = false;
        }
    }
    if (ok) {
        updateNormalHints(window, wg->width, wg->height);
        Atom states[8]; unsigned count = 0;
        if (is_layer_shell) {
            _glfwPlatformSetWindowDecorated(window, false);
            if (_glfw.x11.NET_WM_STATE_STICKY) states[count++] = _glfw.x11.NET_WM_STATE_STICKY;
            if (_glfw.x11.NET_WM_STATE_SKIP_PAGER) states[count++] = _glfw.x11.NET_WM_STATE_SKIP_PAGER;
            if (_glfw.x11.NET_WM_STATE_SKIP_TASKBAR) states[count++] = _glfw.x11.NET_WM_STATE_SKIP_TASKBAR;
#define S(x) if (_glfw.x11.x) { states[count++] = _glfw.x11.x; } else { _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Window manager does not support _%s", #x); ok = false; }
            switch (config.type) {
                case GLFW_LAYER_SHELL_NONE: break;
                case GLFW_LAYER_SHELL_BACKGROUND:  S(NET_WM_STATE_BELOW); break;
                case GLFW_LAYER_SHELL_PANEL:
                    // i3 does not support NET_WM_STATE_BELOW but panels work without it
                    if (_glfw.x11.NET_WM_STATE_BELOW) { S(NET_WM_STATE_BELOW); }
                    break;
                case GLFW_LAYER_SHELL_TOP: case GLFW_LAYER_SHELL_OVERLAY: S(NET_WM_STATE_ABOVE); break;
            }
#undef S
        } else if (wndconfig) {
            if (!wndconfig->decorated) _glfwPlatformSetWindowDecorated(window, false);
            if (_glfw.x11.NET_WM_STATE && !window->monitor) {
                if (wndconfig->floating) {
                    if (_glfw.x11.NET_WM_STATE_ABOVE) states[count++] = _glfw.x11.NET_WM_STATE_ABOVE;
                }
                if (wndconfig->maximized) {
                    if (_glfw.x11.NET_WM_STATE_MAXIMIZED_VERT && _glfw.x11.NET_WM_STATE_MAXIMIZED_HORZ) {
                        states[count++] = _glfw.x11.NET_WM_STATE_MAXIMIZED_VERT;
                        states[count++] = _glfw.x11.NET_WM_STATE_MAXIMIZED_HORZ;
                        window->x11.maximized = true;
                    }
                }
            }
        }
        if (count && _glfw.x11.NET_WM_STATE) XChangeProperty(_glfw.x11.display, window->x11.handle, _glfw.x11.NET_WM_STATE,
                XA_ATOM, 32, PropModeReplace, (unsigned char*) states, count);
    }
    if (!wndconfig && ok) {
        _glfwPlatformSetWindowPos(window, wg->x, wg->y);
        _glfwPlatformSetWindowSize(window, wg->width, wg->height);
    }
    return ok;
#undef config
}

// Create the X11 window (and its colormap)
//
static bool createNativeWindow(_GLFWwindow* window,
                                   const _GLFWwndconfig* wndconfig,
                                   Visual* visual, int depth)
{
    WindowGeometry wg = {.width=wndconfig->width, .height=wndconfig->height};
    if (window->x11.layer_shell.is_active) {
        wg = calculate_layer_geometry(window);
        window->resizable = false;
    }

    // Create a colormap based on the visual used by the current context
    window->x11.colormap = XCreateColormap(_glfw.x11.display,
                                           _glfw.x11.root,
                                           visual,
                                           AllocNone);

    window->x11.transparent = _glfwIsVisualTransparentX11(visual);

    XSetWindowAttributes wa = { 0 };
    wa.colormap = window->x11.colormap;
    wa.event_mask = StructureNotifyMask | KeyPressMask | KeyReleaseMask |
                    PointerMotionMask | ButtonPressMask | ButtonReleaseMask |
                    ExposureMask | FocusChangeMask | VisibilityChangeMask |
                    EnterWindowMask | LeaveWindowMask | PropertyChangeMask;

    _glfwGrabErrorHandlerX11();

    window->x11.parent = _glfw.x11.root;
    debug_rendering("Creating window with geometry: %dx%d@%dx%d\n", wg.width, wg.height, wg.x, wg.y);
    window->x11.handle = XCreateWindow(_glfw.x11.display,
                                       _glfw.x11.root,
                                       wg.x, wg.y,   // Position
                                       wg.width, wg.height,
                                       0,      // Border width
                                       depth,  // Color depth
                                       InputOutput,
                                       visual,
                                       CWBorderPixel | CWColormap | CWEventMask,
                                       &wa);

    _glfwReleaseErrorHandlerX11();

    if (!window->x11.handle)
    {
        _glfwInputErrorX11(GLFW_PLATFORM_ERROR,
                           "X11: Failed to create window");
        return false;
    }

    XSaveContext(_glfw.x11.display,
                 window->x11.handle,
                 _glfw.x11.context,
                 (XPointer) window);

    // Declare the WM protocols supported by GLFW
    {
        Atom protocols[] =
        {
            _glfw.x11.WM_DELETE_WINDOW,
            _glfw.x11.NET_WM_PING
        };

        XSetWMProtocols(_glfw.x11.display, window->x11.handle,
                        protocols, sizeof(protocols) / sizeof(Atom));
    }

    // Declare our PID
    {
        const long pid = getpid();

        XChangeProperty(_glfw.x11.display,  window->x11.handle,
                        _glfw.x11.NET_WM_PID, XA_CARDINAL, 32,
                        PropModeReplace,
                        (unsigned char*) &pid, 1);
    }

    if (!update_wm_hints(window, &wg, wndconfig)) return false;
    // without this floating window position is incorrect on KDE
    if (window->x11.layer_shell.is_active) _glfwPlatformSetWindowPos(window, wg.x, wg.y);

    // Set ICCCM WM_CLASS property
    {
        XClassHint* hint = XAllocClassHint();

        if (strlen(wndconfig->x11.instanceName) &&
            strlen(wndconfig->x11.className))
        {
            hint->res_name = (char*) wndconfig->x11.instanceName;
            hint->res_class = (char*) wndconfig->x11.className;
        }
        else
        {
            const char* resourceName = getenv("RESOURCE_NAME");
            if (resourceName && strlen(resourceName))
                hint->res_name = (char*) resourceName;
            else if (strlen(wndconfig->title))
                hint->res_name = (char*) wndconfig->title;
            else
                hint->res_name = (char*) "glfw-application";

            if (strlen(wndconfig->title))
                hint->res_class = (char*) wndconfig->title;
            else
                hint->res_class = (char*) "GLFW-Application";
        }

        XSetClassHint(_glfw.x11.display, window->x11.handle, hint);
        XFree(hint);
    }

    // Announce support for Xdnd (drag and drop)
    {
        const Atom version = _GLFW_XDND_VERSION;
        XChangeProperty(_glfw.x11.display, window->x11.handle,
                        _glfw.x11.XdndAware, XA_ATOM, 32,
                        PropModeReplace, (unsigned char*) &version, 1);
    }

    _glfwPlatformSetWindowTitle(window, wndconfig->title);
    _glfwPlatformGetWindowPos(window, &window->x11.xpos, &window->x11.ypos);
    _glfwPlatformGetWindowSize(window, &window->x11.width, &window->x11.height);

    if (_glfw.hints.window.blur_radius > 0) _glfwPlatformSetWindowBlur(window, _glfw.hints.window.blur_radius);

    return true;
}

static size_t
get_clipboard_data(const _GLFWClipboardData *cd, const char *mime, char **data) {
    *data = NULL;
    if (cd->get_data == NULL) { return 0; }
    GLFWDataChunk chunk = cd->get_data(mime, NULL, cd->ctype);
    char *buf = NULL;
    size_t sz = 0, cap = 0;
    void *iter = chunk.iter;
    if (!iter) return 0;
    while (true) {
        chunk = cd->get_data(mime, iter, cd->ctype);
        if (!chunk.sz) break;
        if (cap < sz + chunk.sz) {
            cap = MAX(cap * 2, sz + 4 * chunk.sz);
            buf = realloc(buf, cap * sizeof(buf[0]));
        }
        memcpy(buf + sz, chunk.data, chunk.sz);
        sz += chunk.sz;
        if (chunk.free) chunk.free((void*)chunk.free_data);
    }
    *data = buf;
    cd->get_data(NULL, iter, cd->ctype);
    return sz;
}

static void
get_atom_names(const Atom *atoms, int count, char **atom_names) {
    _glfwGrabErrorHandlerX11();
    XGetAtomNames(_glfw.x11.display, (Atom*)atoms, count, atom_names);
    _glfwReleaseErrorHandlerX11();
    if (_glfw.x11.errorCode != Success) {
        for (int i = 0; i < count; i++) {
            _glfwGrabErrorHandlerX11();
            atom_names[i] = XGetAtomName(_glfw.x11.display, atoms[i]);
            _glfwReleaseErrorHandlerX11();
            if (_glfw.x11.errorCode != Success) atom_names[i] = NULL;
        }
    }
}


// Set the specified property to the selection converted to the requested target
//
static Atom writeTargetToProperty(const XSelectionRequestEvent* request)
{
    const AtomArray *aa;
    const _GLFWClipboardData *cd;

    if (request->selection == _glfw.x11.PRIMARY) {
        aa = &_glfw.x11.primary_atoms;
        cd = &_glfw.primary;
    } else {
        aa = &_glfw.x11.clipboard_atoms;
        cd = &_glfw.clipboard;
    }

    if (request->property == None)
    {
        // The requester is a legacy client (ICCCM section 2.2)
        // We don't support legacy clients, so fail here
        return None;
    }

    if (request->target == _glfw.x11.TARGETS)
    {
        // The list of supported targets was requested

        Atom *targets = calloc(aa->sz + 2, sizeof(Atom));
        targets[0] = _glfw.x11.TARGETS;
        targets[1] = _glfw.x11.MULTIPLE;
        for (size_t i = 0; i < aa->sz; i++) targets[i+2] = aa->array[i].atom;
        XChangeProperty(_glfw.x11.display,
                        request->requestor,
                        request->property,
                        XA_ATOM,
                        32,
                        PropModeReplace,
                        (unsigned char*) targets,
                        aa->sz + 2);
        free(targets);
        return request->property;
    }

    if (request->target == _glfw.x11.MULTIPLE)
    {
        // Multiple conversions were requested

        Atom* targets;
        size_t i, j, count;

        count = _glfwGetWindowPropertyX11(request->requestor,
                                          request->property,
                                          _glfw.x11.ATOM_PAIR,
                                          (unsigned char**) &targets);

        for (i = 0;  i < count;  i += 2)
        {
            for (j = 0;  j < aa->sz;  j++)
            {
                if (targets[i] == aa->array[j].atom)
                    break;
            }

            if (j < aa->sz)
            {
                char *data = NULL; size_t sz = get_clipboard_data(cd, aa->array[j].mime, &data);

                if (data) XChangeProperty(_glfw.x11.display,
                                request->requestor,
                                targets[i + 1],
                                targets[i],
                                8,
                                PropModeReplace,
                                (unsigned char *) data,
                                sz);
                free(data);
            }
            else
                targets[i + 1] = None;
        }

        XChangeProperty(_glfw.x11.display,
                        request->requestor,
                        request->property,
                        _glfw.x11.ATOM_PAIR,
                        32,
                        PropModeReplace,
                        (unsigned char*) targets,
                        count);

        XFree(targets);

        return request->property;
    }

    if (request->target == _glfw.x11.SAVE_TARGETS)
    {
        // The request is a check whether we support SAVE_TARGETS
        // It should be handled as a no-op side effect target

        XChangeProperty(_glfw.x11.display,
                        request->requestor,
                        request->property,
                        _glfw.x11.NULL_,
                        32,
                        PropModeReplace,
                        NULL,
                        0);

        return request->property;
    }

    // Conversion to a data target was requested

    for (size_t i = 0;  i < aa->sz;  i++)
    {
        if (request->target == aa->array[i].atom)
        {
            // The requested target is one we support

            char *data = NULL; size_t sz = get_clipboard_data(cd, aa->array[i].mime, &data);
            if (data) XChangeProperty(_glfw.x11.display,
                            request->requestor,
                            request->property,
                            request->target,
                            8,
                            PropModeReplace,
                            (unsigned char *) data,
                            sz);
            free(data);

            return request->property;
        }
    }

    // The requested target is not supported

    return None;
}

static void handleSelectionClear(XEvent* event)
{
    if (event->xselectionclear.selection == _glfw.x11.PRIMARY)
    {
        _glfw_free_clipboard_data(&_glfw.primary);
        _glfwInputClipboardLost(GLFW_PRIMARY_SELECTION);
    }
    else
    {
        _glfw_free_clipboard_data(&_glfw.clipboard);
        _glfwInputClipboardLost(GLFW_CLIPBOARD);
    }
}

static void handleSelectionRequest(XEvent* event)
{
    const XSelectionRequestEvent* request = &event->xselectionrequest;

    XEvent reply = { SelectionNotify };
    reply.xselection.property = writeTargetToProperty(request);
    reply.xselection.display = request->display;
    reply.xselection.requestor = request->requestor;
    reply.xselection.selection = request->selection;
    reply.xselection.target = request->target;
    reply.xselection.time = request->time;

    XSendEvent(_glfw.x11.display, request->requestor, False, 0, &reply);
}

static void
getSelectionString(Atom selection, Atom *targets, size_t num_targets, GLFWclipboardwritedatafun write_data, void *object, bool report_not_found)
{
#define XFREE(x) { if (x) XFree(x); x = NULL; }
    if (XGetSelectionOwner(_glfw.x11.display, selection) == _glfw.x11.helperWindowHandle) {
        write_data(object, NULL, 1);
        return;
    }
    bool found = false;
    for (size_t i = 0; !found && i < num_targets; i++)
    {
        char* data = NULL;
        Atom actualType = None;
        int actualFormat = 0;
        unsigned long itemCount = 0, bytesAfter = 0;
        monotonic_t start = glfwGetTime();
        XEvent notification, dummy;

        XConvertSelection(_glfw.x11.display,
                          selection,
                          targets[i],
                          _glfw.x11.GLFW_SELECTION,
                          _glfw.x11.helperWindowHandle,
                          CurrentTime);

        while (!XCheckTypedWindowEvent(_glfw.x11.display,
                                       _glfw.x11.helperWindowHandle,
                                       SelectionNotify,
                                       &notification))
        {
            monotonic_t time = glfwGetTime();
            if (time - start > s_to_monotonic_t(2ll)) return;
            waitForX11Event(s_to_monotonic_t(2ll) - (time - start));
        }

        if (notification.xselection.property == None)
            continue;

        XCheckIfEvent(_glfw.x11.display,
                      &dummy,
                      isSelPropNewValueNotify,
                      (XPointer) &notification);

        XGetWindowProperty(_glfw.x11.display,
                           notification.xselection.requestor,
                           notification.xselection.property,
                           0,
                           LONG_MAX,
                           True,
                           AnyPropertyType,
                           &actualType,
                           &actualFormat,
                           &itemCount,
                           &bytesAfter,
                           (unsigned char**) &data);

        if (actualType == _glfw.x11.INCR)
        {
            for (;;)
            {
                start = glfwGetTime();
                while (!XCheckIfEvent(_glfw.x11.display,
                                      &dummy,
                                      isSelPropNewValueNotify,
                                      (XPointer) &notification))
                {
                    monotonic_t time = glfwGetTime();
                    if (time - start > s_to_monotonic_t(2ll)) {
                        return;
                    }
                    waitForX11Event(s_to_monotonic_t(2ll) - (time - start));
                }

                XFREE(data);
                XGetWindowProperty(_glfw.x11.display,
                                   notification.xselection.requestor,
                                   notification.xselection.property,
                                   0,
                                   LONG_MAX,
                                   True,
                                   AnyPropertyType,
                                   &actualType,
                                   &actualFormat,
                                   &itemCount,
                                   &bytesAfter,
                                   (unsigned char**) &data);

                if (itemCount)
                {
                    const char *string = data;
                    if (targets[i] == XA_STRING) {
                        string = convertLatin1toUTF8(data);
                        itemCount = strlen(string);
                    }
                    bool ok = write_data(object, string, itemCount);
                    if (string != data) free((void*)string);
                    if (!ok) { XFREE(data); break; }
                } else { found = true; break; }

            }
        }
        else if (actualType == targets[i])
        {
            if (targets[i] == XA_STRING) {
                const char *string = convertLatin1toUTF8(data);
                write_data(object, string, strlen(string)); free((void*)string);
            } else write_data(object, data, itemCount);
            found = true;
        }
        else if (actualType == XA_ATOM && targets[i] == _glfw.x11.TARGETS) {
            found = true;
            write_data(object, data, sizeof(Atom) * itemCount);
        }

        XFREE(data);

    }

    if (!found && report_not_found)
    {
        _glfwInputError(GLFW_FORMAT_UNAVAILABLE,
                        "X11: Failed to convert selection to data from clipboard");
    }
#undef XFREE
}

// Make the specified window and its video mode active on its monitor
//
static void acquireMonitor(_GLFWwindow* window)
{
    if (_glfw.x11.saver.count == 0)
    {
        // Remember old screen saver settings
        XGetScreenSaver(_glfw.x11.display,
                        &_glfw.x11.saver.timeout,
                        &_glfw.x11.saver.interval,
                        &_glfw.x11.saver.blanking,
                        &_glfw.x11.saver.exposure);

        // Disable screen saver
        XSetScreenSaver(_glfw.x11.display, 0, 0, DontPreferBlanking,
                        DefaultExposures);
    }

    if (!window->monitor->window)
        _glfw.x11.saver.count++;

    _glfwSetVideoModeX11(window->monitor, &window->videoMode);

    _glfwInputMonitorWindow(window->monitor, window);
}

// Remove the window and restore the original video mode
//
static void releaseMonitor(_GLFWwindow* window)
{
    if (window->monitor->window != window)
        return;

    _glfwInputMonitorWindow(window->monitor, NULL);
    _glfwRestoreVideoModeX11(window->monitor);

    _glfw.x11.saver.count--;

    if (_glfw.x11.saver.count == 0)
    {
        // Restore old screen saver settings
        XSetScreenSaver(_glfw.x11.display,
                        _glfw.x11.saver.timeout,
                        _glfw.x11.saver.interval,
                        _glfw.x11.saver.blanking,
                        _glfw.x11.saver.exposure);
    }
}

static void onConfigChange(void)
{
    float xscale, yscale;
    _glfwGetSystemContentScaleX11(&xscale, &yscale, true);

    if (xscale != _glfw.x11.contentScaleX || yscale != _glfw.x11.contentScaleY)
    {
        _GLFWwindow* window = _glfw.windowListHead;
        _glfw.x11.contentScaleX = xscale;
        _glfw.x11.contentScaleY = yscale;
        while (window)
        {
            _glfwInputWindowContentScale(window, xscale, yscale);
            window = window->next;
        }
    }
}

// Process the specified X event
//
static void processEvent(XEvent *event)
{
    static bool keymap_dirty = false;
#define UPDATE_KEYMAP_IF_NEEDED if (keymap_dirty) { keymap_dirty = false; glfw_xkb_compile_keymap(&_glfw.x11.xkb, NULL); }

    if (_glfw.x11.randr.available)
    {
        if (event->type == _glfw.x11.randr.eventBase + RRNotify)
        {
            XRRUpdateConfiguration(event);
            _glfwPollMonitorsX11();
            return;
        }
    }

    if (event->type == PropertyNotify &&
        event->xproperty.window == _glfw.x11.root &&
        event->xproperty.atom == _glfw.x11.RESOURCE_MANAGER)
    {
        onConfigChange();
        return;
    }

    if (event->type == GenericEvent)
    {
        if (_glfw.x11.xi.available)
        {
            _GLFWwindow* window = _glfw.x11.disabledCursorWindow;

            if (window &&
                window->rawMouseMotion &&
                event->xcookie.extension == _glfw.x11.xi.majorOpcode &&
                XGetEventData(_glfw.x11.display, &event->xcookie) &&
                event->xcookie.evtype == XI_RawMotion)
            {
                XIRawEvent* re = event->xcookie.data;
                if (re->valuators.mask_len)
                {
                    const double* values = re->raw_values;
                    double xpos = window->virtualCursorPosX;
                    double ypos = window->virtualCursorPosY;

                    if (XIMaskIsSet(re->valuators.mask, 0))
                    {
                        xpos += *values;
                        values++;
                    }

                    if (XIMaskIsSet(re->valuators.mask, 1))
                        ypos += *values;

                    _glfwInputCursorPos(window, xpos, ypos);
                }
            }

            XFreeEventData(_glfw.x11.display, &event->xcookie);
        }

        return;
    }

    if (event->type == SelectionClear)
    {
        handleSelectionClear(event);
        return;
    }
    else if (event->type == SelectionRequest)
    {
        handleSelectionRequest(event);
        return;
    }
    else if (event->type == _glfw.x11.xkb.eventBase)
    {
        XkbEvent *kb_event = (XkbEvent*)event;
        if (kb_event->any.device != (unsigned int)_glfw.x11.xkb.keyboard_device_id) return;
        switch(kb_event->any.xkb_type) {
            case XkbNewKeyboardNotify: {
                XkbNewKeyboardNotifyEvent *newkb_event = (XkbNewKeyboardNotifyEvent*)kb_event;
                if (_glfw.hints.init.debugKeyboard) printf(
                        "Got XkbNewKeyboardNotify event with changes: key codes: %d geometry: %d device id: %d\n",
                        !!(newkb_event->changed & XkbNKN_KeycodesMask), !!(newkb_event->changed & XkbNKN_GeometryMask),
                        !!(newkb_event->changed & XkbNKN_DeviceIDMask));
                if (newkb_event->changed & XkbNKN_DeviceIDMask) {
                    keymap_dirty = true;
                    if (!glfw_xkb_update_x11_keyboard_id(&_glfw.x11.xkb)) return;
                }
                if (newkb_event->changed & XkbNKN_KeycodesMask) {
                    keymap_dirty = true;
                }
                return;
            }
            case XkbMapNotify:
            {
                if (_glfw.hints.init.debugKeyboard) printf("Got XkbMapNotify event, keymaps will be reloaded\n");
                keymap_dirty = true;
                return;
            }
            case XkbStateNotify:
            {
                UPDATE_KEYMAP_IF_NEEDED;
                XkbStateNotifyEvent *state_event = (XkbStateNotifyEvent*)kb_event;
                glfw_xkb_update_modifiers(
                        &_glfw.x11.xkb, state_event->base_mods, state_event->latched_mods,
                        state_event->locked_mods, state_event->base_group, state_event->latched_group, state_event->locked_group
                );
                return;
            }
        }
        return;
    }

    _GLFWwindow* window = NULL;
    if (XFindContext(_glfw.x11.display,
                     event->xany.window,
                     _glfw.x11.context,
                     (XPointer*) &window) != 0)
    {
        // This is an event for a window that has already been destroyed
        return;
    }

    switch (event->type)
    {
        case ReparentNotify:
        {
            window->x11.parent = event->xreparent.parent;
            return;
        }

        case KeyPress:
        {
            UPDATE_KEYMAP_IF_NEEDED;
            glfw_xkb_handle_key_event(window, &_glfw.x11.xkb, event->xkey.keycode, GLFW_PRESS);
            return;
        }

        case KeyRelease:
        {
            UPDATE_KEYMAP_IF_NEEDED;
            if (!_glfw.x11.xkb.detectable)
            {
                // HACK: Key repeat events will arrive as KeyRelease/KeyPress
                //       pairs with similar or identical time stamps
                //       The key repeat logic in _glfwInputKey expects only key
                //       presses to repeat, so detect and discard release events
                if (XEventsQueued(_glfw.x11.display, QueuedAfterReading))
                {
                    XEvent next;
                    XPeekEvent(_glfw.x11.display, &next);

                    if (next.type == KeyPress &&
                        next.xkey.window == event->xkey.window &&
                        next.xkey.keycode == event->xkey.keycode)
                    {
                        // HACK: The time of repeat events sometimes doesn't
                        //       match that of the press event, so add an
                        //       epsilon
                        //       Toshiyuki Takahashi can press a button
                        //       16 times per second so it's fairly safe to
                        //       assume that no human is pressing the key 50
                        //       times per second (value is ms)
                        if ((next.xkey.time - event->xkey.time) < 20)
                        {
                            // This is very likely a server-generated key repeat
                            // event, so ignore it
                            return;
                        }
                    }
                }
            }

            glfw_xkb_handle_key_event(window, &_glfw.x11.xkb, event->xkey.keycode, GLFW_RELEASE);
            return;
        }

        case ButtonPress:
        {
            const int mods = translateState(event->xbutton.state);

            if (event->xbutton.button == Button1)
                _glfwInputMouseClick(window, GLFW_MOUSE_BUTTON_LEFT, GLFW_PRESS, mods);
            else if (event->xbutton.button == Button2)
                _glfwInputMouseClick(window, GLFW_MOUSE_BUTTON_MIDDLE, GLFW_PRESS, mods);
            else if (event->xbutton.button == Button3)
                _glfwInputMouseClick(window, GLFW_MOUSE_BUTTON_RIGHT, GLFW_PRESS, mods);

            // Modern X provides scroll events as mouse button presses
            else if (event->xbutton.button == Button4)
                _glfwInputScroll(window, 0.0, 1.0, 0, mods);
            else if (event->xbutton.button == Button5)
                _glfwInputScroll(window, 0.0, -1.0, 0, mods);
            else if (event->xbutton.button == Button6)
                _glfwInputScroll(window, 1.0, 0.0, 0, mods);
            else if (event->xbutton.button == Button7)
                _glfwInputScroll(window, -1.0, 0.0, 0, mods);

            else
            {
                // Additional buttons after 7 are treated as regular buttons
                // We subtract 4 to fill the gap left by scroll input above
                _glfwInputMouseClick(window,
                                     event->xbutton.button - Button1 - 4,
                                     GLFW_PRESS,
                                     mods);
            }

            return;
        }

        case ButtonRelease:
        {
            const int mods = translateState(event->xbutton.state);

            if (event->xbutton.button == Button1)
            {
                _glfwInputMouseClick(window,
                                     GLFW_MOUSE_BUTTON_LEFT,
                                     GLFW_RELEASE,
                                     mods);
            }
            else if (event->xbutton.button == Button2)
            {
                _glfwInputMouseClick(window,
                                     GLFW_MOUSE_BUTTON_MIDDLE,
                                     GLFW_RELEASE,
                                     mods);
            }
            else if (event->xbutton.button == Button3)
            {
                _glfwInputMouseClick(window,
                                     GLFW_MOUSE_BUTTON_RIGHT,
                                     GLFW_RELEASE,
                                     mods);
            }
            else if (event->xbutton.button > Button7)
            {
                // Additional buttons after 7 are treated as regular buttons
                // We subtract 4 to fill the gap left by scroll input above
                _glfwInputMouseClick(window,
                                     event->xbutton.button - Button1 - 4,
                                     GLFW_RELEASE,
                                     mods);
            }

            return;
        }

        case EnterNotify:
        {
            // XEnterWindowEvent is XCrossingEvent
            const int x = event->xcrossing.x;
            const int y = event->xcrossing.y;

            // HACK: This is a workaround for WMs (KWM, Fluxbox) that otherwise
            //       ignore the defined cursor for hidden cursor mode
            if (window->cursorMode == GLFW_CURSOR_HIDDEN)
                updateCursorImage(window);

            _glfwInputCursorEnter(window, true);
            _glfwInputCursorPos(window, x, y);

            window->x11.lastCursorPosX = x;
            window->x11.lastCursorPosY = y;
            return;
        }

        case LeaveNotify:
        {
            _glfwInputCursorEnter(window, false);
            return;
        }

        case MotionNotify:
        {
            const int x = event->xmotion.x;
            const int y = event->xmotion.y;

            if (x != window->x11.warpCursorPosX ||
                y != window->x11.warpCursorPosY)
            {
                // The cursor was moved by something other than GLFW

                if (window->cursorMode == GLFW_CURSOR_DISABLED)
                {
                    if (_glfw.x11.disabledCursorWindow != window)
                        return;
                    if (window->rawMouseMotion)
                        return;

                    const int dx = x - window->x11.lastCursorPosX;
                    const int dy = y - window->x11.lastCursorPosY;

                    _glfwInputCursorPos(window,
                                        window->virtualCursorPosX + dx,
                                        window->virtualCursorPosY + dy);
                }
                else
                    _glfwInputCursorPos(window, x, y);
            }

            window->x11.lastCursorPosX = x;
            window->x11.lastCursorPosY = y;
            return;
        }

        case ConfigureNotify:
        {
            if (event->xconfigure.width != window->x11.width ||
                event->xconfigure.height != window->x11.height)
            {
                debug_rendering("Window resized to: %d %d from: %d %d\n", event->xconfigure.width, event->xconfigure.height, window->x11.width, window->x11.height);
                _glfwInputFramebufferSize(window,
                                          event->xconfigure.width,
                                          event->xconfigure.height);

                _glfwInputWindowSize(window,
                                     event->xconfigure.width,
                                     event->xconfigure.height);

                window->x11.width = event->xconfigure.width;
                window->x11.height = event->xconfigure.height;
            }

            int xpos = event->xconfigure.x;
            int ypos = event->xconfigure.y;

            // NOTE: ConfigureNotify events from the server are in local
            //       coordinates, so if we are reparented we need to translate
            //       the position into root (screen) coordinates
            if (!event->xany.send_event && window->x11.parent != _glfw.x11.root)
            {
                Window dummy;
                _glfwGrabErrorHandlerX11();
                XTranslateCoordinates(_glfw.x11.display,
                                      window->x11.parent,
                                      _glfw.x11.root,
                                      xpos, ypos,
                                      &xpos, &ypos,
                                      &dummy);
                _glfwReleaseErrorHandlerX11();
                if (_glfw.x11.errorCode != Success) {
                    _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Failed to translate ConfigureNotiy co-ords for reparented window");
                    return;
                }
            }
            if (xpos != window->x11.xpos || ypos != window->x11.ypos)
            {
                debug_rendering("Window moved to: %d %d from: %d %d\n", xpos, ypos, window->x11.xpos, window->x11.xpos);
                _glfwInputWindowPos(window, xpos, ypos);
                window->x11.xpos = xpos;
                window->x11.ypos = ypos;
            }

            return;
        }

        case ClientMessage:
        {
            // Custom client message, probably from the window manager

            if (event->xclient.message_type == None)
                return;

            if (event->xclient.message_type == _glfw.x11.WM_PROTOCOLS)
            {
                const Atom protocol = event->xclient.data.l[0];
                if (protocol == None)
                    return;

                if (protocol == _glfw.x11.WM_DELETE_WINDOW)
                {
                    // The window manager was asked to close the window, for
                    // example by the user pressing a 'close' window decoration
                    // button
                    _glfwInputWindowCloseRequest(window);
                }
                else if (protocol == _glfw.x11.NET_WM_PING)
                {
                    // The window manager is pinging the application to ensure
                    // it's still responding to events

                    XEvent reply = *event;
                    reply.xclient.window = _glfw.x11.root;

                    XSendEvent(_glfw.x11.display, _glfw.x11.root,
                               False,
                               SubstructureNotifyMask | SubstructureRedirectMask,
                               &reply);
                }
            }
            else if (event->xclient.message_type == _glfw.x11.XdndEnter)
            {
                // A drag operation has entered the window
                unsigned long i, count;
                Atom* formats = NULL;
                const bool list = event->xclient.data.l[1] & 1;

                _glfw.x11.xdnd.source  = event->xclient.data.l[0];
                _glfw.x11.xdnd.version = event->xclient.data.l[1] >> 24;
                memset(_glfw.x11.xdnd.format, 0, sizeof(_glfw.x11.xdnd.format));
                _glfw.x11.xdnd.format_priority  = 0;

                if (_glfw.x11.xdnd.version > _GLFW_XDND_VERSION)
                    return;

                if (list)
                {
                    count = _glfwGetWindowPropertyX11(_glfw.x11.xdnd.source,
                                                      _glfw.x11.XdndTypeList,
                                                      XA_ATOM,
                                                      (unsigned char**) &formats);
                }
                else
                {
                    count = 3;
                    formats = (Atom*) event->xclient.data.l + 2;
                }
                char **atom_names = calloc(count, sizeof(char*));
                if (atom_names) {
                    get_atom_names(formats, count, atom_names);

                    for (i = 0;  i < count;  i++)
                    {
                        if (atom_names[i]) {
                            int prio = _glfwInputDrop(window, atom_names[i], NULL, 0);
                            if (prio > _glfw.x11.xdnd.format_priority) {
                                _glfw.x11.xdnd.format_priority = prio;
                                strncpy(_glfw.x11.xdnd.format, atom_names[i], arraysz(_glfw.x11.xdnd.format) - 1);
                            }
                            XFree(atom_names[i]);
                        }
                    }
                    free(atom_names);
                }

                if (list && formats)
                    XFree(formats);
            }
            else if (event->xclient.message_type == _glfw.x11.XdndDrop)
            {
                // The drag operation has finished by dropping on the window
                Time time = CurrentTime;

                if (_glfw.x11.xdnd.version > _GLFW_XDND_VERSION)
                    return;

                if (_glfw.x11.xdnd.format_priority > 0)
                {
                    if (_glfw.x11.xdnd.version >= 1)
                        time = event->xclient.data.l[2];

                    // Request the chosen format from the source window
                    XConvertSelection(_glfw.x11.display,
                                      _glfw.x11.XdndSelection,
                                      XInternAtom(_glfw.x11.display, _glfw.x11.xdnd.format, 0),
                                      _glfw.x11.XdndSelection,
                                      window->x11.handle,
                                      time);
                }
                else if (_glfw.x11.xdnd.version >= 2)
                {
                    XEvent reply = { ClientMessage };
                    reply.xclient.window = _glfw.x11.xdnd.source;
                    reply.xclient.message_type = _glfw.x11.XdndFinished;
                    reply.xclient.format = 32;
                    reply.xclient.data.l[0] = window->x11.handle;
                    reply.xclient.data.l[1] = 0; // The drag was rejected
                    reply.xclient.data.l[2] = None;

                    XSendEvent(_glfw.x11.display, _glfw.x11.xdnd.source,
                               False, NoEventMask, &reply);
                    XFlush(_glfw.x11.display);
                }
            }
            else if (event->xclient.message_type == _glfw.x11.XdndPosition)
            {
                // The drag operation has moved over the window
                const int xabs = (event->xclient.data.l[2] >> 16) & 0xffff;
                const int yabs = (event->xclient.data.l[2]) & 0xffff;
                Window dummy;
                int xpos = 0, ypos = 0;

                if (_glfw.x11.xdnd.version > _GLFW_XDND_VERSION)
                    return;

                _glfwGrabErrorHandlerX11();
                XTranslateCoordinates(_glfw.x11.display,
                                      _glfw.x11.root,
                                      window->x11.handle,
                                      xabs, yabs,
                                      &xpos, &ypos,
                                      &dummy);
                _glfwReleaseErrorHandlerX11();
                if (_glfw.x11.errorCode != Success)
                    _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Failed to get DND event position");

                _glfwInputCursorPos(window, xpos, ypos);

                XEvent reply = { ClientMessage };
                reply.xclient.window = _glfw.x11.xdnd.source;
                reply.xclient.message_type = _glfw.x11.XdndStatus;
                reply.xclient.format = 32;
                reply.xclient.data.l[0] = window->x11.handle;
                reply.xclient.data.l[2] = 0; // Specify an empty rectangle
                reply.xclient.data.l[3] = 0;

                if (_glfw.x11.xdnd.format_priority > 0)
                {
                    // Reply that we are ready to copy the dragged data
                    reply.xclient.data.l[1] = 1; // Accept with no rectangle
                    if (_glfw.x11.xdnd.version >= 2)
                        reply.xclient.data.l[4] = _glfw.x11.XdndActionCopy;
                }

                XSendEvent(_glfw.x11.display, _glfw.x11.xdnd.source,
                           False, NoEventMask, &reply);
                XFlush(_glfw.x11.display);
            }

            return;
        }

        case SelectionNotify:
        {
            if (event->xselection.property == _glfw.x11.XdndSelection)
            {
                // The converted data from the drag operation has arrived
                char* data;
                const unsigned long result =
                    _glfwGetWindowPropertyX11(event->xselection.requestor,
                                              event->xselection.property,
                                              event->xselection.target,
                                              (unsigned char**) &data);

                if (result)
                {
                    _glfwInputDrop(window, _glfw.x11.xdnd.format, data, result);
                }

                if (data)
                    XFree(data);

                if (_glfw.x11.xdnd.version >= 2)
                {
                    XEvent reply = { ClientMessage };
                    reply.xclient.window = _glfw.x11.xdnd.source;
                    reply.xclient.message_type = _glfw.x11.XdndFinished;
                    reply.xclient.format = 32;
                    reply.xclient.data.l[0] = window->x11.handle;
                    reply.xclient.data.l[1] = result;
                    reply.xclient.data.l[2] = _glfw.x11.XdndActionCopy;

                    XSendEvent(_glfw.x11.display, _glfw.x11.xdnd.source,
                               False, NoEventMask, &reply);
                    XFlush(_glfw.x11.display);
                }
            }

            return;
        }

        case FocusIn:
        {
            if (event->xfocus.mode == NotifyGrab ||
                event->xfocus.mode == NotifyUngrab)
            {
                // Ignore focus events from popup indicator windows, window menu
                // key chords and window dragging
                return;
            }

            if (window->cursorMode == GLFW_CURSOR_DISABLED)
                disableCursor(window);

            _glfwInputWindowFocus(window, true);
            return;
        }

        case FocusOut:
        {
            if (event->xfocus.mode == NotifyGrab ||
                event->xfocus.mode == NotifyUngrab)
            {
                // Ignore focus events from popup indicator windows, window menu
                // key chords and window dragging
                return;
            }

            if (window->cursorMode == GLFW_CURSOR_DISABLED)
                enableCursor(window);

            if (window->monitor && window->autoIconify)
                _glfwPlatformIconifyWindow(window);

            _glfwInputWindowFocus(window, false);
            return;
        }

        case Expose:
        {
            _glfwInputWindowDamage(window);
            return;
        }

        case PropertyNotify:
        {
            if (event->xproperty.state != PropertyNewValue)
                return;

            if (event->xproperty.atom == _glfw.x11.WM_STATE)
            {
                const int state = getWindowState(window);
                if (state != IconicState && state != NormalState)
                    return;

                const bool iconified = (state == IconicState);
                if (window->x11.iconified != iconified)
                {
                    if (window->monitor)
                    {
                        if (iconified)
                            releaseMonitor(window);
                        else
                            acquireMonitor(window);
                    }

                    window->x11.iconified = iconified;
                    _glfwInputWindowIconify(window, iconified);
                }
            }
            else if (event->xproperty.atom == _glfw.x11.NET_WM_STATE)
            {
                const bool maximized = _glfwPlatformWindowMaximized(window);
                if (window->x11.maximized != maximized)
                {
                    window->x11.maximized = maximized;
                    int width, height;
                    _glfwPlatformGetWindowSize(window, &width, &height);
                    updateNormalHints(window, width, height);
                    _glfwInputWindowMaximize(window, maximized);
                }
            }

            return;
        }

        case DestroyNotify:
            return;
    }
#undef UPDATE_KEYMAP_IF_NEEDED
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

// Retrieve a single window property of the specified type
// Inspired by fghGetWindowProperty from freeglut
//
unsigned long _glfwGetWindowPropertyX11(Window window,
                                        Atom property,
                                        Atom type,
                                        unsigned char** value)
{
    Atom actualType;
    int actualFormat;
    unsigned long itemCount, bytesAfter;

    XGetWindowProperty(_glfw.x11.display,
                       window,
                       property,
                       0,
                       LONG_MAX,
                       False,
                       type,
                       &actualType,
                       &actualFormat,
                       &itemCount,
                       &bytesAfter,
                       value);

    return itemCount;
}

bool _glfwIsVisualTransparentX11(Visual* visual)
{
    if (!_glfw.x11.xrender.available)
        return false;

    XRenderPictFormat* pf = XRenderFindVisualFormat(_glfw.x11.display, visual);
    return pf && pf->direct.alphaMask;
}

// Push contents of our selection to clipboard manager
//
void _glfwPushSelectionToManagerX11(void)
{
    XConvertSelection(_glfw.x11.display,
                      _glfw.x11.CLIPBOARD_MANAGER,
                      _glfw.x11.SAVE_TARGETS,
                      None,
                      _glfw.x11.helperWindowHandle,
                      CurrentTime);

    for (;;)
    {
        XEvent event;

        while (XCheckIfEvent(_glfw.x11.display, &event, isSelectionEvent, NULL))
        {
            switch (event.type)
            {
                case SelectionRequest:
                    handleSelectionRequest(&event);
                    break;

                case SelectionClear:
                    handleSelectionClear(&event);
                    break;

                case SelectionNotify:
                {
                    if (event.xselection.target == _glfw.x11.SAVE_TARGETS)
                    {
                        // This means one of two things; either the selection
                        // was not owned, which means there is no clipboard
                        // manager, or the transfer to the clipboard manager has
                        // completed
                        // In either case, it means we are done here
                        return;
                    }

                    break;
                }
            }
        }

        waitForX11Event(-1);
    }
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

int _glfwPlatformCreateWindow(_GLFWwindow* window, const _GLFWwndconfig* wndconfig, const _GLFWctxconfig* ctxconfig, const _GLFWfbconfig* fbconfig, const GLFWLayerShellConfig *lsc)
{
    Visual* visual = NULL;
    int depth;
    if (lsc) {
        window->x11.layer_shell.is_active = true;
        window->x11.layer_shell.config = *lsc;
    } else window->x11.layer_shell.is_active = false;

    if (ctxconfig->client != GLFW_NO_API)
    {
        if (ctxconfig->source == GLFW_NATIVE_CONTEXT_API)
        {
            if (!_glfwInitGLX())
                return false;
            if (!_glfwChooseVisualGLX(wndconfig, ctxconfig, fbconfig, &visual, &depth))
                return false;
        }
        else if (ctxconfig->source == GLFW_EGL_CONTEXT_API)
        {
            if (!_glfwInitEGL())
                return false;
            if (!_glfwChooseVisualEGL(wndconfig, ctxconfig, fbconfig, &visual, &depth))
                return false;
        }
        else if (ctxconfig->source == GLFW_OSMESA_CONTEXT_API)
        {
            if (!_glfwInitOSMesa())
                return false;
        }
    }

    if (!visual)
    {
        visual = DefaultVisual(_glfw.x11.display, _glfw.x11.screen);
        depth = DefaultDepth(_glfw.x11.display, _glfw.x11.screen);
    }

    if (!createNativeWindow(window, wndconfig, visual, depth))
        return false;

    if (ctxconfig->client != GLFW_NO_API)
    {
        if (ctxconfig->source == GLFW_NATIVE_CONTEXT_API)
        {
            if (!_glfwCreateContextGLX(window, ctxconfig, fbconfig))
                return false;
        }
        else if (ctxconfig->source == GLFW_EGL_CONTEXT_API)
        {
            if (!_glfwCreateContextEGL(window, ctxconfig, fbconfig))
                return false;
        }
        else if (ctxconfig->source == GLFW_OSMESA_CONTEXT_API)
        {
            if (!_glfwCreateContextOSMesa(window, ctxconfig, fbconfig))
                return false;
        }
    }

    if (window->monitor)
    {
        _glfwPlatformShowWindow(window);
        updateWindowMode(window);
        acquireMonitor(window);
    }

    XFlush(_glfw.x11.display);
    return true;
}

void _glfwPlatformDestroyWindow(_GLFWwindow* window)
{
    if (_glfw.x11.disabledCursorWindow == window)
        _glfw.x11.disabledCursorWindow = NULL;

    if (window->monitor)
        releaseMonitor(window);

    if (window->context.destroy)
        window->context.destroy(window);

    if (window->x11.handle)
    {
        XDeleteContext(_glfw.x11.display, window->x11.handle, _glfw.x11.context);
        XUnmapWindow(_glfw.x11.display, window->x11.handle);
        XDestroyWindow(_glfw.x11.display, window->x11.handle);
        window->x11.handle = (Window) 0;
    }

    if (window->x11.colormap)
    {
        XFreeColormap(_glfw.x11.display, window->x11.colormap);
        window->x11.colormap = (Colormap) 0;
    }

    XFlush(_glfw.x11.display);
}

const GLFWLayerShellConfig*
_glfwPlatformGetLayerShellConfig(_GLFWwindow *window) {
    return &window->x11.layer_shell.config;
}

bool
_glfwPlatformSetLayerShellConfig(_GLFWwindow* window, const GLFWLayerShellConfig *value) {
    if (value) window->x11.layer_shell.config = *value;
    WindowGeometry wg = calculate_layer_geometry(window);
    update_wm_hints(window, &wg, NULL);
    return false;
}

void _glfwPlatformSetWindowTitle(_GLFWwindow* window, const char* title)
{
#if defined(X_HAVE_UTF8_STRING)
    Xutf8SetWMProperties(_glfw.x11.display,
                         window->x11.handle,
                         title, title,
                         NULL, 0,
                         NULL, NULL, NULL);
#else
    // This may be a slightly better fallback than using XStoreName and
    // XSetIconName, which always store their arguments using STRING
    XmbSetWMProperties(_glfw.x11.display,
                       window->x11.handle,
                       title, title,
                       NULL, 0,
                       NULL, NULL, NULL);
#endif

    XChangeProperty(_glfw.x11.display,  window->x11.handle,
                    _glfw.x11.NET_WM_NAME, _glfw.x11.UTF8_STRING, 8,
                    PropModeReplace,
                    (unsigned char*) title, strlen(title));

    XChangeProperty(_glfw.x11.display,  window->x11.handle,
                    _glfw.x11.NET_WM_ICON_NAME, _glfw.x11.UTF8_STRING, 8,
                    PropModeReplace,
                    (unsigned char*) title, strlen(title));

    XFlush(_glfw.x11.display);
}

void _glfwPlatformSetWindowIcon(_GLFWwindow* window,
                                int count, const GLFWimage* images)
{
    if (count)
    {
        int i, j, longCount = 0;

        for (i = 0;  i < count;  i++)
            longCount += 2 + images[i].width * images[i].height;

        unsigned long* icon = calloc(longCount, sizeof(unsigned long));
        unsigned long* target = icon;

        for (i = 0;  i < count;  i++)
        {
            *target++ = images[i].width;
            *target++ = images[i].height;

            for (j = 0;  j < images[i].width * images[i].height;  j++)
            {
                unsigned char *p = images->pixels + j * 4;
                const unsigned char r = *p++, g = *p++, b = *p++, a = *p++;
                *target++ = a << 24 | (r << 16) | (g << 8) | b;
            }
        }

        XChangeProperty(_glfw.x11.display, window->x11.handle,
                        _glfw.x11.NET_WM_ICON,
                        XA_CARDINAL, 32,
                        PropModeReplace,
                        (unsigned char*) icon,
                        longCount);

        free(icon);
    }
    else
    {
        XDeleteProperty(_glfw.x11.display, window->x11.handle,
                        _glfw.x11.NET_WM_ICON);
    }

    XFlush(_glfw.x11.display);
}

void _glfwPlatformGetWindowPos(_GLFWwindow* window, int* xpos, int* ypos)
{
    Window dummy;
    int x = 0, y = 0;

    _glfwGrabErrorHandlerX11();
    XTranslateCoordinates(_glfw.x11.display, window->x11.handle, _glfw.x11.root,
                          0, 0, &x, &y, &dummy);
    _glfwReleaseErrorHandlerX11();
    if (_glfw.x11.errorCode != Success)
        _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Failed to get window position");

    if (xpos)
        *xpos = x;
    if (ypos)
        *ypos = y;
}

void _glfwPlatformSetWindowPos(_GLFWwindow* window, int xpos, int ypos)
{
    // HACK: Explicitly setting PPosition to any value causes some WMs, notably
    //       Compiz and Metacity, to honor the position of unmapped windows
    if (!_glfwPlatformWindowVisible(window))
    {
        long supplied;
        XSizeHints* hints = XAllocSizeHints();

        if (XGetWMNormalHints(_glfw.x11.display, window->x11.handle, hints, &supplied))
        {
            hints->flags |= PPosition;
            hints->x = hints->y = 0;

            XSetWMNormalHints(_glfw.x11.display, window->x11.handle, hints);
        }

        XFree(hints);
    }

    XMoveWindow(_glfw.x11.display, window->x11.handle, xpos, ypos);
    XFlush(_glfw.x11.display);
}

void _glfwPlatformGetWindowSize(_GLFWwindow* window, int* width, int* height)
{
    XWindowAttributes attribs;
    XGetWindowAttributes(_glfw.x11.display, window->x11.handle, &attribs);

    if (width)
        *width = attribs.width;
    if (height)
        *height = attribs.height;
}

void _glfwPlatformSetWindowSize(_GLFWwindow* window, int width, int height)
{
    if (window->monitor)
    {
        if (window->monitor->window == window)
            acquireMonitor(window);
    }
    else
    {
        if (!window->resizable)
            updateNormalHints(window, width, height);

        XResizeWindow(_glfw.x11.display, window->x11.handle, width, height);
    }

    XFlush(_glfw.x11.display);
}

void _glfwPlatformSetWindowSizeLimits(_GLFWwindow* window,
                                      int minwidth UNUSED, int minheight UNUSED,
                                      int maxwidth UNUSED, int maxheight UNUSED)
{
    int width, height;
    _glfwPlatformGetWindowSize(window, &width, &height);
    updateNormalHints(window, width, height);
    XFlush(_glfw.x11.display);
}

void _glfwPlatformSetWindowAspectRatio(_GLFWwindow* window, int numer UNUSED, int denom UNUSED)
{
    int width, height;
    _glfwPlatformGetWindowSize(window, &width, &height);
    updateNormalHints(window, width, height);
    XFlush(_glfw.x11.display);
}

void _glfwPlatformSetWindowSizeIncrements(_GLFWwindow* window, int widthincr UNUSED, int heightincr UNUSED)
{
    int width, height;
    _glfwPlatformGetWindowSize(window, &width, &height);
    updateNormalHints(window, width, height);
    XFlush(_glfw.x11.display);
}

void _glfwPlatformGetFramebufferSize(_GLFWwindow* window, int* width, int* height)
{
    _glfwPlatformGetWindowSize(window, width, height);
}

void _glfwPlatformGetWindowFrameSize(_GLFWwindow* window,
                                     int* left, int* top,
                                     int* right, int* bottom)
{
    long* extents = NULL;

    if (window->monitor || !window->decorated)
        return;

    if (_glfw.x11.NET_FRAME_EXTENTS == None)
        return;

    if (!_glfwPlatformWindowVisible(window) &&
        _glfw.x11.NET_REQUEST_FRAME_EXTENTS)
    {
        XEvent event;

        // Ensure _NET_FRAME_EXTENTS is set, allowing glfwGetWindowFrameSize to
        // function before the window is mapped
        sendEventToWM(window, _glfw.x11.NET_REQUEST_FRAME_EXTENTS,
                      0, 0, 0, 0, 0);

        // HACK: Use a timeout because earlier versions of some window managers
        //       (at least Unity, Fluxbox and Xfwm) failed to send the reply
        //       They have been fixed but broken versions are still in the wild
        //       If you are affected by this and your window manager is NOT
        //       listed above, PLEASE report it to their and our issue trackers
        while (!XCheckIfEvent(_glfw.x11.display,
                              &event,
                              isFrameExtentsEvent,
                              (XPointer) window))
        {
            if (!waitForX11Event(ms_to_monotonic_t(500ll)))
            {
                _glfwInputError(GLFW_PLATFORM_ERROR,
                                "X11: The window manager has a broken _NET_REQUEST_FRAME_EXTENTS implementation; please report this issue");
                return;
            }
        }
    }

    if (_glfwGetWindowPropertyX11(window->x11.handle,
                                  _glfw.x11.NET_FRAME_EXTENTS,
                                  XA_CARDINAL,
                                  (unsigned char**) &extents) == 4)
    {
        if (left)
            *left = extents[0];
        if (top)
            *top = extents[2];
        if (right)
            *right = extents[1];
        if (bottom)
            *bottom = extents[3];
    }

    if (extents)
        XFree(extents);
}

void _glfwPlatformGetWindowContentScale(_GLFWwindow* window UNUSED,
                                        float* xscale, float* yscale)
{
    if (xscale)
        *xscale = _glfw.x11.contentScaleX;
    if (yscale)
        *yscale = _glfw.x11.contentScaleY;
}

monotonic_t _glfwPlatformGetDoubleClickInterval(_GLFWwindow* window UNUSED)
{
    return ms_to_monotonic_t(500ll);
}

void _glfwPlatformIconifyWindow(_GLFWwindow* window)
{
    XIconifyWindow(_glfw.x11.display, window->x11.handle, _glfw.x11.screen);
    XFlush(_glfw.x11.display);
}

void _glfwPlatformRestoreWindow(_GLFWwindow* window)
{
    if (_glfwPlatformWindowIconified(window))
    {
        XMapWindow(_glfw.x11.display, window->x11.handle);
        waitForVisibilityNotify(window);
    }
    else if (_glfwPlatformWindowVisible(window))
    {
        if (_glfw.x11.NET_WM_STATE &&
            _glfw.x11.NET_WM_STATE_MAXIMIZED_VERT &&
            _glfw.x11.NET_WM_STATE_MAXIMIZED_HORZ)
        {
            sendEventToWM(window,
                          _glfw.x11.NET_WM_STATE,
                          _NET_WM_STATE_REMOVE,
                          _glfw.x11.NET_WM_STATE_MAXIMIZED_VERT,
                          _glfw.x11.NET_WM_STATE_MAXIMIZED_HORZ,
                          1, 0);
        }
    }

    XFlush(_glfw.x11.display);
}

void _glfwPlatformMaximizeWindow(_GLFWwindow* window)
{
    if (!_glfw.x11.NET_WM_STATE ||
        !_glfw.x11.NET_WM_STATE_MAXIMIZED_VERT ||
        !_glfw.x11.NET_WM_STATE_MAXIMIZED_HORZ)
    {
        return;
    }

    if (_glfwPlatformWindowVisible(window))
    {
        sendEventToWM(window,
                    _glfw.x11.NET_WM_STATE,
                    _NET_WM_STATE_ADD,
                    _glfw.x11.NET_WM_STATE_MAXIMIZED_VERT,
                    _glfw.x11.NET_WM_STATE_MAXIMIZED_HORZ,
                    1, 0);
    }
    else
    {
        Atom* states = NULL;
        unsigned long count =
            _glfwGetWindowPropertyX11(window->x11.handle,
                                      _glfw.x11.NET_WM_STATE,
                                      XA_ATOM,
                                      (unsigned char**) &states);

        // NOTE: We don't check for failure as this property may not exist yet
        //       and that's fine (and we'll create it implicitly with append)

        Atom missing[2] =
        {
            _glfw.x11.NET_WM_STATE_MAXIMIZED_VERT,
            _glfw.x11.NET_WM_STATE_MAXIMIZED_HORZ
        };
        unsigned long missingCount = 2;

        for (unsigned long i = 0;  i < count;  i++)
        {
            for (unsigned long j = 0;  j < missingCount;  j++)
            {
                if (states[i] == missing[j])
                {
                    missing[j] = missing[missingCount - 1];
                    missingCount--;
                }
            }
        }

        if (states)
            XFree(states);

        if (!missingCount)
            return;

        XChangeProperty(_glfw.x11.display, window->x11.handle,
                        _glfw.x11.NET_WM_STATE, XA_ATOM, 32,
                        PropModeAppend,
                        (unsigned char*) missing,
                        missingCount);
    }

    XFlush(_glfw.x11.display);
}

void _glfwPlatformShowWindow(_GLFWwindow* window)
{
    if (_glfwPlatformWindowVisible(window))
        return;

    XMapWindow(_glfw.x11.display, window->x11.handle);
    // without this floating window position is incorrect on KDE
    if (window->x11.layer_shell.is_active) {
        WindowGeometry wg = calculate_layer_geometry(window);
        _glfwPlatformSetWindowPos(window, wg.x, wg.y);
    }
    waitForVisibilityNotify(window);
}

void _glfwPlatformHideWindow(_GLFWwindow* window)
{
    XUnmapWindow(_glfw.x11.display, window->x11.handle);
    XFlush(_glfw.x11.display);
}

void _glfwPlatformRequestWindowAttention(_GLFWwindow* window)
{
    if (!_glfw.x11.NET_WM_STATE || !_glfw.x11.NET_WM_STATE_DEMANDS_ATTENTION)
        return;

    sendEventToWM(window,
                  _glfw.x11.NET_WM_STATE,
                  _NET_WM_STATE_ADD,
                  _glfw.x11.NET_WM_STATE_DEMANDS_ATTENTION,
                  0, 1, 0);
}

int _glfwPlatformWindowBell(_GLFWwindow* window)
{
    return XkbBell(_glfw.x11.display, window->x11.handle, 100, (Atom)0) ? true : false;
}

void _glfwPlatformFocusWindow(_GLFWwindow* window)
{
    if (_glfw.x11.NET_ACTIVE_WINDOW)
        sendEventToWM(window, _glfw.x11.NET_ACTIVE_WINDOW, 1, 0, 0, 0, 0);
    else if (_glfwPlatformWindowVisible(window))
    {
        XRaiseWindow(_glfw.x11.display, window->x11.handle);
        XSetInputFocus(_glfw.x11.display, window->x11.handle,
                       RevertToParent, CurrentTime);
    }

    XFlush(_glfw.x11.display);
}

void _glfwPlatformSetWindowMonitor(_GLFWwindow* window,
                                   _GLFWmonitor* monitor,
                                   int xpos, int ypos,
                                   int width, int height,
                                   int refreshRate UNUSED)
{
    if (window->monitor == monitor)
    {
        if (monitor)
        {
            if (monitor->window == window)
                acquireMonitor(window);
        }
        else
        {
            if (!window->resizable)
                updateNormalHints(window, width, height);

            XMoveResizeWindow(_glfw.x11.display, window->x11.handle,
                              xpos, ypos, width, height);
        }

        XFlush(_glfw.x11.display);
        return;
    }

    if (window->monitor)
        releaseMonitor(window);

    _glfwInputWindowMonitor(window, monitor);
    updateNormalHints(window, width, height);

    if (window->monitor)
    {
        if (!_glfwPlatformWindowVisible(window))
        {
            XMapRaised(_glfw.x11.display, window->x11.handle);
            waitForVisibilityNotify(window);
        }

        updateWindowMode(window);
        acquireMonitor(window);
    }
    else
    {
        updateWindowMode(window);
        XMoveResizeWindow(_glfw.x11.display, window->x11.handle,
                          xpos, ypos, width, height);
    }

    XFlush(_glfw.x11.display);
}

int _glfwPlatformWindowFocused(_GLFWwindow* window)
{
    Window focused;
    int state;

    XGetInputFocus(_glfw.x11.display, &focused, &state);
    return window->x11.handle == focused;
}

int _glfwPlatformWindowOccluded(_GLFWwindow* window UNUSED)
{
    return false;
}

int _glfwPlatformWindowIconified(_GLFWwindow* window)
{
    return getWindowState(window) == IconicState;
}

int _glfwPlatformWindowVisible(_GLFWwindow* window)
{
    XWindowAttributes wa;
    XGetWindowAttributes(_glfw.x11.display, window->x11.handle, &wa);
    return wa.map_state == IsViewable;
}

int _glfwPlatformWindowMaximized(_GLFWwindow* window)
{
    Atom* states;
    unsigned long i;
    bool maximized = false;

    if (!_glfw.x11.NET_WM_STATE ||
        !_glfw.x11.NET_WM_STATE_MAXIMIZED_VERT ||
        !_glfw.x11.NET_WM_STATE_MAXIMIZED_HORZ)
    {
        return maximized;
    }

    const unsigned long count =
        _glfwGetWindowPropertyX11(window->x11.handle,
                                  _glfw.x11.NET_WM_STATE,
                                  XA_ATOM,
                                  (unsigned char**) &states);

    for (i = 0;  i < count;  i++)
    {
        if (states[i] == _glfw.x11.NET_WM_STATE_MAXIMIZED_VERT ||
            states[i] == _glfw.x11.NET_WM_STATE_MAXIMIZED_HORZ)
        {
            maximized = true;
            break;
        }
    }

    if (states)
        XFree(states);

    return maximized;
}

int _glfwPlatformWindowHovered(_GLFWwindow* window)
{
    Window w = _glfw.x11.root;
    while (w)
    {
        Window root;
        int rootX, rootY, childX, childY;
        unsigned int mask;

        _glfwGrabErrorHandlerX11();

        const Bool result = XQueryPointer(_glfw.x11.display, w,
                                          &root, &w, &rootX, &rootY,
                                          &childX, &childY, &mask);

        _glfwReleaseErrorHandlerX11();

        if (_glfw.x11.errorCode == BadWindow)
            w = _glfw.x11.root;
        else if (!result)
            return false;
        else if (w == window->x11.handle)
            return true;
    }

    return false;
}

int _glfwPlatformFramebufferTransparent(_GLFWwindow* window)
{
    if (!window->x11.transparent)
        return false;

    return XGetSelectionOwner(_glfw.x11.display, _glfw.x11.NET_WM_CM_Sx) != None;
}

void _glfwPlatformSetWindowResizable(_GLFWwindow* window, bool enabled UNUSED)
{
    int width, height;
    _glfwPlatformGetWindowSize(window, &width, &height);
    updateNormalHints(window, width, height);
}

void _glfwPlatformSetWindowDecorated(_GLFWwindow* window, bool enabled)
{
    struct
    {
        unsigned long flags;
        unsigned long functions;
        unsigned long decorations;
        long input_mode;
        unsigned long status;
    } hints = {0};

    hints.flags = MWM_HINTS_DECORATIONS;
    hints.decorations = enabled ? MWM_DECOR_ALL : 0;

    XChangeProperty(_glfw.x11.display, window->x11.handle,
                    _glfw.x11.MOTIF_WM_HINTS,
                    _glfw.x11.MOTIF_WM_HINTS, 32,
                    PropModeReplace,
                    (unsigned char*) &hints,
                    sizeof(hints) / sizeof(long));
}

void _glfwPlatformSetWindowFloating(_GLFWwindow* window, bool enabled)
{
    if (!_glfw.x11.NET_WM_STATE || !_glfw.x11.NET_WM_STATE_ABOVE)
        return;

    if (_glfwPlatformWindowVisible(window))
    {
        const long action = enabled ? _NET_WM_STATE_ADD : _NET_WM_STATE_REMOVE;
        sendEventToWM(window,
                      _glfw.x11.NET_WM_STATE,
                      action,
                      _glfw.x11.NET_WM_STATE_ABOVE,
                      0, 1, 0);
    }
    else
    {
        Atom* states = NULL;
        unsigned long i, count;

        count = _glfwGetWindowPropertyX11(window->x11.handle,
                                          _glfw.x11.NET_WM_STATE,
                                          XA_ATOM,
                                          (unsigned char**) &states);

        // NOTE: We don't check for failure as this property may not exist yet
        //       and that's fine (and we'll create it implicitly with append)

        if (enabled)
        {
            for (i = 0;  i < count;  i++)
            {
                if (states[i] == _glfw.x11.NET_WM_STATE_ABOVE)
                    break;
            }

            if (i < count)
                return;

            XChangeProperty(_glfw.x11.display, window->x11.handle,
                            _glfw.x11.NET_WM_STATE, XA_ATOM, 32,
                            PropModeAppend,
                            (unsigned char*) &_glfw.x11.NET_WM_STATE_ABOVE,
                            1);
        }
        else if (states)
        {
            for (i = 0;  i < count;  i++)
            {
                if (states[i] == _glfw.x11.NET_WM_STATE_ABOVE)
                    break;
            }

            if (i == count)
                return;

            states[i] = states[count - 1];
            count--;

            XChangeProperty(_glfw.x11.display, window->x11.handle,
                            _glfw.x11.NET_WM_STATE, XA_ATOM, 32,
                            PropModeReplace, (unsigned char*) states, count);
        }

        if (states)
            XFree(states);
    }

    XFlush(_glfw.x11.display);
}

void _glfwPlatformSetWindowMousePassthrough(_GLFWwindow* window, bool enabled)
{
    if (!_glfw.x11.xshape.available)
        return;

    if (enabled)
    {
        Region region = XCreateRegion();
        XShapeCombineRegion(_glfw.x11.display, window->x11.handle,
                            ShapeInput, 0, 0, region, ShapeSet);
        XDestroyRegion(region);
    }
    else
    {
        XShapeCombineMask(_glfw.x11.display, window->x11.handle,
                          ShapeInput, 0, 0, None, ShapeSet);
    }
}

float _glfwPlatformGetWindowOpacity(_GLFWwindow* window)
{
    float opacity = 1.f;

    if (XGetSelectionOwner(_glfw.x11.display, _glfw.x11.NET_WM_CM_Sx))
    {
        CARD32* value = NULL;

        if (_glfwGetWindowPropertyX11(window->x11.handle,
                                      _glfw.x11.NET_WM_WINDOW_OPACITY,
                                      XA_CARDINAL,
                                      (unsigned char**) &value))
        {
            opacity = (float) (*value / (double) 0xffffffffu);
        }

        if (value)
            XFree(value);
    }

    return opacity;
}

void _glfwPlatformSetWindowOpacity(_GLFWwindow* window, float opacity)
{
    const CARD32 value = (CARD32) (0xffffffffu * (double) opacity);
    XChangeProperty(_glfw.x11.display, window->x11.handle,
                    _glfw.x11.NET_WM_WINDOW_OPACITY, XA_CARDINAL, 32,
                    PropModeReplace, (unsigned char*) &value, 1);
}

static unsigned
dispatch_x11_queued_events(int num_events) {
    unsigned dispatched = num_events > 0 ? num_events : 0;
    while (num_events-- > 0) {
        XEvent event;
        XNextEvent(_glfw.x11.display, &event);
        processEvent(&event);
    }
    return dispatched;
}

static unsigned
_glfwDispatchX11Events(void) {
    _GLFWwindow* window;
    unsigned dispatched = 0;

#if defined(__linux__)
    if (_glfw.joysticksInitialized)
        _glfwDetectJoystickConnectionLinux();
#endif
    dispatched += dispatch_x11_queued_events(XEventsQueued(_glfw.x11.display, QueuedAfterFlush));

    window = _glfw.x11.disabledCursorWindow;
    if (window)
    {
        int width, height;
        _glfwPlatformGetWindowSize(window, &width, &height);

        // NOTE: Re-center the cursor only if it has moved since the last call,
        //       to avoid breaking glfwWaitEvents with MotionNotify
        if (window->x11.lastCursorPosX != width / 2 ||
            window->x11.lastCursorPosY != height / 2)
        {
            _glfwPlatformSetCursorPos(window, width / 2.f, height / 2.f);
        }
    }

    XFlush(_glfw.x11.display);
    // XFlush can cause events to be queued, we don't use QueuedAfterFlush here
    // as something might have inserted events into the queue, but we want to guarantee
    // a flush.
    dispatched += dispatch_x11_queued_events(XEventsQueued(_glfw.x11.display, QueuedAlready));
    return dispatched;
}

void _glfwPlatformSetRawMouseMotion(_GLFWwindow *window, bool enabled)
{
    if (!_glfw.x11.xi.available)
        return;

    if (_glfw.x11.disabledCursorWindow != window)
        return;

    if (enabled)
        enableRawMouseMotion(window);
    else
        disableRawMouseMotion(window);
}

bool _glfwPlatformRawMouseMotionSupported(void)
{
    return _glfw.x11.xi.available;
}

void _glfwPlatformPollEvents(void)
{
    _glfwDispatchX11Events();
    handleEvents(0);
}

void _glfwPlatformWaitEvents(void)
{
    monotonic_t timeout = _glfwDispatchX11Events() ? 0 : -1;
    handleEvents(timeout);
}

void _glfwPlatformWaitEventsTimeout(monotonic_t timeout)
{
    if (_glfwDispatchX11Events()) timeout = 0;
    handleEvents(timeout);
}

void _glfwPlatformPostEmptyEvent(void)
{
    wakeupEventLoop(&_glfw.x11.eventLoopData);
}

void _glfwPlatformGetCursorPos(_GLFWwindow* window, double* xpos, double* ypos)
{
    Window root, child;
    int rootX, rootY, childX, childY;
    unsigned int mask;

    XQueryPointer(_glfw.x11.display, window->x11.handle,
                  &root, &child,
                  &rootX, &rootY, &childX, &childY,
                  &mask);

    if (xpos)
        *xpos = childX;
    if (ypos)
        *ypos = childY;
}

void _glfwPlatformSetCursorPos(_GLFWwindow* window, double x, double y)
{
    // Store the new position so it can be recognized later
    window->x11.warpCursorPosX = (int) x;
    window->x11.warpCursorPosY = (int) y;

    XWarpPointer(_glfw.x11.display, None, window->x11.handle,
                 0,0,0,0, (int) x, (int) y);
    XFlush(_glfw.x11.display);
}

void _glfwPlatformSetCursorMode(_GLFWwindow* window, int mode)
{
    if (mode == GLFW_CURSOR_DISABLED)
    {
        if (_glfwPlatformWindowFocused(window))
            disableCursor(window);
    }
    else if (_glfw.x11.disabledCursorWindow == window)
        enableCursor(window);
    else
        updateCursorImage(window);

    XFlush(_glfw.x11.display);
}

const char* _glfwPlatformGetNativeKeyName(int native_key)
{

    return glfw_xkb_keysym_name(native_key);
}

int _glfwPlatformGetNativeKeyForKey(uint32_t key)
{
    return glfw_xkb_sym_for_key(key);
}

int _glfwPlatformCreateCursor(_GLFWcursor* cursor,
                              const GLFWimage* image,
                              int xhot, int yhot, int count UNUSED)
{
    cursor->x11.handle = _glfwCreateCursorX11(image, xhot, yhot);
    if (!cursor->x11.handle)
        return false;

    return true;
}

static int
set_cursor_from_font(_GLFWcursor* cursor, int native) {
    cursor->x11.handle = XCreateFontCursor(_glfw.x11.display, native);
    if (!cursor->x11.handle) {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "X11: Failed to create standard cursor");
        return false;
    }
    return true;
}

static bool
try_cursor_names(_GLFWcursor *cursor, int arg_count, ...) {
    va_list ap;
    va_start(ap, arg_count);
    const char *first_name = "";
    for (int i = 0; i < arg_count; i++) {
        const char *name = va_arg(ap, const char *);
        first_name = name;
        cursor->x11.handle = XcursorLibraryLoadCursor(_glfw.x11.display, name);
        if (cursor->x11.handle) break;
    }
    va_end(ap);
    if (!cursor->x11.handle) {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "X11: Failed to load standard cursor: %s with %d aliases via Xcursor library", first_name, arg_count);
        return false;
    }
    return true;
}


int _glfwPlatformCreateStandardCursor(_GLFWcursor* cursor, GLFWCursorShape shape)
{
    switch(shape) {
        /* start glfw to xc mapping (auto generated by gen-key-constants.py do not edit) */
        case GLFW_DEFAULT_CURSOR: return set_cursor_from_font(cursor, XC_left_ptr);
        case GLFW_TEXT_CURSOR: return set_cursor_from_font(cursor, XC_xterm);
        case GLFW_POINTER_CURSOR: return set_cursor_from_font(cursor, XC_hand2);
        case GLFW_HELP_CURSOR: return set_cursor_from_font(cursor, XC_question_arrow);
        case GLFW_WAIT_CURSOR: return set_cursor_from_font(cursor, XC_clock);
        case GLFW_PROGRESS_CURSOR: return try_cursor_names(cursor, 3, "progress", "half-busy", "left_ptr_watch");
        case GLFW_CROSSHAIR_CURSOR: return set_cursor_from_font(cursor, XC_tcross);
        case GLFW_CELL_CURSOR: return set_cursor_from_font(cursor, XC_plus);
        case GLFW_VERTICAL_TEXT_CURSOR: return try_cursor_names(cursor, 1, "vertical-text");
        case GLFW_MOVE_CURSOR: return set_cursor_from_font(cursor, XC_fleur);
        case GLFW_E_RESIZE_CURSOR: return set_cursor_from_font(cursor, XC_right_side);
        case GLFW_NE_RESIZE_CURSOR: return set_cursor_from_font(cursor, XC_top_right_corner);
        case GLFW_NW_RESIZE_CURSOR: return set_cursor_from_font(cursor, XC_top_left_corner);
        case GLFW_N_RESIZE_CURSOR: return set_cursor_from_font(cursor, XC_top_side);
        case GLFW_SE_RESIZE_CURSOR: return set_cursor_from_font(cursor, XC_bottom_right_corner);
        case GLFW_SW_RESIZE_CURSOR: return set_cursor_from_font(cursor, XC_bottom_left_corner);
        case GLFW_S_RESIZE_CURSOR: return set_cursor_from_font(cursor, XC_bottom_side);
        case GLFW_W_RESIZE_CURSOR: return set_cursor_from_font(cursor, XC_left_side);
        case GLFW_EW_RESIZE_CURSOR: return set_cursor_from_font(cursor, XC_sb_h_double_arrow);
        case GLFW_NS_RESIZE_CURSOR: return set_cursor_from_font(cursor, XC_sb_v_double_arrow);
        case GLFW_NESW_RESIZE_CURSOR: return try_cursor_names(cursor, 3, "nesw-resize", "size_bdiag", "size-bdiag");
        case GLFW_NWSE_RESIZE_CURSOR: return try_cursor_names(cursor, 3, "nwse-resize", "size_fdiag", "size-fdiag");
        case GLFW_ZOOM_IN_CURSOR: return try_cursor_names(cursor, 2, "zoom-in", "zoom_in");
        case GLFW_ZOOM_OUT_CURSOR: return try_cursor_names(cursor, 2, "zoom-out", "zoom_out");
        case GLFW_ALIAS_CURSOR: return try_cursor_names(cursor, 1, "dnd-link");
        case GLFW_COPY_CURSOR: return try_cursor_names(cursor, 1, "dnd-copy");
        case GLFW_NOT_ALLOWED_CURSOR: return try_cursor_names(cursor, 3, "not-allowed", "forbidden", "crossed_circle");
        case GLFW_NO_DROP_CURSOR: return try_cursor_names(cursor, 2, "no-drop", "dnd-no-drop");
        case GLFW_GRAB_CURSOR: return set_cursor_from_font(cursor, XC_hand1);
        case GLFW_GRABBING_CURSOR: return try_cursor_names(cursor, 3, "grabbing", "closedhand", "dnd-none");
/* end glfw to xc mapping */
        case GLFW_INVALID_CURSOR: return false;
    }
    return false;
}

void _glfwPlatformDestroyCursor(_GLFWcursor* cursor)
{
    if (cursor->x11.handle)
        XFreeCursor(_glfw.x11.display, cursor->x11.handle);
}

void _glfwPlatformSetCursor(_GLFWwindow* window, _GLFWcursor* cursor UNUSED)
{
    if (window->cursorMode == GLFW_CURSOR_NORMAL)
    {
        updateCursorImage(window);
        XFlush(_glfw.x11.display);
    }
}

static MimeAtom atom_for_mime(const char *mime) {
    for (size_t i = 0; i < _glfw.x11.mime_atoms.sz; i++) {
        MimeAtom ma = _glfw.x11.mime_atoms.array[i];
        if (strcmp(ma.mime, mime) == 0) {
            return ma;
        }
    }
    MimeAtom ma = {.mime=_glfw_strdup(mime), .atom=XInternAtom(_glfw.x11.display, mime, 0)};
    if (_glfw.x11.mime_atoms.capacity < _glfw.x11.mime_atoms.sz + 1) {
        _glfw.x11.mime_atoms.capacity += 32;
        _glfw.x11.mime_atoms.array = realloc(_glfw.x11.mime_atoms.array, _glfw.x11.mime_atoms.capacity * sizeof(_glfw.x11.mime_atoms.array[0]));
    }
    _glfw.x11.mime_atoms.array[_glfw.x11.mime_atoms.sz++] = ma;
    return ma;
}

void _glfwPlatformSetClipboard(GLFWClipboardType t) {
    Atom which = None;
    _GLFWClipboardData *cd = NULL;
    AtomArray *aa = NULL;
    switch (t) {
        case GLFW_CLIPBOARD: which = _glfw.x11.CLIPBOARD; cd = &_glfw.clipboard; aa = &_glfw.x11.clipboard_atoms; break;
        case GLFW_PRIMARY_SELECTION: which = _glfw.x11.PRIMARY; cd = &_glfw.primary; aa = &_glfw.x11.primary_atoms; break;
    }
    XSetSelectionOwner(_glfw.x11.display, which, _glfw.x11.helperWindowHandle, CurrentTime);
    if (XGetSelectionOwner(_glfw.x11.display, which) != _glfw.x11.helperWindowHandle) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "X11: Failed to become owner of clipboard selection");
    }
    if (aa->capacity < cd->num_mime_types + 32) {
        aa->capacity = cd->num_mime_types + 32;
        aa->array = reallocarray(aa->array, aa->capacity, sizeof(aa->array[0]));
    }
    aa->sz = 0;
    for (size_t i = 0; i < cd->num_mime_types; i++) {
        MimeAtom *a = aa->array + aa->sz++;
        *a = atom_for_mime(cd->mime_types[i]);
        if (strcmp(cd->mime_types[i], "text/plain") == 0) {
            a = aa->array + aa->sz++;
            a->atom = _glfw.x11.UTF8_STRING;
            a->mime = "text/plain";
        }
    }
}

typedef struct chunked_writer {
    char *buf; size_t sz, cap;
    bool is_self_offer;
} chunked_writer;

static bool
write_chunk(void *object, const char *data, size_t sz) {
    chunked_writer *cw = object;
    if (data) {
        if (cw->cap < cw->sz + sz) {
            cw->cap = MAX(cw->cap * 2, cw->sz + 8*sz);
            cw->buf = realloc(cw->buf, cw->cap * sizeof(cw->buf[0]));
        }
        memcpy(cw->buf + cw->sz, data, sz);
        cw->sz += sz;
    } else if (sz == 1) cw->is_self_offer = true;
    return true;
}

static void
get_available_mime_types(Atom which_clipboard, GLFWclipboardwritedatafun write_data, void *object) {
    chunked_writer cw = {0};
    getSelectionString(which_clipboard, &_glfw.x11.TARGETS, 1, write_chunk, &cw, false);
    if (cw.is_self_offer) {
        write_data(object, NULL, 1);
        return;
    }
    size_t count = 0;
    bool ok = true;
    if (cw.buf) {
        Atom *atoms = (Atom*)cw.buf;
        count = cw.sz / sizeof(Atom);
        char **names = calloc(count, sizeof(char*));
        get_atom_names(atoms, count, names);
        for (size_t i = 0; i < count; i++) {
            if (strchr(names[i], '/')) {
                if (ok) ok = write_data(object, names[i], strlen(names[i]));
            } else {
                if (atoms[i] == _glfw.x11.UTF8_STRING || atoms[i] == XA_STRING) {
                    if (ok) ok = write_data(object, "text/plain", strlen("text/plain"));
                }
            }
            XFree(names[i]);
        }
        free(cw.buf);
        free(names);
    }
}

void
_glfwPlatformGetClipboard(GLFWClipboardType clipboard_type, const char* mime_type, GLFWclipboardwritedatafun write_data, void *object) {
    Atom atoms[4], which = clipboard_type == GLFW_PRIMARY_SELECTION ? _glfw.x11.PRIMARY : _glfw.x11.CLIPBOARD;
    if (mime_type == NULL) {
        get_available_mime_types(which, write_data, object);
        return;
    }
    size_t count = 0;
    if (strcmp(mime_type, "text/plain") == 0) {
        // UTF8_STRING is what xclip uses by default, and there are people out there that expect to be able to paste from it with a single read operation. See https://github.com/kovidgoyal/kitty/issues/5842
        // Also ancient versions of GNOME use DOS line endings even for text/plain;charset=utf-8. See https://github.com/kovidgoyal/kitty/issues/5528#issuecomment-1325348218
        atoms[count++] = _glfw.x11.UTF8_STRING;
        // we need to do this because GTK/GNOME is moronic they convert text/plain to DOS line endings, see
        // https://gitlab.gnome.org/GNOME/gtk/-/issues/2307
        atoms[count++] = atom_for_mime("text/plain;charset=utf-8").atom;
        atoms[count++] = atom_for_mime("text/plain").atom;
        atoms[count++] = XA_STRING;
    } else {
        atoms[count++] = atom_for_mime(mime_type).atom;
    }
    getSelectionString(which, atoms, count, write_data, object, true);
}

EGLenum _glfwPlatformGetEGLPlatform(EGLint** attribs)
{
    if (_glfw.egl.ANGLE_platform_angle)
    {
        int type = 0;

        if (_glfw.egl.ANGLE_platform_angle_opengl)
        {
            if (_glfw.hints.init.angleType == GLFW_ANGLE_PLATFORM_TYPE_OPENGL)
                type = EGL_PLATFORM_ANGLE_TYPE_OPENGL_ANGLE;
        }

        if (_glfw.egl.ANGLE_platform_angle_vulkan)
        {
            if (_glfw.hints.init.angleType == GLFW_ANGLE_PLATFORM_TYPE_VULKAN)
                type = EGL_PLATFORM_ANGLE_TYPE_VULKAN_ANGLE;
        }

        if (type)
        {
            *attribs = calloc(5, sizeof(EGLint));
            (*attribs)[0] = EGL_PLATFORM_ANGLE_TYPE_ANGLE;
            (*attribs)[1] = type;
            (*attribs)[2] = EGL_PLATFORM_ANGLE_NATIVE_PLATFORM_TYPE_ANGLE;
            (*attribs)[3] = EGL_PLATFORM_X11_EXT;
            (*attribs)[4] = EGL_NONE;
            return EGL_PLATFORM_ANGLE_ANGLE;
        }
    }

    if (_glfw.egl.EXT_platform_base && _glfw.egl.EXT_platform_x11)
        return EGL_PLATFORM_X11_EXT;

    return 0;
}

EGLNativeDisplayType _glfwPlatformGetEGLNativeDisplay(void)
{
    return _glfw.x11.display;
}

EGLNativeWindowType _glfwPlatformGetEGLNativeWindow(_GLFWwindow* window)
{
    if (_glfw.egl.platform)
        return &window->x11.handle;
    else
        return (EGLNativeWindowType) window->x11.handle;
}

void _glfwPlatformGetRequiredInstanceExtensions(char** extensions)
{
    if (!_glfw.vk.KHR_surface)
        return;

    if (!_glfw.vk.KHR_xcb_surface)
    {
        if (!_glfw.vk.KHR_xlib_surface)
            return;
    }

    extensions[0] = "VK_KHR_surface";

    // NOTE: VK_KHR_xcb_surface is preferred due to some early ICDs exposing but
    //       not correctly implementing VK_KHR_xlib_surface
    if (_glfw.vk.KHR_xcb_surface)
        extensions[1] = "VK_KHR_xcb_surface";
    else
        extensions[1] = "VK_KHR_xlib_surface";
}

int _glfwPlatformGetPhysicalDevicePresentationSupport(VkInstance instance,
                                                      VkPhysicalDevice device,
                                                      uint32_t queuefamily)
{
    VisualID visualID = XVisualIDFromVisual(DefaultVisual(_glfw.x11.display,
                                                          _glfw.x11.screen));

    if (_glfw.vk.KHR_xcb_surface)
    {
        PFN_vkGetPhysicalDeviceXcbPresentationSupportKHR
            vkGetPhysicalDeviceXcbPresentationSupportKHR =
            (PFN_vkGetPhysicalDeviceXcbPresentationSupportKHR)
            vkGetInstanceProcAddr(instance, "vkGetPhysicalDeviceXcbPresentationSupportKHR");
        if (!vkGetPhysicalDeviceXcbPresentationSupportKHR)
        {
            _glfwInputError(GLFW_API_UNAVAILABLE,
                            "X11: Vulkan instance missing VK_KHR_xcb_surface extension");
            return false;
        }

        xcb_connection_t* connection = XGetXCBConnection(_glfw.x11.display);
        if (!connection)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "X11: Failed to retrieve XCB connection");
            return false;
        }

        return vkGetPhysicalDeviceXcbPresentationSupportKHR(device,
                                                            queuefamily,
                                                            connection,
                                                            visualID);
    }
    else
    {
        PFN_vkGetPhysicalDeviceXlibPresentationSupportKHR
            vkGetPhysicalDeviceXlibPresentationSupportKHR =
            (PFN_vkGetPhysicalDeviceXlibPresentationSupportKHR)
            vkGetInstanceProcAddr(instance, "vkGetPhysicalDeviceXlibPresentationSupportKHR");
        if (!vkGetPhysicalDeviceXlibPresentationSupportKHR)
        {
            _glfwInputError(GLFW_API_UNAVAILABLE,
                            "X11: Vulkan instance missing VK_KHR_xlib_surface extension");
            return false;
        }

        return vkGetPhysicalDeviceXlibPresentationSupportKHR(device,
                                                             queuefamily,
                                                             _glfw.x11.display,
                                                             visualID);
    }
}

VkResult _glfwPlatformCreateWindowSurface(VkInstance instance,
                                          _GLFWwindow* window,
                                          const VkAllocationCallbacks* allocator,
                                          VkSurfaceKHR* surface)
{
    if (_glfw.vk.KHR_xcb_surface)
    {
        VkResult err;
        VkXcbSurfaceCreateInfoKHR sci;
        PFN_vkCreateXcbSurfaceKHR vkCreateXcbSurfaceKHR;

        xcb_connection_t* connection = XGetXCBConnection(_glfw.x11.display);
        if (!connection)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "X11: Failed to retrieve XCB connection");
            return VK_ERROR_EXTENSION_NOT_PRESENT;
        }

        vkCreateXcbSurfaceKHR = (PFN_vkCreateXcbSurfaceKHR)
            vkGetInstanceProcAddr(instance, "vkCreateXcbSurfaceKHR");
        if (!vkCreateXcbSurfaceKHR)
        {
            _glfwInputError(GLFW_API_UNAVAILABLE,
                            "X11: Vulkan instance missing VK_KHR_xcb_surface extension");
            return VK_ERROR_EXTENSION_NOT_PRESENT;
        }

        memset(&sci, 0, sizeof(sci));
        sci.sType = VK_STRUCTURE_TYPE_XCB_SURFACE_CREATE_INFO_KHR;
        sci.connection = connection;
        sci.window = window->x11.handle;

        err = vkCreateXcbSurfaceKHR(instance, &sci, allocator, surface);
        if (err)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "X11: Failed to create Vulkan XCB surface: %s",
                            _glfwGetVulkanResultString(err));
        }

        return err;
    }
    else
    {
        VkResult err;
        VkXlibSurfaceCreateInfoKHR sci;
        PFN_vkCreateXlibSurfaceKHR vkCreateXlibSurfaceKHR;

        vkCreateXlibSurfaceKHR = (PFN_vkCreateXlibSurfaceKHR)
            vkGetInstanceProcAddr(instance, "vkCreateXlibSurfaceKHR");
        if (!vkCreateXlibSurfaceKHR)
        {
            _glfwInputError(GLFW_API_UNAVAILABLE,
                            "X11: Vulkan instance missing VK_KHR_xlib_surface extension");
            return VK_ERROR_EXTENSION_NOT_PRESENT;
        }

        memset(&sci, 0, sizeof(sci));
        sci.sType = VK_STRUCTURE_TYPE_XLIB_SURFACE_CREATE_INFO_KHR;
        sci.dpy = _glfw.x11.display;
        sci.window = window->x11.handle;

        err = vkCreateXlibSurfaceKHR(instance, &sci, allocator, surface);
        if (err)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "X11: Failed to create Vulkan X11 surface: %s",
                            _glfwGetVulkanResultString(err));
        }

        return err;
    }
}

void
_glfwPlatformUpdateIMEState(_GLFWwindow *w, const GLFWIMEUpdateEvent *ev) {
    glfw_xkb_update_ime_state(w, &_glfw.x11.xkb, ev);
}

int
_glfwPlatformSetWindowBlur(_GLFWwindow *window, int blur_radius) {
    if (_glfw.x11._KDE_NET_WM_BLUR_BEHIND_REGION == None) {
        _glfw.x11._KDE_NET_WM_BLUR_BEHIND_REGION = XInternAtom(_glfw.x11.display, "_KDE_NET_WM_BLUR_BEHIND_REGION", False);
    }
    if (_glfw.x11._KDE_NET_WM_BLUR_BEHIND_REGION != None) {
        uint32_t data = 0;
        if (blur_radius > 0) {
            XChangeProperty(_glfw.x11.display, window->x11.handle, _glfw.x11._KDE_NET_WM_BLUR_BEHIND_REGION,
                    XA_CARDINAL, 32, PropModeReplace, (unsigned char*) &data, 1);
        } else {
            XDeleteProperty(_glfw.x11.display, window->x11.handle, _glfw.x11._KDE_NET_WM_BLUR_BEHIND_REGION);
        }
        return 1;
    }
    return 0;
}


bool
_glfwPlatformGrabKeyboard(bool grab) {
    int result;
    if (grab) {
        result = XGrabKeyboard(_glfw.x11.display, _glfw.x11.root, True, GrabModeAsync, GrabModeAsync, CurrentTime);
    } else {
        result = XUngrabKeyboard(_glfw.x11.display, CurrentTime);
    }
    return result == GrabSuccess;
}

//////////////////////////////////////////////////////////////////////////
//////                        GLFW native API                       //////
//////////////////////////////////////////////////////////////////////////

GLFWAPI Display* glfwGetX11Display(void)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    return _glfw.x11.display;
}

GLFWAPI unsigned long glfwGetX11Window(GLFWwindow* handle)
{
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(None);
    return window->x11.handle;
}

GLFWAPI int glfwGetNativeKeyForName(const char* keyName, bool caseSensitive) {
    return glfw_xkb_keysym_from_name(keyName, caseSensitive);
}

GLFWAPI unsigned long long glfwDBusUserNotify(const GLFWDBUSNotificationData *n, GLFWDBusnotificationcreatedfun callback, void *data) {
    return glfw_dbus_send_user_notification(n, callback, data);
}

GLFWAPI void glfwDBusSetUserNotificationHandler(GLFWDBusnotificationactivatedfun handler) {
    glfw_dbus_set_user_notification_activated_handler(handler);
}

GLFWAPI int glfwSetX11LaunchCommand(GLFWwindow *handle, char **argv, int argc)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(0);
    _GLFWwindow* window = (_GLFWwindow*) handle;
    return XSetCommand(_glfw.x11.display, window->x11.handle, argv, argc);
}


