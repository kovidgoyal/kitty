/*
 * desktop.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <dlfcn.h>
#include <canberra.h>

#define FUNC(name, restype, ...) typedef restype (*name##_func)(__VA_ARGS__); static name##_func name = NULL
#define LOAD_FUNC(handle, name) {\
    *(void **) (&name) = dlsym(handle, #name); \
    const char* error = dlerror(); \
    if (error != NULL) { \
        PyErr_Format(PyExc_OSError, "Failed to load the function %s with error: %s", #name, error); dlclose(handle); handle = NULL; return NULL; \
    } \
}

FUNC(sn_display_new, void*, void*, void*, void*);
FUNC(sn_launchee_context_new_from_environment, void*, void*, int);
FUNC(sn_launchee_context_new, void*, void*, int, const char*);
FUNC(sn_display_unref, void, void*);
FUNC(sn_launchee_context_setup_window, void, void*, int32_t);
FUNC(sn_launchee_context_complete, void, void*);
FUNC(sn_launchee_context_unref, void, void*);

static void* libsn_handle = NULL;

static PyObject*
init_x11_startup_notification(PyObject UNUSED *self, PyObject *args) {
    static bool done = false;
    static const char* libname = "libstartup-notification-1.so";
    // some installs are missing the .so symlink, so try the full name
    static const char* libname2 = "libstartup-notification-1.so.0";
    static const char* libname3 = "libstartup-notification-1.so.0.0.0";
    if (!done) {
        done = true;

        libsn_handle = dlopen(libname, RTLD_LAZY);
        if (libsn_handle == NULL) libsn_handle = dlopen(libname2, RTLD_LAZY);
        if (libsn_handle == NULL) libsn_handle = dlopen(libname3, RTLD_LAZY);
        if (libsn_handle == NULL) {
            PyErr_Format(PyExc_OSError, "Failed to load %s with error: %s", libname, dlerror());
            return NULL;
        }
        dlerror();    /* Clear any existing error */
#define F(name) LOAD_FUNC(libsn_handle, name)
        F(sn_display_new);
        F(sn_launchee_context_new_from_environment);
        F(sn_launchee_context_new);
        F(sn_display_unref);
        F(sn_launchee_context_setup_window);
        F(sn_launchee_context_complete);
        F(sn_launchee_context_unref);
#undef F
    }

    int window_id;
    PyObject *dp;
    char *startup_id = NULL;
    if (!PyArg_ParseTuple(args, "O!i|z", &PyLong_Type, &dp, &window_id, &startup_id)) return NULL;
    void* display = PyLong_AsVoidPtr(dp);
    void* sn_display = sn_display_new(display, NULL, NULL);
    if (!sn_display) { PyErr_SetString(PyExc_OSError, "Failed to create SnDisplay"); return NULL; }
    void *ctx = startup_id ? sn_launchee_context_new(sn_display, 0, startup_id) : sn_launchee_context_new_from_environment(sn_display, 0);
    sn_display_unref(sn_display);
    if (!ctx) { PyErr_SetString(PyExc_OSError, "Failed to create startup-notification context"); return NULL; }
    sn_launchee_context_setup_window(ctx, window_id);
    return PyLong_FromVoidPtr(ctx);
}

static PyObject*
end_x11_startup_notification(PyObject UNUSED *self, PyObject *args) {
    if (!libsn_handle) Py_RETURN_NONE;
    PyObject *dp;
    if (!PyArg_ParseTuple(args, "O!", &PyLong_Type, &dp)) return NULL;
    void *ctx = PyLong_AsVoidPtr(dp);
    sn_launchee_context_complete(ctx);
    sn_launchee_context_unref(ctx);

    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    METHODB(init_x11_startup_notification, METH_VARARGS),
    METHODB(end_x11_startup_notification, METH_VARARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static ca_context *canberra_ctx = NULL;

void
play_canberra_sound(const char *which_sound, const char *event_id) {
    if (canberra_ctx == NULL) ca_context_create(&canberra_ctx);
    ca_context_play(
        canberra_ctx, 0,
        CA_PROP_EVENT_ID, which_sound,
        CA_PROP_EVENT_DESCRIPTION, event_id,
        NULL
    );
}

static void
finalize(void) {
    if (libsn_handle) dlclose(libsn_handle);
    libsn_handle = NULL;
    if (canberra_ctx) ca_context_destroy(canberra_ctx);
    canberra_ctx = NULL;
}

bool
init_desktop(PyObject *m) {
    if (PyModule_AddFunctions(m, module_methods) != 0) return false;
    if (Py_AtExit(finalize) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to register the desktop.c at exit handler");
        return false;
    }
    return true;
}
