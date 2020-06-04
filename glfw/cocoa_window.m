//========================================================================
// GLFW 3.4 macOS - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2009-2019 Camilla Löwy <elmindreda@glfw.org>
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

#include <float.h>
#include <string.h>


#define PARAGRAPH_UTF_8                        0xc2a7 // §
#define MASCULINE_UTF_8                        0xc2ba // º
#define A_DIAERESIS_UPPER_CASE_UTF_8           0xc384 // Ä
#define O_DIAERESIS_UPPER_CASE_UTF_8           0xc396 // Ö
#define U_DIAERESIS_UPPER_CASE_UTF_8           0xc39c // Ü
#define S_SHARP_UTF_8                          0xc39f // ß
#define A_GRAVE_LOWER_CASE_UTF_8               0xc3a0 // à
#define A_DIAERESIS_LOWER_CASE_UTF_8           0xc3a4 // ä
#define A_RING_LOWER_CASE_UTF_8                0xc3a5 // å
#define AE_LOWER_CASE_UTF_8                    0xc3a6 // æ
#define C_CEDILLA_LOWER_CASE_UTF_8             0xc3a7 // ç
#define E_GRAVE_LOWER_CASE_UTF_8               0xc3a8 // è
#define E_ACUTE_LOWER_CASE_UTF_8               0xc3a9 // é
#define I_GRAVE_LOWER_CASE_UTF_8               0xc3ac // ì
#define N_TILDE_LOWER_CASE_UTF_8               0xc3b1 // ñ
#define O_GRAVE_LOWER_CASE_UTF_8               0xc3b2 // ò
#define O_DIAERESIS_LOWER_CASE_UTF_8           0xc3b6 // ö
#define O_SLASH_LOWER_CASE_UTF_8               0xc3b8 // ø
#define U_GRAVE_LOWER_CASE_UTF_8               0xc3b9 // ù
#define U_DIAERESIS_LOWER_CASE_UTF_8           0xc3bc // ü
#define CYRILLIC_A_LOWER_CASE_UTF_8            0xd0b0 // а
#define CYRILLIC_BE_LOWER_CASE_UTF_8           0xd0b1 // б
#define CYRILLIC_VE_LOWER_CASE_UTF_8           0xd0b2 // в
#define CYRILLIC_GHE_LOWER_CASE_UTF_8          0xd0b3 // г
#define CYRILLIC_DE_LOWER_CASE_UTF_8           0xd0b4 // д
#define CYRILLIC_IE_LOWER_CASE_UTF_8           0xd0b5 // е
#define CYRILLIC_ZHE_LOWER_CASE_UTF_8          0xd0b6 // ж
#define CYRILLIC_ZE_LOWER_CASE_UTF_8           0xd0b7 // з
#define CYRILLIC_I_LOWER_CASE_UTF_8            0xd0b8 // и
#define CYRILLIC_SHORT_I_LOWER_CASE_UTF_8      0xd0b9 // й
#define CYRILLIC_KA_LOWER_CASE_UTF_8           0xd0ba // к
#define CYRILLIC_EL_LOWER_CASE_UTF_8           0xd0bb // л
#define CYRILLIC_EM_LOWER_CASE_UTF_8           0xd0bc // м
#define CYRILLIC_EN_LOWER_CASE_UTF_8           0xd0bd // н
#define CYRILLIC_O_LOWER_CASE_UTF_8            0xd0be // о
#define CYRILLIC_PE_LOWER_CASE_UTF_8           0xd0bf // п
#define CYRILLIC_ER_LOWER_CASE_UTF_8           0xd180 // р
#define CYRILLIC_ES_LOWER_CASE_UTF_8           0xd181 // с
#define CYRILLIC_TE_LOWER_CASE_UTF_8           0xd182 // т
#define CYRILLIC_U_LOWER_CASE_UTF_8            0xd183 // у
#define CYRILLIC_EF_LOWER_CASE_UTF_8           0xd184 // ф
#define CYRILLIC_HA_LOWER_CASE_UTF_8           0xd185 // х
#define CYRILLIC_TSE_LOWER_CASE_UTF_8          0xd186 // ц
#define CYRILLIC_CHE_LOWER_CASE_UTF_8          0xd187 // ч
#define CYRILLIC_SHA_LOWER_CASE_UTF_8          0xd188 // ш
#define CYRILLIC_SHCHA_LOWER_CASE_UTF_8        0xd189 // щ
#define CYRILLIC_HARD_SIGN_LOWER_CASE_UTF_8    0xd18a // ъ
#define CYRILLIC_YERU_LOWER_CASE_UTF_8         0xd18b // ы
#define CYRILLIC_SOFT_SIGN_LOWER_CASE_UTF_8    0xd18c // ь
#define CYRILLIC_E_LOWER_CASE_UTF_8            0xd18d // э
#define CYRILLIC_YU_LOWER_CASE_UTF_8           0xd18e // ю
#define CYRILLIC_YA_LOWER_CASE_UTF_8           0xd18f // я
#define CYRILLIC_IO_LOWER_CASE_UTF_8           0xd191 // ё

// Returns the style mask corresponding to the window settings
//
static NSUInteger getStyleMask(_GLFWwindow* window)
{
    NSUInteger styleMask = NSWindowStyleMaskMiniaturizable;

    if (window->monitor || !window->decorated)
        styleMask |= NSWindowStyleMaskBorderless;
    else
    {
        styleMask |= NSWindowStyleMaskTitled |
                     NSWindowStyleMaskClosable;

        if (window->resizable)
            styleMask |= NSWindowStyleMaskResizable;
    }

    return styleMask;
}


CGDirectDisplayID displayIDForWindow(_GLFWwindow *w) {
    NSWindow *nw = w->ns.object;
    NSDictionary *dict = [nw.screen deviceDescription];
    NSNumber *displayIDns = dict[@"NSScreenNumber"];
    if (displayIDns) return [displayIDns unsignedIntValue];
    return (CGDirectDisplayID)-1;
}

static unsigned long long display_link_shutdown_timer = 0;
#define DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL s_to_monotonic_t(30ll)

void
_glfwShutdownCVDisplayLink(unsigned long long timer_id UNUSED, void *user_data UNUSED) {
    display_link_shutdown_timer = 0;
    for (size_t i = 0; i < _glfw.ns.displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &_glfw.ns.displayLinks.entries[i];
        if (dl->displayLink) CVDisplayLinkStop(dl->displayLink);
        dl->lastRenderFrameRequestedAt = 0;
    }
}

static inline void
requestRenderFrame(_GLFWwindow *w, GLFWcocoarenderframefun callback) {
    if (!callback) {
        w->ns.renderFrameRequested = false;
        w->ns.renderFrameCallback = NULL;
        return;
    }
    w->ns.renderFrameCallback = callback;
    w->ns.renderFrameRequested = true;
    CGDirectDisplayID displayID = displayIDForWindow(w);
    if (display_link_shutdown_timer) {
        _glfwPlatformUpdateTimer(display_link_shutdown_timer, DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL, true);
    } else {
        display_link_shutdown_timer = _glfwPlatformAddTimer(DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL, false, _glfwShutdownCVDisplayLink, NULL, NULL);
    }
    monotonic_t now = glfwGetTime();
    for (size_t i = 0; i < _glfw.ns.displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &_glfw.ns.displayLinks.entries[i];
        if (dl->displayID == displayID) {
            dl->lastRenderFrameRequestedAt = now;
            if (!CVDisplayLinkIsRunning(dl->displayLink)) CVDisplayLinkStart(dl->displayLink);
        } else if (dl->displayLink && dl->lastRenderFrameRequestedAt && now - dl->lastRenderFrameRequestedAt >= DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL) {
            CVDisplayLinkStop(dl->displayLink);
            dl->lastRenderFrameRequestedAt = 0;
        }
    }
}

void
_glfwRestartDisplayLinks(void) {
    _GLFWwindow* window;
    for (window = _glfw.windowListHead;  window;  window = window->next) {
        if (window->ns.renderFrameRequested && window->ns.renderFrameCallback) {
            requestRenderFrame(window, window->ns.renderFrameCallback);
        }
    }
}

// Returns whether the cursor is in the content area of the specified window
//
static bool cursorInContentArea(_GLFWwindow* window)
{
    const NSPoint pos = [window->ns.object mouseLocationOutsideOfEventStream];
    return [window->ns.view mouse:pos inRect:[window->ns.view frame]];
}

// Hides the cursor if not already hidden
//
static void hideCursor(_GLFWwindow* window UNUSED)
{
    if (!_glfw.ns.cursorHidden)
    {
        [NSCursor hide];
        _glfw.ns.cursorHidden = true;
    }
}

// Shows the cursor if not already shown
//
static void showCursor(_GLFWwindow* window UNUSED)
{
    if (_glfw.ns.cursorHidden)
    {
        [NSCursor unhide];
        _glfw.ns.cursorHidden = false;
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
                                    _glfwTransformYNS(bounds.origin.y + bounds.size.height - 1),
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
    const char *last_char = buf + sizeof(buf) - 1;
    if (!src[0]) return "<none>";
    while (*src) {
        int num = snprintf(p, sizeof(buf) - (p - buf), "0x%x ", (unsigned char)*(src++));
        if (num < 0) return "<error>";
        if (p + num >= last_char) break;
        p += num;
    }
    if (p != buf) *(--p) = 0;
    return buf;
}

static const char*
safe_name_for_keycode(unsigned int keycode) {
    const char *ans = _glfwPlatformGetNativeKeyName(keycode);
    if (!ans) return "<noname>";
    if ((1 <= ans[0] && ans[0] <= 31) || ans[0] == 127) ans = "<cc>";
    return ans;
}


// Translates a macOS keycode to a GLFW keycode
//
static int translateKey(unsigned int key, bool apply_keymap)
{
    if (apply_keymap) {
        // Look for the effective key name after applying any keyboard layouts/mappings
        const char *name_chars = _glfwPlatformGetNativeKeyName(key);
        uint32_t name = 0;
        if (name_chars) {
            for (int i = 0; i < 4; i++) {
                if (!name_chars[i]) break;
                name <<= 8;
                name |= (uint8_t)name_chars[i];
            }
        }
        if (name) {
            // Key name
            switch(name) {
#define K(ch, name) case ch: return GLFW_KEY_##name
                K('!', EXCLAM);
                K('"', DOUBLE_QUOTE);
                K('#', NUMBER_SIGN);
                K('$', DOLLAR);
                K('&', AMPERSAND);
                K('\'', APOSTROPHE);
                K('(', PARENTHESIS_LEFT);
                K(')', PARENTHESIS_RIGHT);
                K('+', PLUS);
                K(',', COMMA);
                K('-', MINUS);
                K('.', PERIOD);
                K('/', SLASH);
                K('0', 0);
                K('1', 1);
                K('2', 2);
                K('3', 3);
                K('5', 5);
                K('6', 6);
                K('7', 7);
                K('8', 8);
                K('9', 9);
                K(':', COLON);
                K(';', SEMICOLON);
                K('<', LESS);
                K('=', EQUAL);
                K('>', GREATER);
                K('@', AT);
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
                K('[', LEFT_BRACKET);
                K('\\', BACKSLASH);
                K(']', RIGHT_BRACKET);
                K('^', CIRCUMFLEX);
                K('_', UNDERSCORE);
                K('`', GRAVE_ACCENT);
                K(PARAGRAPH_UTF_8, PARAGRAPH);
                K(MASCULINE_UTF_8, MASCULINE);
                K(A_DIAERESIS_UPPER_CASE_UTF_8, A_DIAERESIS);
                K(O_DIAERESIS_UPPER_CASE_UTF_8, O_DIAERESIS);
                K(U_DIAERESIS_UPPER_CASE_UTF_8, U_DIAERESIS);
                K(S_SHARP_UTF_8, S_SHARP);
                K(A_GRAVE_LOWER_CASE_UTF_8, A_GRAVE);
                K(A_DIAERESIS_LOWER_CASE_UTF_8, A_DIAERESIS);
                K(A_RING_LOWER_CASE_UTF_8, A_RING);
                K(AE_LOWER_CASE_UTF_8, AE);
                K(C_CEDILLA_LOWER_CASE_UTF_8, C_CEDILLA);
                K(E_GRAVE_LOWER_CASE_UTF_8, E_GRAVE);
                K(E_ACUTE_LOWER_CASE_UTF_8, E_ACUTE);
                K(I_GRAVE_LOWER_CASE_UTF_8, I_GRAVE);
                K(N_TILDE_LOWER_CASE_UTF_8, N_TILDE);
                K(O_GRAVE_LOWER_CASE_UTF_8, O_GRAVE);
                K(O_DIAERESIS_LOWER_CASE_UTF_8, O_DIAERESIS);
                K(O_SLASH_LOWER_CASE_UTF_8, O_SLASH);
                K(U_GRAVE_LOWER_CASE_UTF_8, U_GRAVE);
                K(U_DIAERESIS_LOWER_CASE_UTF_8, U_DIAERESIS);
                K(CYRILLIC_A_LOWER_CASE_UTF_8, CYRILLIC_A);
                K(CYRILLIC_BE_LOWER_CASE_UTF_8, CYRILLIC_BE);
                K(CYRILLIC_VE_LOWER_CASE_UTF_8, CYRILLIC_VE);
                K(CYRILLIC_GHE_LOWER_CASE_UTF_8, CYRILLIC_GHE);
                K(CYRILLIC_DE_LOWER_CASE_UTF_8, CYRILLIC_DE);
                K(CYRILLIC_IE_LOWER_CASE_UTF_8, CYRILLIC_IE);
                K(CYRILLIC_ZHE_LOWER_CASE_UTF_8, CYRILLIC_ZHE);
                K(CYRILLIC_ZE_LOWER_CASE_UTF_8, CYRILLIC_ZE);
                K(CYRILLIC_I_LOWER_CASE_UTF_8, CYRILLIC_I);
                K(CYRILLIC_SHORT_I_LOWER_CASE_UTF_8, CYRILLIC_SHORT_I);
                K(CYRILLIC_KA_LOWER_CASE_UTF_8, CYRILLIC_KA);
                K(CYRILLIC_EL_LOWER_CASE_UTF_8, CYRILLIC_EL);
                K(CYRILLIC_EM_LOWER_CASE_UTF_8, CYRILLIC_EM);
                K(CYRILLIC_EN_LOWER_CASE_UTF_8, CYRILLIC_EN);
                K(CYRILLIC_O_LOWER_CASE_UTF_8, CYRILLIC_O);
                K(CYRILLIC_PE_LOWER_CASE_UTF_8, CYRILLIC_PE);
                K(CYRILLIC_ER_LOWER_CASE_UTF_8, CYRILLIC_ER);
                K(CYRILLIC_ES_LOWER_CASE_UTF_8, CYRILLIC_ES);
                K(CYRILLIC_TE_LOWER_CASE_UTF_8, CYRILLIC_TE);
                K(CYRILLIC_U_LOWER_CASE_UTF_8, CYRILLIC_U);
                K(CYRILLIC_EF_LOWER_CASE_UTF_8, CYRILLIC_EF);
                K(CYRILLIC_HA_LOWER_CASE_UTF_8, CYRILLIC_HA);
                K(CYRILLIC_TSE_LOWER_CASE_UTF_8, CYRILLIC_TSE);
                K(CYRILLIC_CHE_LOWER_CASE_UTF_8, CYRILLIC_CHE);
                K(CYRILLIC_SHA_LOWER_CASE_UTF_8, CYRILLIC_SHA);
                K(CYRILLIC_SHCHA_LOWER_CASE_UTF_8, CYRILLIC_SHCHA);
                K(CYRILLIC_HARD_SIGN_LOWER_CASE_UTF_8, CYRILLIC_HARD_SIGN);
                K(CYRILLIC_YERU_LOWER_CASE_UTF_8, CYRILLIC_YERU);
                K(CYRILLIC_SOFT_SIGN_LOWER_CASE_UTF_8, CYRILLIC_SOFT_SIGN);
                K(CYRILLIC_E_LOWER_CASE_UTF_8, CYRILLIC_E);
                K(CYRILLIC_YU_LOWER_CASE_UTF_8, CYRILLIC_YU);
                K(CYRILLIC_YA_LOWER_CASE_UTF_8, CYRILLIC_YA);
                K(CYRILLIC_IO_LOWER_CASE_UTF_8, CYRILLIC_IO);
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


// Delegate for window related notifications {{{

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
    (void)sender;
    _glfwInputWindowCloseRequest(window);
    return NO;
}

- (void)windowDidResize:(NSNotification *)notification
{
    (void)notification;
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
        window->ns.fbWidth  = (int)fbRect.size.width;
        window->ns.fbHeight = (int)fbRect.size.height;
        _glfwInputFramebufferSize(window, (int)fbRect.size.width, (int)fbRect.size.height);
    }

    if (contentRect.size.width != window->ns.width ||
        contentRect.size.height != window->ns.height)
    {
        window->ns.width  = (int)contentRect.size.width;
        window->ns.height = (int)contentRect.size.height;
        _glfwInputWindowSize(window, (int)contentRect.size.width, (int)contentRect.size.height);
    }
}

- (void)windowDidMove:(NSNotification *)notification
{
    (void)notification;
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
    (void)notification;
    _glfwInputWindowOcclusion(window, !([window->ns.object occlusionState] & NSWindowOcclusionStateVisible));
}

- (void)windowDidMiniaturize:(NSNotification *)notification
{
    (void)notification;
    if (window->monitor)
        releaseMonitor(window);

    _glfwInputWindowIconify(window, true);
}

- (void)windowDidDeminiaturize:(NSNotification *)notification
{
    (void)notification;
    if (window->monitor)
        acquireMonitor(window);

    _glfwInputWindowIconify(window, false);
}

- (void)windowDidBecomeKey:(NSNotification *)notification
{
    (void)notification;
    if (_glfw.ns.disabledCursorWindow == window)
        _glfwCenterCursorInContentArea(window);

    _glfwInputWindowFocus(window, true);
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
    (void)notification;
    if (window->monitor && window->autoIconify)
        _glfwPlatformIconifyWindow(window);
    showCursor(window);

    _glfwInputWindowFocus(window, false);
}

- (void)windowDidChangeScreen:(NSNotification *)notification
{
    (void)notification;
    if (window->ns.renderFrameRequested && window->ns.renderFrameCallback) {
        // Ensure that if the window changed its monitor, CVDisplayLink
        // is running for the new monitor
        requestRenderFrame(window, window->ns.renderFrameCallback);
    }
}

@end // }}}


// Content view class for the GLFW window {{{

@interface GLFWContentView : NSView <NSTextInputClient>
{
    _GLFWwindow* window;
    NSTrackingArea* trackingArea;
    NSMutableAttributedString* markedText;
    NSRect markedRect;
    NSString *input_source_at_last_key_event;
}

- (void) removeGLFWWindow;
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
        markedRect = NSMakeRect(0.0, 0.0, 0.0, 0.0);
        input_source_at_last_key_event = nil;

        [self updateTrackingAreas];
        [self registerForDraggedTypes:@[NSPasteboardTypeFileURL, NSPasteboardTypeString]];
    }

    return self;
}

- (void)dealloc
{
    [trackingArea release];
    [markedText release];
    if (input_source_at_last_key_event) [input_source_at_last_key_event release];
    [super dealloc];
}

- (void) removeGLFWWindow
{
    window = NULL;
}

- (_GLFWwindow*)glfwWindow {
    return window;
}

- (BOOL)isOpaque
{
    return window && [window->ns.object isOpaque];
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
    if (!window) return;
    _glfwInputLiveResize(window, true);
}

- (void)viewDidEndLiveResize
{
    if (!window) return;
    _glfwInputLiveResize(window, false);
}

- (BOOL)wantsUpdateLayer
{
    return YES;
}

- (void)updateLayer
{
    if (!window) return;
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
    (void)event;
    if (window) updateCursorImage(window);
}

- (BOOL)acceptsFirstMouse:(NSEvent *)event
{
    (void)event;
    return NO;  // changed by Kovid, to follow cocoa platform conventions
}

- (void)mouseDown:(NSEvent *)event
{
    if (!window) return;
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
    if (!window) return;
    _glfwInputMouseClick(window,
                         GLFW_MOUSE_BUTTON_LEFT,
                         GLFW_RELEASE,
                         translateFlags([event modifierFlags]));
}

- (void)mouseMoved:(NSEvent *)event
{
    if (!window) return;
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
        // NOTE: The returned location uses base 0,1 not 0,0
        const NSPoint pos = [event locationInWindow];

        _glfwInputCursorPos(window, pos.x, contentRect.size.height - pos.y);
    }

    window->ns.cursorWarpDeltaX = 0;
    window->ns.cursorWarpDeltaY = 0;
}

- (void)rightMouseDown:(NSEvent *)event
{
    if (!window) return;
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
    if (!window) return;
    _glfwInputMouseClick(window,
                         GLFW_MOUSE_BUTTON_RIGHT,
                         GLFW_RELEASE,
                         translateFlags([event modifierFlags]));
}

- (void)otherMouseDown:(NSEvent *)event
{
    if (!window) return;
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
    if (!window) return;
    _glfwInputMouseClick(window,
                         (int) [event buttonNumber],
                         GLFW_RELEASE,
                         translateFlags([event modifierFlags]));
}

- (void)mouseExited:(NSEvent *)event
{
    (void)event;
    if (!window) return;
    _glfwInputCursorEnter(window, false);
}

- (void)mouseEntered:(NSEvent *)event
{
    (void)event;
    if (!window) return;
    _glfwInputCursorEnter(window, true);
}

- (void)viewDidChangeBackingProperties
{
    if (!window) return;
    const NSRect contentRect = [window->ns.view frame];
    const NSRect fbRect = [window->ns.view convertRectToBacking:contentRect];

    if (fbRect.size.width != window->ns.fbWidth ||
        fbRect.size.height != window->ns.fbHeight)
    {
        window->ns.fbWidth  = (int)fbRect.size.width;
        window->ns.fbHeight = (int)fbRect.size.height;
        _glfwInputFramebufferSize(window, (int)fbRect.size.width, (int)fbRect.size.height);
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
    (void)rect;
    if (!window) return;
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

static inline bool
is_ascii_control_char(char x) {
    return x == 0 || (1 <= x && x <= 31) || x == 127;
}

- (void)keyDown:(NSEvent *)event
{
    const bool previous_has_marked_text = [self hasMarkedText];
    bool input_source_changed = false;
    NSTextInputContext *inpctx = [NSTextInputContext currentInputContext];
    if (inpctx && (!input_source_at_last_key_event || ![input_source_at_last_key_event isEqualToString:inpctx.selectedKeyboardInputSource])) {
        input_source_at_last_key_event = [inpctx.selectedKeyboardInputSource retain];
        input_source_changed = true;
    }

    const unsigned int keycode = [event keyCode];
    const NSUInteger flags = [event modifierFlags];
    const int mods = translateFlags(flags);
    const int key = translateKey(keycode, true);
    const bool process_text = !window->ns.textInputFilterCallback || window->ns.textInputFilterCallback(key, mods, keycode, flags) != 1;
    [self unmarkText];
    _glfw.ns.text[0] = 0;
    GLFWkeyevent glfw_keyevent;
    _glfwInitializeKeyEvent(&glfw_keyevent, key, keycode, GLFW_PRESS, mods);
    if (!_glfw.ns.unicodeData) {
        // Using the cocoa API for key handling is disabled, as there is no
        // reliable way to handle dead keys using it. Only use it if the
        // keyboard unicode data is not available.
        if (process_text) {
            // this will call insertText with the text for this event, if any
            [self interpretKeyEvents:[NSArray arrayWithObject:event]];
        }
    } else {
        if (input_source_changed) {
            debug_key(@"Input source changed, clearing pre-edit text and resetting deadkey state\n");
            glfw_keyevent.text = NULL;
            glfw_keyevent.ime_state = 1;
            window->ns.deadKeyState = 0;
            _glfwInputKeyboard(window, &glfw_keyevent); // clear pre-edit text
        }

        static UniChar text[256];
        UniCharCount char_count = 0;
        const bool in_compose_sequence = window->ns.deadKeyState != 0;
        if (UCKeyTranslate(
                    [(NSData*) _glfw.ns.unicodeData bytes],
                    keycode,
                    kUCKeyActionDown,
                    convert_cocoa_to_carbon_modifiers(flags),
                    LMGetKbdType(),
                    (process_text ? 0 : kUCKeyTranslateNoDeadKeysMask),
                    &(window->ns.deadKeyState),
                    sizeof(text)/sizeof(text[0]),
                    &char_count,
                    text
                    ) != noErr) {
            debug_key(@"UCKeyTranslate failed for keycode: 0x%x (%@) %@\n",
                    keycode, @(safe_name_for_keycode(keycode)), @(format_mods(mods)));
            window->ns.deadKeyState = 0;
            return;
        }
        debug_key(@"keycode: 0x%x (%@) %@char_count: %lu deadKeyState: %u repeat: %d",
                keycode, @(safe_name_for_keycode(keycode)), @(format_mods(mods)), char_count, window->ns.deadKeyState, event.ARepeat);
        if (process_text) {
            // this will call insertText which will fill up _glfw.ns.text
            [self interpretKeyEvents:[NSArray arrayWithObject:event]];
        } else {
            window->ns.deadKeyState = 0;
        }
        if (window->ns.deadKeyState && (char_count == 0 || keycode == 0x75)) {
            // 0x75 is the delete key which needs to be ignored during a compose sequence
            debug_key(@"Sending pre-edit text for dead key (text: %@ markedText: %@).\n", @(format_text(_glfw.ns.text)), markedText);
            glfw_keyevent.text = [[markedText string] UTF8String];
            glfw_keyevent.ime_state = 1;
            _glfwInputKeyboard(window, &glfw_keyevent); // update pre-edit text
            return;
        }
        if (in_compose_sequence) {
            debug_key(@"Clearing pre-edit text at end of compose sequence\n");
            glfw_keyevent.text = NULL;
            glfw_keyevent.ime_state = 1;
            _glfwInputKeyboard(window, &glfw_keyevent); // clear pre-edit text
        }
    }
    if (is_ascii_control_char(_glfw.ns.text[0])) _glfw.ns.text[0] = 0;  // don't send text for ascii control codes
    debug_key(@"text: %@ glfw_key: %@ marked_text: %@\n",
            @(format_text(_glfw.ns.text)), @(_glfwGetKeyName(key)), markedText);
    if (!window->ns.deadKeyState) {
        if ([self hasMarkedText]) {
            glfw_keyevent.text = [[markedText string] UTF8String];
            glfw_keyevent.ime_state = 1;
            _glfwInputKeyboard(window, &glfw_keyevent); // update pre-edit text
        } else if (previous_has_marked_text) {
            glfw_keyevent.text = NULL;
            glfw_keyevent.ime_state = 1;
            _glfwInputKeyboard(window, &glfw_keyevent); // clear pre-edit text
        }
        if (([self hasMarkedText] || previous_has_marked_text) && !_glfw.ns.text[0]) {
            // do not pass keys like BACKSPACE while there's pre-edit text, let IME handle it
            return;
        }
    }
    glfw_keyevent.text = _glfw.ns.text;
    glfw_keyevent.ime_state = 0;
    _glfwInputKeyboard(window, &glfw_keyevent);
}

- (void)flagsChanged:(NSEvent *)event
{
    int action;
    const unsigned int modifierFlags =
        [event modifierFlags] & NSEventModifierFlagDeviceIndependentFlagsMask;
    const int key = translateKey([event keyCode], false);
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

    GLFWkeyevent glfw_keyevent;
    _glfwInitializeKeyEvent(&glfw_keyevent, key, [event keyCode], action, mods);
    _glfwInputKeyboard(window, &glfw_keyevent);
}

- (void)keyUp:(NSEvent *)event
{
    const int key = translateKey([event keyCode], true);
    const int mods = translateFlags([event modifierFlags]);

    GLFWkeyevent glfw_keyevent;
    _glfwInitializeKeyEvent(&glfw_keyevent, key, [event keyCode], GLFW_RELEASE, mods);
    _glfwInputKeyboard(window, &glfw_keyevent);
}

- (void)scrollWheel:(NSEvent *)event
{
    double deltaX = [event scrollingDeltaX];
    double deltaY = [event scrollingDeltaY];

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

    _glfwInputScroll(window, deltaX, deltaY, flags, translateFlags([event modifierFlags]));
}

- (NSDragOperation)draggingEntered:(id <NSDraggingInfo>)sender
{
    (void)sender;
    // HACK: We don't know what to say here because we don't know what the
    //       application wants to do with the paths
    return NSDragOperationGeneric;
}

- (BOOL)performDragOperation:(id <NSDraggingInfo>)sender
{
    const NSRect contentRect = [window->ns.view frame];
    // NOTE: The returned location uses base 0,1 not 0,0
    const NSPoint pos = [sender draggingLocation];
    _glfwInputCursorPos(window, pos.x, contentRect.size.height - pos.y);

    NSPasteboard* pasteboard = [sender draggingPasteboard];
    NSDictionary* options = @{NSPasteboardURLReadingFileURLsOnlyKey:@YES};
    NSArray* objs = [pasteboard readObjectsForClasses:@[[NSURL class], [NSString class]]
                                              options:options];
    if (!objs) return NO;
    const NSUInteger count = [objs count];
    if (count)
    {
        for (NSUInteger i = 0;  i < count;  i++)
        {
            id obj = objs[i];
            if ([obj isKindOfClass:[NSURL class]]) {
                const char *path = [obj fileSystemRepresentation];
                _glfwInputDrop(window, "text/plain;charset=utf-8", path, strlen(path));
            } else if ([obj isKindOfClass:[NSString class]]) {
                const char *text = [obj UTF8String];
                _glfwInputDrop(window, "text/plain;charset=utf-8", text, strlen(text));
            } else {
                _glfwInputError(GLFW_PLATFORM_ERROR,
                                "Cocoa: Object is neither a URL nor a string");
            }
        }
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
    (void)selectedRange; (void)replacementRange;
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

void _glfwPlatformUpdateIMEState(_GLFWwindow *w, int which, int a, int b, int c, int d) {
    [w->ns.view updateIMEStateFor: which left:(CGFloat)a top:(CGFloat)b cellWidth:(CGFloat)c cellHeight:(CGFloat)d];
}

- (void)updateIMEStateFor:(int)which
                     left:(CGFloat)left
                      top:(CGFloat)top
                cellWidth:(CGFloat)cellWidth
               cellHeight:(CGFloat)cellHeight
{
    (void) which;
    left /= window->ns.xscale;
    top /= window->ns.yscale;
    cellWidth /= window->ns.xscale;
    cellHeight /= window->ns.yscale;
    debug_key(@"updateIMEState: %f, %f, %f, %f\n", left, top, cellWidth, cellHeight);
    const NSRect frame = [window->ns.view frame];
    const NSRect rectInView = NSMakeRect(left,
                                         frame.size.height - top - cellHeight,
                                         cellWidth, cellHeight);
    markedRect = [window->ns.object convertRectToScreen: rectInView];
}

- (NSArray*)validAttributesForMarkedText
{
    return [NSArray array];
}

- (NSAttributedString*)attributedSubstringForProposedRange:(NSRange)range
                                               actualRange:(NSRangePointer)actualRange
{
    (void)range; (void)actualRange;
    return nil;
}

- (NSUInteger)characterIndexForPoint:(NSPoint)point
{
    (void)point;
    return 0;
}

- (NSRect)firstRectForCharacterRange:(NSRange)range
                         actualRange:(NSRangePointer)actualRange
{
    (void)range; (void)actualRange;
    return markedRect;
}

- (void)insertText:(id)string replacementRange:(NSRange)replacementRange
{
    (void)replacementRange;
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
    (void)selector;
}

@end
// }}}

// GLFW window class {{{

@interface GLFWWindow : NSWindow {
    _GLFWwindow* glfw_window;
}

- (instancetype)initWithGlfwWindow:(NSRect)contentRect
                         styleMask:(NSWindowStyleMask)style
                           backing:(NSBackingStoreType)backingStoreType
                        initWindow:(_GLFWwindow *)initWindow;

- (void) removeGLFWWindow;
@end

@implementation GLFWWindow

- (instancetype)initWithGlfwWindow:(NSRect)contentRect
                         styleMask:(NSWindowStyleMask)style
                           backing:(NSBackingStoreType)backingStoreType
                        initWindow:(_GLFWwindow *)initWindow
{
    self = [super initWithContentRect:contentRect styleMask:style backing:backingStoreType defer:NO];
    if (self != nil) glfw_window = initWindow;
    return self;
}

- (void) removeGLFWWindow
{
    glfw_window = NULL;
}


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
    if (glfw_window && glfw_window->ns.toggleFullscreenCallback && glfw_window->ns.toggleFullscreenCallback((GLFWwindow*)glfw_window) == 1)
            return;
    [super toggleFullScreen:sender];
}

@end
// }}}


// Create the Cocoa window
//
static bool createNativeWindow(_GLFWwindow* window,
                                   const _GLFWwndconfig* wndconfig,
                                   const _GLFWfbconfig* fbconfig)
{
    window->ns.delegate = [[GLFWWindowDelegate alloc] initWithGlfwWindow:window];
    if (window->ns.delegate == nil)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to create window delegate");
        return false;
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
        initWithGlfwWindow:contentRect
                  styleMask:getStyleMask(window)
                    backing:NSBackingStoreBuffered
                 initWindow:window
    ];

    if (window->ns.object == nil)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Cocoa: Failed to create window");
        return false;
    }

    if (window->monitor)
        [window->ns.object setLevel:NSMainMenuWindowLevel + 1];
    else
    {
        [(NSWindow*) window->ns.object center];
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
        [window->ns.object setFrameAutosaveName:@(wndconfig->ns.frameName)];

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
    [window->ns.object setTitle:@(wndconfig->title)];
    [window->ns.object setDelegate:window->ns.delegate];
    [window->ns.object setAcceptsMouseMovedEvents:YES];
    [window->ns.object setRestorable:NO];

    _glfwPlatformGetWindowSize(window, &window->ns.width, &window->ns.height);
    _glfwPlatformGetFramebufferSize(window, &window->ns.fbWidth, &window->ns.fbHeight);

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
    window->ns.deadKeyState = 0;
    if (!_glfw.ns.finishedLaunching)
    {
        [NSApp run];
        _glfw.ns.finishedLaunching = true;
    }

    if (!createNativeWindow(window, wndconfig, fbconfig))
        return false;

    if (ctxconfig->client != GLFW_NO_API)
    {
        if (ctxconfig->source == GLFW_NATIVE_CONTEXT_API)
        {
            if (!_glfwInitNSGL())
                return false;
            if (!_glfwCreateContextNSGL(window, ctxconfig, fbconfig))
                return false;
        }
        else if (ctxconfig->source == GLFW_EGL_CONTEXT_API)
        {
            // EGL implementation on macOS use CALayer* EGLNativeWindowType so we
            // need to get the layer for EGL window surface creation.
            [window->ns.view setWantsLayer:YES];
            window->ns.layer = [window->ns.view layer];

            if (!_glfwInitEGL())
                return false;
            if (!_glfwCreateContextEGL(window, ctxconfig, fbconfig))
                return false;
        }
        else if (ctxconfig->source == GLFW_OSMESA_CONTEXT_API)
        {
            if (!_glfwInitOSMesa())
                return false;
            if (!_glfwCreateContextOSMesa(window, ctxconfig, fbconfig))
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

    [window->ns.view removeGLFWWindow];
    [window->ns.view release];
    window->ns.view = nil;

    [window->ns.object removeGLFWWindow];
    [window->ns.object close];
    window->ns.object = nil;
}

void _glfwPlatformSetWindowTitle(_GLFWwindow* window UNUSED, const char* title)
{
    NSString* string = @(title);
    [window->ns.object setTitle:string];
    // HACK: Set the miniwindow title explicitly as setTitle: doesn't update it
    //       if the window lacks NSWindowStyleMaskTitled
    [window->ns.object setMiniwindowTitle:string];
}

void _glfwPlatformSetWindowIcon(_GLFWwindow* window UNUSED,
                                int count UNUSED, const GLFWimage* images UNUSED)
{
    _glfwInputError(GLFW_FEATURE_UNAVAILABLE,
                    "Cocoa: Regular windows do not have icons on macOS");
}

void _glfwPlatformGetWindowPos(_GLFWwindow* window, int* xpos, int* ypos)
{
    const NSRect contentRect =
        [window->ns.object contentRectForFrameRect:[window->ns.object frame]];

    if (xpos)
        *xpos = (int)contentRect.origin.x;
    if (ypos)
        *ypos = (int)_glfwTransformYNS(contentRect.origin.y + contentRect.size.height - 1);
}

void _glfwPlatformSetWindowPos(_GLFWwindow* window, int x, int y)
{
    const NSRect contentRect = [window->ns.view frame];
    const NSRect dummyRect = NSMakeRect(x, _glfwTransformYNS(y + contentRect.size.height - 1), 0, 0);
    const NSRect frameRect = [window->ns.object frameRectForContentRect:dummyRect];
    [window->ns.object setFrameOrigin:frameRect.origin];
}

void _glfwPlatformGetWindowSize(_GLFWwindow* window, int* width, int* height)
{
    const NSRect contentRect = [window->ns.view frame];

    if (width)
        *width = (int)contentRect.size.width;
    if (height)
        *height = (int)contentRect.size.height;
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
        NSRect contentRect =
            [window->ns.object contentRectForFrameRect:[window->ns.object frame]];
        contentRect.origin.y += contentRect.size.height - height;
        contentRect.size = NSMakeSize(width, height);
        [window->ns.object setFrame:[window->ns.object frameRectForContentRect:contentRect]
                            display:YES];
    }
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
    if (numer != GLFW_DONT_CARE && denom != GLFW_DONT_CARE)
        [window->ns.object setContentAspectRatio:NSMakeSize(numer, denom)];
    else
        [window->ns.object setResizeIncrements:NSMakeSize(1.0, 1.0)];
}

void _glfwPlatformSetWindowSizeIncrements(_GLFWwindow* window, int widthincr, int heightincr)
{
    if (widthincr != GLFW_DONT_CARE && heightincr != GLFW_DONT_CARE)
        [window->ns.object setResizeIncrements:NSMakeSize(widthincr, heightincr)];
    else
        [window->ns.object setResizeIncrements:NSMakeSize(1.0, 1.0)];
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
        *left = (int)(contentRect.origin.x - frameRect.origin.x);
    if (top)
        *top = (int)(frameRect.origin.y + frameRect.size.height -
               contentRect.origin.y - contentRect.size.height);
    if (right)
        *right = (int)(frameRect.origin.x + frameRect.size.width -
                 contentRect.origin.x - contentRect.size.width);
    if (bottom)
        *bottom = (int)(contentRect.origin.y - frameRect.origin.y);
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

monotonic_t _glfwPlatformGetDoubleClickInterval(_GLFWwindow* window UNUSED)
{
    return s_double_to_monotonic_t([NSEvent doubleClickInterval]);
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

void _glfwPlatformRequestWindowAttention(_GLFWwindow* window UNUSED)
{
    [NSApp requestUserAttention:NSInformationalRequest];
}

int _glfwPlatformWindowBell(_GLFWwindow* window UNUSED)
{
    NSBeep();
    return true;
}

void _glfwPlatformFocusWindow(_GLFWwindow* window)
{
    // Make us the active application
    // HACK: This is here to prevent applications using only hidden windows from
    //       being activated, but should probably not be done every time any
    //       window is shown
    [NSApp activateIgnoringOtherApps:YES];
    [window->ns.object makeKeyAndOrderFront:nil];
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
            const NSRect contentRect =
                NSMakeRect(xpos, _glfwTransformYNS(ypos + height - 1), width, height);
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

    if (window->monitor)
    {
        [window->ns.object setLevel:NSMainMenuWindowLevel + 1];
        [window->ns.object setHasShadow:NO];

        acquireMonitor(window);
    }
    else
    {
        NSRect contentRect = NSMakeRect(xpos, _glfwTransformYNS(ypos + height - 1),
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
        return false;
    }

    return NSMouseInRect(point,
        [window->ns.object convertRectToScreen:[window->ns.view frame]], NO);
}

int _glfwPlatformFramebufferTransparent(_GLFWwindow* window)
{
    return ![window->ns.object isOpaque] && ![window->ns.view isOpaque];
}

void _glfwPlatformSetWindowResizable(_GLFWwindow* window, bool enabled UNUSED)
{
    [window->ns.object setStyleMask:getStyleMask(window)];
}

void _glfwPlatformSetWindowDecorated(_GLFWwindow* window, bool enabled UNUSED)
{
    [window->ns.object setStyleMask:getStyleMask(window)];
    [window->ns.object makeFirstResponder:window->ns.view];
}

void _glfwPlatformSetWindowFloating(_GLFWwindow* window, bool enabled)
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

void _glfwPlatformSetRawMouseMotion(_GLFWwindow *window UNUSED, bool enabled UNUSED)
{
    _glfwInputError(GLFW_FEATURE_UNIMPLEMENTED,
                    "Cocoa: Raw mouse motion not yet implemented");
}

bool _glfwPlatformRawMouseMotionSupported(void)
{
    return false;
}

void
_glfwDispatchRenderFrame(CGDirectDisplayID displayID) {
    _GLFWwindow *w = _glfw.windowListHead;
    while (w) {
        if (w->ns.renderFrameRequested && displayID == displayIDForWindow(w)) {
            w->ns.renderFrameRequested = false;
            w->ns.renderFrameCallback((GLFWwindow*)w);
        }
        w = w->next;
    }
}

void _glfwPlatformGetCursorPos(_GLFWwindow* window, double* xpos, double* ypos)
{
    const NSRect contentRect = [window->ns.view frame];
    // NOTE: The returned location uses base 0,1 not 0,0
    const NSPoint pos = [window->ns.object mouseLocationOutsideOfEventStream];

    if (xpos)
        *xpos = pos.x;
    if (ypos)
        *ypos = contentRect.size.height - pos.y;
}

void _glfwPlatformSetCursorPos(_GLFWwindow* window, double x, double y)
{
    updateCursorImage(window);

    const NSRect contentRect = [window->ns.view frame];
    // NOTE: The returned location uses base 0,1 not 0,0
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

void _glfwPlatformSetCursorMode(_GLFWwindow* window, int mode UNUSED)
{
    if (_glfwPlatformWindowFocused(window))
        updateCursorMode(window);
}

const char* _glfwPlatformGetNativeKeyName(int keycode)
{
    UInt32 deadKeyState = 0;
    UniChar characters[8];
    UniCharCount characterCount = 0;

    if (UCKeyTranslate([(NSData*) _glfw.ns.unicodeData bytes],
                       keycode,
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

int _glfwPlatformGetNativeKeyForKey(int key)
{
    return _glfw.ns.key_to_keycode[key];
}

int _glfwPlatformCreateCursor(_GLFWcursor* cursor,
                              const GLFWimage* image,
                              int xhot, int yhot, int count)
{
    NSImage* native;
    NSBitmapImageRep* rep;

    native = [[NSImage alloc] initWithSize:NSMakeSize(image->width, image->height)];
    if (native == nil)
        return false;

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
            return false;

        memcpy([rep bitmapData], src->pixels, src->width * src->height * 4);
        [native addRepresentation:rep];
        [rep release];
    }

    cursor->ns.object = [[NSCursor alloc] initWithImage:native
                                                hotSpot:NSMakePoint(xhot, yhot)];

    [native release];
    if (cursor->ns.object == nil)
        return false;
    return true;
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
            return false;
    }
#undef C
#undef U

    if (!cursor->ns.object)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to retrieve standard cursor");
        return false;
    }

    [cursor->ns.object retain];
    return true;
}

void _glfwPlatformDestroyCursor(_GLFWcursor* cursor)
{
    if (cursor->ns.object)
        [(NSCursor*) cursor->ns.object release];
}

void _glfwPlatformSetCursor(_GLFWwindow* window, _GLFWcursor* cursor UNUSED)
{
    if (cursorInContentArea(window))
        updateCursorImage(window);
}

bool _glfwPlatformToggleFullscreen(_GLFWwindow* w, unsigned int flags) {
    NSWindow *window = w->ns.object;
    bool made_fullscreen = true;
    bool traditional = !(flags & 1);
    NSWindowStyleMask sm = [window styleMask];
    bool in_fullscreen = sm & NSWindowStyleMaskFullScreen;
    if (traditional) {
        if (!(in_fullscreen)) {
            sm |= NSWindowStyleMaskBorderless | NSWindowStyleMaskFullScreen;
            [[NSApplication sharedApplication] setPresentationOptions: NSApplicationPresentationAutoHideMenuBar | NSApplicationPresentationAutoHideDock];
        } else {
            made_fullscreen = false;
            sm &= ~(NSWindowStyleMaskBorderless | NSWindowStyleMaskFullScreen);
            [[NSApplication sharedApplication] setPresentationOptions: NSApplicationPresentationDefault];
        }
        [window setStyleMask: sm];
    } else {
        if (in_fullscreen) made_fullscreen = false;
        [window toggleFullScreen: nil];
    }
    return made_fullscreen;
}

void _glfwPlatformSetClipboardString(const char* string)
{
    NSPasteboard* pasteboard = [NSPasteboard generalPasteboard];
    [pasteboard declareTypes:@[NSPasteboardTypeString] owner:nil];
    [pasteboard setString:@(string) forType:NSPasteboardTypeString];
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
    if (_glfw.vk.KHR_surface && _glfw.vk.EXT_metal_surface)
    {
        extensions[0] = "VK_KHR_surface";
        extensions[1] = "VK_EXT_metal_surface";
    }
    else if (_glfw.vk.KHR_surface && _glfw.vk.MVK_macos_surface)
    {
        extensions[0] = "VK_KHR_surface";
        extensions[1] = "VK_MVK_macos_surface";
    }
}

int _glfwPlatformGetPhysicalDevicePresentationSupport(VkInstance instance UNUSED,
                                                      VkPhysicalDevice device UNUSED,
                                                      uint32_t queuefamily UNUSED)
{
    return true;
}

VkResult _glfwPlatformCreateWindowSurface(VkInstance instance,
                                          _GLFWwindow* window,
                                          const VkAllocationCallbacks* allocator,
                                          VkSurfaceKHR* surface)
{
#if MAC_OS_X_VERSION_MAX_ALLOWED >= 101100
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

    VkResult err;

    if (_glfw.vk.EXT_metal_surface)
    {
        VkMetalSurfaceCreateInfoEXT sci;

        PFN_vkCreateMetalSurfaceEXT vkCreateMetalSurfaceEXT;
        vkCreateMetalSurfaceEXT = (PFN_vkCreateMetalSurfaceEXT)
            vkGetInstanceProcAddr(instance, "vkCreateMetalSurfaceEXT");
        if (!vkCreateMetalSurfaceEXT)
        {
            _glfwInputError(GLFW_API_UNAVAILABLE,
                            "Cocoa: Vulkan instance missing VK_EXT_metal_surface extension");
            return VK_ERROR_EXTENSION_NOT_PRESENT;
        }

        memset(&sci, 0, sizeof(sci));
        sci.sType = VK_STRUCTURE_TYPE_METAL_SURFACE_CREATE_INFO_EXT;
        sci.pLayer = window->ns.layer;

        err = vkCreateMetalSurfaceEXT(instance, &sci, allocator, surface);
    }
    else
    {
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

        memset(&sci, 0, sizeof(sci));
        sci.sType = VK_STRUCTURE_TYPE_MACOS_SURFACE_CREATE_INFO_MVK;
        sci.pView = window->ns.view;

        err = vkCreateMacOSSurfaceMVK(instance, &sci, allocator, surface);
    }

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

GLFWAPI void glfwCocoaRequestRenderFrame(GLFWwindow *w, GLFWcocoarenderframefun callback) {
    requestRenderFrame((_GLFWwindow*)w, callback);
}

GLFWAPI void glfwGetCocoaKeyEquivalent(int glfw_key, int glfw_mods, char *cocoa_key, size_t key_sz, int *cocoa_mods) {
    *cocoa_mods = 0;
    memset(cocoa_key, 0, key_sz);

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

    uint32_t utf_8_key = 0;
    unichar utf_16_key = 0;

START_ALLOW_CASE_RANGE
    switch(glfw_key) {
#define K8(ch, name) case GLFW_KEY_##name: utf_8_key = ch; break;
#define K16(ch, name) case GLFW_KEY_##name: utf_16_key = ch; break;
        K8('!', EXCLAM);
        K8('"', DOUBLE_QUOTE);
        K8('#', NUMBER_SIGN);
        K8('$', DOLLAR);
        K8('&', AMPERSAND);
        K8('\'', APOSTROPHE);
        K8('(', PARENTHESIS_LEFT);
        K8(')', PARENTHESIS_RIGHT);
        K8('+', PLUS);
        K8(',', COMMA);
        K8('-', MINUS);
        K8('.', PERIOD);
        K8('/', SLASH);
        K8('0', 0);
        K8('1', 1);
        K8('2', 2);
        K8('3', 3);
        K8('5', 5);
        K8('6', 6);
        K8('7', 7);
        K8('8', 8);
        K8('9', 9);
        K8(':', COLON);
        K8(';', SEMICOLON);
        K8('<', LESS);
        K8('=', EQUAL);
        K8('>', GREATER);
        K8('@', AT);
        K8('[', LEFT_BRACKET);
        K8('\\', BACKSLASH);
        K8(']', RIGHT_BRACKET);
        K8('^', CIRCUMFLEX);
        K8('_', UNDERSCORE);
        K8('`', GRAVE_ACCENT);
        K8('a', A);
        K8('b', B);
        K8('c', C);
        K8('d', D);
        K8('e', E);
        K8('f', F);
        K8('g', G);
        K8('h', H);
        K8('i', I);
        K8('j', J);
        K8('k', K);
        K8('l', L);
        K8('m', M);
        K8('n', N);
        K8('o', O);
        K8('p', P);
        K8('q', Q);
        K8('r', R);
        K8('s', S);
        K8('t', T);
        K8('u', U);
        K8('v', V);
        K8('w', W);
        K8('x', X);
        K8('y', Y);
        K8('z', Z);
        K8(PARAGRAPH_UTF_8, PARAGRAPH);
        K8(MASCULINE_UTF_8, MASCULINE);
        K8(S_SHARP_UTF_8, S_SHARP);
        K8(A_GRAVE_LOWER_CASE_UTF_8, A_GRAVE);
        K8(A_DIAERESIS_LOWER_CASE_UTF_8, A_DIAERESIS);
        K8(A_RING_LOWER_CASE_UTF_8, A_RING);
        K8(AE_LOWER_CASE_UTF_8, AE);
        K8(C_CEDILLA_LOWER_CASE_UTF_8, C_CEDILLA);
        K8(E_GRAVE_LOWER_CASE_UTF_8, E_GRAVE);
        K8(E_ACUTE_LOWER_CASE_UTF_8, E_ACUTE);
        K8(I_GRAVE_LOWER_CASE_UTF_8, I_GRAVE);
        K8(N_TILDE_LOWER_CASE_UTF_8, N_TILDE);
        K8(O_GRAVE_LOWER_CASE_UTF_8, O_GRAVE);
        K8(O_DIAERESIS_LOWER_CASE_UTF_8, O_DIAERESIS);
        K8(O_SLASH_LOWER_CASE_UTF_8, O_SLASH);
        K8(U_GRAVE_LOWER_CASE_UTF_8, U_GRAVE);
        K8(U_DIAERESIS_LOWER_CASE_UTF_8, U_DIAERESIS);
        K8(CYRILLIC_A_LOWER_CASE_UTF_8, CYRILLIC_A);
        K8(CYRILLIC_BE_LOWER_CASE_UTF_8, CYRILLIC_BE);
        K8(CYRILLIC_VE_LOWER_CASE_UTF_8, CYRILLIC_VE);
        K8(CYRILLIC_GHE_LOWER_CASE_UTF_8, CYRILLIC_GHE);
        K8(CYRILLIC_DE_LOWER_CASE_UTF_8, CYRILLIC_DE);
        K8(CYRILLIC_IE_LOWER_CASE_UTF_8, CYRILLIC_IE);
        K8(CYRILLIC_ZHE_LOWER_CASE_UTF_8, CYRILLIC_ZHE);
        K8(CYRILLIC_ZE_LOWER_CASE_UTF_8, CYRILLIC_ZE);
        K8(CYRILLIC_I_LOWER_CASE_UTF_8, CYRILLIC_I);
        K8(CYRILLIC_SHORT_I_LOWER_CASE_UTF_8, CYRILLIC_SHORT_I);
        K8(CYRILLIC_KA_LOWER_CASE_UTF_8, CYRILLIC_KA);
        K8(CYRILLIC_EL_LOWER_CASE_UTF_8, CYRILLIC_EL);
        K8(CYRILLIC_EM_LOWER_CASE_UTF_8, CYRILLIC_EM);
        K8(CYRILLIC_EN_LOWER_CASE_UTF_8, CYRILLIC_EN);
        K8(CYRILLIC_O_LOWER_CASE_UTF_8, CYRILLIC_O);
        K8(CYRILLIC_PE_LOWER_CASE_UTF_8, CYRILLIC_PE);
        K8(CYRILLIC_ER_LOWER_CASE_UTF_8, CYRILLIC_ER);
        K8(CYRILLIC_ES_LOWER_CASE_UTF_8, CYRILLIC_ES);
        K8(CYRILLIC_TE_LOWER_CASE_UTF_8, CYRILLIC_TE);
        K8(CYRILLIC_U_LOWER_CASE_UTF_8, CYRILLIC_U);
        K8(CYRILLIC_EF_LOWER_CASE_UTF_8, CYRILLIC_EF);
        K8(CYRILLIC_HA_LOWER_CASE_UTF_8, CYRILLIC_HA);
        K8(CYRILLIC_TSE_LOWER_CASE_UTF_8, CYRILLIC_TSE);
        K8(CYRILLIC_CHE_LOWER_CASE_UTF_8, CYRILLIC_CHE);
        K8(CYRILLIC_SHA_LOWER_CASE_UTF_8, CYRILLIC_SHA);
        K8(CYRILLIC_SHCHA_LOWER_CASE_UTF_8, CYRILLIC_SHCHA);
        K8(CYRILLIC_HARD_SIGN_LOWER_CASE_UTF_8, CYRILLIC_HARD_SIGN);
        K8(CYRILLIC_YERU_LOWER_CASE_UTF_8, CYRILLIC_YERU);
        K8(CYRILLIC_SOFT_SIGN_LOWER_CASE_UTF_8, CYRILLIC_SOFT_SIGN);
        K8(CYRILLIC_E_LOWER_CASE_UTF_8, CYRILLIC_E);
        K8(CYRILLIC_YU_LOWER_CASE_UTF_8, CYRILLIC_YU);
        K8(CYRILLIC_YA_LOWER_CASE_UTF_8, CYRILLIC_YA);
        K8(CYRILLIC_IO_LOWER_CASE_UTF_8, CYRILLIC_IO);

        K8(0x35, ESCAPE);
        K8('\r', ENTER);
        K8('\t', TAB);
        K16(NSBackspaceCharacter, BACKSPACE);
        K16(NSInsertFunctionKey, INSERT);
        K16(NSDeleteCharacter, DELETE);
        K16(NSLeftArrowFunctionKey, LEFT);
        K16(NSRightArrowFunctionKey, RIGHT);
        K16(NSUpArrowFunctionKey, UP);
        K16(NSDownArrowFunctionKey, DOWN);
        K16(NSPageUpFunctionKey, PAGE_UP);
        K16(NSPageDownFunctionKey, PAGE_DOWN);
        K16(NSHomeFunctionKey, HOME);
        K16(NSEndFunctionKey, END);
        K16(NSPrintFunctionKey, PRINT_SCREEN);
        case GLFW_KEY_F1 ... GLFW_KEY_F24:
            utf_16_key = NSF1FunctionKey + (glfw_key - GLFW_KEY_F1); break;
#undef K8
#undef K16
END_ALLOW_CASE_RANGE
    }
    if (utf_16_key != 0) {
         strncpy(cocoa_key, [[NSString stringWithCharacters:&utf_16_key length:1] UTF8String], key_sz - 1);
    } else {
        unsigned str_pos = 0;
        for (unsigned i = 0; i < 4 && str_pos < key_sz - 1; i++) {
            uint8_t byte = (utf_8_key >> 24) & 0xff;
            utf_8_key <<= 8;
            if (byte != 0) cocoa_key[str_pos++] = byte;
        }
        cocoa_key[str_pos] = 0;
    }
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

// Transforms a y-coordinate between the CG display and NS screen spaces
//
float _glfwTransformYNS(float y)
{
    return CGDisplayBounds(CGMainDisplayID()).size.height - y - 1;
}

void _glfwCocoaPostEmptyEvent(void) {
    NSEvent* event = [NSEvent otherEventWithType:NSEventTypeApplicationDefined
                                        location:NSMakePoint(0, 0)
                                   modifierFlags:0
                                       timestamp:0
                                    windowNumber:0
                                         context:nil
                                         subtype:0
                                           data1:0
                                           data2:0];
    [NSApp postEvent:event atStart:YES];
}
