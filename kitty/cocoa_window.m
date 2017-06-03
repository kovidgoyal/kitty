/*
 * cocoa_window.m
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */


#include "data-types.h"
#include <Cocoa/Cocoa.h>

#ifndef NSWindowStyleMaskTitled
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
