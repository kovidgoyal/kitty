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
PyObject* glfw_wait_events(PyObject UNUSED *self);
PyObject* glfw_post_empty_event(PyObject UNUSED *self);
PyObject* glfw_get_physical_dpi(PyObject UNUSED *self);
