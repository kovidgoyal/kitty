/*
 * cocoa_window.m
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */


#include "state.h"
#include "cleanup.h"
#include "monotonic.h"
#include <Cocoa/Cocoa.h>
#ifndef KITTY_USE_DEPRECATED_MACOS_NOTIFICATION_API
#include <UserNotifications/UserNotifications.h>
#endif

#include <AvailabilityMacros.h>
// Needed for _NSGetProgname
#include <crt_externs.h>
#include <objc/runtime.h>
#include <xlocale.h>

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

#define PENDING(selector, which) - (void)selector:(id)sender { (void)sender; set_cocoa_pending_action(which, NULL); }

@implementation GlobalMenuTarget

PENDING(edit_config_file, PREFERENCES_WINDOW)
PENDING(new_os_window, NEW_OS_WINDOW)
PENDING(detach_tab, DETACH_TAB)
PENDING(close_os_window, CLOSE_OS_WINDOW)
PENDING(close_tab, CLOSE_TAB)
PENDING(new_tab, NEW_TAB)
PENDING(next_tab, NEXT_TAB)
PENDING(previous_tab, PREVIOUS_TAB)
PENDING(new_window, NEW_WINDOW)
PENDING(close_window, CLOSE_WINDOW)

- (void)open_kitty_website_url:(id)sender {
    (void)sender;
    [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:@"https://sw.kovidgoyal.net/kitty/"]];
}

#undef PENDING

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

typedef struct {
    char key[32];
    NSEventModifierFlags mods;
} GlobalShortcut;
typedef struct {
    GlobalShortcut new_os_window, close_os_window, close_tab, edit_config_file;
    GlobalShortcut previous_tab, next_tab, new_tab, new_window, close_window;
} GlobalShortcuts;
static GlobalShortcuts global_shortcuts;

static PyObject*
cocoa_set_global_shortcut(PyObject *self UNUSED, PyObject *args) {
    int mods;
    unsigned int key;
    const char *name;
    if (!PyArg_ParseTuple(args, "siI", &name, &mods, &key)) return NULL;
    GlobalShortcut *gs = NULL;
#define Q(x) if (strcmp(name, #x) == 0) gs = &global_shortcuts.x
    Q(new_os_window); else Q(close_os_window); else Q(close_tab); else Q(edit_config_file);
    else Q(new_tab); else Q(next_tab); else Q(previous_tab);
    else Q(new_window); else Q(close_window);
#undef Q
    if (gs == NULL) { PyErr_SetString(PyExc_KeyError, "Unknown shortcut name"); return NULL; }
    int cocoa_mods;
    get_cocoa_key_equivalent(key, mods, gs->key, 32, &cocoa_mods);
    gs->mods = cocoa_mods;
    if (gs->key[0]) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

// Implementation of applicationDockMenu: for the app delegate
static NSMenu *dockMenu = nil;
static NSMenu *
get_dock_menu(id self UNUSED, SEL _cmd UNUSED, NSApplication *sender UNUSED) {
    if (!dockMenu) {
        GlobalMenuTarget *global_menu_target = [GlobalMenuTarget shared_instance];
        dockMenu = [[NSMenu alloc] init];
        [[dockMenu addItemWithTitle:@"New OS Window"
                             action:@selector(new_os_window:)
                      keyEquivalent:@""]
                          setTarget:global_menu_target];
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

#ifdef KITTY_USE_DEPRECATED_MACOS_NOTIFICATION_API

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
    char *identifier = NULL, *title = NULL, *informativeText = NULL, *subtitle = NULL;
    if (!PyArg_ParseTuple(args, "zsz|z", &identifier, &title, &informativeText, &subtitle)) return NULL;
    NSUserNotificationCenter *center = [NSUserNotificationCenter defaultUserNotificationCenter];
    if (!center) {PyErr_SetString(PyExc_RuntimeError, "Failed to get the user notification center"); return NULL; }
    if (!center.delegate) center.delegate = [[NotificationDelegate alloc] init];
    NSUserNotification *n = [NSUserNotification new];
    if (title) n.title = @(title);
    if (subtitle) n.subtitle = @(subtitle);
    if (informativeText) n.informativeText = @(informativeText);
    if (identifier) {
        n.userInfo = @{@"user_id": @(identifier)};
    }
    [center deliverNotification:n];
    Py_RETURN_NONE;
}

#else

@interface NotificationDelegate : NSObject <UNUserNotificationCenterDelegate>
@end

@implementation NotificationDelegate
    - (void)userNotificationCenter:(UNUserNotificationCenter *)center
            didReceiveNotificationResponse:(UNNotificationResponse *)response
            withCompletionHandler:(void (^)(void))completionHandler {
        (void)(center);
        if (notification_activated_callback) {
            NSString *identifier = [[[response notification] request] identifier];
            PyObject *ret = PyObject_CallFunction(notification_activated_callback, "z",
                    identifier ? [identifier UTF8String] : NULL);
            if (ret == NULL) PyErr_Print();
            else Py_DECREF(ret);
        }
        completionHandler();
    }
@end


static void
schedule_notification(const char *identifier, const char *title, const char *body, const char *subtitle) {
    UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
    if (!center) return;
    // Configure the notification's payload.
    UNMutableNotificationContent* content = [[UNMutableNotificationContent alloc] init];
    if (title) content.title = @(title);
    if (body) content.body = @(body);
    if (subtitle) content.subtitle = @(subtitle);
    // Deliver the notification
    static unsigned long counter = 1;
    UNNotificationRequest* request = [
        UNNotificationRequest requestWithIdentifier:(identifier ? @(identifier) : [NSString stringWithFormat:@"Id_%lu", counter++])
        content:content trigger:nil];
    [center addNotificationRequest:request withCompletionHandler:^(NSError * _Nullable error) {
        if (error != nil) {
            log_error("Failed to show notification: %s", [[error localizedDescription] UTF8String]);
        }
    }];
    [content release];
}


typedef struct {
    char *identifier, *title, *body, *subtitle;
} QueuedNotification;

typedef struct {
    QueuedNotification *notifications;
    size_t count, capacity;
} NotificationQueue;
static NotificationQueue notification_queue = {0};

static void
queue_notification(const char *identifier, const char *title, const char* body, const char* subtitle) {
    ensure_space_for((&notification_queue), notifications, QueuedNotification, notification_queue.count + 16, capacity, 16, true);
    QueuedNotification *n = notification_queue.notifications + notification_queue.count++;
    n->identifier = identifier ? strdup(identifier) : NULL;
    n->title = title ? strdup(title) : NULL;
    n->body = body ? strdup(body) : NULL;
    n->subtitle = subtitle ? strdup(subtitle) : NULL;
}

static void
drain_pending_notifications(BOOL granted) {
    if (granted) {
        for (size_t i = 0; i < notification_queue.count; i++) {
            QueuedNotification *n = notification_queue.notifications + i;
            schedule_notification(n->identifier, n->title, n->body, n->subtitle);
        }
    }
    while(notification_queue.count) {
        QueuedNotification *n = notification_queue.notifications + --notification_queue.count;
        free(n->identifier); free(n->title); free(n->body); free(n->subtitle);
        n->identifier = NULL; n->title = NULL; n->body = NULL; n->subtitle = NULL;
    }
}

static PyObject*
cocoa_send_notification(PyObject *self UNUSED, PyObject *args) {
    char *identifier = NULL, *title = NULL, *body = NULL, *subtitle = NULL;
    if (!PyArg_ParseTuple(args, "zsz|z", &identifier, &title, &body, &subtitle)) return NULL;

    UNUserNotificationCenter *center = [UNUserNotificationCenter currentNotificationCenter];
    if (!center) Py_RETURN_NONE;
    if (!center.delegate) center.delegate = [[NotificationDelegate alloc] init];
    queue_notification(identifier, title, body, subtitle);

    [center requestAuthorizationWithOptions:(UNAuthorizationOptionAlert)
        completionHandler:^(BOOL granted, NSError * _Nullable error) {
            if (error != nil) {
                log_error("Failed to request permission for showing notification: %s", [[error localizedDescription] UTF8String]);
            }
            dispatch_async(dispatch_get_main_queue(), ^{
                drain_pending_notifications(granted);
            });
        }
    ];
    Py_RETURN_NONE;
}

#endif

@interface ServiceProvider : NSObject
@end

@implementation ServiceProvider

- (BOOL)openTab:(NSPasteboard*)pasteboard
        userData:(NSString *) UNUSED userData error:(NSError **) UNUSED error {
    return [self openFilesFromPasteboard:pasteboard type:NEW_TAB_WITH_WD];
}

- (BOOL)openOSWindow:(NSPasteboard*)pasteboard
        userData:(NSString *) UNUSED userData  error:(NSError **) UNUSED error {
    return [self openFilesFromPasteboard:pasteboard type:NEW_OS_WINDOW_WITH_WD];
}

- (BOOL)openFilesFromPasteboard:(NSPasteboard *)pasteboard type:(int)type {
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
    return YES;
}

@end

// global menu {{{
void
cocoa_create_global_menu(void) {
    NSString* app_name = find_app_name();
    NSMenu* bar = [[NSMenu alloc] init];
    GlobalMenuTarget *global_menu_target = [GlobalMenuTarget shared_instance];
    [NSApp setMainMenu:bar];

#define MENU_ITEM(menu, title, name) { \
    NSMenuItem *__mi = [menu addItemWithTitle:title action:@selector(name:) keyEquivalent:@(global_shortcuts.name.key)]; \
    [__mi setKeyEquivalentModifierMask:global_shortcuts.name.mods]; \
    [__mi setTarget:global_menu_target]; \
}

    NSMenuItem* appMenuItem =
        [bar addItemWithTitle:@""
                       action:NULL
                keyEquivalent:@""];
    NSMenu* appMenu = [[NSMenu alloc] init];
    [appMenuItem setSubmenu:appMenu];

    [appMenu addItemWithTitle:[NSString stringWithFormat:@"About %@", app_name]
                       action:@selector(orderFrontStandardAboutPanel:)
                keyEquivalent:@""];
    [appMenu addItem:[NSMenuItem separatorItem]];
    MENU_ITEM(appMenu, @"Preferences…", edit_config_file);

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

    [[appMenu addItemWithTitle:@"Secure Keyboard Entry"
                        action:@selector(toggleSecureInput:)
                 keyEquivalent:@"s"]
        setKeyEquivalentModifierMask:NSEventModifierFlagOption | NSEventModifierFlagCommand];
    [appMenu addItem:[NSMenuItem separatorItem]];

    [appMenu addItemWithTitle:[NSString stringWithFormat:@"Quit %@", app_name]
                       action:@selector(terminate:)
                keyEquivalent:@"q"];
    [appMenu release];

    NSMenuItem* shellMenuItem =
        [bar addItemWithTitle:@"Shell"
                       action:NULL
                keyEquivalent:@""];
    NSMenu* shellMenu = [[NSMenu alloc] initWithTitle:@"Shell"];
    [shellMenuItem setSubmenu:shellMenu];
    MENU_ITEM(shellMenu, @"New OS Window", new_os_window);
    MENU_ITEM(shellMenu, @"New Tab", new_tab);
    MENU_ITEM(shellMenu, @"New Window", new_window);
    [shellMenu addItem:[NSMenuItem separatorItem]];
    MENU_ITEM(shellMenu, @"Close OS Window", close_os_window);
    MENU_ITEM(shellMenu, @"Close Tab", close_tab);
    MENU_ITEM(shellMenu, @"Close Window", close_window);
    [shellMenu release];

    NSMenuItem* windowMenuItem =
        [bar addItemWithTitle:@""
                       action:NULL
                keyEquivalent:@""];
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
    MENU_ITEM(windowMenu, @"Show Previous Tab", previous_tab);
    MENU_ITEM(windowMenu, @"Show Next Tab", next_tab);
    [[windowMenu addItemWithTitle:@"Move Tab to New Window"
                           action:@selector(detach_tab:)
                    keyEquivalent:@""] setTarget:global_menu_target];

    [windowMenu addItem:[NSMenuItem separatorItem]];
    [[windowMenu addItemWithTitle:@"Enter Full Screen"
                           action:@selector(toggleFullScreen:)
                    keyEquivalent:@"f"]
     setKeyEquivalentModifierMask:NSEventModifierFlagControl | NSEventModifierFlagCommand];
    [NSApp setWindowsMenu:windowMenu];
    [windowMenu release];

    NSMenuItem* helpMenuItem =
        [bar addItemWithTitle:@"Help"
                       action:NULL
                keyEquivalent:@""];
    NSMenu* helpMenu = [[NSMenu alloc] initWithTitle:@"Help"];
    [helpMenuItem setSubmenu:helpMenu];
    [[helpMenu addItemWithTitle:[NSString stringWithFormat:@"Visit %@ website", app_name]
                         action:@selector(open_kitty_website_url:)
                  keyEquivalent:@"?"]
                      setTarget:global_menu_target];
    [NSApp setHelpMenu:helpMenu];
    [helpMenu release];

    [bar release];

    class_addMethod(
        object_getClass([NSApp delegate]),
        @selector(applicationDockMenu:),
        (IMP)get_dock_menu,
        "@@:@");


    [NSApp setServicesProvider:[[[ServiceProvider alloc] init] autorelease]];
#undef MENU_ITEM
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
    return (q & flags) == q;
}

void
cocoa_focus_window(void *w) {
    NSWindow *window = (NSWindow*)w;
    [window makeKeyWindow];
}

long
cocoa_window_number(void *w) {
    NSWindow *window = (NSWindow*)w;
    return [window windowNumber];
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
    // Make sure the locale value is valid, that is it can be used
    // to construct an actual locale
    const char* locale_utf8 = [locale UTF8String];
    locale_t test_locale = newlocale(LC_ALL_MASK, locale_utf8, NULL);
    if (!test_locale) { Py_RETURN_NONE; }
    freelocale(test_locale);
    return Py_BuildValue("s", locale_utf8);

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
    Py_CLEAR(notification_activated_callback);

#ifndef KITTY_USE_DEPRECATED_MACOS_NOTIFICATION_API
    drain_pending_notifications(NO);
    free(notification_queue.notifications);
    notification_queue.notifications = NULL;
    notification_queue.capacity = 0;
#endif

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

void
cocoa_system_beep(void) {
    NSBeep();
}

static PyMethodDef module_methods[] = {
    {"cocoa_get_lang", (PyCFunction)cocoa_get_lang, METH_NOARGS, ""},
    {"cocoa_set_global_shortcut", (PyCFunction)cocoa_set_global_shortcut, METH_VARARGS, ""},
    {"cocoa_send_notification", (PyCFunction)cocoa_send_notification, METH_VARARGS, ""},
    {"cocoa_set_notification_activated_callback", (PyCFunction)set_notification_activated_callback, METH_O, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_cocoa(PyObject *module) {
    memset(&global_shortcuts, 0, sizeof(global_shortcuts));
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    register_at_exit_cleanup_func(COCOA_CLEANUP_FUNC, cleanup);
    return true;
}
