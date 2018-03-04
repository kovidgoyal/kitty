/*
 * logging.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <stdarg.h>
#include <time.h>
#include <sys/time.h>


void
log_error(const char *fmt, ...) {
    va_list ar;
    struct timeval tv;
    gettimeofday(&tv, NULL);
    struct tm *tmp = localtime(&tv.tv_sec);
    if (tmp) {
        char tbuf[256], buf[256];
        if (strftime(buf, sizeof(buf), "%j %H:%M:%S.%%06u", tmp) != 0) {
            snprintf(tbuf, sizeof(tbuf), buf, tv.tv_usec);
            fprintf(stderr, "[%s] ", tbuf);
        }
    }
    va_start(ar, fmt);
    vfprintf(stderr, fmt, ar);
    va_end(ar);
    fprintf(stderr, "\n");
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
    return true;
}
