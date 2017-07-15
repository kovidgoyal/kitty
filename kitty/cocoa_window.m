/*
 * cocoa_window.m
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */


#include "data-types.h"
#include <Cocoa/Cocoa.h>
#include <AvailabilityMacros.h>

#if (MAC_OS_X_VERSION_MAX_ALLOWED < 101200)
#define NSWindowStyleMaskTitled NSTitledWindowMask 
#endif

PyObject*
cocoa_hide_titlebar(PyObject UNUSED *self, PyObject *window_id) {
    NSWindow *window = (NSWindow*)PyLong_AsVoidPtr(window_id);
    
    @try {
        [window setStyleMask:
            [window styleMask] & ~NSWindowStyleMaskTitled];
    } @catch (NSException *e) {
        return PyErr_Format(PyExc_ValueError, "Failed to set style mask: %s: %s", [[e name] UTF8String], [[e reason] UTF8String]);
    }
    Py_RETURN_NONE;
}


PyObject*
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
