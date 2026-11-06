/*
 * startup-timing.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "startup-timing.h"
#include <stdarg.h>

static struct {
    bool enabled;
    monotonic_t launch_time, previous;
} st = {0};

static double
as_ms(monotonic_t t) {
    return (double)t / 1e6;
}

bool
startup_timing_enabled(void) {
    return st.enabled;
}

static void
vprint(monotonic_t at, const char *fmt, va_list args) {
    fprintf(stderr, "[startup] %8.2f ms (+%7.2f ms) ", as_ms(at - st.launch_time), as_ms(at - st.previous));
    vfprintf(stderr, fmt, args);
    fputc('\n', stderr);
    fflush(stderr);
    st.previous = at;
}

static void
print_at(monotonic_t at, const char *fmt, ...) {
    va_list args;
    va_start(args, fmt);
    vprint(at, fmt, args);
    va_end(args);
}

void
startup_timing(const char *fmt, ...) {
    if (!st.enabled) return;
    const monotonic_t now = monotonic_clock_now();
    va_list args;
    va_start(args, fmt);
    vprint(now, fmt, args);
    va_end(args);
}

void
startup_timing_thread(const char *name, monotonic_t start, monotonic_t end) {
    if (!st.enabled) return;
    fprintf(
        stderr,
        "[startup]                         %s ran in a thread from %.2f ms to %.2f ms, taking %.2f ms\n",
        name,
        as_ms(start - st.launch_time),
        as_ms(end - st.launch_time),
        as_ms(end - start));
    fflush(stderr);
}

void
startup_timing_frame_presented(void) {
    if (!st.enabled) return;
    startup_timing("First frame presented");
    st.enabled = false;
}

static PyObject *
set_startup_timing(PyObject *self UNUSED, PyObject *args) {
    long long launch_time = 0, python_initialized_time = 0;
    if (!PyArg_ParseTuple(args, "LL", &launch_time, &python_initialized_time)) return NULL;
    st.enabled = true;
    // Without times from the launcher, use the time at which this module was loaded
    const bool has_launch_time = launch_time > 0;
    st.launch_time = has_launch_time ? launch_time : monotonic_start_time;
    st.previous = st.launch_time;
    if (has_launch_time) {
        print_at(st.launch_time, "Process started");
        if (python_initialized_time > 0) print_at(python_initialized_time, "Python interpreter initialized");
    } else print_at(st.launch_time, "The fast_data_types module was loaded, the process start time is unknown");
    Py_RETURN_NONE;
}

static PyObject *
py_startup_timing(PyObject *self UNUSED, PyObject *msg) {
    if (!PyUnicode_Check(msg)) {
        PyErr_SetString(PyExc_TypeError, "msg must be a string");
        return NULL;
    }
    if (st.enabled) startup_timing("%s", PyUnicode_AsUTF8(msg));
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    METHODB(set_startup_timing, METH_VARARGS), {"startup_timing", (PyCFunction)py_startup_timing, METH_O, ""}, {NULL, NULL, 0, NULL} /* Sentinel */
};

bool
init_startup_timing(PyObject *module) {
    return PyModule_AddFunctions(module, module_methods) == 0;
}
