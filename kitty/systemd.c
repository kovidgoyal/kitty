/*
 * systemd.c
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define _GNU_SOURCE
#include "data-types.h"
#include "cleanup.h"

#ifdef KITTY_HAS_SYSTEMD
#include <systemd/sd-login.h>
#include <systemd/sd-bus.h>

static struct {
    sd_bus *user_bus;
    bool initialized;
} systemd = {0};

static void
ensure_initialized(void) {
    if (!systemd.initialized) {
        systemd.initialized = true;
        int ret = sd_bus_default_user(&systemd.user_bus);
        if (ret < 0) { log_error("Failed to open systemd user bus with error: %s", strerror(-ret)); }
    }
}

#define RAII_bus_error(name) __attribute__((cleanup(sd_bus_error_free))) sd_bus_error name = SD_BUS_ERROR_NULL;
#define RAII_message(name) __attribute__((cleanup(sd_bus_message_unrefp))) sd_bus_message *name = NULL;

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
    ensure_initialized();
    if (!systemd.user_bus) {
        PyErr_SetString(PyExc_RuntimeError, "Could not connect to systemd user bus");
        return false;
    }
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
    if (systemd.user_bus) {
        sd_bus_unref(systemd.user_bus);
    }
    memset(&systemd, 0, sizeof(systemd));
}

#endif

static PyObject*
systemd_move_pid_into_new_scope(PyObject *self UNUSED, PyObject *args) {
    long pid; const char *scope_name, *description;
    if (!PyArg_ParseTuple(args, "lss", &pid, &scope_name, &description)) return NULL;
#ifdef KITTY_HAS_SYSTEMD
    move_pid_into_new_scope(pid, scope_name, description);
#else
    PyErr_SetString(PyExc_NotImplementedError, "not supported on this platform");
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
#ifdef KITTY_HAS_SYSTEMD
    register_at_exit_cleanup_func(SYSTEMD_CLEANUP_FUNC, finalize);
#endif
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;

    return true;
}
