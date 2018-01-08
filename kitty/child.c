/*
 * child.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <unistd.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>

static inline char**
serialize_string_tuple(PyObject *src) {
    Py_ssize_t sz = PyTuple_GET_SIZE(src);
    char **ans = calloc(sz + 1, sizeof(char*));
    if (!ans) fatal("Out of memory");
    for (Py_ssize_t i = 0; i < sz; i++) ans[i] = PyUnicode_AsUTF8(PyTuple_GET_ITEM(src, i));
    return ans;
}

extern char **environ;

static inline void
write_to_stderr(const char *text) {
    size_t sz = strlen(text);
    size_t written = 0;
    while(written < sz) {
        ssize_t amt = write(2, text + written, sz - written);
        if (amt == 0) break;
        if (amt < 0) {
            if (errno == EAGAIN || errno == EINTR) continue;
            break;
        }
        written += amt;
    }
}

static PyObject*
spawn(PyObject *self UNUSED, PyObject *args) {
    PyObject *argv_p, *env_p;
    int master, slave, stdin_read_fd, stdin_write_fd;
    char* cwd;
    if (!PyArg_ParseTuple(args, "sO!O!iiii", &cwd, &PyTuple_Type, &argv_p, &PyTuple_Type, &env_p, &master, &slave, &stdin_read_fd, &stdin_write_fd)) return NULL;
    char name[2048] = {0};
    if (ttyname_r(slave, name, sizeof(name) - 1) != 0) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    char **argv = serialize_string_tuple(argv_p);
    char **env = serialize_string_tuple(env_p);

#define exit_on_err(m) { write_to_stderr(m); write_to_stderr(": "); write_to_stderr(strerror(errno)); exit(EXIT_FAILURE); }
    pid_t pid = fork();
    switch(pid) {
        case 0:
            // child
            // Use only signal-safe functions (man 7 signal-safety)
            if (chdir(cwd) != 0) { if (chdir("/") != 0) {} };  // ignore failure to chdir to /
            if (setsid() == -1) exit_on_err("setsid() in child process failed");
            if (dup2(slave, 1) == -1) exit_on_err("dup2() failed for fd number 1");
            if (dup2(slave, 2) == -1) exit_on_err("dup2() failed for fd number 2");
            if (stdin_read_fd > -1) {
                if (dup2(stdin_read_fd, 0) == -1) exit_on_err("dup2() failed for fd number 0");
                close(stdin_read_fd);
                close(stdin_write_fd);
            } else {
                if (dup2(slave, 0) == -1) exit_on_err("dup2() failed for fd number 0");
            }
            close(slave);
            close(master);
            for (int c = 3; c < 201; c++) close(c);

            // Establish the controlling terminal (see man 7 credentials)
            int tfd = open(name, O_RDWR);
            if (tfd == -1) exit_on_err("Failed to open controlling terminal");
            close(tfd);

            environ = env;
            execvp(argv[0], argv);
            // Report the failure and exec a shell instead, so that we are not left
            // with a forked but not exec'ed process
            write_to_stderr("Failed to launch child: ");
            write_to_stderr(argv[0]);
            write_to_stderr("\nWith error: ");
            write_to_stderr(strerror(errno));
            write_to_stderr("\nPress Enter to exit.\n");
            execlp("sh", "sh", "-c", "read w", NULL);
            exit(EXIT_FAILURE);
            break;
        case -1:
            PyErr_SetFromErrno(PyExc_OSError);
            break;
        default:
            break;
    }
#undef exit_on_err
    free(argv);
    free(env);
    if (PyErr_Occurred()) return NULL;
    return PyLong_FromLong(pid);
}

static PyMethodDef module_methods[] = {
    METHODB(spawn, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_child(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
