/*
 * systemd.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "cleanup.h"
#include <dlfcn.h>

#define FUNC(name, restype, ...) typedef restype (*name##_func)(__VA_ARGS__); static name##_func name = NULL
#define LOAD_FUNC(name) {\
    *(void **) (&name) = dlsym(systemd.lib, #name); \
    if (!name) { \
        const char* error = dlerror(); \
        if (error != NULL) { \
            log_error("Failed to load the function %s with error: %s", #name, error); return; \
        } \
    } \
}

typedef struct sd_bus sd_bus;

static struct {
    void *lib;
    sd_bus *user_bus;
    bool initialized, functions_loaded, ok;
} systemd = {0};

typedef struct {
    const char *name;
    const char *message;
    int _need_free;
    int64_t filler;  // just in case systemd ever increases the size of this struct
} sd_bus_error;
typedef struct sd_bus_message sd_bus_message;

FUNC(sd_bus_default_user, int, sd_bus**);
FUNC(sd_bus_message_unref, sd_bus_message*, sd_bus_message*);
FUNC(sd_bus_error_free, void, sd_bus_error*);
FUNC(sd_bus_unref, sd_bus*, sd_bus*);
FUNC(sd_bus_message_new_method_call, int, sd_bus *, sd_bus_message **m, const char *destination, const char *path, const char *interface, const char *member);
FUNC(sd_bus_message_append, int, sd_bus_message *m, const char *types, ...);
FUNC(sd_bus_message_open_container, int, sd_bus_message *m, char type, const char *contents);
FUNC(sd_bus_message_close_container, int, sd_bus_message *m);
FUNC(sd_pid_get_user_slice, int, pid_t pid, char **slice);
FUNC(sd_bus_call, int, sd_bus *bus, sd_bus_message *m, uint64_t usec, sd_bus_error *ret_error, sd_bus_message **reply);

static void
ensure_initialized(void) {
    if (systemd.initialized) return;
    systemd.initialized = true;

    const char* libnames[] = {
#if defined(_KITTY_SYSTEMD_LIBRARY)
        _KITTY_SYSTEMD_LIBRARY,
#else
        "libsystemd.so",
        // some installs are missing the .so symlink, so try the full name
        "libsystemd.so.0",
        "libsystemd.so.0.38.0",
#endif
        NULL
    };
    for (int i = 0; libnames[i]; i++) {
        systemd.lib = dlopen(libnames[i], RTLD_LAZY);
        if (systemd.lib) break;
    }
    if (systemd.lib == NULL) {
        log_error("Failed to load %s with error: %s\n", libnames[0], dlerror());
        return;
    }
    LOAD_FUNC(sd_bus_default_user);
    LOAD_FUNC(sd_bus_message_unref);
    LOAD_FUNC(sd_bus_error_free);
    LOAD_FUNC(sd_bus_unref);
    LOAD_FUNC(sd_bus_message_new_method_call);
    LOAD_FUNC(sd_bus_message_append);
    LOAD_FUNC(sd_bus_message_open_container);
    LOAD_FUNC(sd_bus_message_close_container);
    LOAD_FUNC(sd_pid_get_user_slice);
    LOAD_FUNC(sd_bus_call);
    systemd.functions_loaded = true;

    int ret = sd_bus_default_user(&systemd.user_bus);
    if (ret < 0) { log_error("Failed to open systemd user bus with error: %s", strerror(-ret)); return; }
    systemd.ok = true;
}

static inline void err_cleanup(sd_bus_error *p) { sd_bus_error_free(p); }
#define RAII_bus_error(name) __attribute__((cleanup(err_cleanup))) sd_bus_error name = {0};
static inline void msg_cleanup(sd_bus_message **p) { sd_bus_message_unref(*p); }
#define RAII_message(name) __attribute__((cleanup(msg_cleanup))) sd_bus_message *name = NULL;

#define SYSTEMD_DESTINATION "org.freedesktop.systemd1"
#define SYSTEMD_PATH "/org/freedesktop/systemd1"
#define SYSTEMD_INTERFACE "org.freedesktop.systemd1.Manager"

static bool
set_systemd_error(int r, const char *msg) {
    RAII_PyObject(m, PyUnicode_FromFormat("Failed to %s: %s", msg, strerror(-r)));
    if (m) {
        RAII_PyObject(e, Py_BuildValue("(iO)", -r, m));
        if (e) PyErr_SetObject(PyExc_OSError, e);
    }
    return false;
}

static bool
set_reply_error(const char* func_name, int r, const sd_bus_error *err) {
    RAII_PyObject(m, PyUnicode_FromFormat("Failed to call %s: %s: %s", func_name, err->name, err->message));
    if (m) {
        RAII_PyObject(e, Py_BuildValue("(iO)", -r, m));
        if (e) PyErr_SetObject(PyExc_OSError, e);
    }
    return false;
}

static bool
move_pid_into_new_scope(pid_t pid, const char* scope_name, const char *description) {
    pid_t parent_pid = getpid();
    RAII_bus_error(err); RAII_message(m); RAII_message(reply);
    int r;
#define checked_call(func, ...) if ((r = func(__VA_ARGS__)) < 0) { return set_systemd_error(r, #func); }
    checked_call(sd_bus_message_new_method_call, systemd.user_bus, &m, SYSTEMD_DESTINATION, SYSTEMD_PATH, SYSTEMD_INTERFACE, "StartTransientUnit");
    // mode is "fail" which means it will fail if a unit with scope_name already exists
    checked_call(sd_bus_message_append, m, "ss", scope_name, "fail");
    checked_call(sd_bus_message_open_container, m, 'a', "(sv)");
    if (description && description[0]) {
        checked_call(sd_bus_message_append, m, "(sv)", "Description", "s", description);
    }
    RAII_ALLOC(char, slice, NULL);
    if (sd_pid_get_user_slice(parent_pid, &slice) >= 0) {
        checked_call(sd_bus_message_append, m, "(sv)", "Slice", "s", slice);
    } else {
        // Fallback
        checked_call(sd_bus_message_append, m, "(sv)", "Slice", "s", "kitty.slice");
    }

    // Add the PID to this scope
    checked_call(sd_bus_message_open_container, m, 'r', "sv");
    checked_call(sd_bus_message_append, m, "s", "PIDs");
    checked_call(sd_bus_message_open_container, m, 'v', "au");
    checked_call(sd_bus_message_open_container, m, 'a', "u");
    checked_call(sd_bus_message_append, m, "u", pid);
    checked_call(sd_bus_message_close_container, m); // au
    checked_call(sd_bus_message_close_container, m); // v
    checked_call(sd_bus_message_close_container, m); // (sv)

    // If something in this process group is OOMkilled dont kill the rest of
    // the process group. Since typically the shell is not causing the OOM
    // something being run inside it is.
    checked_call(sd_bus_message_append, m, "(sv)", "OOMPolicy", "s", "continue");

    // Make sure shells are terminated with SIGHUP not just SIGTERM
    checked_call(sd_bus_message_append, m, "(sv)", "SendSIGHUP", "b", true);

    // Unload this unit in failed state as well
    checked_call(sd_bus_message_append, m, "(sv)", "CollectMode", "s", "inactive-or-failed");

    // Only kill the main process on stop
    checked_call(sd_bus_message_append, m, "(sv)", "KillMode", "s", "process");

    checked_call(sd_bus_message_close_container, m); // End properties a(sv)
                                                     //
    checked_call(sd_bus_message_append, m, "a(sa(sv))", 0);  // No auxiliary units
                                                             //
    if ((r=sd_bus_call(systemd.user_bus, m, 0 /* timeout default */, &err, &reply)) < 0) return set_reply_error("StartTransientUnit", r, &err);

    return true;
#undef checked_call
}

static void
finalize(void) {
    if (systemd.user_bus) sd_bus_unref(systemd.user_bus);
    if (systemd.lib) dlclose(systemd.lib);
    memset(&systemd, 0, sizeof(systemd));
}

static bool
ensure_initialized_and_useable(void) {
    ensure_initialized();
    if (!systemd.ok) {
        if (!systemd.lib) PyErr_SetString(PyExc_NotImplementedError, "Could not load libsystemd");
        else if (!systemd.functions_loaded) PyErr_SetString(PyExc_NotImplementedError, "Could not load libsystemd functions");
        else PyErr_SetString(PyExc_NotImplementedError, "Could not connect to systemd user bus");
        return false;
    }
    return true;
}

static PyObject*
systemd_move_pid_into_new_scope(PyObject *self UNUSED, PyObject *args) {
    long pid; const char *scope_name, *description;
    if (!PyArg_ParseTuple(args, "lss", &pid, &scope_name, &description)) return NULL;
#ifdef __APPLE__
    (void)ensure_initialized_and_useable; (void)move_pid_into_new_scope;
    PyErr_SetString(PyExc_NotImplementedError, "not supported on this platform");
#else
    if (!ensure_initialized_and_useable()) return NULL;
    move_pid_into_new_scope(pid, scope_name, description);
#endif
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}


static PyMethodDef module_methods[] = {
    METHODB(systemd_move_pid_into_new_scope, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_systemd_module(PyObject *module) {
    register_at_exit_cleanup_func(SYSTEMD_CLEANUP_FUNC, finalize);
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;

    return true;
}
