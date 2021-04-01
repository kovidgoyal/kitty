/*
 * desktop.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "cleanup.h"
#include <dlfcn.h>

#define FUNC(name, restype, ...) typedef restype (*name##_func)(__VA_ARGS__); static name##_func name = NULL
#define LOAD_FUNC(handle, name) {\
    *(void **) (&name) = dlsym(handle, #name); \
    if (!name) { \
        const char* error = dlerror(); \
        if (error != NULL) { \
            PyErr_Format(PyExc_OSError, "Failed to load the function %s with error: %s", #name, error); dlclose(handle); handle = NULL; return NULL; \
        } \
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
    if (!done) {
        done = true;

        const char* libnames[] = {
#if defined(_KITTY_STARTUP_NOTIFICATION_LIBRARY)
            _KITTY_STARTUP_NOTIFICATION_LIBRARY,
#else
            "libstartup-notification-1.so",
            // some installs are missing the .so symlink, so try the full name
            "libstartup-notification-1.so.0",
            "libstartup-notification-1.so.0.0.0",
#endif
            NULL
        };
        for (int i = 0; libnames[i]; i++) {
            libsn_handle = dlopen(libnames[i], RTLD_LAZY);
            if (libsn_handle) break;
        }
        if (libsn_handle == NULL) {
            PyErr_Format(PyExc_OSError, "Failed to load %s with error: %s", libnames[0], dlerror());
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

static void* libcanberra_handle = NULL;
static void *canberra_ctx = NULL;
FUNC(ca_context_create, int, void**);
FUNC(ca_context_destroy, int, void*);
typedef int (*ca_context_play_func)(void*, uint32_t, ...); static ca_context_play_func ca_context_play = NULL;

static PyObject*
load_libcanberra_functions(void) {
    LOAD_FUNC(libcanberra_handle, ca_context_create);
    LOAD_FUNC(libcanberra_handle, ca_context_play);
    LOAD_FUNC(libcanberra_handle, ca_context_destroy);
    return NULL;
}

static void
load_libcanberra(void) {
    static bool done = false;
    if (done) return;
    done = true;
    const char* libnames[] = {
#if defined(_KITTY_CANBERRA_LIBRARY)
        _KITTY_CANBERRA_LIBRARY,
#else
        "libcanberra.so",
        // some installs are missing the .so symlink, so try the full name
        "libcanberra.so.0",
        "libcanberra.so.0.2.5",
#endif
        NULL
    };
    for (int i = 0; libnames[i]; i++) {
        libcanberra_handle = dlopen(libnames[i], RTLD_LAZY);
        if (libcanberra_handle) break;
    }
    if (libcanberra_handle == NULL) {
        fprintf(stderr, "Failed to load %s, cannot play beep sound, with error: %s\n", libnames[0], dlerror());
        return;
    }
    load_libcanberra_functions();
    if (PyErr_Occurred()) {
        PyErr_Print();
        dlclose(libcanberra_handle); libcanberra_handle = NULL;
        return;
    }
    if (ca_context_create(&canberra_ctx) != 0) {
        fprintf(stderr, "Failed to create libcanberra context, cannot play beep sound\n");
        ca_context_destroy(canberra_ctx); canberra_ctx = NULL;
        dlclose(libcanberra_handle); libcanberra_handle = NULL;
    }
}

void
play_canberra_sound(const char *which_sound, const char *event_id) {
    load_libcanberra();
    if (libcanberra_handle == NULL || canberra_ctx == NULL) return;
    ca_context_play(
        canberra_ctx, 0,
        "event.id", which_sound,
        "event.description", event_id,
        NULL
    );
}

static void
finalize(void) {
    if (libsn_handle) dlclose(libsn_handle);
    libsn_handle = NULL;
    if (canberra_ctx) ca_context_destroy(canberra_ctx);
    canberra_ctx = NULL;
    if (libcanberra_handle) dlclose(libcanberra_handle);
}

bool
init_desktop(PyObject *m) {
    if (PyModule_AddFunctions(m, module_methods) != 0) return false;
    register_at_exit_cleanup_func(DESKTOP_CLEANUP_FUNC, finalize);
    return true;
}
