/*
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

bool init_glfw(PyObject *m);

PyObject* glfw_set_error_callback(PyObject UNUSED *self, PyObject *callback);
PyObject* glfw_init(PyObject UNUSED *self);
PyObject* glfw_terminate(PyObject UNUSED *self);
PyObject* glfw_window_hint(PyObject UNUSED *self, PyObject *args);
PyObject* glfw_swap_interval(PyObject UNUSED *self, PyObject *args);
PyObject* glfw_wait_events(PyObject UNUSED *self, PyObject*);
PyObject* glfw_post_empty_event(PyObject UNUSED *self);
PyObject* glfw_get_physical_dpi(PyObject UNUSED *self);
PyObject* glfw_get_key_name(PyObject UNUSED *self, PyObject *args);

#ifdef __APPLE__
PyObject* cocoa_hide_titlebar(PyObject UNUSED *self, PyObject *window_id);
PyObject* cocoa_get_lang(PyObject UNUSED *self);
#define COCOA_HIDE_TITLEBAR {"cocoa_hide_titlebar", (PyCFunction)cocoa_hide_titlebar, METH_O, ""}, 
#define COCOA_GET_LANG {"cocoa_get_lang", (PyCFunction)cocoa_get_lang, METH_NOARGS, ""}, 
#else
#define COCOA_HIDE_TITLEBAR
#define COCOA_GET_LANG
#endif

#define GLFW_FUNC_WRAPPERS \
    {"glfw_set_error_callback", (PyCFunction)glfw_set_error_callback, METH_O, ""}, \
    {"glfw_init", (PyCFunction)glfw_init, METH_NOARGS, ""}, \
    {"glfw_terminate", (PyCFunction)glfw_terminate, METH_NOARGS, ""}, \
    {"glfw_window_hint", (PyCFunction)glfw_window_hint, METH_VARARGS, ""}, \
    {"glfw_swap_interval", (PyCFunction)glfw_swap_interval, METH_VARARGS, ""}, \
    {"glfw_wait_events", (PyCFunction)glfw_wait_events, METH_VARARGS, ""}, \
    {"glfw_post_empty_event", (PyCFunction)glfw_post_empty_event, METH_NOARGS, ""}, \
    {"glfw_get_physical_dpi", (PyCFunction)glfw_get_physical_dpi, METH_NOARGS, ""}, \
    {"glfw_get_key_name", (PyCFunction)glfw_get_key_name, METH_VARARGS, ""}, \
    COCOA_HIDE_TITLEBAR \
    COCOA_GET_LANG

