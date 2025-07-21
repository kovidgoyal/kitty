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
#include <sys/param.h> // For MAXPATHLEN
#include <pthread.h>

// Needed for _NSGetProgname
#include <crt_externs.h>

// Change to our application bundle's resources directory, if present
//
static void changeToResourcesDirectory(void)
{
    char resourcesPath[MAXPATHLEN];

    CFBundleRef bundle = CFBundleGetMainBundle();
    if (!bundle)
        return;

    CFURLRef resourcesURL = CFBundleCopyResourcesDirectoryURL(bundle);

    CFStringRef last = CFURLCopyLastPathComponent(resourcesURL);
    if (CFStringCompare(CFSTR("Resources"), last, 0) != kCFCompareEqualTo)
    {
        CFRelease(last);
        CFRelease(resourcesURL);
        return;
    }

    CFRelease(last);

    if (!CFURLGetFileSystemRepresentation(resourcesURL,
                                          true,
                                          (UInt8*) resourcesPath,
                                          MAXPATHLEN))
    {
        CFRelease(resourcesURL);
        return;
    }

    CFRelease(resourcesURL);

    chdir(resourcesPath);
}

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
        id name = bundleInfo[nameKeys[i]];
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
            appName = @(*progname);
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

// Retrieve Unicode data for the current keyboard layout
//
static bool updateUnicodeDataNS(void)
{
    if (_glfw.ns.inputSource)
    {
        CFRelease(_glfw.ns.inputSource);
        _glfw.ns.inputSource = NULL;
        _glfw.ns.unicodeData = nil;
    }

    for (_GLFWwindow *window = _glfw.windowListHead;  window;  window = window->next)
        window->ns.deadKeyState = 0;

    _glfw.ns.inputSource = TISCopyCurrentKeyboardLayoutInputSource();
    if (!_glfw.ns.inputSource)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to retrieve keyboard layout input source");
        return false;
    }

    _glfw.ns.unicodeData =
        TISGetInputSourceProperty(_glfw.ns.inputSource,
                                  kTISPropertyUnicodeKeyLayoutData);
    if (!_glfw.ns.unicodeData)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to retrieve keyboard layout Unicode data");
        return false;
    }

    return true;
}

// Load HIToolbox.framework and the TIS symbols we need from it
//
static bool initializeTIS(void)
{
    // This works only because Cocoa has already loaded it properly
    _glfw.ns.tis.bundle =
        CFBundleGetBundleWithIdentifier(CFSTR("com.apple.HIToolbox"));
    if (!_glfw.ns.tis.bundle)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to load HIToolbox.framework");
        return false;
    }

    CFStringRef* kPropertyUnicodeKeyLayoutData =
        CFBundleGetDataPointerForName(_glfw.ns.tis.bundle,
                                      CFSTR("kTISPropertyUnicodeKeyLayoutData"));
    *(void **)&_glfw.ns.tis.CopyCurrentKeyboardLayoutInputSource =
        CFBundleGetFunctionPointerForName(_glfw.ns.tis.bundle,
                                          CFSTR("TISCopyCurrentKeyboardLayoutInputSource"));
    *(void **)&_glfw.ns.tis.GetInputSourceProperty =
        CFBundleGetFunctionPointerForName(_glfw.ns.tis.bundle,
                                          CFSTR("TISGetInputSourceProperty"));
    *(void **)&_glfw.ns.tis.GetKbdType =
        CFBundleGetFunctionPointerForName(_glfw.ns.tis.bundle,
                                          CFSTR("LMGetKbdType"));

    if (!kPropertyUnicodeKeyLayoutData ||
        !TISCopyCurrentKeyboardLayoutInputSource ||
        !TISGetInputSourceProperty ||
        !LMGetKbdType)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to load TIS API symbols");
        return false;
    }

    _glfw.ns.tis.kPropertyUnicodeKeyLayoutData =
        *kPropertyUnicodeKeyLayoutData;

    return updateUnicodeDataNS();
}

static void
display_reconfigured(CGDirectDisplayID display UNUSED, CGDisplayChangeSummaryFlags flags, void *userInfo UNUSED)
{
    if (flags & kCGDisplayBeginConfigurationFlag) {
        return;
    }
    if (flags & kCGDisplaySetModeFlag) {
        // GPU possibly changed
    }
}

static NSDictionary<NSString*,NSNumber*> *global_shortcuts = nil;

@interface GLFWHelper : NSObject
@end

@implementation GLFWHelper

- (void)selectedKeyboardInputSourceChanged:(NSObject* )object
{
    (void)object;
    updateUnicodeDataNS();
}

- (void)doNothing:(id)object
{
    (void)object;
}

// watch for settings change and rebuild global_shortcuts using key/value observing on NSUserDefaults
- (void)observeValueForKeyPath:(NSString *)keyPath ofObject:(id)object change:(NSDictionary *)change context:(void *)context
{
    (void)keyPath; (void)object; (void)change; (void)context;
    if (global_shortcuts != nil) {
        [global_shortcuts release];
        global_shortcuts = nil;
    }
}

@end // GLFWHelper

// Delegate for application related notifications {{{

@interface GLFWApplicationDelegate : NSObject <NSApplicationDelegate>
@end

@implementation GLFWApplicationDelegate

- (void)applicationDidActivate:(NSNotification *)notification {
    NSRunningApplication *app = notification.userInfo[NSWorkspaceApplicationKey];
    if (app && app.processIdentifier != getpid()) {
        _glfw.ns.previous_front_most_application = app.processIdentifier;
        debug_rendering("Front most application changed to: %s pid: %d\n", app.bundleIdentifier.UTF8String, app.processIdentifier)
    }
}

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender
{
    (void)sender;
    if (_glfw.callbacks.application_close) _glfw.callbacks.application_close(0);
    return NSTerminateCancel;
}

- (BOOL)applicationSupportsSecureRestorableState:(NSApplication *)app {
    return YES;
}

static GLFWapplicationshouldhandlereopenfun handle_reopen_callback = NULL;

- (BOOL)applicationShouldHandleReopen:(NSApplication *)sender hasVisibleWindows:(BOOL)flag
{
    (void)sender;
    if (!handle_reopen_callback) return YES;
    if (handle_reopen_callback(flag)) return YES;
    return NO;
}

- (void)applicationDidChangeScreenParameters:(NSNotification *) notification
{
    (void)notification;
    _GLFWwindow* window;

    for (window = _glfw.windowListHead;  window;  window = window->next)
    {
        if (window->context.client != GLFW_NO_API)
            [window->context.nsgl.object update];
    }

    _glfwPollMonitorsNS();
}

static GLFWapplicationwillfinishlaunchingfun finish_launching_callback = NULL;

- (void)applicationWillFinishLaunching:(NSNotification *)notification
{
    (void)notification;
    if (_glfw.hints.init.ns.menubar)
    {
        // In case we are unbundled, make us a proper UI application
        [NSApp setActivationPolicy:NSApplicationActivationPolicyRegular];

        // Menu bar setup must go between sharedApplication and finishLaunching
        // in order to properly emulate the behavior of NSApplicationMain

        if ([[NSBundle mainBundle] pathForResource:@"MainMenu" ofType:@"nib"])
        {
            [[NSBundle mainBundle] loadNibNamed:@"MainMenu"
                                          owner:NSApp
                                topLevelObjects:&_glfw.ns.nibObjects];
        }
        else
            createMenuBar();
    }
    if (finish_launching_callback) finish_launching_callback(false);
}

- (BOOL)application:(NSApplication *)sender openFile:(NSString *)filename {
    (void)sender;
    if (!filename || !_glfw.ns.url_open_callback) return NO;
    const char *url = NULL;
    @try {
        url = [[[NSURL fileURLWithPath:filename] absoluteString] UTF8String];
    } @catch(NSException *exc) {
        NSLog(@"Converting openFile filename: %@ failed with error: %@", filename, exc.reason);
        return NO;
    }
    if (!url) return NO;
    return _glfw.ns.url_open_callback(url);
}

- (void)application:(NSApplication *)sender openFiles:(NSArray *)filenames {
    (void)sender;
    if (!_glfw.ns.url_open_callback || !filenames) return;
    for (id x in filenames) {
        NSString *filename = x;
        const char *url = NULL;
        @try {
            url = [[[NSURL fileURLWithPath:filename] absoluteString] UTF8String];
        } @catch(NSException *exc) {
            NSLog(@"Converting openFiles filename: %@ failed with error: %@", filename, exc.reason);
        }
        if (url) _glfw.ns.url_open_callback(url);
    }
}

// Remove openFile and openFiles when the minimum supported macOS version is 10.13
- (void)application:(NSApplication *)sender openURLs:(NSArray<NSURL *> *)urls
{
    (void)sender;
    if (!_glfw.ns.url_open_callback || !urls) return;
    for (id x in urls) {
        NSURL *ns_url = x;
        const char *url = NULL;
        @try {
            url = [[ns_url absoluteString] UTF8String];
        } @catch(NSException *exc) {
            NSLog(@"Converting openURLs url: %@ failed with error: %@", ns_url, exc.reason);
        }
        if (url) _glfw.ns.url_open_callback(url);
    }
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification
{
    if (finish_launching_callback) finish_launching_callback(true);
    (void)notification;
    [NSApp stop:nil];

    CGDisplayRegisterReconfigurationCallback(display_reconfigured, NULL);
    _glfwCocoaPostEmptyEvent();
}

- (void)applicationWillTerminate:(NSNotification *)aNotification
{
    (void)aNotification;
    CGDisplayRemoveReconfigurationCallback(display_reconfigured, NULL);
}

- (void)applicationDidHide:(NSNotification *)notification
{
    (void)notification;
    int i;

    for (i = 0;  i < _glfw.monitorCount;  i++)
        _glfwRestoreVideoModeNS(_glfw.monitors[i]);
}

@end // GLFWApplicationDelegate
// }}}


@interface GLFWApplication : NSApplication
- (void)tick_callback;
- (void)render_frame_received:(id)displayIDAsID;
@end

@implementation GLFWApplication
- (void)tick_callback
{
    _glfwDispatchTickCallback();
}

- (void)render_frame_received:(id)displayIDAsID
{
    CGDirectDisplayID displayID = [(NSNumber*)displayIDAsID unsignedIntValue];
    _glfwDispatchRenderFrame(displayID);
}

@end


//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

void* _glfwLoadLocalVulkanLoaderNS(void)
{
    CFBundleRef bundle = CFBundleGetMainBundle();
    if (!bundle)
        return NULL;

    CFURLRef url =
        CFBundleCopyAuxiliaryExecutableURL(bundle, CFSTR("libvulkan.1.dylib"));
    if (!url)
        return NULL;

    char path[PATH_MAX];
    void* handle = NULL;

    if (CFURLGetFileSystemRepresentation(url, true, (UInt8*) path, sizeof(path) - 1))
        handle = _glfw_dlopen(path);

    CFRelease(url);
    return handle;
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

/**
 * Apple Symbolic HotKeys Ids
 * To find this symbolic hot keys indices do:
 * 1. open Terminal
 * 2. restore defaults in System Preferences > Keyboard > Shortcuts
 * 3. defaults read com.apple.symbolichotkeys > current.txt
 * 4. enable/disable given symbolic hot key in System Preferences > Keyboard > Shortcuts
 * 5. defaults read com.apple.symbolichotkeys | diff -C 5 current.txt -
 * 6. restore defaults in System Preferences > Keyboard > Shortcuts
 */
typedef enum AppleShortcutNames {
    // launchpad & dock
    kSHKTurnDockHidingOnOrOff                   = 52,   // Opt, Cmd, D
    kSHKShowLaunchpad                           = 160,  //

    // display
    kSHKDecreaseDisplayBrightness1              = 53,   // F14 (Fn)
    kSHKDecreaseDisplayBrightness2              = 55,   // F14 (Fn, Ctrl)
    kSHKIncreaseDisplayBrightness1              = 54,   // F15 (Fn)
    kSHKIncreaseDisplayBrightness2              = 56,   // F15 (Fn, Ctrl)

    // mission control
    kSHKMissionControl                          = 32,   // Ctrl, Arrow Up
    kSHKShowNotificationCenter                  = 163,  //
    kSHKTurnDoNotDisturbOnOrOff                 = 175,  //
    kSHKApplicationWindows                      = 33,   // Ctrl, Arrow Down
    kSHKShowDesktop                             = 36,   // F11
    kSHKMoveLeftASpace                          = 79,   // Ctrl, Arrow Left
    kSHKMoveRightASpace                         = 81,   // Ctrl, Arrow Right
    kSHKSwitchToDesktop1                        = 118,  // Ctrl, 1
    kSHKSwitchToDesktop2                        = 119,  // Ctrl, 2
    kSHKSwitchToDesktop3                        = 120,  // Ctrl, 3
    kSHKSwitchToDesktop4                        = 121,  // Ctrl, 4
    kSHKQuickNote                               = 190,  // Fn, Q

    // keyboard
    kSHKChangeTheWayTabMovesFocus               = 13,   // Ctrl, F7
    kSHKTurnKeyboardAccessOnOrOff               = 12,   // Ctrl, F1
    kSHKMoveFocusToTheMenuBar                   = 7,    // Ctrl, F2
    kSHKMoveFocusToTheDock                      = 8,    // Ctrl, F3
    kSHKMoveFocusToActiveOrNextWindow           = 9,    // Ctrl, F4
    kSHKMoveFocusToTheWindowToolbar             = 10,   // Ctrl, F5
    kSHKMoveFocusToTheFloatingWindow            = 11,   // Ctrl, F6
    kSHKMoveFocusToNextWindow                   = 27,   // Cmd, `
    kSHKMoveFocusToStatusMenus                  = 57,   // Ctrl, F8

    // input sources
    kSHKSelectThePreviousInputSource            = 60,   // Ctrl, Space bar
    kSHKSelectNextSourceInInputMenu             = 61,   // Ctrl, Opt, Space bar

    // screenshots
    kSHKSavePictureOfScreenAsAFile              = 28,   // Shift, Cmd, 3
    kSHKCopyPictureOfScreenToTheClipboard       = 29,   // Ctrl, Shift, Cmd, 3
    kSHKSavePictureOfSelectedAreaAsAFile        = 30,   // Shift, Cmd, 4
    kSHKCopyPictureOfSelectedAreaToTheClipboard = 31,   // Ctrl, Shift, Cmd, 4
    kSHKScreenshotAndRecordingOptions           = 184,  // Shift, Cmd, 5

    // spotlight
    kSHKShowSpotlightSearch                     = 64,   // Cmd, Space bar
    kSHKShowFinderSearchWindow                  = 65,   // Opt, Cmd, Space bar

    // accessibility
    kSHKTurnZoomOnOrOff                         = 15,   // Opt, Cmd, 8
    kSHKTurnImageSmoothingOnOrOff               = 23,   // Opt, Cmd, Backslash "\"
    kSHKZoomOut                                 = 19,   // Opt, Cmd, -
    kSHKZoomIn                                  = 17,   // Opt, Cmd, =
    kSHKTurnFocusFollowingOnOrOff               = 179,  //

    kSHKIncreaseContrast                        = 25,   // Ctrl, Opt, Cmd, .
    kSHKDecreaseContrast                        = 26,   // Ctrl, Opt, Cmd, ,

    kSHKInvertColors                            = 21,   // Ctrl, Opt, Cmd, 8
    kSHKTurnVoiceOverOnOrOff                    = 59,   // Cmd, F5
    kSHKShowAccessibilityControls               = 162,  // Opt, Cmd, F5

    // app shortcuts
    kSHKShowHelpMenu                            = 98,   // Shift, Cmd, /

    // deprecated (Not shown on macOS Monterey)
    kSHKMoveFocusToTheWindowDrawer              = 51,   // Opt, Cmd, `
    kSHKShowDashboard                           = 62,   // F12
    kSHKLookUpInDictionary                      = 70,   // Shift, Cmd, E
    kSHKHideAndShowFrontRow                     = 73,   // Cmd, Esc
    kSHKActivateSpaces                          = 75,   // F8

    // unknown
    kSHKUnknown                                 = 0,    //
} AppleShortcutNames;

static bool
is_shiftable_shortcut(int scv) {
    return scv == kSHKMoveFocusToActiveOrNextWindow || scv == kSHKMoveFocusToNextWindow;
}

#define USEFUL_MODS(x) (x & (NSEventModifierFlagShift | NSEventModifierFlagOption | NSEventModifierFlagCommand | NSEventModifierFlagControl | NSEventModifierFlagFunction))

static void
build_global_shortcuts_lookup(void) {
    // dump these in a terminal with: defaults read com.apple.symbolichotkeys
    NSMutableDictionary<NSString*, NSNumber*> *temp = [NSMutableDictionary dictionaryWithCapacity:128];  // will be autoreleased
    NSMutableSet<NSNumber*> *temp_configured = [NSMutableSet setWithCapacity:128];  // will be autoreleased
    NSMutableSet<NSNumber*> *temp_missing_value = [NSMutableSet setWithCapacity:128];  // will be autoreleased
    NSDictionary *apple_settings = [[NSUserDefaults standardUserDefaults] persistentDomainForName:@"com.apple.symbolichotkeys"];
    if (apple_settings) {
        NSDictionary<NSString*, id> *symbolic_hotkeys = [apple_settings objectForKey:@"AppleSymbolicHotKeys"];
        if (symbolic_hotkeys) {
            for (NSString *key in symbolic_hotkeys) {
                id obj = symbolic_hotkeys[key];
                if (![key isKindOfClass:[NSString class]] || ![obj isKindOfClass:[NSDictionary class]]) continue;
                NSInteger sc = [key integerValue];
                NSDictionary *sc_value = obj;
                id enabled = [sc_value objectForKey:@"enabled"];
                if (!enabled || ![enabled isKindOfClass:[NSNumber class]]) continue;
                [temp_configured addObject:@(sc)];
                if (![enabled boolValue]) continue;
                id v = [sc_value objectForKey:@"value"];
                if (!v || ![v isKindOfClass:[NSDictionary class]]) {
                    if ([enabled boolValue]) [temp_missing_value addObject:@(sc)];
                    continue;
                }
                NSDictionary *value = v;
                id t = [value objectForKey:@"type"];
                if (!t || ![t isKindOfClass:[NSString class]] || ![t isEqualToString:@"standard"]) continue;
                id p = [value objectForKey:@"parameters"];
                if (!p || ![p isKindOfClass:[NSArray class]] || [(NSArray*)p count] < 2) continue;
                NSArray<NSNumber*> *parameters = p;
                NSInteger ch = [parameters[0] isKindOfClass:[NSNumber class]] ? [parameters[0] integerValue] : 0xffff;
                NSInteger vk = [parameters[1] isKindOfClass:[NSNumber class]] ? [parameters[1] integerValue] : 0xffff;
                NSEventModifierFlags mods = ([parameters count] > 2 && [parameters[2] isKindOfClass:[NSNumber class]]) ? [parameters[2] unsignedIntegerValue] : 0;
                mods = USEFUL_MODS(mods);
                static char buf[64];
#define S(x, k) snprintf(buf, sizeof(buf) - 1, #x":%lx:%ld", (unsigned long)mods, (long)k)
                if (ch == 0xffff) { if (vk == 0xffff) continue; S(v, vk); } else S(c, ch);
                temp[@(buf)] = @(sc);
                // the move to next window shortcuts also respond to the same shortcut + shift
                if (is_shiftable_shortcut([key intValue]) && !(mods & NSEventModifierFlagShift)) {
                    mods |= NSEventModifierFlagShift;
                    if (ch == 0xffff) S(v, vk); else S(c, ch);
                    temp[@(buf)] = @(sc);
                }
#undef S
            }
        }
    }

    // Add global shortcut definitions when the default enabled shortcut is not defined,
    // or when the default enabled shortcut is not disabled and is missing a value.
    // Here are the shortcuts that are enabled by default in the standard ANSI (US) layout.
    // macOS provides separate configurations for some languages or keyboards.
    // In general, the rules here will not take effect.
    static char buf[64];
#define S(i, t, m, k) if ([temp_configured member:@(i)] == nil || [temp_missing_value member:@(i)] != nil) { \
        snprintf(buf, sizeof(buf) - 1, #t":%lx:%ld", (unsigned long)m, (long)k); \
        temp[@(buf)] = @(i); \
    }

    // launchpad & dock
    S(kSHKTurnDockHidingOnOrOff, c, (NSEventModifierFlagOption | NSEventModifierFlagCommand), 'd'); // Opt, Cmd, D
    // mission control
    S(kSHKMissionControl, v, NSEventModifierFlagControl, 126); // Ctrl, Arrow Up
    S(kSHKApplicationWindows, v, NSEventModifierFlagControl, 125); // Ctrl, Arrow Down
    // keyboard
    S(kSHKMoveFocusToTheMenuBar, v, NSEventModifierFlagControl, 120); // Ctrl, F2
    S(kSHKMoveFocusToTheDock, v, NSEventModifierFlagControl, 99); // Ctrl, F3
    S(kSHKMoveFocusToActiveOrNextWindow, v, NSEventModifierFlagControl, 118); // Ctrl, F4
    S(kSHKMoveFocusToActiveOrNextWindow, v, (NSEventModifierFlagShift | NSEventModifierFlagControl), 118); // Shift, Ctrl, F4
    S(kSHKMoveFocusToNextWindow, c, NSEventModifierFlagCommand, 96); // Cmd, `
    S(kSHKMoveFocusToNextWindow, c, (NSEventModifierFlagShift | NSEventModifierFlagCommand), 96); // Shift, Cmd, `
    S(kSHKMoveFocusToStatusMenus, v, NSEventModifierFlagControl, 100); // Ctrl, F8
    // input sources
    S(kSHKSelectThePreviousInputSource, c, NSEventModifierFlagControl, 32); // Ctrl, Space bar
    S(kSHKSelectNextSourceInInputMenu, c, (NSEventModifierFlagControl | NSEventModifierFlagOption), 32); // Ctrl, Opt, Space bar
    // spotlight
    S(kSHKShowSpotlightSearch, c, NSEventModifierFlagCommand, 32); // Cmd, Space bar
    S(kSHKShowFinderSearchWindow, c, (NSEventModifierFlagOption | NSEventModifierFlagCommand), 32); // Opt, Cmd, Space bar

#undef S
    global_shortcuts = [[NSDictionary dictionaryWithDictionary:temp] retain];
    /* NSLog(@"global_shortcuts: %@", global_shortcuts); */
}

static int
is_active_apple_global_shortcut(NSEvent *event) {
    if (global_shortcuts == nil) build_global_shortcuts_lookup();
    NSEventModifierFlags modifierFlags = USEFUL_MODS([event modifierFlags]);
    static char lookup_key[64];
#define LOOKUP(t, k) \
    snprintf(lookup_key, sizeof(lookup_key) - 1, #t":%lx:%ld", (unsigned long)modifierFlags, (long)k); \
    NSNumber *sc = global_shortcuts[@(lookup_key)]; \
    if (sc != nil) return [sc intValue]; \

    if ([event.charactersIgnoringModifiers length] == 1) {
        if (modifierFlags & NSEventModifierFlagShift) {
            const uint32_t ch_without_shift = vk_to_unicode_key_with_current_layout([event keyCode]);
            if (ch_without_shift < GLFW_FKEY_FIRST || ch_without_shift > GLFW_FKEY_LAST) {
                LOOKUP(c, ch_without_shift);
            }
        }
        const unichar ch = [event.charactersIgnoringModifiers characterAtIndex:0];
        LOOKUP(c, ch);
    }
    unsigned short vk = [event keyCode];
    if (vk != 0xffff) {
        LOOKUP(v, vk);
    }
#undef LOOKUP
    return kSHKUnknown;
}

static bool
is_useful_apple_global_shortcut(int sc) {
    switch(sc) {
        // launchpad & dock
        case kSHKTurnDockHidingOnOrOff:                   // Opt, Cmd, D
        case kSHKShowLaunchpad:                           //

        // display
        case kSHKDecreaseDisplayBrightness1:              // F14 (Fn)
        case kSHKDecreaseDisplayBrightness2:              // F14 (Fn, Ctrl)
        case kSHKIncreaseDisplayBrightness1:              // F15 (Fn)
        case kSHKIncreaseDisplayBrightness2:              // F14 (Fn, Ctrl)

        // mission control
        case kSHKMissionControl:                          // Ctrl, Arrow Up
        case kSHKShowNotificationCenter:                  //
        case kSHKTurnDoNotDisturbOnOrOff:                 //
        case kSHKApplicationWindows:                      // Ctrl, Arrow Down
        case kSHKShowDesktop:                             // F11
        case kSHKMoveLeftASpace:                          // Ctrl, Arrow Left
        case kSHKMoveRightASpace:                         // Ctrl, Arrow Right
        case kSHKSwitchToDesktop1:                        // Ctrl, 1
        case kSHKSwitchToDesktop2:                        // Ctrl, 2
        case kSHKSwitchToDesktop3:                        // Ctrl, 3
        case kSHKSwitchToDesktop4:                        // Ctrl, 4
        case kSHKQuickNote:                               // Fn, Q

        // keyboard
        /* case kSHKChangeTheWayTabMovesFocus:               // Ctrl, F7 */
        /* case kSHKTurnKeyboardAccessOnOrOff:               // Ctrl, F1 */
        case kSHKMoveFocusToTheMenuBar:                   // Ctrl, F2
        case kSHKMoveFocusToTheDock:                      // Ctrl, F3
        case kSHKMoveFocusToActiveOrNextWindow:           // Ctrl, F4
        /* case kSHKMoveFocusToTheWindowToolbar:             // Ctrl, F5 */
        /* case kSHKMoveFocusToTheFloatingWindow:            // Ctrl, F6 */
        case kSHKMoveFocusToNextWindow:                   // Cmd, `
        case kSHKMoveFocusToStatusMenus:                  // Ctrl, F8

        // input sources
        case kSHKSelectThePreviousInputSource:            // Ctrl, Space bar
        case kSHKSelectNextSourceInInputMenu:             // Ctrl, Opt, Space bar

        // screenshots
        /* case kSHKSavePictureOfScreenAsAFile:              // Shift, Cmd, 3 */
        /* case kSHKCopyPictureOfScreenToTheClipboard:       // Ctrl, Shift, Cmd, 3 */
        /* case kSHKSavePictureOfSelectedAreaAsAFile:        // Shift, Cmd, 4 */
        /* case kSHKCopyPictureOfSelectedAreaToTheClipboard: // Ctrl, Shift, Cmd, 4 */
        /* case kSHKScreenshotAndRecordingOptions:           // Shift, Cmd, 5 */

        // spotlight
        case kSHKShowSpotlightSearch:                     // Cmd, Space bar
        case kSHKShowFinderSearchWindow:                  // Opt, Cmd, Space bar

        // accessibility
        /* case kSHKTurnZoomOnOrOff:                         // Opt, Cmd, 8 */
        /* case kSHKTurnImageSmoothingOnOrOff:               // Opt, Cmd, Backslash "\" */
        /* case kSHKZoomOut:                                 // Opt, Cmd, - */
        /* case kSHKZoomIn:                                  // Opt, Cmd, = */
        /* case kSHKTurnFocusFollowingOnOrOff:               // */
        /* case kSHKIncreaseContrast:                        // Ctrl, Opt, Cmd, . */
        /* case kSHKDecreaseContrast:                        // Ctrl, Opt, Cmd, , */
        /* case kSHKInvertColors:                            // Ctrl, Opt, Cmd, 8 */
        /* case kSHKTurnVoiceOverOnOrOff:                    // Cmd, F5 */
        /* case kSHKShowAccessibilityControls:               // Opt, Cmd, F5 */

        // app shortcuts
        /* case kSHKShowHelpMenu:                            // Shift, Cmd, / */

        // deprecated (Not shown on macOS Monterey)
        /* case kSHKMoveFocusToTheWindowDrawer:              // Opt, Cmd, ` */
        /* case kSHKShowDashboard:                           // F12 */
        /* case kSHKLookUpInDictionary:                      // Shift, Cmd, E */
        /* case kSHKHideAndShowFrontRow:                     // Cmd, Esc */
        /* case kSHKActivateSpaces:                          // F8 */
            return true;
        default:
            return false;
    }
}

static bool
is_apple_jis_layout_function_key(NSEvent *event) {
    return [event keyCode] == 0x66 /* kVK_JIS_Eisu */ || [event keyCode] == 0x68 /* kVK_JIS_Kana */;
}

GLFWAPI GLFWapplicationshouldhandlereopenfun glfwSetApplicationShouldHandleReopen(GLFWapplicationshouldhandlereopenfun callback) {
    GLFWapplicationshouldhandlereopenfun previous = handle_reopen_callback;
    handle_reopen_callback = callback;
    return previous;
}

GLFWAPI GLFWapplicationwillfinishlaunchingfun glfwSetApplicationWillFinishLaunching(GLFWapplicationwillfinishlaunchingfun callback) {
    GLFWapplicationwillfinishlaunchingfun previous = finish_launching_callback;
    finish_launching_callback = callback;
    return previous;
}

int _glfwPlatformInit(bool *supports_window_occlusion)
{
    @autoreleasepool {

    *supports_window_occlusion = true;
    _glfw.ns.helper = [[GLFWHelper alloc] init];

    [NSThread detachNewThreadSelector:@selector(doNothing:)
                             toTarget:_glfw.ns.helper
                           withObject:nil];

    if (NSApp)
        _glfw.ns.finishedLaunching = true;

    [GLFWApplication sharedApplication];

    _glfw.ns.delegate = [[GLFWApplicationDelegate alloc] init];
    if (_glfw.ns.delegate == nil)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to create application delegate");
        return false;
    }

    [NSApp setDelegate:_glfw.ns.delegate];
    [[[NSWorkspace sharedWorkspace] notificationCenter]
        addObserver:_glfw.ns.delegate
        selector:@selector(applicationDidActivate:)
        name:NSWorkspaceDidActivateApplicationNotification
        object:nil];
    static struct {
        unsigned short virtual_key_code;
        NSEventModifierFlags input_source_switch_modifiers;
        NSTimeInterval timestamp;
    } last_keydown_shortcut_event;
    last_keydown_shortcut_event.virtual_key_code = 0xffff;
    last_keydown_shortcut_event.input_source_switch_modifiers = 0;

    NSEvent* (^keydown_block)(NSEvent*) = ^ NSEvent* (NSEvent* event)
    {
        debug_key("---------------- key down -------------------\n");
        debug_key("%s\n", [[event description] UTF8String]);
        if (!_glfw.ignoreOSKeyboardProcessing && !_glfw.keyboard_grabbed) {
            // first check if there is a global menu bar shortcut
            if ([[NSApp mainMenu] performKeyEquivalent:event]) {
                debug_key("keyDown triggered global menu bar action ignoring\n");
                last_keydown_shortcut_event.virtual_key_code = [event keyCode];
                last_keydown_shortcut_event.input_source_switch_modifiers = 0;
                last_keydown_shortcut_event.timestamp = [event timestamp];
                return nil;
            }
            // now check if there is a useful apple shortcut
            int global_shortcut = is_active_apple_global_shortcut(event);
            if (is_useful_apple_global_shortcut(global_shortcut)) {
                debug_key("keyDown triggered global macOS shortcut ignoring\n");
                last_keydown_shortcut_event.virtual_key_code = [event keyCode];
                // record the modifier keys if switching to the next input source
                last_keydown_shortcut_event.input_source_switch_modifiers = (global_shortcut == kSHKSelectNextSourceInInputMenu) ? USEFUL_MODS([event modifierFlags]) : 0;
                last_keydown_shortcut_event.timestamp = [event timestamp];
                return event;
            }
            // check for JIS keyboard layout function keys
            if (is_apple_jis_layout_function_key(event)) {
                debug_key("keyDown triggered JIS layout function key ignoring\n");
                last_keydown_shortcut_event.virtual_key_code = [event keyCode];
                last_keydown_shortcut_event.input_source_switch_modifiers = 0;
                last_keydown_shortcut_event.timestamp = [event timestamp];
                return event;
            }
        }
        last_keydown_shortcut_event.virtual_key_code = 0xffff;
        NSWindow *kw = [NSApp keyWindow];
        if (kw && kw.contentView) [kw.contentView keyDown:event];
        else debug_key("keyDown ignored as no keyWindow present\n");
        return nil;
    };

    NSEvent* (^keyup_block)(NSEvent*) = ^ NSEvent* (NSEvent* event)
    {
        debug_key("----------------- key up --------------------\n");
        debug_key("%s\n", [[event description] UTF8String]);
        if (last_keydown_shortcut_event.virtual_key_code != 0xffff && last_keydown_shortcut_event.virtual_key_code == [event keyCode]) {
            // ignore as the corresponding key down event triggered a menu bar or macOS shortcut
            last_keydown_shortcut_event.virtual_key_code = 0xffff;
            debug_key("keyUp ignored as corresponds to previous keyDown that triggered a shortcut\n");
            return nil;
        }
        NSWindow *kw = [NSApp keyWindow];
        if (kw && kw.contentView) [kw.contentView keyUp:event];
        else debug_key("keyUp ignored as no keyWindow present\n");
        return nil;
    };

    NSEvent* (^flags_changed_block)(NSEvent*) = ^ NSEvent* (NSEvent* event)
    {
        debug_key("-------------- flags changed -----------------\n");
        debug_key("%s\n", [[event description] UTF8String]);
        last_keydown_shortcut_event.virtual_key_code = 0xffff;
        // switching to the next input source is only confirmed when all modifier keys are released
        if (last_keydown_shortcut_event.input_source_switch_modifiers) {
            if (!([event modifierFlags] & last_keydown_shortcut_event.input_source_switch_modifiers))
                last_keydown_shortcut_event.input_source_switch_modifiers = 0;
            return event;
        }
        NSWindow *kw = [NSApp keyWindow];
        if (kw && kw.contentView) [kw.contentView flagsChanged:event];
        else debug_key("flagsChanged ignored as no keyWindow present\n");
        return nil;
    };

    _glfw.ns.keyUpMonitor =
        [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyUp
                                              handler:keyup_block];
    _glfw.ns.keyDownMonitor =
        [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown
                                              handler:keydown_block];
    _glfw.ns.flagsChangedMonitor =
        [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskFlagsChanged
                                              handler:flags_changed_block];

    if (_glfw.hints.init.ns.chdir)
        changeToResourcesDirectory();

    NSDictionary* defaults = @{
        // Press and Hold prevents some keys from emitting repeated characters
        @"ApplePressAndHoldEnabled": @NO,
        // Dont generate openFile events from command line arguments
        @"NSTreatUnknownArgumentsAsOpen": @"NO",
    };
    [[NSUserDefaults standardUserDefaults] registerDefaults:defaults];

    NSUserDefaults *apple_settings = [[NSUserDefaults alloc] initWithSuiteName:@"com.apple.symbolichotkeys"];
    [apple_settings addObserver:_glfw.ns.helper
                     forKeyPath:@"AppleSymbolicHotKeys"
                        options:NSKeyValueObservingOptionNew
                        context:NULL];
    _glfw.ns.appleSettings = apple_settings;

    [[NSNotificationCenter defaultCenter]
        addObserver:_glfw.ns.helper
           selector:@selector(selectedKeyboardInputSourceChanged:)
               name:NSTextInputContextKeyboardSelectionDidChangeNotification
             object:nil];

    _glfw.ns.eventSource = CGEventSourceCreate(kCGEventSourceStateHIDSystemState);
    if (!_glfw.ns.eventSource)
        return false;

    CGEventSourceSetLocalEventsSuppressionInterval(_glfw.ns.eventSource, 0.0);

    if (!initializeTIS())
        return false;

    _glfwPollMonitorsNS();
    return true;

    } // autoreleasepool
}

void _glfwPlatformTerminate(void)
{
    @autoreleasepool {

    _glfwClearDisplayLinks();

    if (_glfw.ns.inputSource)
    {
        CFRelease(_glfw.ns.inputSource);
        _glfw.ns.inputSource = NULL;
        _glfw.ns.unicodeData = nil;
    }

    if (_glfw.ns.eventSource)
    {
        CFRelease(_glfw.ns.eventSource);
        _glfw.ns.eventSource = NULL;
    }

    if (_glfw.ns.delegate)
    {
        [NSApp setDelegate:nil];
        [_glfw.ns.delegate release];
        _glfw.ns.delegate = nil;
    }

    if (_glfw.ns.helper)
    {
        [[NSNotificationCenter defaultCenter]
            removeObserver:_glfw.ns.helper
                      name:NSTextInputContextKeyboardSelectionDidChangeNotification
                    object:nil];
        [[NSNotificationCenter defaultCenter]
            removeObserver:_glfw.ns.helper];
        if (_glfw.ns.appleSettings)
            [_glfw.ns.appleSettings removeObserver:_glfw.ns.helper forKeyPath:@"AppleSymbolicHotKeys"];
        [_glfw.ns.helper release];
        _glfw.ns.helper = nil;
    }

    if (_glfw.ns.keyUpMonitor)
        [NSEvent removeMonitor:_glfw.ns.keyUpMonitor];
    if (_glfw.ns.keyDownMonitor)
        [NSEvent removeMonitor:_glfw.ns.keyDownMonitor];
    if (_glfw.ns.flagsChangedMonitor)
        [NSEvent removeMonitor:_glfw.ns.flagsChangedMonitor];

    if (_glfw.ns.appleSettings != nil) {
        [_glfw.ns.appleSettings release];
        _glfw.ns.appleSettings = nil;
    }

    _glfwTerminateNSGL();
    if (global_shortcuts != nil) { [global_shortcuts release]; global_shortcuts = nil; }

    } // autoreleasepool
}

const char* _glfwPlatformGetVersionString(void)
{
    return _GLFW_VERSION_NUMBER " Cocoa NSGL EGL OSMesa"
#if defined(_GLFW_BUILD_DLL)
        " dynamic"
#endif
        ;
}

static GLFWtickcallback tick_callback = NULL;
static void* tick_callback_data = NULL;
static bool tick_callback_requested = false;
static pthread_t main_thread;
static NSLock *tick_lock = NULL;


void _glfwDispatchTickCallback(void) {
    if (tick_lock && tick_callback) {
        while(true) {
            bool do_call = false;
            [tick_lock lock];
            if (tick_callback_requested) { do_call = true; tick_callback_requested = false; }
            [tick_lock unlock];
            if (do_call) tick_callback(tick_callback_data);
            else break;
        }
    }
}

static void
request_tick_callback(void) {
    if (!tick_callback_requested) {
        tick_callback_requested = true;
        [NSApp performSelectorOnMainThread:@selector(tick_callback) withObject:nil waitUntilDone:NO];
    }
}

void _glfwPlatformPostEmptyEvent(void)
{
    if (pthread_equal(pthread_self(), main_thread)) {
        request_tick_callback();
    } else if (tick_lock) {
        [tick_lock lock];
        request_tick_callback();
        [tick_lock unlock];
    }
}


void _glfwPlatformStopMainLoop(void) {
    [NSApp stop:nil];
    _glfwCocoaPostEmptyEvent();
}

void _glfwPlatformRunMainLoop(GLFWtickcallback callback, void* data) {
    main_thread = pthread_self();
    tick_callback = callback;
    tick_callback_data = data;
    tick_lock = [NSLock new];
    [NSApp run];
    [tick_lock release];
    tick_lock = NULL;
    tick_callback = NULL;
    tick_callback_data = NULL;
}


typedef struct {
    NSTimer *os_timer;
    unsigned long long id;
    bool repeats;
    monotonic_t interval;
    GLFWuserdatafun callback;
    void *callback_data;
    GLFWuserdatafun free_callback_data;
} Timer;

static Timer timers[128] = {{0}};
static size_t num_timers = 0;

static void
remove_timer_at(size_t idx) {
    if (idx < num_timers) {
        Timer *t = timers + idx;
        if (t->os_timer) { [t->os_timer invalidate]; t->os_timer = NULL; }
        if (t->callback_data && t->free_callback_data) { t->free_callback_data(t->id, t->callback_data); t->callback_data = NULL; }
        remove_i_from_array(timers, idx, num_timers);
    }
}

static void schedule_timer(Timer *t) {
    t->os_timer = [NSTimer scheduledTimerWithTimeInterval:monotonic_t_to_s_double(t->interval) repeats:(t->repeats ? YES: NO) block:^(NSTimer *os_timer) {
        for (size_t i = 0; i < num_timers; i++) {
            if (timers[i].os_timer == os_timer) {
                timers[i].callback(timers[i].id, timers[i].callback_data);
                if (!timers[i].repeats) remove_timer_at(i);
                break;
            }
        }
    }];
}

unsigned long long _glfwPlatformAddTimer(monotonic_t interval, bool repeats, GLFWuserdatafun callback, void *callback_data, GLFWuserdatafun free_callback) {
    static unsigned long long timer_counter = 0;
    if (num_timers >= sizeof(timers)/sizeof(timers[0]) - 1) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Too many timers added");
        return 0;
    }
    Timer *t = timers + num_timers++;
    t->id = ++timer_counter;
    t->repeats = repeats;
    t->interval = interval;
    t->callback = callback;
    t->callback_data = callback_data;
    t->free_callback_data = free_callback;
    schedule_timer(t);
    return timer_counter;
}

void _glfwPlatformRemoveTimer(unsigned long long timer_id) {
    for (size_t i = 0; i < num_timers; i++) {
        if (timers[i].id == timer_id) {
            remove_timer_at(i);
            break;
        }
    }
}

void _glfwPlatformUpdateTimer(unsigned long long timer_id, monotonic_t interval, bool enabled) {
    for (size_t i = 0; i < num_timers; i++) {
        if (timers[i].id == timer_id) {
            Timer *t = timers + i;
            if (t->os_timer) { [t->os_timer invalidate]; t->os_timer = NULL; }
            t->interval = interval;
            if (enabled) schedule_timer(t);
            break;
        }
    }
}

void _glfwPlatformInputColorScheme(GLFWColorScheme appearance UNUSED) { }
bool _glfwPlatformGrabKeyboard(bool grab UNUSED) { return true; /* directly uses _glfw.keyboard_grabbed */ }
