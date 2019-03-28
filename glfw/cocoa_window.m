//========================================================================
// GLFW 3.3 macOS - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2009-2016 Camilla Löwy <elmindreda@glfw.org>
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

#include "internal.h"

#include <float.h>
#include <string.h>

// Needed for _NSGetProgname
#include <crt_externs.h>

// Returns the style mask corresponding to the window settings
//
static NSUInteger getStyleMask(_GLFWwindow* window)
{
    NSUInteger styleMask = 0;

    if (window->monitor || !window->decorated)
        styleMask |= NSWindowStyleMaskBorderless;
    else
    {
        styleMask |= NSWindowStyleMaskTitled |
                     NSWindowStyleMaskClosable |
                     NSWindowStyleMaskMiniaturizable;

        if (window->resizable)
            styleMask |= NSWindowStyleMaskResizable;
    }

    return styleMask;
}

// Returns whether the cursor is in the content area of the specified window
//
static GLFWbool cursorInContentArea(_GLFWwindow* window)
{
    const NSPoint pos = [window->ns.object mouseLocationOutsideOfEventStream];
    return [window->ns.view mouse:pos inRect:[window->ns.view frame]];
}

// Hides the cursor if not already hidden
//
static void hideCursor(_GLFWwindow* window)
{
    if (!_glfw.ns.cursorHidden)
    {
        [NSCursor hide];
        _glfw.ns.cursorHidden = GLFW_TRUE;
    }
}

// Shows the cursor if not already shown
//
static void showCursor(_GLFWwindow* window)
{
    if (_glfw.ns.cursorHidden)
    {
        [NSCursor unhide];
        _glfw.ns.cursorHidden = GLFW_FALSE;
    }
}

// Updates the cursor image according to its cursor mode
//
static void updateCursorImage(_GLFWwindow* window)
{
    if (window->cursorMode == GLFW_CURSOR_NORMAL)
    {
        showCursor(window);

        if (window->cursor)
            [(NSCursor*) window->cursor->ns.object set];
        else
            [[NSCursor arrowCursor] set];
    }
    else
        hideCursor(window);
}

// Apply chosen cursor mode to a focused window
//
static void updateCursorMode(_GLFWwindow* window)
{
    if (window->cursorMode == GLFW_CURSOR_DISABLED)
    {
        _glfw.ns.disabledCursorWindow = window;
        _glfwPlatformGetCursorPos(window,
                                  &_glfw.ns.restoreCursorPosX,
                                  &_glfw.ns.restoreCursorPosY);
        _glfwCenterCursorInContentArea(window);
        CGAssociateMouseAndMouseCursorPosition(false);
    }
    else if (_glfw.ns.disabledCursorWindow == window)
    {
        _glfw.ns.disabledCursorWindow = NULL;
        CGAssociateMouseAndMouseCursorPosition(true);
        _glfwPlatformSetCursorPos(window,
                                  _glfw.ns.restoreCursorPosX,
                                  _glfw.ns.restoreCursorPosY);
    }

    if (cursorInContentArea(window))
        updateCursorImage(window);
}

// Make the specified window and its video mode active on its monitor
//
static void acquireMonitor(_GLFWwindow* window)
{
    _glfwSetVideoModeNS(window->monitor, &window->videoMode);
    const CGRect bounds = CGDisplayBounds(window->monitor->ns.displayID);
    const NSRect frame = NSMakeRect(bounds.origin.x,
                                    _glfwTransformYNS(bounds.origin.y + bounds.size.height),
                                    bounds.size.width,
                                    bounds.size.height);

    [window->ns.object setFrame:frame display:YES];

    _glfwInputMonitorWindow(window->monitor, window);
}

// Remove the window and restore the original video mode
//
static void releaseMonitor(_GLFWwindow* window)
{
    if (window->monitor->window != window)
        return;

    _glfwInputMonitorWindow(window->monitor, NULL);
    _glfwRestoreVideoModeNS(window->monitor);
}

// Translates macOS key modifiers into GLFW ones
//
static int translateFlags(NSUInteger flags)
{
    int mods = 0;

    if (flags & NSEventModifierFlagShift)
        mods |= GLFW_MOD_SHIFT;
    if (flags & NSEventModifierFlagControl)
        mods |= GLFW_MOD_CONTROL;
    if (flags & NSEventModifierFlagOption)
        mods |= GLFW_MOD_ALT;
    if (flags & NSEventModifierFlagCommand)
        mods |= GLFW_MOD_SUPER;
    if (flags & NSEventModifierFlagCapsLock)
        mods |= GLFW_MOD_CAPS_LOCK;

    return mods;
}

#define debug_key(...) if (_glfw.hints.init.debugKeyboard) NSLog(__VA_ARGS__)

static inline const char*
format_mods(int mods) {
    static char buf[128];
    char *p = buf, *s;
#define pr(x) p += snprintf(p, sizeof(buf) - (p - buf) - 1, x)
    pr("mods: ");
    s = p;
    if (mods & GLFW_MOD_CONTROL) pr("ctrl+");
    if (mods & GLFW_MOD_ALT) pr("alt+");
    if (mods & GLFW_MOD_SHIFT) pr("shift+");
    if (mods & GLFW_MOD_SUPER) pr("super+");
    if (mods & GLFW_MOD_CAPS_LOCK) pr("capslock+");
    if (mods & GLFW_MOD_NUM_LOCK) pr("numlock+");
    if (p == s) pr("none");
    else p--;
    pr(" ");
#undef pr
    return buf;
}

static inline const char*
format_text(const char *src) {
    static char buf[256];
    char *p = buf;
    if (!src[0]) return "<none>";
    while (*src) {
        p += snprintf(p, sizeof(buf) - (p - buf), "0x%x ", (unsigned char)*(src++));
    }
    if (p != buf) *(--p) = 0;
    return buf;
}

static const char*
safe_name_for_scancode(unsigned int scancode) {
    const char *ans = _glfwPlatformGetScancodeName(scancode);
    if (!ans) return "<noname>";
    if ((1 <= ans[0] && ans[0] <= 31) || ans[0] == 127) ans = "<cc>";
    return ans;
}


// Translates a macOS keycode to a GLFW keycode
//
static int translateKey(unsigned int key, GLFWbool apply_keymap)
{
    if (apply_keymap) {
        // Look for the effective key name after applying any keyboard layouts/mappings
        const char *name = _glfwPlatformGetScancodeName(key);
        if (name && name[1] == 0) {
            // Single letter key name
            switch(name[0]) {
#define K(ch, name) case ch: return GLFW_KEY_##name
                K('A', A); K('a', A);
                K('B', B); K('b', B);
                K('C', C); K('c', C);
                K('D', D); K('d', D);
                K('E', E); K('e', E);
                K('F', F); K('f', F);
                K('G', G); K('g', G);
                K('H', H); K('h', H);
                K('I', I); K('i', I);
                K('J', J); K('j', J);
                K('K', K); K('k', K);
                K('L', L); K('l', L);
                K('M', M); K('m', M);
                K('N', N); K('n', N);
                K('O', O); K('o', O);
                K('P', P); K('p', P);
                K('Q', Q); K('q', Q);
                K('R', R); K('r', R);
                K('S', S); K('s', S);
                K('T', T); K('t', T);
                K('U', U); K('u', U);
                K('V', V); K('v', V);
                K('W', W); K('w', W);
                K('X', X); K('x', X);
                K('Y', Y); K('y', Y);
                K('Z', Z); K('z', Z);
                K('0', 0);
                K('1', 1);
                K('2', 2);
                K('3', 3);
                K('5', 5);
                K('6', 6);
                K('7', 7);
                K('8', 8);
                K('9', 9);
                K('\'', APOSTROPHE);
                K(',', COMMA);
                K('.', PERIOD);
                K('/', SLASH);
                K('-', MINUS);
                K('=', EQUAL);
                K(';', SEMICOLON);
                K('[', LEFT_BRACKET);
                K(']', RIGHT_BRACKET);
                K('+', PLUS);
                K('`', GRAVE_ACCENT);
                K('\\', BACKSLASH);
#undef K
                default:
                    break;
            }
        }
    }
    if (key >= sizeof(_glfw.ns.keycodes) / sizeof(_glfw.ns.keycodes[0]))
        return GLFW_KEY_UNKNOWN;

    return _glfw.ns.keycodes[key];
}

// Translate a GLFW keycode to a Cocoa modifier flag
//
static NSUInteger translateKeyToModifierFlag(int key)
{
    switch (key)
    {
        case GLFW_KEY_LEFT_SHIFT:
        case GLFW_KEY_RIGHT_SHIFT:
            return NSEventModifierFlagShift;
        case GLFW_KEY_LEFT_CONTROL:
        case GLFW_KEY_RIGHT_CONTROL:
            return NSEventModifierFlagControl;
        case GLFW_KEY_LEFT_ALT:
        case GLFW_KEY_RIGHT_ALT:
            return NSEventModifierFlagOption;
        case GLFW_KEY_LEFT_SUPER:
        case GLFW_KEY_RIGHT_SUPER:
            return NSEventModifierFlagCommand;
        case GLFW_KEY_CAPS_LOCK:
            return NSEventModifierFlagCapsLock;
    }

    return 0;
}

// Defines a constant for empty ranges in NSTextInputClient
//
static const NSRange kEmptyRange = { NSNotFound, 0 };


//------------------------------------------------------------------------
// Delegate for window related notifications
//------------------------------------------------------------------------

@interface GLFWWindowDelegate : NSObject
{
    _GLFWwindow* window;
}

- (instancetype)initWithGlfwWindow:(_GLFWwindow *)initWindow;

@end

@implementation GLFWWindowDelegate

- (instancetype)initWithGlfwWindow:(_GLFWwindow *)initWindow
{
    self = [super init];
    if (self != nil)
        window = initWindow;

    return self;
}

- (BOOL)windowShouldClose:(id)sender
{
    _glfwInputWindowCloseRequest(window);
    return NO;
}

- (void)windowDidResize:(NSNotification *)notification
{
    if (window->context.client != GLFW_NO_API)
        [window->context.nsgl.object update];

    if (_glfw.ns.disabledCursorWindow == window)
        _glfwCenterCursorInContentArea(window);

    const int maximized = [window->ns.object isZoomed];
    if (window->ns.maximized != maximized)
    {
        window->ns.maximized = maximized;
        _glfwInputWindowMaximize(window, maximized);
    }

    const NSRect contentRect = [window->ns.view frame];
    const NSRect fbRect = [window->ns.view convertRectToBacking:contentRect];

    if (fbRect.size.width != window->ns.fbWidth ||
        fbRect.size.height != window->ns.fbHeight)
    {
        window->ns.fbWidth  = fbRect.size.width;
        window->ns.fbHeight = fbRect.size.height;
        _glfwInputFramebufferSize(window, fbRect.size.width, fbRect.size.height);
    }

    if (contentRect.size.width != window->ns.width ||
        contentRect.size.height != window->ns.height)
    {
        window->ns.width  = contentRect.size.width;
        window->ns.height = contentRect.size.height;
        _glfwInputWindowSize(window, contentRect.size.width, contentRect.size.height);
    }
}

- (void)windowDidMove:(NSNotification *)notification
{
    if (window->context.client != GLFW_NO_API)
        [window->context.nsgl.object update];

    if (_glfw.ns.disabledCursorWindow == window)
        _glfwCenterCursorInContentArea(window);

    int x, y;
    _glfwPlatformGetWindowPos(window, &x, &y);
    _glfwInputWindowPos(window, x, y);
}

- (void)windowDidChangeOcclusionState:(NSNotification *)notification
{
    _glfwInputWindowOcclusion(window, !([window->ns.object occlusionState] & NSWindowOcclusionStateVisible));
}

- (void)windowDidMiniaturize:(NSNotification *)notification
{
    if (window->monitor)
        releaseMonitor(window);

    _glfwInputWindowIconify(window, GLFW_TRUE);
}

- (void)windowDidDeminiaturize:(NSNotification *)notification
{
    if (window->monitor)
        acquireMonitor(window);

    _glfwInputWindowIconify(window, GLFW_FALSE);
}

- (void)windowDidBecomeKey:(NSNotification *)notification
{
    if (_glfw.ns.disabledCursorWindow == window)
        _glfwCenterCursorInContentArea(window);

    _glfwInputWindowFocus(window, GLFW_TRUE);
    updateCursorMode(window);
    if (window->cursorMode == GLFW_CURSOR_HIDDEN) hideCursor(window);
    if (_glfw.ns.disabledCursorWindow != window && cursorInContentArea(window))
    {
        double x = 0, y = 0;
        _glfwPlatformGetCursorPos(window, &x, &y);
        _glfwInputCursorPos(window, x, y);
    }
}

- (void)windowDidResignKey:(NSNotification *)notification
{
    if (window->monitor && window->autoIconify)
        _glfwPlatformIconifyWindow(window);
    showCursor(window);

    _glfwInputWindowFocus(window, GLFW_FALSE);
}

@end


//------------------------------------------------------------------------
// Delegate for application related notifications
//------------------------------------------------------------------------

@interface GLFWApplicationDelegate : NSObject
@end

@implementation GLFWApplicationDelegate

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender
{
    _GLFWwindow* window;

    for (window = _glfw.windowListHead;  window;  window = window->next)
        _glfwInputWindowCloseRequest(window);

    return NSTerminateCancel;
}

static GLFWapplicationshouldhandlereopenfun handle_reopen_callback = NULL;

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag
{
    if (!handle_reopen_callback) return YES;
    if (handle_reopen_callback(flag)) return YES;
    return NO;
}

- (void)applicationDidChangeScreenParameters:(NSNotification *) notification
{
    _GLFWwindow* window;

    for (window = _glfw.windowListHead;  window;  window = window->next)
    {
        if (window->context.client != GLFW_NO_API)
            [window->context.nsgl.object update];
    }

    _glfwPollMonitorsNS();
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification
{
    [NSApp stop:nil];

    _glfwPlatformPostEmptyEvent();
}

- (void)applicationDidHide:(NSNotification *)notification
{
    int i;

    for (i = 0;  i < _glfw.monitorCount;  i++)
        _glfwRestoreVideoModeNS(_glfw.monitors[i]);
}

@end


//------------------------------------------------------------------------
// Content view class for the GLFW window
//------------------------------------------------------------------------

@interface GLFWContentView : NSView <NSTextInputClient>
{
    _GLFWwindow* window;
    NSTrackingArea* trackingArea;
    NSMutableAttributedString* markedText;
}

- (instancetype)initWithGlfwWindow:(_GLFWwindow *)initWindow;

@end

@implementation GLFWContentView

- (instancetype)initWithGlfwWindow:(_GLFWwindow *)initWindow
{
    self = [super init];
    if (self != nil)
    {
        window = initWindow;
        trackingArea = nil;
        markedText = [[NSMutableAttributedString alloc] init];

        [self updateTrackingAreas];
        [self registerForDraggedTypes:@[NSPasteboardTypeFileURL]];
    }

    return self;
}

- (void)dealloc
{
    [trackingArea release];
    [markedText release];
    [super dealloc];
}

- (_GLFWwindow*)glfwWindow {
    return window;
}

- (BOOL)isOpaque
{
    return [window->ns.object isOpaque];
}

- (BOOL)canBecomeKeyView
{
    return YES;
}

- (BOOL)acceptsFirstResponder
{
    return YES;
}

- (void) viewWillStartLiveResize
{
    _glfwInputLiveResize(window, true);
}

- (void)viewDidEndLiveResize
{
    _glfwInputLiveResize(window, false);
}


- (BOOL)wantsUpdateLayer
{
    return YES;
}

- (void)updateLayer
{
    if (window->context.client != GLFW_NO_API) {
        @try {
            [window->context.nsgl.object update];
        } @catch (NSException *e) {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                    "Failed to update NSGL Context object with error: %s (%s)",
                    [[e name] UTF8String], [[e reason] UTF8String]);
        }
    }

    _glfwInputWindowDamage(window);
}

- (void)cursorUpdate:(NSEvent *)event
{
    updateCursorImage(window);
}

- (BOOL)acceptsFirstMouse:(NSEvent *)event
{
    return NO;  // changed by Kovid, to follow cocoa platform conventions
}

- (void)mouseDown:(NSEvent *)event
{
    _glfwInputMouseClick(window,
                         GLFW_MOUSE_BUTTON_LEFT,
                         GLFW_PRESS,
                         translateFlags([event modifierFlags]));
}

- (void)mouseDragged:(NSEvent *)event
{
    [self mouseMoved:event];
}

- (void)mouseUp:(NSEvent *)event
{
    _glfwInputMouseClick(window,
                         GLFW_MOUSE_BUTTON_LEFT,
                         GLFW_RELEASE,
                         translateFlags([event modifierFlags]));
}

- (void)mouseMoved:(NSEvent *)event
{
    if (window->cursorMode == GLFW_CURSOR_DISABLED)
    {
        const double dx = [event deltaX] - window->ns.cursorWarpDeltaX;
        const double dy = [event deltaY] - window->ns.cursorWarpDeltaY;

        _glfwInputCursorPos(window,
                            window->virtualCursorPosX + dx,
                            window->virtualCursorPosY + dy);
    }
    else
    {
        const NSRect contentRect = [window->ns.view frame];
        const NSPoint pos = [event locationInWindow];

        _glfwInputCursorPos(window, pos.x, contentRect.size.height - pos.y);
    }

    window->ns.cursorWarpDeltaX = 0;
    window->ns.cursorWarpDeltaY = 0;
}

- (void)rightMouseDown:(NSEvent *)event
{
    _glfwInputMouseClick(window,
                         GLFW_MOUSE_BUTTON_RIGHT,
                         GLFW_PRESS,
                         translateFlags([event modifierFlags]));
}

- (void)rightMouseDragged:(NSEvent *)event
{
    [self mouseMoved:event];
}

- (void)rightMouseUp:(NSEvent *)event
{
    _glfwInputMouseClick(window,
                         GLFW_MOUSE_BUTTON_RIGHT,
                         GLFW_RELEASE,
                         translateFlags([event modifierFlags]));
}

- (void)otherMouseDown:(NSEvent *)event
{
    _glfwInputMouseClick(window,
                         (int) [event buttonNumber],
                         GLFW_PRESS,
                         translateFlags([event modifierFlags]));
}

- (void)otherMouseDragged:(NSEvent *)event
{
    [self mouseMoved:event];
}

- (void)otherMouseUp:(NSEvent *)event
{
    _glfwInputMouseClick(window,
                         (int) [event buttonNumber],
                         GLFW_RELEASE,
                         translateFlags([event modifierFlags]));
}

- (void)mouseExited:(NSEvent *)event
{
    _glfwInputCursorEnter(window, GLFW_FALSE);
}

- (void)mouseEntered:(NSEvent *)event
{
    _glfwInputCursorEnter(window, GLFW_TRUE);
}

- (void)viewDidChangeBackingProperties
{
    const NSRect contentRect = [window->ns.view frame];
    const NSRect fbRect = [window->ns.view convertRectToBacking:contentRect];

    if (fbRect.size.width != window->ns.fbWidth ||
        fbRect.size.height != window->ns.fbHeight)
    {
        window->ns.fbWidth  = fbRect.size.width;
        window->ns.fbHeight = fbRect.size.height;
        _glfwInputFramebufferSize(window, fbRect.size.width, fbRect.size.height);
    }

    const float xscale = fbRect.size.width / contentRect.size.width;
    const float yscale = fbRect.size.height / contentRect.size.height;

    if (xscale != window->ns.xscale || yscale != window->ns.yscale)
    {
        window->ns.xscale = xscale;
        window->ns.yscale = yscale;
        _glfwInputWindowContentScale(window, xscale, yscale);

        if (window->ns.retina && window->ns.layer)
            [window->ns.layer setContentsScale:[window->ns.object backingScaleFactor]];
    }
}

- (void)drawRect:(NSRect)rect
{
    _glfwInputWindowDamage(window);
}

- (void)updateTrackingAreas
{
    if (trackingArea != nil)
    {
        [self removeTrackingArea:trackingArea];
        [trackingArea release];
    }

    const NSTrackingAreaOptions options = NSTrackingMouseEnteredAndExited |
                                          NSTrackingActiveAlways |
                                          NSTrackingEnabledDuringMouseDrag |
                                          NSTrackingCursorUpdate |
                                          NSTrackingInVisibleRect |
                                          NSTrackingAssumeInside;

    trackingArea = [[NSTrackingArea alloc] initWithRect:[self bounds]
                                                options:options
                                                  owner:self
                                               userInfo:nil];

    [self addTrackingArea:trackingArea];
    [super updateTrackingAreas];
}

static inline UInt32
convert_cocoa_to_carbon_modifiers(NSUInteger flags) {
    UInt32 mods = 0;
    if (flags & NSEventModifierFlagShift)
        mods |= shiftKey;
    if (flags & NSEventModifierFlagControl)
        mods |= controlKey;
    if (flags & NSEventModifierFlagOption)
        mods |= optionKey;
    if (flags & NSEventModifierFlagCommand)
        mods |= cmdKey;
    if (flags & NSEventModifierFlagCapsLock)
        mods |= alphaLock;

    return (mods >> 8) & 0xFF;
}

static inline void
convert_utf16_to_utf8(UniChar *src, UniCharCount src_length, char *dest, size_t dest_sz) {
    CFStringRef string = CFStringCreateWithCharactersNoCopy(kCFAllocatorDefault,
                                                            src,
                                                            src_length,
                                                            kCFAllocatorNull);
    CFStringGetCString(string,
                       dest,
                       dest_sz,
                       kCFStringEncodingUTF8);
    CFRelease(string);
}

static inline GLFWbool
is_ascii_control_char(char x) {
    return x == 0 || (1 <= x && x <= 31) || x == 127;
}

- (void)keyDown:(NSEvent *)event
{
    const unsigned int scancode = [event keyCode];
    const NSUInteger flags = [event modifierFlags];
    const int mods = translateFlags(flags);
    const int key = translateKey(scancode, GLFW_TRUE);
    const GLFWbool process_text = !window->ns.textInputFilterCallback || window->ns.textInputFilterCallback(key, mods, scancode, flags) != 1;
    _glfw.ns.text[0] = 0;
    if (!_glfw.ns.unicodeData) {
        // Using the cocoa API for key handling is disabled, as there is no
        // reliable way to handle dead keys using it. Only use it if the
        // keyboard unicode data is not available.
        if (process_text) {
            // this will call insertText with the text for this event, if any
            [self interpretKeyEvents:[NSArray arrayWithObject:event]];
        }
    } else {
        static UniChar text[256];
        UniCharCount char_count = 0;
        if (UCKeyTranslate(
                    [(NSData*) _glfw.ns.unicodeData bytes],
                    scancode,
                    kUCKeyActionDown,
                    convert_cocoa_to_carbon_modifiers(flags),
                    LMGetKbdType(),
                    (process_text ? 0 : kUCKeyTranslateNoDeadKeysMask),
                    &(window->ns.deadKeyState),
                    sizeof(text)/sizeof(text[0]),
                    &char_count,
                    text
                    ) != noErr) {
            debug_key(@"UCKeyTranslate failed for scancode: 0x%x (%s) %s\n", scancode, safe_name_for_scancode(scancode), format_mods(mods));
            window->ns.deadKeyState = 0;
            return;
        }
        debug_key(@"scancode: 0x%x (%s) %schar_count: %lu deadKeyState: %u ", scancode, safe_name_for_scancode(scancode), format_mods(mods), char_count, window->ns.deadKeyState);
        if (process_text) {
            // this will call insertText which will fill up _glfw.ns.text
            [self interpretKeyEvents:[NSArray arrayWithObject:event]];
        } else {
            window->ns.deadKeyState = 0;
        }
        if (window->ns.deadKeyState && (char_count == 0 || scancode == 0x75)) {
            // 0x75 is the delete key which needs to be ignored during a compose sequence
            debug_key(@"Ignoring dead key (text: %s).\n", format_text(_glfw.ns.text));
            return;
        }
    }
    if (is_ascii_control_char(_glfw.ns.text[0])) _glfw.ns.text[0] = 0;  // don't send text for ascii control codes
    debug_key(@"text: %s glfw_key: %s\n",
            format_text(_glfw.ns.text), _glfwGetKeyName(key));
    _glfwInputKeyboard(window, key, scancode, GLFW_PRESS, mods, _glfw.ns.text, 0);
}

- (void)flagsChanged:(NSEvent *)event
{
    int action;
    const unsigned int modifierFlags =
        [event modifierFlags] & NSEventModifierFlagDeviceIndependentFlagsMask;
    const int key = translateKey([event keyCode], GLFW_FALSE);
    const int mods = translateFlags(modifierFlags);
    const NSUInteger keyFlag = translateKeyToModifierFlag(key);

    if (keyFlag & modifierFlags)
    {
        if (window->keys[key] == GLFW_PRESS)
            action = GLFW_RELEASE;
        else
            action = GLFW_PRESS;
    }
    else
        action = GLFW_RELEASE;

    _glfwInputKeyboard(window, key, [event keyCode], action, mods, "", 0);
}

- (void)keyUp:(NSEvent *)event
{
    const int key = translateKey([event keyCode], GLFW_TRUE);
    const int mods = translateFlags([event modifierFlags]);
    _glfwInputKeyboard(window, key, [event keyCode], GLFW_RELEASE, mods, "", 0);
}

- (void)scrollWheel:(NSEvent *)event
{
    double deltaX, deltaY;

    deltaX = [event scrollingDeltaX];
    deltaY = [event scrollingDeltaY];
    int flags = [event hasPreciseScrollingDeltas] ? 1 : 0;
    if (flags) {
        float xscale = 1, yscale = 1;
        _glfwPlatformGetWindowContentScale(window, &xscale, &yscale);
        if (xscale > 0) deltaX *= xscale;
        if (yscale > 0) deltaY *= yscale;
    }

    switch([event momentumPhase]) {
        case NSEventPhaseBegan:
            flags |= (1 << 1); break;
        case NSEventPhaseStationary:
            flags |= (2 << 1); break;
        case NSEventPhaseChanged:
            flags |= (3 << 1); break;
        case NSEventPhaseEnded:
            flags |= (4 << 1); break;
        case NSEventPhaseCancelled:
            flags |= (5 << 1); break;
        case NSEventPhaseMayBegin:
            flags |= (6 << 1); break;
        case NSEventPhaseNone:
        default:
            break;
    }

    _glfwInputScroll(window, deltaX, deltaY, flags);
}

- (NSDragOperation)draggingEntered:(id <NSDraggingInfo>)sender
{
    // HACK: We don't know what to say here because we don't know what the
    // application wants to do with the paths
    return NSDragOperationGeneric;
}

- (BOOL)performDragOperation:(id <NSDraggingInfo>)sender
{
    const NSRect contentRect = [window->ns.view frame];
    _glfwInputCursorPos(window,
                        [sender draggingLocation].x,
                        contentRect.size.height - [sender draggingLocation].y);
    NSPasteboard* pasteboard = [sender draggingPasteboard];
    NSDictionary* options = @{NSPasteboardURLReadingFileURLsOnlyKey:@YES};
    NSArray* urls = [pasteboard readObjectsForClasses:@[[NSURL class]]
                                              options:options];
    if (!urls) return NO;
    const NSUInteger count = [urls count];

    if (count)
    {
        char** paths = calloc(count, sizeof(char*));

        for (NSUInteger i = 0;  i < count;  i++)
            paths[i] = _glfw_strdup([[urls objectAtIndex:i] fileSystemRepresentation]);

        _glfwInputDrop(window, (int) count, (const char**) paths);

        for (NSUInteger i = 0;  i < count;  i++)
            free(paths[i]);
        free(paths);
    }

    return YES;
}

- (BOOL)hasMarkedText
{
    return [markedText length] > 0;
}

- (NSRange)markedRange
{
    if ([markedText length] > 0)
        return NSMakeRange(0, [markedText length] - 1);
    else
        return kEmptyRange;
}

- (NSRange)selectedRange
{
    return kEmptyRange;
}

- (void)setMarkedText:(id)string
        selectedRange:(NSRange)selectedRange
     replacementRange:(NSRange)replacementRange
{
    [markedText release];
    if ([string isKindOfClass:[NSAttributedString class]])
        markedText = [[NSMutableAttributedString alloc] initWithAttributedString:string];
    else
        markedText = [[NSMutableAttributedString alloc] initWithString:string];
}

- (void)unmarkText
{
    [[markedText mutableString] setString:@""];
}

- (NSArray*)validAttributesForMarkedText
{
    return [NSArray array];
}

- (NSAttributedString*)attributedSubstringForProposedRange:(NSRange)range
                                               actualRange:(NSRangePointer)actualRange
{
    return nil;
}

- (NSUInteger)characterIndexForPoint:(NSPoint)point
{
    return 0;
}

- (NSRect)firstRectForCharacterRange:(NSRange)range
                         actualRange:(NSRangePointer)actualRange
{
    int xpos, ypos;
    _glfwPlatformGetWindowPos(window, &xpos, &ypos);
    const NSRect contentRect = [window->ns.view frame];
    return NSMakeRect(xpos, _glfwTransformYNS(ypos + contentRect.size.height), 0.0, 0.0);
}

- (void)insertText:(id)string replacementRange:(NSRange)replacementRange
{
    NSString* characters;
    if ([string isKindOfClass:[NSAttributedString class]])
        characters = [string string];
    else
        characters = (NSString*) string;
    // insertText can be called multiple times for a single key event
    char *s = _glfw.ns.text + strnlen(_glfw.ns.text, sizeof(_glfw.ns.text));
    snprintf(s, sizeof(_glfw.ns.text) - (s - _glfw.ns.text), "%s", [characters UTF8String]);
    _glfw.ns.text[sizeof(_glfw.ns.text) - 1] = 0;
}

- (void)doCommandBySelector:(SEL)selector
{
}

@end


//------------------------------------------------------------------------
// GLFW window class
//------------------------------------------------------------------------

@interface GLFWWindow : NSWindow {}
@end

@implementation GLFWWindow

- (BOOL)canBecomeKeyWindow
{
    // Required for NSWindowStyleMaskBorderless windows
    return YES;
}

- (BOOL)canBecomeMainWindow
{
    return YES;
}

- (void)toggleFullScreen:(nullable id)sender
{
    GLFWContentView *view = [self contentView];
    if (view)
    {
        _GLFWwindow *window = [view glfwWindow];
        if (window && window->ns.toggleFullscreenCallback && window->ns.toggleFullscreenCallback((GLFWwindow*)window) == 1)
            return;
    }
    [super toggleFullScreen:sender];
}

@end


// Set up the menu bar (manually)
// This is nasty, nasty stuff -- calls to undocumented semi-private APIs that
// could go away at any moment, lots of stuff that really should be
// localize(d|able), etc.  Add a nib to save us this horror.
//
static void createMenuBar(void)
{
    size_t i;
    NSString* appName = nil;
    NSDictionary* bundleInfo = [[NSBundle mainBundle] infoDictionary];
    NSString* nameKeys[] =
    {
        @"CFBundleDisplayName",
        @"CFBundleName",
        @"CFBundleExecutable",
    };

    // Try to figure out what the calling application is called

    for (i = 0;  i < sizeof(nameKeys) / sizeof(nameKeys[0]);  i++)
    {
        id name = [bundleInfo objectForKey:nameKeys[i]];
        if (name &&
            [name isKindOfClass:[NSString class]] &&
            ![name isEqualToString:@""])
        {
            appName = name;
            break;
        }
    }

    if (!appName)
    {
        char** progname = _NSGetProgname();
        if (progname && *progname)
            appName = [NSString stringWithUTF8String:*progname];
        else
            appName = @"GLFW Application";
    }

    NSMenu* bar = [[NSMenu alloc] init];
    [NSApp setMainMenu:bar];

    NSMenuItem* appMenuItem =
        [bar addItemWithTitle:@"" action:NULL keyEquivalent:@""];
    NSMenu* appMenu = [[NSMenu alloc] init];
    [appMenuItem setSubmenu:appMenu];

    [appMenu addItemWithTitle:[NSString stringWithFormat:@"About %@", appName]
                       action:@selector(orderFrontStandardAboutPanel:)
                keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    NSMenu* servicesMenu = [[NSMenu alloc] init];
    [NSApp setServicesMenu:servicesMenu];
    [[appMenu addItemWithTitle:@"Services"
                       action:NULL
                keyEquivalent:@""] setSubmenu:servicesMenu];
    [servicesMenu release];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:[NSString stringWithFormat:@"Hide %@", appName]
                       action:@selector(hide:)
                keyEquivalent:@"h"];
    [[appMenu addItemWithTitle:@"Hide Others"
                       action:@selector(hideOtherApplications:)
                keyEquivalent:@"h"]
        setKeyEquivalentModifierMask:NSEventModifierFlagOption | NSEventModifierFlagCommand];
    [appMenu addItemWithTitle:@"Show All"
                       action:@selector(unhideAllApplications:)
                keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    [appMenu addItemWithTitle:[NSString stringWithFormat:@"Quit %@", appName]
                       action:@selector(terminate:)
                keyEquivalent:@"q"];

    NSMenuItem* windowMenuItem =
        [bar addItemWithTitle:@"" action:NULL keyEquivalent:@""];
    [bar release];
    NSMenu* windowMenu = [[NSMenu alloc] initWithTitle:@"Window"];
    [NSApp setWindowsMenu:windowMenu];
    [windowMenuItem setSubmenu:windowMenu];

    [windowMenu addItemWithTitle:@"Minimize"
                          action:@selector(performMiniaturize:)
                   keyEquivalent:@"m"];
    [windowMenu addItemWithTitle:@"Zoom"
                          action:@selector(performZoom:)
                   keyEquivalent:@""];
    [windowMenu addItem:[NSMenuItem separatorItem]];
    [windowMenu addItemWithTitle:@"Bring All to Front"
                          action:@selector(arrangeInFront:)
                   keyEquivalent:@""];

    // TODO: Make this appear at the bottom of the menu (for consistency)
    [windowMenu addItem:[NSMenuItem separatorItem]];
    [[windowMenu addItemWithTitle:@"Enter Full Screen"
                           action:@selector(toggleFullScreen:)
                    keyEquivalent:@"f"]
     setKeyEquivalentModifierMask:NSEventModifierFlagControl | NSEventModifierFlagCommand];

    // Prior to Snow Leopard, we need to use this oddly-named semi-private API
    // to get the application menu working properly.
    SEL setAppleMenuSelector = NSSelectorFromString(@"setAppleMenu:");
    [NSApp performSelector:setAppleMenuSelector withObject:appMenu];
}

// Initialize the Cocoa Application Kit
//
static GLFWbool initializeAppKit(void)
{
    if (_glfw.ns.delegate)
        return GLFW_TRUE;

    // There can only be one application delegate, but we allocate it the
    // first time a window is created to keep all window code in this file
    _glfw.ns.delegate = [[GLFWApplicationDelegate alloc] init];
    if (_glfw.ns.delegate == nil)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to create application delegate");
        return GLFW_FALSE;
    }
    [NSApp setDelegate:_glfw.ns.delegate];

    if (_glfw.hints.init.ns.menubar)
    {
        // In case we are unbundled, make us a proper UI application
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];

        // Menu bar setup must go between sharedApplication above and
        // finishLaunching below, in order to properly emulate the behavior
        // of NSApplicationMain

        // disabled by Kovid
        /* if ([[NSBundle mainBundle] pathForResource:@"MainMenu" ofType:@"nib"]) */
        /*     [NSApp loadMainMenu]; */
        /* else */
            createMenuBar();
    }

    [NSApp run];

    // Press and Hold prevents some keys from emitting repeated characters
    NSDictionary* defaults = @{@"ApplePressAndHoldEnabled":@NO};

    [[NSUserDefaults standardUserDefaults] registerDefaults:defaults];

    return GLFW_TRUE;
}

// Create the Cocoa window
//
static GLFWbool createNativeWindow(_GLFWwindow* window,
                                   const _GLFWwndconfig* wndconfig,
                                   const _GLFWfbconfig* fbconfig)
{
    window->ns.delegate = [[GLFWWindowDelegate alloc] initWithGlfwWindow:window];
    if (window->ns.delegate == nil)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to create window delegate");
        return GLFW_FALSE;
    }

    NSRect contentRect;

    if (window->monitor)
    {
        GLFWvidmode mode;
        int xpos, ypos;

        _glfwPlatformGetVideoMode(window->monitor, &mode);
        _glfwPlatformGetMonitorPos(window->monitor, &xpos, &ypos);

        contentRect = NSMakeRect(xpos, ypos, mode.width, mode.height);
    }
    else
        contentRect = NSMakeRect(0, 0, wndconfig->width, wndconfig->height);

    window->ns.object = [[GLFWWindow alloc]
        initWithContentRect:contentRect
                  styleMask:getStyleMask(window)
                    backing:NSBackingStoreBuffered
                      defer:NO];

    if (window->ns.object == nil)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Cocoa: Failed to create window");
        return GLFW_FALSE;
    }

    if (window->monitor)
        [window->ns.object setLevel:NSMainMenuWindowLevel + 1];
    else
    {
        [window->ns.object center];
        _glfw.ns.cascadePoint =
            NSPointToCGPoint([window->ns.object cascadeTopLeftFromPoint:
                              NSPointFromCGPoint(_glfw.ns.cascadePoint)]);

        if (wndconfig->resizable)
        {
            const NSWindowCollectionBehavior behavior =
                NSWindowCollectionBehaviorFullScreenPrimary |
                NSWindowCollectionBehaviorManaged;
            [window->ns.object setCollectionBehavior:behavior];
        }

        if (wndconfig->floating)
            [window->ns.object setLevel:NSFloatingWindowLevel];

        if (wndconfig->maximized)
            [window->ns.object zoom:nil];
    }

    if (strlen(wndconfig->ns.frameName))
        [window->ns.object setFrameAutosaveName:[NSString stringWithUTF8String:wndconfig->ns.frameName]];

    window->ns.view = [[GLFWContentView alloc] initWithGlfwWindow:window];

    window->ns.retina = wndconfig->ns.retina;

    if (fbconfig->transparent)
    {
        [window->ns.object setOpaque:NO];
        [window->ns.object setHasShadow:NO];
        [window->ns.object setBackgroundColor:[NSColor clearColor]];
    }

    [window->ns.object setContentView:window->ns.view];
    [window->ns.object makeFirstResponder:window->ns.view];
    [window->ns.object setTitle:[NSString stringWithUTF8String:wndconfig->title]];
    [window->ns.object setDelegate:window->ns.delegate];
    [window->ns.object setAcceptsMouseMovedEvents:YES];
    [window->ns.object setRestorable:NO];

    _glfwPlatformGetWindowSize(window, &window->ns.width, &window->ns.height);
    _glfwPlatformGetFramebufferSize(window, &window->ns.fbWidth, &window->ns.fbHeight);

    return GLFW_TRUE;
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

int _glfwPlatformCreateWindow(_GLFWwindow* window,
                              const _GLFWwndconfig* wndconfig,
                              const _GLFWctxconfig* ctxconfig,
                              const _GLFWfbconfig* fbconfig)
{
    window->ns.deadKeyState = 0;
    if (!initializeAppKit())
        return GLFW_FALSE;

    if (!createNativeWindow(window, wndconfig, fbconfig))
        return GLFW_FALSE;

    if (ctxconfig->client != GLFW_NO_API)
    {
        if (ctxconfig->source == GLFW_NATIVE_CONTEXT_API)
        {
            if (!_glfwInitNSGL())
                return GLFW_FALSE;
            if (!_glfwCreateContextNSGL(window, ctxconfig, fbconfig))
                return GLFW_FALSE;
        }
        else if (ctxconfig->source == GLFW_EGL_CONTEXT_API)
        {
            if (!_glfwInitEGL())
                return GLFW_FALSE;
            if (!_glfwCreateContextEGL(window, ctxconfig, fbconfig))
                return GLFW_FALSE;
        }
        else if (ctxconfig->source == GLFW_OSMESA_CONTEXT_API)
        {
            if (!_glfwInitOSMesa())
                return GLFW_FALSE;
            if (!_glfwCreateContextOSMesa(window, ctxconfig, fbconfig))
                return GLFW_FALSE;
        }
    }

    if (window->monitor)
    {
        _glfwPlatformShowWindow(window);
        _glfwPlatformFocusWindow(window);
        acquireMonitor(window);
    }

    return GLFW_TRUE;
}

void _glfwPlatformDestroyWindow(_GLFWwindow* window)
{
    if (_glfw.ns.disabledCursorWindow == window)
        _glfw.ns.disabledCursorWindow = NULL;

    [window->ns.object orderOut:nil];

    if (window->monitor)
        releaseMonitor(window);

    if (window->context.destroy)
        window->context.destroy(window);

    [window->ns.object setDelegate:nil];
    [window->ns.delegate release];
    window->ns.delegate = nil;

    [window->ns.view release];
    window->ns.view = nil;

    [window->ns.object close];
    window->ns.object = nil;
}

void _glfwPlatformSetWindowTitle(_GLFWwindow* window, const char *title)
{
    NSString* string = [NSString stringWithUTF8String:title];
    [window->ns.object setTitle:string];
    // HACK: Set the miniwindow title explicitly as setTitle: doesn't update it
    //       if the window lacks NSWindowStyleMaskTitled
    [window->ns.object setMiniwindowTitle:string];
}

void _glfwPlatformSetWindowIcon(_GLFWwindow* window,
                                int count, const GLFWimage* images)
{
    // Regular windows do not have icons
}

void _glfwPlatformGetWindowPos(_GLFWwindow* window, int* xpos, int* ypos)
{
    const NSRect contentRect =
        [window->ns.object contentRectForFrameRect:[window->ns.object frame]];

    if (xpos)
        *xpos = contentRect.origin.x;
    if (ypos)
        *ypos = _glfwTransformYNS(contentRect.origin.y + contentRect.size.height);
}

void _glfwPlatformSetWindowPos(_GLFWwindow* window, int x, int y)
{
    const NSRect contentRect = [window->ns.view frame];
    const NSRect dummyRect = NSMakeRect(x, _glfwTransformYNS(y + contentRect.size.height), 0, 0);
    const NSRect frameRect = [window->ns.object frameRectForContentRect:dummyRect];
    [window->ns.object setFrameOrigin:frameRect.origin];
}

void _glfwPlatformGetWindowSize(_GLFWwindow* window, int* width, int* height)
{
    const NSRect contentRect = [window->ns.view frame];

    if (width)
        *width = contentRect.size.width;
    if (height)
        *height = contentRect.size.height;
}

void _glfwPlatformSetWindowSize(_GLFWwindow* window, int width, int height)
{
    if (window->monitor)
    {
        if (window->monitor->window == window)
            acquireMonitor(window);
    }
    else
        [window->ns.object setContentSize:NSMakeSize(width, height)];
}

void _glfwPlatformSetWindowSizeLimits(_GLFWwindow* window,
                                      int minwidth, int minheight,
                                      int maxwidth, int maxheight)
{
    if (minwidth == GLFW_DONT_CARE || minheight == GLFW_DONT_CARE)
        [window->ns.object setContentMinSize:NSMakeSize(0, 0)];
    else
        [window->ns.object setContentMinSize:NSMakeSize(minwidth, minheight)];

    if (maxwidth == GLFW_DONT_CARE || maxheight == GLFW_DONT_CARE)
        [window->ns.object setContentMaxSize:NSMakeSize(DBL_MAX, DBL_MAX)];
    else
        [window->ns.object setContentMaxSize:NSMakeSize(maxwidth, maxheight)];
}

void _glfwPlatformSetWindowAspectRatio(_GLFWwindow* window, int numer, int denom)
{
    if (numer == GLFW_DONT_CARE || denom == GLFW_DONT_CARE)
        [window->ns.object setResizeIncrements:NSMakeSize(1.0, 1.0)];
    else
        [window->ns.object setContentAspectRatio:NSMakeSize(numer, denom)];
}

void _glfwPlatformGetFramebufferSize(_GLFWwindow* window, int* width, int* height)
{
    const NSRect contentRect = [window->ns.view frame];
    const NSRect fbRect = [window->ns.view convertRectToBacking:contentRect];

    if (width)
        *width = (int) fbRect.size.width;
    if (height)
        *height = (int) fbRect.size.height;
}

void _glfwPlatformGetWindowFrameSize(_GLFWwindow* window,
                                     int* left, int* top,
                                     int* right, int* bottom)
{
    const NSRect contentRect = [window->ns.view frame];
    const NSRect frameRect = [window->ns.object frameRectForContentRect:contentRect];

    if (left)
        *left = contentRect.origin.x - frameRect.origin.x;
    if (top)
        *top = frameRect.origin.y + frameRect.size.height -
               contentRect.origin.y - contentRect.size.height;
    if (right)
        *right = frameRect.origin.x + frameRect.size.width -
                 contentRect.origin.x - contentRect.size.width;
    if (bottom)
        *bottom = contentRect.origin.y - frameRect.origin.y;
}

void _glfwPlatformGetWindowContentScale(_GLFWwindow* window,
                                        float* xscale, float* yscale)
{
    const NSRect points = [window->ns.view frame];
    const NSRect pixels = [window->ns.view convertRectToBacking:points];

    if (xscale)
        *xscale = (float) (pixels.size.width / points.size.width);
    if (yscale)
        *yscale = (float) (pixels.size.height / points.size.height);
}

double _glfwPlatformGetDoubleClickInterval(_GLFWwindow* window)
{
    return [NSEvent doubleClickInterval];
}

void _glfwPlatformIconifyWindow(_GLFWwindow* window)
{
    [window->ns.object miniaturize:nil];
}

void _glfwPlatformRestoreWindow(_GLFWwindow* window)
{
    if ([window->ns.object isMiniaturized])
        [window->ns.object deminiaturize:nil];
    else if ([window->ns.object isZoomed])
        [window->ns.object zoom:nil];
}

void _glfwPlatformMaximizeWindow(_GLFWwindow* window)
{
    if (![window->ns.object isZoomed])
        [window->ns.object zoom:nil];
}

void _glfwPlatformShowWindow(_GLFWwindow* window)
{
    [window->ns.object orderFront:nil];
}

void _glfwPlatformHideWindow(_GLFWwindow* window)
{
    [window->ns.object orderOut:nil];
}

void _glfwPlatformRequestWindowAttention(_GLFWwindow* window)
{
    [NSApp requestUserAttention:NSInformationalRequest];
}

int _glfwPlatformWindowBell(_GLFWwindow* window)
{
    NSBeep();
    return GLFW_TRUE;
}

void _glfwPlatformFocusWindow(_GLFWwindow* window)
{
    // Make us the active application
    // HACK: This has been moved here from initializeAppKit to prevent
    //       applications using only hidden windows from being activated, but
    //       should probably not be done every time any window is shown
    [NSApp activateIgnoringOtherApps:YES];

    [window->ns.object makeKeyAndOrderFront:nil];
}

void _glfwPlatformSetWindowMonitor(_GLFWwindow* window,
                                   _GLFWmonitor* monitor,
                                   int xpos, int ypos,
                                   int width, int height,
                                   int refreshRate)
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
            const NSRect contentRect =
                NSMakeRect(xpos, _glfwTransformYNS(ypos + height), width, height);
            const NSRect frameRect =
                [window->ns.object frameRectForContentRect:contentRect
                                                 styleMask:getStyleMask(window)];

            [window->ns.object setFrame:frameRect display:YES];
        }

        return;
    }

    if (window->monitor)
        releaseMonitor(window);

    _glfwInputWindowMonitor(window, monitor);

    const NSUInteger styleMask = getStyleMask(window);
    [window->ns.object setStyleMask:styleMask];
    // HACK: Changing the style mask can cause the first responder to be cleared
    [window->ns.object makeFirstResponder:window->ns.view];

    if (monitor)
    {
        [window->ns.object setLevel:NSMainMenuWindowLevel + 1];
        [window->ns.object setHasShadow:NO];

        acquireMonitor(window);
    }
    else
    {
        NSRect contentRect = NSMakeRect(xpos, _glfwTransformYNS(ypos + height),
                                        width, height);
        NSRect frameRect = [window->ns.object frameRectForContentRect:contentRect
                                                            styleMask:styleMask];
        [window->ns.object setFrame:frameRect display:YES];

        if (window->numer != GLFW_DONT_CARE &&
            window->denom != GLFW_DONT_CARE)
        {
            [window->ns.object setContentAspectRatio:NSMakeSize(window->numer,
                                                                window->denom)];
        }

        if (window->minwidth != GLFW_DONT_CARE &&
            window->minheight != GLFW_DONT_CARE)
        {
            [window->ns.object setContentMinSize:NSMakeSize(window->minwidth,
                                                            window->minheight)];
        }

        if (window->maxwidth != GLFW_DONT_CARE &&
            window->maxheight != GLFW_DONT_CARE)
        {
            [window->ns.object setContentMaxSize:NSMakeSize(window->maxwidth,
                                                            window->maxheight)];
        }

        if (window->floating)
            [window->ns.object setLevel:NSFloatingWindowLevel];
        else
            [window->ns.object setLevel:NSNormalWindowLevel];

        [window->ns.object setHasShadow:YES];
        // HACK: Clearing NSWindowStyleMaskTitled resets and disables the window
        //       title property but the miniwindow title property is unaffected
        [window->ns.object setTitle:[window->ns.object miniwindowTitle]];
    }
}

int _glfwPlatformWindowFocused(_GLFWwindow* window)
{
    return [window->ns.object isKeyWindow];
}

int _glfwPlatformWindowOccluded(_GLFWwindow* window)
{
    return !([window->ns.object occlusionState] & NSWindowOcclusionStateVisible);
}

int _glfwPlatformWindowIconified(_GLFWwindow* window)
{
    return [window->ns.object isMiniaturized];
}

int _glfwPlatformWindowVisible(_GLFWwindow* window)
{
    return [window->ns.object isVisible];
}

int _glfwPlatformWindowMaximized(_GLFWwindow* window)
{
    return [window->ns.object isZoomed];
}

int _glfwPlatformWindowHovered(_GLFWwindow* window)
{
    const NSPoint point = [NSEvent mouseLocation];

    if ([NSWindow windowNumberAtPoint:point belowWindowWithWindowNumber:0] !=
        [window->ns.object windowNumber])
    {
        return GLFW_FALSE;
    }

    return NSPointInRect(point,
        [window->ns.object convertRectToScreen:[window->ns.view bounds]]);
}

int _glfwPlatformFramebufferTransparent(_GLFWwindow* window)
{
    return ![window->ns.object isOpaque] && ![window->ns.view isOpaque];
}

void _glfwPlatformSetWindowResizable(_GLFWwindow* window, GLFWbool enabled)
{
    [window->ns.object setStyleMask:getStyleMask(window)];
}

void _glfwPlatformSetWindowDecorated(_GLFWwindow* window, GLFWbool enabled)
{
    [window->ns.object setStyleMask:getStyleMask(window)];
    [window->ns.object makeFirstResponder:window->ns.view];
}

void _glfwPlatformSetWindowFloating(_GLFWwindow* window, GLFWbool enabled)
{
    if (enabled)
        [window->ns.object setLevel:NSFloatingWindowLevel];
    else
        [window->ns.object setLevel:NSNormalWindowLevel];
}

float _glfwPlatformGetWindowOpacity(_GLFWwindow* window)
{
    return (float) [window->ns.object alphaValue];
}

void _glfwPlatformSetWindowOpacity(_GLFWwindow* window, float opacity)
{
    [window->ns.object setAlphaValue:opacity];
}

CGDirectDisplayID displayIDForWindow(_GLFWwindow *w) {
    NSWindow *nw = w->ns.object;
    NSDictionary *dict = [nw.screen deviceDescription];
    NSNumber *displayIDns = [dict objectForKey:@"NSScreenNumber"];
    if (displayIDns) return [displayIDns unsignedIntValue];
    return (CGDirectDisplayID)-1;
}

void
_glfwDispatchRenderFrame(CGDirectDisplayID displayID) {
    _GLFWwindow *w = _glfw.windowListHead;
    while (w) {
        if (w->ns.renderFrameRequested && displayID == displayIDForWindow(w)) {
            w->ns.renderFrameRequested = GLFW_FALSE;
            w->ns.renderFrameCallback((GLFWwindow*)w);
        }
        w = w->next;
    }
}

static inline void
requestRenderFrame(_GLFWwindow *w, GLFWcocoarenderframefun callback) {
    if (!callback) {
        w->ns.renderFrameRequested = GLFW_FALSE;
        w->ns.renderFrameCallback = NULL;
        return;
    }
    w->ns.renderFrameCallback = callback;
    w->ns.renderFrameRequested = GLFW_TRUE;
    CGDirectDisplayID displayID = displayIDForWindow(w);
    [_glfw.ns.displayLinks.lock lock];
    for (size_t i = 0; i < _glfw.ns.displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &_glfw.ns.displayLinks.entries[i];
        if (dl->displayID == displayID) {
            dl->renderFrameRequested = GLFW_TRUE;
            if (!dl->displayLinkStarted) {
                CVDisplayLinkStart(dl->displayLink);
                dl->displayLinkStarted = GLFW_TRUE;
            }
            break;
        }
    }
    [_glfw.ns.displayLinks.lock unlock];
}

void _glfwCocoaPostEmptyEvent(short subtype, long data1, bool at_start)
{
    @autoreleasepool {
    NSEvent* event = [NSEvent otherEventWithType:NSEventTypeApplicationDefined
                                        location:NSMakePoint(0, 0)
                                   modifierFlags:0
                                       timestamp:0
                                    windowNumber:0
                                         context:nil
                                         subtype:subtype
                                           data1:data1
                                           data2:0];
    [NSApp postEvent:event atStart:at_start ? YES : NO];
    }
}

void _glfwPlatformPostEmptyEvent(void)
{
    _glfwCocoaPostEmptyEvent(0, 0, true);
}

void _glfwPlatformGetCursorPos(_GLFWwindow* window, double* xpos, double* ypos)
{
    const NSRect contentRect = [window->ns.view frame];
    const NSPoint pos = [window->ns.object mouseLocationOutsideOfEventStream];

    if (xpos)
        *xpos = pos.x;
    if (ypos)
        *ypos = contentRect.size.height - pos.y - 1;
}

void _glfwPlatformSetCursorPos(_GLFWwindow* window, double x, double y)
{
    updateCursorImage(window);

    const NSRect contentRect = [window->ns.view frame];
    const NSPoint pos = [window->ns.object mouseLocationOutsideOfEventStream];

    window->ns.cursorWarpDeltaX += x - pos.x;
    window->ns.cursorWarpDeltaY += y - contentRect.size.height + pos.y;

    if (window->monitor)
    {
        CGDisplayMoveCursorToPoint(window->monitor->ns.displayID,
                                   CGPointMake(x, y));
    }
    else
    {
        const NSRect localRect = NSMakeRect(x, contentRect.size.height - y - 1, 0, 0);
        const NSRect globalRect = [window->ns.object convertRectToScreen:localRect];
        const NSPoint globalPoint = globalRect.origin;

        CGWarpMouseCursorPosition(CGPointMake(globalPoint.x,
                                              _glfwTransformYNS(globalPoint.y)));
    }
}

void _glfwPlatformSetCursorMode(_GLFWwindow* window, int mode)
{
    if (_glfwPlatformWindowFocused(window))
        updateCursorMode(window);
}

const char* _glfwPlatformGetScancodeName(int scancode)
{
    UInt32 deadKeyState = 0;
    UniChar characters[8];
    UniCharCount characterCount = 0;

    if (UCKeyTranslate([(NSData*) _glfw.ns.unicodeData bytes],
                       scancode,
                       kUCKeyActionDisplay,
                       0,
                       LMGetKbdType(),
                       kUCKeyTranslateNoDeadKeysBit,
                       &deadKeyState,
                       sizeof(characters) / sizeof(characters[0]),
                       &characterCount,
                       characters) != noErr)
    {
        return NULL;
    }

    if (!characterCount)
        return NULL;

    convert_utf16_to_utf8(characters, characterCount, _glfw.ns.keyName, sizeof(_glfw.ns.keyName));
    return _glfw.ns.keyName;
}

int _glfwPlatformGetKeyScancode(int key)
{
    return _glfw.ns.scancodes[key];
}

int _glfwPlatformCreateCursor(_GLFWcursor* cursor,
                              const GLFWimage* image,
                              int xhot, int yhot, int count)
{
    NSImage* native;
    NSBitmapImageRep* rep;

    native = [[NSImage alloc] initWithSize:NSMakeSize(image->width, image->height)];
    if (native == nil)
        return GLFW_FALSE;

    for (int i = 0; i < count; i++) {
        const GLFWimage *src = image + i;
        rep = [[NSBitmapImageRep alloc]
            initWithBitmapDataPlanes:NULL
                        pixelsWide:src->width
                        pixelsHigh:src->height
                    bitsPerSample:8
                    samplesPerPixel:4
                            hasAlpha:YES
                            isPlanar:NO
                    colorSpaceName:NSCalibratedRGBColorSpace
                        bitmapFormat:NSBitmapFormatAlphaNonpremultiplied
                        bytesPerRow:src->width * 4
                        bitsPerPixel:32];
        if (rep == nil)
            return GLFW_FALSE;

        memcpy([rep bitmapData], src->pixels, src->width * src->height * 4);
        [native addRepresentation:rep];
        [rep release];
    }

    cursor->ns.object = [[NSCursor alloc] initWithImage:native
                                                hotSpot:NSMakePoint(xhot, yhot)];
    [native release];
    if (cursor->ns.object == nil)
        return GLFW_FALSE;
    return GLFW_TRUE;
}

int _glfwPlatformCreateStandardCursor(_GLFWcursor* cursor, GLFWCursorShape shape)
{
#define C(name, val) case name: cursor->ns.object = [NSCursor val]; break;
#define U(name, val) case name: cursor->ns.object = [[NSCursor class] performSelector:@selector(val)]; break;
    switch(shape) {
        C(GLFW_ARROW_CURSOR, arrowCursor);
        C(GLFW_IBEAM_CURSOR, IBeamCursor);
        C(GLFW_CROSSHAIR_CURSOR, crosshairCursor);
        C(GLFW_HAND_CURSOR, pointingHandCursor);
        C(GLFW_HRESIZE_CURSOR, resizeLeftRightCursor);
        C(GLFW_VRESIZE_CURSOR, resizeUpDownCursor);
        U(GLFW_NW_RESIZE_CURSOR, _windowResizeNorthWestSouthEastCursor);
        U(GLFW_NE_RESIZE_CURSOR, _windowResizeNorthEastSouthWestCursor);
        U(GLFW_SW_RESIZE_CURSOR, _windowResizeNorthEastSouthWestCursor);
        U(GLFW_SE_RESIZE_CURSOR, _windowResizeNorthWestSouthEastCursor);
        case GLFW_INVALID_CURSOR:
            return GLFW_FALSE;
    }
#undef C
#undef U

    if (!cursor->ns.object)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to retrieve standard cursor");
        return GLFW_FALSE;
    }

    [cursor->ns.object retain];
    return GLFW_TRUE;
}

void _glfwPlatformDestroyCursor(_GLFWcursor* cursor)
{
    if (cursor->ns.object)
        [(NSCursor*) cursor->ns.object release];
}

void _glfwPlatformSetCursor(_GLFWwindow* window, _GLFWcursor* cursor)
{
    if (cursorInContentArea(window))
        updateCursorImage(window);
}

void _glfwPlatformSetClipboardString(const char* string)
{
    NSPasteboard* pasteboard = [NSPasteboard generalPasteboard];
    [pasteboard declareTypes:@[NSPasteboardTypeString] owner:nil];
    [pasteboard setString:[NSString stringWithUTF8String:string]
                  forType:NSPasteboardTypeString];
}

const char* _glfwPlatformGetClipboardString(void)
{
    NSPasteboard* pasteboard = [NSPasteboard generalPasteboard];

    if (![[pasteboard types] containsObject:NSPasteboardTypeString])
    {
        _glfwInputError(GLFW_FORMAT_UNAVAILABLE,
                        "Cocoa: Failed to retrieve string from pasteboard");
        return NULL;
    }

    NSString* object = [pasteboard stringForType:NSPasteboardTypeString];
    if (!object)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to retrieve object from pasteboard");
        return NULL;
    }

    free(_glfw.ns.clipboardString);
    _glfw.ns.clipboardString = _glfw_strdup([object UTF8String]);

    return _glfw.ns.clipboardString;
}

void _glfwPlatformGetRequiredInstanceExtensions(char** extensions)
{
    if (!_glfw.vk.KHR_surface || !_glfw.vk.MVK_macos_surface)
        return;

    extensions[0] = "VK_KHR_surface";
    extensions[1] = "VK_MVK_macos_surface";
}

int _glfwPlatformGetPhysicalDevicePresentationSupport(VkInstance instance,
                                                      VkPhysicalDevice device,
                                                      uint32_t queuefamily)
{
    return GLFW_TRUE;
}

VkResult _glfwPlatformCreateWindowSurface(VkInstance instance,
                                          _GLFWwindow* window,
                                          const VkAllocationCallbacks* allocator,
                                          VkSurfaceKHR* surface)
{
#if MAC_OS_X_VERSION_MAX_ALLOWED >= 101100
    VkResult err;
    VkMacOSSurfaceCreateInfoMVK sci;
    PFN_vkCreateMacOSSurfaceMVK vkCreateMacOSSurfaceMVK;

    vkCreateMacOSSurfaceMVK = (PFN_vkCreateMacOSSurfaceMVK)
        vkGetInstanceProcAddr(instance, "vkCreateMacOSSurfaceMVK");
    if (!vkCreateMacOSSurfaceMVK)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE,
                        "Cocoa: Vulkan instance missing VK_MVK_macos_surface extension");
        return VK_ERROR_EXTENSION_NOT_PRESENT;
    }

    // HACK: Dynamically load Core Animation to avoid adding an extra
    //       dependency for the majority who don't use MoltenVK
    NSBundle* bundle = [NSBundle bundleWithPath:@"/System/Library/Frameworks/QuartzCore.framework"];
    if (!bundle)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to find QuartzCore.framework");
        return VK_ERROR_EXTENSION_NOT_PRESENT;
    }

    // NOTE: Create the layer here as makeBackingLayer should not return nil
    window->ns.layer = [[bundle classNamed:@"CAMetalLayer"] layer];
    if (!window->ns.layer)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to create layer for view");
        return VK_ERROR_EXTENSION_NOT_PRESENT;
    }

    if (window->ns.retina)
        [window->ns.layer setContentsScale:[window->ns.object backingScaleFactor]];
    [window->ns.view setLayer:window->ns.layer];
    [window->ns.view setWantsLayer:YES];

    memset(&sci, 0, sizeof(sci));
    sci.sType = VK_STRUCTURE_TYPE_MACOS_SURFACE_CREATE_INFO_MVK;
    sci.pView = window->ns.view;

    err = vkCreateMacOSSurfaceMVK(instance, &sci, allocator, surface);
    if (err)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to create Vulkan surface: %s",
                        _glfwGetVulkanResultString(err));
    }

    return err;
#else
    return VK_ERROR_EXTENSION_NOT_PRESENT;
#endif
}


//////////////////////////////////////////////////////////////////////////
//////                        GLFW native API                       //////
//////////////////////////////////////////////////////////////////////////

GLFWAPI id glfwGetCocoaWindow(GLFWwindow* handle)
{
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(nil);
    return window->ns.object;
}

GLFWAPI GLFWcocoatextinputfilterfun glfwSetCocoaTextInputFilter(GLFWwindow *handle, GLFWcocoatextinputfilterfun callback) {
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(nil);
    GLFWcocoatextinputfilterfun previous = window->ns.textInputFilterCallback;
    window->ns.textInputFilterCallback = callback;
    return previous;
}

GLFWAPI GLFWcocoatogglefullscreenfun glfwSetCocoaToggleFullscreenIntercept(GLFWwindow *handle, GLFWcocoatogglefullscreenfun callback) {
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(nil);
    GLFWcocoatogglefullscreenfun previous = window->ns.toggleFullscreenCallback;
    window->ns.toggleFullscreenCallback = callback;
    return previous;
}

GLFWAPI GLFWapplicationshouldhandlereopenfun glfwSetApplicationShouldHandleReopen(GLFWapplicationshouldhandlereopenfun callback) {
    GLFWapplicationshouldhandlereopenfun previous = handle_reopen_callback;
    handle_reopen_callback = callback;
    return previous;
}

GLFWAPI void glfwCocoaRequestRenderFrame(GLFWwindow *w, GLFWcocoarenderframefun callback) {
    requestRenderFrame((_GLFWwindow*)w, callback);
}

GLFWAPI void glfwGetCocoaKeyEquivalent(int glfw_key, int glfw_mods, unsigned short *cocoa_key, int *cocoa_mods) {
    *cocoa_key = 0;
    *cocoa_mods = 0;

    if (glfw_mods & GLFW_MOD_SHIFT)
        *cocoa_mods |= NSEventModifierFlagShift;
    if (glfw_mods & GLFW_MOD_CONTROL)
        *cocoa_mods |= NSEventModifierFlagControl;
    if (glfw_mods & GLFW_MOD_ALT)
        *cocoa_mods |= NSEventModifierFlagOption;
    if (glfw_mods & GLFW_MOD_SUPER)
        *cocoa_mods |= NSEventModifierFlagCommand;
    if (glfw_mods & GLFW_MOD_CAPS_LOCK)
        *cocoa_mods |= NSEventModifierFlagCapsLock;

    switch(glfw_key) {
#define K(ch, name) case GLFW_KEY_##name: *cocoa_key = ch; break;
        K('a', A);
        K('b', B);
        K('c', C);
        K('d', D);
        K('e', E);
        K('f', F);
        K('g', G);
        K('h', H);
        K('i', I);
        K('j', J);
        K('k', K);
        K('l', L);
        K('m', M);
        K('n', N);
        K('o', O);
        K('p', P);
        K('q', Q);
        K('r', R);
        K('s', S);
        K('t', T);
        K('u', U);
        K('v', V);
        K('w', W);
        K('x', X);
        K('y', Y);
        K('z', Z);
        K('0', 0);
        K('1', 1);
        K('2', 2);
        K('3', 3);
        K('5', 5);
        K('6', 6);
        K('7', 7);
        K('8', 8);
        K('9', 9);
        K('\'', APOSTROPHE);
        K(',', COMMA);
        K('.', PERIOD);
        K('/', SLASH);
        K('-', MINUS);
        K('=', EQUAL);
        K(';', SEMICOLON);
        K('[', LEFT_BRACKET);
        K(']', RIGHT_BRACKET);
        K('+', PLUS);
        K('`', GRAVE_ACCENT);
        K('\\', BACKSLASH);

        K(0x35, ESCAPE);
        K('\r', ENTER);
        K('\t', TAB);
        K(NSBackspaceCharacter, BACKSPACE);
        K(NSInsertFunctionKey, INSERT);
        K(NSDeleteCharacter, DELETE);
        K(NSLeftArrowFunctionKey, LEFT);
        K(NSRightArrowFunctionKey, RIGHT);
        K(NSUpArrowFunctionKey, UP);
        K(NSDownArrowFunctionKey, DOWN);
        K(NSPageUpFunctionKey, PAGE_UP);
        K(NSPageDownFunctionKey, PAGE_DOWN);
        K(NSHomeFunctionKey, HOME);
        K(NSEndFunctionKey, END);
        K(NSPrintFunctionKey, PRINT_SCREEN);
        case GLFW_KEY_F1 ... GLFW_KEY_F24:
            *cocoa_key = NSF1FunctionKey + (glfw_key - GLFW_KEY_F1); break;
        case GLFW_KEY_KP_0 ... GLFW_KEY_KP_9:
            *cocoa_key = NSEventModifierFlagNumericPad | (0x52 + (glfw_key - GLFW_KEY_KP_0)); break;
        K((unichar)(0x41|NSEventModifierFlagNumericPad), KP_DECIMAL);
        K((unichar)(0x43|NSEventModifierFlagNumericPad), KP_MULTIPLY);
        K((unichar)(0x45|NSEventModifierFlagNumericPad), KP_ADD);
        K((unichar)(0x4B|NSEventModifierFlagNumericPad), KP_DIVIDE);
        K((unichar)(0x4E|NSEventModifierFlagNumericPad), KP_SUBTRACT);
        K((unichar)(0x51|NSEventModifierFlagNumericPad), KP_EQUAL);
#undef K
    }
}

//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

// Transforms a y-coordinate between the CG display and NS screen spaces
//
float _glfwTransformYNS(float y)
{
    return CGDisplayBounds(CGMainDisplayID()).size.height - y;
}
