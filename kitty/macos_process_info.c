/*
 * macos_process_info.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

#include <sys/sysctl.h>
typedef void* rusage_info_t;  // needed for libproc.h
#include <libproc.h>

static PyObject*
cwd_of_process(PyObject *self UNUSED, PyObject *pid_) {
    if (!PyLong_Check(pid_)) { PyErr_SetString(PyExc_TypeError, "pid must be an int"); return NULL; }
    long pid = PyLong_AsLong(pid_);
    if (pid < 0) { PyErr_SetString(PyExc_TypeError, "pid cannot be negative"); return NULL; }
    struct proc_vnodepathinfo vpi;
    int ret = proc_pidinfo(pid, PROC_PIDVNODEPATHINFO, 0, &vpi, sizeof(vpi));
    if (ret < 0) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    return PyUnicode_FromString(vpi.pvi_cdir.vip_path);
}

// Read the maximum argument size for processes
static int
get_argmax(void) {
    int argmax;
    int mib[] = { CTL_KERN, KERN_ARGMAX };
    size_t size = sizeof(argmax);

    if (sysctl(mib, 2, &argmax, &size, NULL, 0) == 0)
        return argmax;
    return 0;
}

static PyObject*
get_all_processes(PyObject *self UNUSED, PyObject *args UNUSED) {
    pid_t num = proc_listallpids(NULL, 0);
    if (num <= 0) return PyTuple_New(0);
    size_t sz = sizeof(pid_t) * num * 2;
    pid_t *buf = malloc(sz);
    if (!buf) return PyErr_NoMemory();
    num = proc_listallpids(buf, sz);
    if (num <= 0) { free(buf); return PyTuple_New(0); }
    PyObject *ans = PyTuple_New(num);
    if (!ans) { free(buf); return NULL; }
    for (pid_t i = 0; i < num; i++) {
        long long pid = buf[i];
        PyObject *t = PyLong_FromLongLong(pid);
        if (!t) { free(buf); Py_CLEAR(ans); return NULL; }
        PyTuple_SET_ITEM(ans, i, t);
    }
    return ans;
}

static PyObject*
cmdline_of_process(PyObject *self UNUSED, PyObject *pid_) {
    // Taken from psutil, with thanks (BSD 3-clause license)
    int mib[3];
    int nargs;
    size_t len;
    char *procargs = NULL;
    char *arg_ptr;
    char *arg_end;
    char *curr_arg;
    size_t argmax;

    PyObject *py_arg = NULL;
    PyObject *py_retlist = NULL;
    if (!PyLong_Check(pid_)) { PyErr_SetString(PyExc_TypeError, "pid must be an int"); goto error; }
    long pid = PyLong_AsLong(pid_);
    if (pid < 0) { PyErr_SetString(PyExc_TypeError, "pid cannot be negative"); goto error; }

    // special case for PID 0 (kernel_task) where cmdline cannot be fetched
    if (pid == 0)
        return Py_BuildValue("[]");

    // read argmax and allocate memory for argument space.
    argmax = get_argmax();
    if (!argmax) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    procargs = (char *)malloc(argmax);
    if (NULL == procargs) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    // read argument space
    mib[0] = CTL_KERN;
    mib[1] = KERN_PROCARGS2;
    mib[2] = (pid_t)pid;
    if (sysctl(mib, 3, procargs, &argmax, NULL, 0) < 0) {
        // In case of zombie process or non-existent process we'll get EINVAL.
        if (errno == EINVAL)
            PyErr_Format(PyExc_ValueError, "process with pid %ld either does not exist or is a zombie or you dont have permission", pid);
        else
            PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    arg_end = &procargs[argmax];
    // copy the number of arguments to nargs
    memcpy(&nargs, procargs, sizeof(nargs));

    arg_ptr = procargs + sizeof(nargs);
    len = strlen(arg_ptr);
    arg_ptr += len + 1;

    if (arg_ptr == arg_end) {
        free(procargs);
        return Py_BuildValue("[]");
    }

    // skip ahead to the first argument
    for (; arg_ptr < arg_end; arg_ptr++) {
        if (*arg_ptr != '\0')
            break;
    }

    // iterate through arguments
    curr_arg = arg_ptr;
    py_retlist = Py_BuildValue("[]");
    if (!py_retlist)
        goto error;
    while (arg_ptr < arg_end && nargs > 0) {
        if (*arg_ptr++ == '\0') {
            py_arg = PyUnicode_DecodeFSDefault(curr_arg);
            if (! py_arg)
                goto error;
            if (PyList_Append(py_retlist, py_arg))
                goto error;
            Py_DECREF(py_arg);
            // iterate to next arg and decrement # of args
            curr_arg = arg_ptr;
            nargs--;
        }
    }

    free(procargs);
    return py_retlist;

error:
    Py_XDECREF(py_arg);
    Py_XDECREF(py_retlist);
    if (procargs != NULL)
        free(procargs);
    return NULL;

}

PyObject *
environ_of_process(PyObject *self UNUSED, PyObject *pid_) {
    // Taken from psutil, with thanks (BSD 3-clause license)
    int mib[3];
    int nargs;
    char *procargs = NULL;
    char *procenv = NULL;
    char *arg_ptr;
    char *arg_end;
    char *env_start;
    size_t argmax;
    PyObject *py_ret = NULL;
    if (!PyLong_Check(pid_)) { PyErr_SetString(PyExc_TypeError, "pid must be an int"); goto error; }
    long pid = PyLong_AsLong(pid_);
    if (pid < 0) { PyErr_SetString(PyExc_TypeError, "pid cannot be negative"); goto error; }

    // special case for PID 0 (kernel_task) where cmdline cannot be fetched
    if (pid == 0)
        goto empty;

    // read argmax and allocate memory for argument space.
    argmax = get_argmax();
    if (! argmax) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    procargs = (char *)malloc(argmax);
    if (NULL == procargs) {
        PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    // read argument space
    mib[0] = CTL_KERN;
    mib[1] = KERN_PROCARGS2;
    mib[2] = (pid_t)pid;
    if (sysctl(mib, 3, procargs, &argmax, NULL, 0) < 0) {
        // In case of zombie process or a non-existent process we'll get EINVAL
        // to NSP and _psosx.py will translate it to ZP.
        if (errno == EINVAL)
            PyErr_Format(PyExc_ValueError, "process with pid %ld either does not exist or is a zombie or you dont have permission", pid);
        else
            PyErr_SetFromErrno(PyExc_OSError);
        goto error;
    }

    arg_end = &procargs[argmax];
    // copy the number of arguments to nargs
    memcpy(&nargs, procargs, sizeof(nargs));

    // skip executable path
    arg_ptr = procargs + sizeof(nargs);
    arg_ptr = memchr(arg_ptr, '\0', arg_end - arg_ptr);

    if (arg_ptr == NULL || arg_ptr == arg_end)
        goto empty;

    // skip ahead to the first argument
    for (; arg_ptr < arg_end; arg_ptr++) {
        if (*arg_ptr != '\0')
            break;
    }

    // iterate through arguments
    while (arg_ptr < arg_end && nargs > 0) {
        if (*arg_ptr++ == '\0')
            nargs--;
    }

    // build an environment variable block
    env_start = arg_ptr;

    procenv = calloc(1, arg_end - arg_ptr);
    if (procenv == NULL) {
        PyErr_NoMemory();
        goto error;
    }

    while (*arg_ptr != '\0' && arg_ptr < arg_end) {
        char *s = memchr(arg_ptr + 1, '\0', arg_end - arg_ptr);

        if (s == NULL)
            break;

        memcpy(procenv + (arg_ptr - env_start), arg_ptr, s - arg_ptr);

        arg_ptr = s + 1;
    }

    py_ret = PyUnicode_DecodeFSDefaultAndSize(
        procenv, arg_ptr - env_start + 1);
    if (!py_ret) {
        // XXX: don't want to free() this as per:
        // https://github.com/giampaolo/psutil/issues/926
        // It sucks but not sure what else to do.
        procargs = NULL;
        goto error;
    }

    free(procargs);
    free(procenv);

    return py_ret;

empty:
    if (procargs != NULL)
        free(procargs);
    return Py_BuildValue("s", "");

error:
    Py_XDECREF(py_ret);
    free(procargs);
    free(procenv);
    return NULL;
}


static PyMethodDef module_methods[] = {
    {"cwd_of_process", (PyCFunction)cwd_of_process, METH_O, ""},
    {"cmdline_of_process", (PyCFunction)cmdline_of_process, METH_O, ""},
    {"environ_of_process", (PyCFunction)environ_of_process, METH_O, ""},
    {"get_all_processes", (PyCFunction)get_all_processes, METH_NOARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_macos_process_info(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
