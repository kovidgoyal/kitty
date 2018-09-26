/*
 * cocoa_window.m
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */


#include "state.h"
#include <Cocoa/Cocoa.h>

#include <AvailabilityMacros.h>
// Needed for _NSGetProgname
#include <crt_externs.h>

#if (MAC_OS_X_VERSION_MAX_ALLOWED < 101200)
#define NSWindowStyleMaskResizable NSResizableWindowMask
#define NSEventModifierFlagOption NSAlternateKeyMask
#define NSEventModifierFlagCommand NSCommandKeyMask
#define NSEventModifierFlagControl NSControlKeyMask
#endif

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
        id name = [infoDictionary objectForKey:name_keys[i]];
        if (name &&
            [name isKindOfClass:[NSString class]] &&
            ![name isEqualToString:@""])
        {
            return name;
        }
    }

    char** progname = _NSGetProgname();
    if (progname && *progname)
        return [NSString stringWithUTF8String:*progname];

    // Really shouldn't get here
    return @"kitty";
}

@interface GlobalMenuTarget : NSObject
+ (GlobalMenuTarget *) shared_instance;
@end

@implementation GlobalMenuTarget

- (void) show_preferences              : (id)sender {
    (void)sender;
    set_cocoa_pending_action(PREFERENCES_WINDOW);
}

- (void) new_os_window              : (id)sender {
    (void)sender;
    set_cocoa_pending_action(NEW_OS_WINDOW);
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

void
cocoa_update_nsgl_context(void* id) {
    NSOpenGLContext *ctx = id;
    [ctx update];
}

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
}

void
cocoa_update_title(PyObject *pytitle) {
    NSString *title = [[NSString alloc] initWithUTF8String:PyUnicode_AsUTF8(pytitle)];
    NSMenu *bar = [NSApp mainMenu];
    if (title_menu != NULL) {
        [bar removeItem:title_menu];
    }
    title_menu = [bar addItemWithTitle:@"" action:NULL keyEquivalent:@""];
    NSMenu *m = [[NSMenu alloc] initWithTitle:[NSString stringWithFormat:@" :: %@", title]];
    [title_menu setSubmenu:m];
    [m release];
    [title release];
}

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

void
cocoa_focus_window(void *w) {
    NSWindow *window = (NSWindow*)w;
    [window makeKeyWindow];
}

bool
cocoa_toggle_fullscreen(void *w, bool traditional) {
    NSWindow *window = (NSWindow*)w;
    bool made_fullscreen = true;
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

static PyObject*
cocoa_get_lang(PyObject UNUSED *self) {
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
}

void
cocoa_set_hide_from_tasks(void) {
    [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
}

void
cocoa_set_titlebar_color(void *w, color_type titlebar_color)
{
    NSWindow *window = (NSWindow *)w;

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
}

static PyMethodDef module_methods[] = {
    {"cocoa_get_lang", (PyCFunction)cocoa_get_lang, METH_NOARGS, ""},
    {"cocoa_set_new_window_trigger", (PyCFunction)cocoa_set_new_window_trigger, METH_VARARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_cocoa(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
