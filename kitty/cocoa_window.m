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
    NSView *native_view = (NSView*)PyLong_AsVoidPtr(window_id);
    NSWindow* window = [native_view window];
    [window setStyleMask:
        [window styleMask] & ~NSWindowStyleMaskTitled];
    Py_RETURN_NONE;
}
