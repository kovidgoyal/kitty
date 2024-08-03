/*
 * desktop.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "safe-wrappers.h"
#include "cleanup.h"
#include "loop-utils.h"
#include "threading.h"
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

static void* libcanberra_handle = NULL;
static void *canberra_ctx = NULL;
FUNC(ca_context_create, int, void**);
FUNC(ca_context_destroy, int, void*);
FUNC(ca_context_play_full, int, void*, uint32_t, void*, void(*)(void), void*);
typedef int (*ca_context_play_func)(void*, uint32_t, ...); static ca_context_play_func ca_context_play = NULL;
typedef int (*ca_context_change_props_func)(void*, ...); static ca_context_change_props_func ca_context_change_props = NULL;

static PyObject*
load_libcanberra_functions(void) {
    LOAD_FUNC(libcanberra_handle, ca_context_create);
    LOAD_FUNC(libcanberra_handle, ca_context_play);
    LOAD_FUNC(libcanberra_handle, ca_context_play_full);
    LOAD_FUNC(libcanberra_handle, ca_context_destroy);
    LOAD_FUNC(libcanberra_handle, ca_context_change_props);
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
        canberra_ctx = NULL;
        dlclose(libcanberra_handle); libcanberra_handle = NULL;
    } else {
        if (ca_context_change_props(canberra_ctx, "application.name", "kitty Terminal", "application.id", "kitty", NULL) != 0) {
            fprintf(stderr, "Failed to set basic properties on libcanberra context, cannot play beep sound\n");
        }
    }
}

typedef struct {
    char *which_sound, *event_id, *media_role, *theme_name;
    bool is_path;
} CanberraEvent;

static pthread_t canberra_thread;
static int canberra_pipe_r = -1, canberra_pipe_w = -1;
static pthread_mutex_t canberra_lock;
static CanberraEvent current_sound = {0};

static void
free_canberra_event_fields(CanberraEvent *e) {
    free(e->which_sound); e->which_sound = NULL;
    free(e->event_id); e->event_id = NULL;
    free(e->media_role); e->media_role = NULL;
    free(e->theme_name); e->theme_name = NULL;
}

static void
play_current_sound(void) {
    CanberraEvent e;
    pthread_mutex_lock(&canberra_lock);
    e = current_sound;
    current_sound = (const CanberraEvent){ 0 };
    pthread_mutex_unlock(&canberra_lock);
    if (e.which_sound && e.event_id && e.media_role) {
        const char *which_type = e.is_path ? "media.filename" : "event.id";
        ca_context_play(
            canberra_ctx, 0,
            which_type, e.which_sound,
            "event.description", e.event_id,
            "media.role", e.media_role,
            "canberra.xdg-theme.name", e.theme_name,
            NULL
        );
        free_canberra_event_fields(&e);
    }
}

static void
queue_canberra_sound(const char *which_sound, const char *event_id, bool is_path, const char *media_role, const char *theme_name) {
    pthread_mutex_lock(&canberra_lock);
    current_sound.which_sound = strdup(which_sound);
    current_sound.event_id = strdup(event_id);
    current_sound.media_role = strdup(media_role);
    current_sound.is_path = is_path;
    current_sound.theme_name = theme_name ? strdup(theme_name) : NULL;
    pthread_mutex_unlock(&canberra_lock);
    while (true) {
        ssize_t ret = write(canberra_pipe_w, "w", 1);
        if (ret < 0) {
            if (errno == EINTR) continue;
            log_error("Failed to write to canberra wakeup fd with error: %s", strerror(errno));
        }
        break;
    }
}

static void*
canberra_play_loop(void *x UNUSED) {
    // canberra hangs on misconfigured systems. We dont want kitty to hang so use a thread.
    // For example: https://github.com/kovidgoyal/kitty/issues/5646
    static char buf[16];
    set_thread_name("LinuxAudioSucks");
    while (true) {
        int ret = read(canberra_pipe_r, buf, sizeof(buf));
        if (ret < 0) {
            if (errno == EINTR || errno == EAGAIN) continue;
            break;
        }
        play_current_sound();
    }
    safe_close(canberra_pipe_r, __FILE__, __LINE__);
    return NULL;
}

void
play_canberra_sound(const char *which_sound, const char *event_id, bool is_path, const char *media_role, const char *theme_name) {
    load_libcanberra();
    if (libcanberra_handle == NULL || canberra_ctx == NULL) return;
    int ret;
    if (canberra_pipe_r == -1) {
        int fds[2];
        if ((ret = pthread_mutex_init(&canberra_lock, NULL)) != 0) return;
        if (!self_pipe(fds, false)) return;
        canberra_pipe_r = fds[0]; canberra_pipe_w = fds[1];
        int flags = fcntl(canberra_pipe_w, F_GETFL);
        fcntl(canberra_pipe_w, F_SETFL, flags | O_NONBLOCK);
        if ((ret = pthread_create(&canberra_thread, NULL, canberra_play_loop, NULL)) != 0) return;
    }
    queue_canberra_sound(which_sound, event_id, is_path, media_role, theme_name);
}

static PyObject*
play_desktop_sound_async(PyObject *self UNUSED, PyObject *args, PyObject *kw) {
    const char *which, *event_id = "test sound";
    const char *theme_name = OPT(bell_theme);
    if (!theme_name || !theme_name[0]) theme_name = "__custom";
    int is_path = 0;
    static const char* kwlist[] = {"sound_name", "event_id", "is_path", "theme_name", NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kw, "s|sps", (char**)kwlist, &which, &event_id, &is_path, &theme_name)) return NULL;
    play_canberra_sound(which, event_id, is_path, "event", theme_name);
    Py_RETURN_NONE;
}

static void
finalize(void) {
    if (libsn_handle) dlclose(libsn_handle);
    libsn_handle = NULL;
    if (canberra_pipe_w > -1) {
        pthread_mutex_lock(&canberra_lock);
        free_canberra_event_fields(&current_sound);
        pthread_mutex_unlock(&canberra_lock);
        safe_close(canberra_pipe_w, __FILE__, __LINE__);
    }
    if (canberra_ctx) ca_context_destroy(canberra_ctx);
    canberra_ctx = NULL;
    if (libcanberra_handle) dlclose(libcanberra_handle);
}

static PyMethodDef module_methods[] = {
    METHODB(init_x11_startup_notification, METH_VARARGS),
    METHODB(end_x11_startup_notification, METH_VARARGS),
    {"play_desktop_sound_async", (PyCFunction)(void(*)(void))play_desktop_sound_async, METH_VARARGS | METH_KEYWORDS, ""},

    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_desktop(PyObject *m) {
    if (PyModule_AddFunctions(m, module_methods) != 0) return false;
    register_at_exit_cleanup_func(DESKTOP_CLEANUP_FUNC, finalize);
    return true;
}
