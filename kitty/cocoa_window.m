/*
 * cocoa_window.m
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */


#include "data-types.h"
#include <Cocoa/Cocoa.h>

PyObject*
cocoa_hide_titlebar(PyObject UNUSED *self, PyObject *window_id) {
    NSView *native_view = (NSView*)PyLong_AsVoidPtr(window_id);
    NSWindow* window = [native_view window];
    [window setStyleMask:
        [window styleMask] & ~NSTitledWindowMask];
    Py_RETURN_NONE;
}
