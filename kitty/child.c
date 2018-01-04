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

static PyObject*
spawn(PyObject *self UNUSED, PyObject *args) {
    PyObject *argv_p, *env_p;
    int master, slave, stdin_read_fd, stdin_write_fd;
    char* cwd;
    if (!PyArg_ParseTuple(args, "sO!O!iiii", &cwd, &PyTuple_Type, &argv_p, &PyTuple_Type, &env_p, &master, &slave, &stdin_read_fd, &stdin_write_fd)) return NULL;
    char **argv = serialize_string_tuple(argv_p);
    char **env = serialize_string_tuple(env_p);

    pid_t pid = fork();
    if (pid == 0) {
        // child
        // We cannot use malloc before exec() as it might deadlock if a thread in the parent process is in the middle of a malloc itself
        if (chdir(cwd) != 0) chdir("/");
        if (setsid() == -1) { perror("setsid() in child process failed"); exit(EXIT_FAILURE); }
        if (dup2(slave, 1) == -1) { perror("dup2() failed for fd number 1"); exit(EXIT_FAILURE); }
        if (dup2(slave, 2) == -1) { perror("dup2() failed for fd number 2"); exit(EXIT_FAILURE); }
        if (stdin_read_fd > -1) {
            if (dup2(stdin_read_fd, 0) == -1) { perror("dup2() failed for fd number 0"); exit(EXIT_FAILURE); }
            close(stdin_read_fd);
            close(stdin_write_fd);
        } else {
            if (dup2(slave, 0) == -1) { perror("dup2() failed for fd number 0"); exit(EXIT_FAILURE); }
        }
        close(slave);
        close(master);
        for (int c = 3; c < 201; c++) close(c);

        // Establish the controlling terminal (see man 7 credentials)
        char *name = ttyname(1);
        if (name == NULL) { perror("Failed to call ttyname()"); exit(EXIT_FAILURE); }
        int tfd = open(name, O_RDWR);
        if (tfd == -1) { perror("Failed to open controlling terminal"); exit(EXIT_FAILURE); }
        close(tfd);

        environ = env;
        execvp(argv[0], argv);
        // Report the failure and exec a shell instead, so that we are not left
        // with a forked but not execed process
        fprintf(stderr, "Failed to launch child: %s\nWith error: %s [%d]\n", argv[0], strerror(errno), errno);
        fprintf(stderr, "Press Enter to exit.\n");
        fflush(stderr);
        execlp("sh", "sh", "-c", "read w", NULL);
        exit(EXIT_FAILURE);
    } else {
        free(argv);
        free(env);
    }
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
