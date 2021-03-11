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

@end // GLFWHelper

// Delegate for application related notifications {{{

@interface GLFWApplicationDelegate : NSObject <NSApplicationDelegate>
@end

@implementation GLFWApplicationDelegate

- (NSApplicationTerminateReply)applicationShouldTerminate:(NSApplication *)sender
{
    (void)sender;
    if (_glfw.callbacks.application_close) _glfw.callbacks.application_close(0);
    return NSTerminateCancel;
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
    if (finish_launching_callback)
        finish_launching_callback();
}

- (BOOL)application:(NSApplication *)theApplication openFile:(NSString *)filename {
    (void)theApplication;
    if (!filename || !_glfw.ns.file_open_callback) return NO;
    const char *path = NULL;
    @try {
        path = [[NSFileManager defaultManager] fileSystemRepresentationWithPath: filename];
    } @catch(NSException *exc) {
        NSLog(@"Converting openFile filename: %@ failed with error: %@", filename, exc.reason);
        return NO;
    }
    if (!path) return NO;
    return _glfw.ns.file_open_callback(path);
}

- (void)application:(NSApplication *)sender openFiles:(NSArray *)filenames {
    (void)sender;
    if (!_glfw.ns.file_open_callback || !filenames) return;
    for (id x in filenames) {
        NSString *filename = x;
        const char *path = NULL;
        @try {
            path = [[NSFileManager defaultManager] fileSystemRepresentationWithPath: filename];
        } @catch(NSException *exc) {
            NSLog(@"Converting openFiles filename: %@ failed with error: %@", filename, exc.reason);
        }
        if (path) _glfw.ns.file_open_callback(path);
    }
}

- (void)applicationDidFinishLaunching:(NSNotification *)notification
{
    (void)notification;
    [NSApp stop:nil];
    if (_glfw.ns.file_open_callback) _glfw.ns.file_open_callback(":cocoa::application launched::");

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

static inline bool
is_ctrl_tab(NSEvent *event, NSEventModifierFlags modifierFlags) {
    if (
            (modifierFlags == NSEventModifierFlagControl &&
                [event.charactersIgnoringModifiers isEqualToString:@"\t"]) ||
            (modifierFlags == (NSEventModifierFlagControl | NSEventModifierFlagShift) &&
                [event.charactersIgnoringModifiers isEqualToString:@"\x19"])
       ) return true;
    return false;
}

static inline bool
is_cmd_period(NSEvent *event, NSEventModifierFlags modifierFlags) {
    if (modifierFlags != NSEventModifierFlagCommand) return false;
    if ([event.charactersIgnoringModifiers isEqualToString:@"."]) return true;
    return false;
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

int _glfwPlatformInit(void)
{
    @autoreleasepool {

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

    NSEvent* (^keydown_block)(NSEvent*) = ^ NSEvent* (NSEvent* event)
    {
        NSEventModifierFlags modifierFlags = [event modifierFlags] & NSEventModifierFlagDeviceIndependentFlagsMask;
        if (is_ctrl_tab(event, modifierFlags) || is_cmd_period(event, modifierFlags)) {
            // Cocoa swallows Ctrl+Tab to cycle between views
            [[NSApp keyWindow].contentView keyDown:event];
        }

        return event;
    };

    NSEvent* (^keyup_block)(NSEvent*) = ^ NSEvent* (NSEvent* event)
    {
        NSEventModifierFlags modifierFlags = [event modifierFlags] & NSEventModifierFlagDeviceIndependentFlagsMask;
        if (modifierFlags & NSEventModifierFlagCommand) {
            // From http://cocoadev.com/index.pl?GameKeyboardHandlingAlmost
            // This works around an AppKit bug, where key up events while holding
            // down the command key don't get sent to the key window.
            [[NSApp keyWindow] sendEvent:event];
        }
        if (is_ctrl_tab(event, modifierFlags) || is_cmd_period(event, modifierFlags)) {
            // Cocoa swallows Ctrl+Tab to cycle between views
            [[NSApp keyWindow].contentView keyUp:event];
        }

        return event;
    };

    _glfw.ns.keyUpMonitor =
        [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyUp
                                              handler:keyup_block];
    _glfw.ns.keyDownMonitor =
        [NSEvent addLocalMonitorForEventsMatchingMask:NSEventMaskKeyDown
                                              handler:keydown_block];

    if (_glfw.hints.init.ns.chdir)
        changeToResourcesDirectory();

    NSDictionary* defaults = @{
        // Press and Hold prevents some keys from emitting repeated characters
        @"ApplePressAndHoldEnabled": @NO,
        // Dont generate openFile events from command line arguments
        @"NSTreatUnknownArgumentsAsOpen": @"NO",
    };
    [[NSUserDefaults standardUserDefaults] registerDefaults:defaults];

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
        [_glfw.ns.helper release];
        _glfw.ns.helper = nil;
    }

    if (_glfw.ns.keyUpMonitor)
        [NSEvent removeMonitor:_glfw.ns.keyUpMonitor];
    if (_glfw.ns.keyDownMonitor)
        [NSEvent removeMonitor:_glfw.ns.keyDownMonitor];

    free(_glfw.ns.clipboardString);

    _glfwTerminateNSGL();

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


void _glfwDispatchTickCallback() {
    if (tick_lock && tick_callback) {
        [tick_lock lock];
        while(tick_callback_requested) {
            tick_callback_requested = false;
            tick_callback(tick_callback_data);
        }
        [tick_lock unlock];
    }
}

static void
request_tick_callback() {
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

static inline void
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
