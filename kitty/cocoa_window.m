/*
 * cocoa_window.m
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */


#include "state.h"
#include "monotonic.h"
#include <Cocoa/Cocoa.h>

#include <AvailabilityMacros.h>
// Needed for _NSGetProgname
#include <crt_externs.h>
#include <objc/runtime.h>

#if (MAC_OS_X_VERSION_MAX_ALLOWED < 101200)
#define NSWindowStyleMaskResizable NSResizableWindowMask
#define NSEventModifierFlagOption NSAlternateKeyMask
#define NSEventModifierFlagCommand NSCommandKeyMask
#define NSEventModifierFlagControl NSControlKeyMask
#endif

typedef int CGSConnectionID;
typedef int CGSWindowID;
typedef int CGSWorkspaceID;
typedef enum _CGSSpaceSelector {
    kCGSSpaceCurrent = 5,
    kCGSSpaceAll = 7
} CGSSpaceSelector;
extern CGSConnectionID _CGSDefaultConnection(void);
CFArrayRef CGSCopySpacesForWindows(CGSConnectionID Connection, CGSSpaceSelector Type, CFArrayRef Windows);

static NSMenuItem* title_menu = NULL;


static NSString*
find_app_name(void) {
    size_t i;
    NSDictionary* infoDictionary = [[NSBundle mainBundle] infoDictionary];

    // Keys to search for as potential application names
    NSString* name_keys[] =
    {
        @"CFBundleDisplayName",
        @"CFBundleName",
        @"CFBundleExecutable",
    };

    for (i = 0;  i < sizeof(name_keys) / sizeof(name_keys[0]);  i++)
    {
        id name = infoDictionary[name_keys[i]];
        if (name &&
            [name isKindOfClass:[NSString class]] &&
            ![name isEqualToString:@""])
        {
            return name;
        }
    }

    char** progname = _NSGetProgname();
    if (progname && *progname)
        return @(*progname);

    // Really shouldn't get here
    return @"kitty";
}

@interface GlobalMenuTarget : NSObject
+ (GlobalMenuTarget *) shared_instance;
@end

@implementation GlobalMenuTarget

- (void) show_preferences              : (id)sender {
    (void)sender;
    set_cocoa_pending_action(PREFERENCES_WINDOW, NULL);
}

- (void) new_os_window              : (id)sender {
    (void)sender;
    set_cocoa_pending_action(NEW_OS_WINDOW, NULL);
}


+ (GlobalMenuTarget *) shared_instance
{
    static GlobalMenuTarget *sharedGlobalMenuTarget = nil;
    @synchronized(self)
    {
        if (!sharedGlobalMenuTarget)
            sharedGlobalMenuTarget = [[GlobalMenuTarget alloc] init];
        return sharedGlobalMenuTarget;
    }
}

@end

static unichar new_window_key = 0;
static NSEventModifierFlags new_window_mods = 0;

static PyObject*
cocoa_set_new_window_trigger(PyObject *self UNUSED, PyObject *args) {
    int mods, key;
    if (!PyArg_ParseTuple(args, "ii", &mods, &key)) return NULL;
    int nwm;
    get_cocoa_key_equivalent(key, mods, &new_window_key, &nwm);
    new_window_mods = nwm;
    if (new_window_key) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

// Implementation of applicationDockMenu: for the app delegate
static NSMenu *dockMenu = nil;
static NSMenu *
get_dock_menu(id self UNUSED, SEL _cmd UNUSED, NSApplication *sender UNUSED) {
    if (!dockMenu) {
        GlobalMenuTarget *global_menu_target = [GlobalMenuTarget shared_instance];
        dockMenu = [[NSMenu alloc] init];
        NSMenuItem *newWindowItem = [dockMenu addItemWithTitle:@"New OS window"
                            action:@selector(new_os_window:)
                            keyEquivalent:@""];
        [newWindowItem setTarget:global_menu_target];
    }
    return dockMenu;
}

static PyObject *notification_activated_callback = NULL;
static PyObject*
set_notification_activated_callback(PyObject *self UNUSED, PyObject *callback) {
    if (notification_activated_callback) Py_DECREF(notification_activated_callback);
    notification_activated_callback = callback;
    Py_INCREF(callback);
    Py_RETURN_NONE;
}

@interface NotificationDelegate : NSObject <NSUserNotificationCenterDelegate>
@end

@implementation NotificationDelegate
    - (void)userNotificationCenter:(NSUserNotificationCenter *)center
            didDeliverNotification:(NSUserNotification *)notification {
        (void)(center); (void)(notification);
    }

    - (BOOL) userNotificationCenter:(NSUserNotificationCenter *)center
            shouldPresentNotification:(NSUserNotification *)notification {
        (void)(center); (void)(notification);
        return YES;
    }

    - (void) userNotificationCenter:(NSUserNotificationCenter *)center
            didActivateNotification:(NSUserNotification *)notification {
        (void)(center); (void)(notification);
        if (notification_activated_callback) {
            PyObject *ret = PyObject_CallFunction(notification_activated_callback, "z",
                    notification.userInfo[@"user_id"] ? [notification.userInfo[@"user_id"] UTF8String] : NULL);
            if (ret == NULL) PyErr_Print();
            else Py_DECREF(ret);
        }
    }
@end

static PyObject*
cocoa_send_notification(PyObject *self UNUSED, PyObject *args) {
    char *identifier = NULL, *title = NULL, *subtitle = NULL, *informativeText = NULL, *path_to_image = NULL;
    if (!PyArg_ParseTuple(args, "zssz|z", &identifier, &title, &informativeText, &path_to_image, &subtitle)) return NULL;
    NSUserNotificationCenter *center = [NSUserNotificationCenter defaultUserNotificationCenter];
    if (!center) {PyErr_SetString(PyExc_RuntimeError, "Failed to get the user notification center"); return NULL; }
    if (!center.delegate) center.delegate = [[NotificationDelegate alloc] init];
    NSUserNotification *n = [NSUserNotification new];
    NSImage *img = nil;
    if (path_to_image) {
        NSString *p = @(path_to_image);
        NSURL *url = [NSURL fileURLWithPath:p];
        img = [[NSImage alloc] initWithContentsOfURL:url];
        [url release]; [p release];
        if (img) {
            [n setValue:img forKey:@"_identityImage"];
            [n setValue:@(false) forKey:@"_identityImageHasBorder"];
        }
        [img release];
    }
#define SET(x) { \
    if (x) { \
        NSString *t = @(x); \
        n.x = t; \
        [t release]; \
    }}
    SET(title); SET(subtitle); SET(informativeText);
#undef SET
    if (identifier) {
        n.userInfo = @{@"user_id": @(identifier)};
    }
    [center deliverNotification:n];
    Py_RETURN_NONE;
}

@interface ServiceProvider : NSObject
@end

@implementation ServiceProvider

- (void)openTab:(NSPasteboard*)pasteboard
        userData:(NSString *) UNUSED userData error:(NSError **) UNUSED error {
    [self openFilesFromPasteboard:pasteboard type:NEW_TAB_WITH_WD];
}

- (void)openOSWindow:(NSPasteboard*)pasteboard
        userData:(NSString *) UNUSED userData  error:(NSError **) UNUSED error {
    [self openFilesFromPasteboard:pasteboard type:NEW_OS_WINDOW_WITH_WD];
}

- (void)openFilesFromPasteboard:(NSPasteboard *)pasteboard type:(int)type {
    NSDictionary *options = @{ NSPasteboardURLReadingFileURLsOnlyKey: @YES };
    NSArray *filePathArray = [pasteboard readObjectsForClasses:[NSArray arrayWithObject:[NSURL class]] options:options];
    for (NSURL *url in filePathArray) {
        NSString *path = [url path];
        BOOL isDirectory = NO;
        if ([[NSFileManager defaultManager] fileExistsAtPath:path isDirectory:&isDirectory]) {
            if (!isDirectory) {
                path = [path stringByDeletingLastPathComponent];
            }
            set_cocoa_pending_action(type, [path UTF8String]);
        }
    }
}

@end

// global menu {{{
void
cocoa_create_global_menu(void) {
    NSString* app_name = find_app_name();
    NSMenu* bar = [[NSMenu alloc] init];
    GlobalMenuTarget *global_menu_target = [GlobalMenuTarget shared_instance];
    [NSApp setMainMenu:bar];

    NSMenuItem* appMenuItem =
        [bar addItemWithTitle:@"" action:NULL keyEquivalent:@""];
    NSMenu* appMenu = [[NSMenu alloc] init];
    [appMenuItem setSubmenu:appMenu];

    [appMenu addItemWithTitle:[NSString stringWithFormat:@"About %@", app_name]
                       action:@selector(orderFrontStandardAboutPanel:)
                       keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    NSMenuItem* preferences_menu_item = [[NSMenuItem alloc] initWithTitle:@"Preferences..." action:@selector(show_preferences:) keyEquivalent:@","], *new_os_window_menu_item = NULL;
    [preferences_menu_item setTarget:global_menu_target];
    [appMenu addItem:preferences_menu_item];
    if (new_window_key) {
        NSString *s = [NSString stringWithCharacters:&new_window_key length:1];
        new_os_window_menu_item = [[NSMenuItem alloc] initWithTitle:@"New OS window" action:@selector(new_os_window:) keyEquivalent:s];
        [new_os_window_menu_item setKeyEquivalentModifierMask:new_window_mods];
        [new_os_window_menu_item setTarget:global_menu_target];
        [appMenu addItem:new_os_window_menu_item];
        [s release];
    }


    [appMenu addItemWithTitle:[NSString stringWithFormat:@"Hide %@", app_name]
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

    NSMenu* servicesMenu = [[NSMenu alloc] init];
    [NSApp setServicesMenu:servicesMenu];
    [[appMenu addItemWithTitle:@"Services"
                       action:NULL
                keyEquivalent:@""] setSubmenu:servicesMenu];
    [servicesMenu release];

    [appMenu addItem:[NSMenuItem separatorItem]];

    [appMenu addItemWithTitle:[NSString stringWithFormat:@"Quit %@", app_name]
                       action:@selector(terminate:)
                       keyEquivalent:@"q"];
    [appMenu release];

    NSMenuItem* windowMenuItem =
        [bar addItemWithTitle:@"" action:NULL keyEquivalent:@""];
    NSMenu* windowMenu = [[NSMenu alloc] initWithTitle:@"Window"];
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

    [windowMenu addItem:[NSMenuItem separatorItem]];
    [[windowMenu addItemWithTitle:@"Enter Full Screen"
                           action:@selector(toggleFullScreen:)
                    keyEquivalent:@"f"]
     setKeyEquivalentModifierMask:NSEventModifierFlagControl | NSEventModifierFlagCommand];
    [NSApp setWindowsMenu:windowMenu];
    [windowMenu release];
    [preferences_menu_item release];
    if (new_os_window_menu_item) {
        [new_os_window_menu_item release];
    }

    [bar release];

    class_addMethod(
            object_getClass([NSApp delegate]),
            @selector(applicationDockMenu:),
            (IMP)get_dock_menu,
            "@@:@");


    [NSApp setServicesProvider:[[[ServiceProvider alloc] init] autorelease]];
}

void
cocoa_update_menu_bar_title(PyObject *pytitle) {
    NSString *title = @(PyUnicode_AsUTF8(pytitle));
    NSMenu *bar = [NSApp mainMenu];
    if (title_menu != NULL) {
        [bar removeItem:title_menu];
    }
    title_menu = [bar addItemWithTitle:@"" action:NULL keyEquivalent:@""];
    NSMenu *m = [[NSMenu alloc] initWithTitle:[NSString stringWithFormat:@" :: %@", title]];
    [title_menu setSubmenu:m];
    [m release];
} // }}}

bool
cocoa_make_window_resizable(void *w, bool resizable) {
    NSWindow *window = (NSWindow*)w;

    @try {
        if (resizable) {
            [window setStyleMask:
                [window styleMask] | NSWindowStyleMaskResizable];
        } else {
            [window setStyleMask:
                [window styleMask] & ~NSWindowStyleMaskResizable];
        }
    } @catch (NSException *e) {
        log_error("Failed to set style mask: %s: %s", [[e name] UTF8String], [[e reason] UTF8String]);
        return false;
    }
    return true;
}

#define NSLeftAlternateKeyMask  (0x000020 | NSEventModifierFlagOption)
#define NSRightAlternateKeyMask (0x000040 | NSEventModifierFlagOption)

bool
cocoa_alt_option_key_pressed(NSUInteger flags) {
    NSUInteger q = (OPT(macos_option_as_alt) == 1) ? NSRightAlternateKeyMask : NSLeftAlternateKeyMask;
    return ((q & flags) == q) ? true : false;
}

void
cocoa_focus_window(void *w) {
    NSWindow *window = (NSWindow*)w;
    [window makeKeyWindow];
}

size_t
cocoa_get_workspace_ids(void *w, size_t *workspace_ids, size_t array_sz) {
    NSWindow *window = (NSWindow*)w;
    if (!window) return 0;
    NSArray *window_array = @[ @([window windowNumber]) ];
    CFArrayRef spaces = CGSCopySpacesForWindows(_CGSDefaultConnection(), kCGSSpaceAll, (__bridge CFArrayRef)window_array);
    CFIndex ans = CFArrayGetCount(spaces);
    if (ans > 0) {
        for (CFIndex i = 0; i < MIN(ans, (CFIndex)array_sz); i++) {
            NSNumber *s = (NSNumber*)CFArrayGetValueAtIndex(spaces, i);
            workspace_ids[i] = [s intValue];
        }
    } else ans = 0;
    CFRelease(spaces);
    return ans;
}

static PyObject*
cocoa_get_lang(PyObject UNUSED *self) {
    @autoreleasepool {

    NSString* locale = nil;
    NSString* lang_code = [[NSLocale currentLocale] objectForKey:NSLocaleLanguageCode];
    NSString* country_code = [[NSLocale currentLocale] objectForKey:NSLocaleCountryCode];
    if (lang_code && country_code) {
        locale = [NSString stringWithFormat:@"%@_%@", lang_code, country_code];
    } else {
        locale = [[NSLocale currentLocale] localeIdentifier];
    }
    if (!locale) { Py_RETURN_NONE; }
    return Py_BuildValue("s", [locale UTF8String]);

    } // autoreleasepool
}

monotonic_t
cocoa_cursor_blink_interval(void) {
    @autoreleasepool {

    NSUserDefaults *defaults = [NSUserDefaults standardUserDefaults];
    double on_period_ms = [defaults doubleForKey:@"NSTextInsertionPointBlinkPeriodOn"];
    double off_period_ms = [defaults doubleForKey:@"NSTextInsertionPointBlinkPeriodOff"];
    double period_ms = [defaults doubleForKey:@"NSTextInsertionPointBlinkPeriod"];
    double max_value = 60 * 1000.0, ans = -1.0;
    if (on_period_ms != 0. || off_period_ms != 0.) {
        ans = on_period_ms + off_period_ms;
    } else if (period_ms != 0.) {
        ans = period_ms;
    }
    return ans > max_value ? 0ll : ms_double_to_monotonic_t(ans);

    } // autoreleasepool
}

void
cocoa_set_activation_policy(bool hide_from_tasks) {
    [NSApp setActivationPolicy:(hide_from_tasks ? NSApplicationActivationPolicyAccessory : NSApplicationActivationPolicyRegular)];
}

void
cocoa_set_titlebar_color(void *w, color_type titlebar_color)
{
    @autoreleasepool {

    NSWindow *window = (NSWindow*)w;

    double red = ((titlebar_color >> 16) & 0xFF) / 255.0;
    double green = ((titlebar_color >> 8) & 0xFF) / 255.0;
    double blue = (titlebar_color & 0xFF) / 255.0;

    NSColor *background =
        [NSColor colorWithSRGBRed:red
                            green:green
                             blue:blue
                            alpha:1.0];
    [window setTitlebarAppearsTransparent:YES];
    [window setBackgroundColor:background];

    double luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue;

    if (luma < 0.5) {
        [window setAppearance:[NSAppearance appearanceNamed:NSAppearanceNameVibrantDark]];
    } else {
        [window setAppearance:[NSAppearance appearanceNamed:NSAppearanceNameVibrantLight]];
    }

    } // autoreleasepool
}

static void
cleanup() {
    @autoreleasepool {

    if (dockMenu) [dockMenu release];
    dockMenu = nil;
    if (notification_activated_callback) Py_DECREF(notification_activated_callback);
    notification_activated_callback = NULL;

    } // autoreleasepool
}

void
cocoa_hide_window_title(void *w)
{
    @autoreleasepool {

    NSWindow *window = (NSWindow*)w;
    [window setTitleVisibility:NSWindowTitleHidden];

    } // autoreleasepool
}

static PyMethodDef module_methods[] = {
    {"cocoa_get_lang", (PyCFunction)cocoa_get_lang, METH_NOARGS, ""},
    {"cocoa_set_new_window_trigger", (PyCFunction)cocoa_set_new_window_trigger, METH_VARARGS, ""},
    {"cocoa_send_notification", (PyCFunction)cocoa_send_notification, METH_VARARGS, ""},
    {"cocoa_set_notification_activated_callback", (PyCFunction)set_notification_activated_callback, METH_O, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_cocoa(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (Py_AtExit(cleanup) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to register the cocoa_window at exit handler");
        return false;
    }
    return true;
}
