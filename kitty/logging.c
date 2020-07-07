/*
 * logging.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <stdlib.h>
#include <stdarg.h>
#include <time.h>
#include <sys/time.h>
#ifdef __APPLE__
#include <os/log.h>
#endif


static bool use_os_log = false;

void
log_error(const char *fmt, ...) {
    va_list ar;
    struct timeval tv;
#ifdef __APPLE__
    // Apple does not provide a varargs style os_logv
    char logbuf[16 * 1024] = {0};
#else
    char logbuf[4];
#endif
    char *p = logbuf;
#define bufprint(func, ...) { if ((size_t)(p - logbuf) < sizeof(logbuf) - 2) { p += func(p, sizeof(logbuf) - (p - logbuf), __VA_ARGS__); } }
    if (!use_os_log) {  // Apple's os_log already records timestamps
        gettimeofday(&tv, NULL);
        struct tm stack_tmp;
        struct tm *tmp = localtime_r(&tv.tv_sec, &stack_tmp);
        if (tmp) {
            char tbuf[256] = {0}, buf[256] = {0};
            if (strftime(buf, sizeof(buf), "%j %H:%M:%S.%%06u", tmp) != 0) {
                snprintf(tbuf, sizeof(tbuf), buf, tv.tv_usec);
                fprintf(stderr, "[%s] ", tbuf);
            }
        }
    }
    va_start(ar, fmt);
    if (use_os_log) { bufprint(vsnprintf, fmt, ar); }
    else vfprintf(stderr, fmt, ar);
    va_end(ar);
#ifdef __APPLE__
    if (use_os_log) os_log(OS_LOG_DEFAULT, "%{public}s", logbuf);
#endif
    if (!use_os_log) fprintf(stderr, "\n");
}

static PyObject*
log_error_string(PyObject *self UNUSED, PyObject *args) {
    const char *msg;
    if (!PyArg_ParseTuple(args, "s", &msg)) return NULL;
    log_error("%s", msg);
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    METHODB(log_error_string, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_logging(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
#ifdef __APPLE__
    if (getenv("KITTY_LAUNCHED_BY_LAUNCH_SERVICES") != NULL) use_os_log = true;
#endif
    return true;
}
