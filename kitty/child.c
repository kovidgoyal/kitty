/*
 * child.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "safe-wrappers.h"
#include <unistd.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <errno.h>
#include <string.h>
#include <signal.h>
#include <sys/ioctl.h>
#include <termios.h>

static inline char**
serialize_string_tuple(PyObject *src) {
    Py_ssize_t sz = PyTuple_GET_SIZE(src);

    char **ans = calloc(sz + 1, sizeof(char*));
    if (!ans) fatal("Out of memory");
    for (Py_ssize_t i = 0; i < sz; i++) {
        const char *pysrc = PyUnicode_AsUTF8(PyTuple_GET_ITEM(src, i));
        size_t len = strlen(pysrc);
        ans[i] = calloc(len + 1, sizeof(char));
        if (ans[i] == NULL) fatal("Out of memory");
        memcpy(ans[i], pysrc, len);
    }
    return ans;
}

static inline void
free_string_tuple(char** data) {
    size_t i = 0;
    while(data[i]) free(data[i++]);
    free(data);
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

#define exit_on_err(m) { write_to_stderr(m); write_to_stderr(": "); write_to_stderr(strerror(errno)); exit(EXIT_FAILURE); }

static inline void
wait_for_terminal_ready(int fd) {
    char data;
    while(1) {
        int ret = read(fd, &data, 1);
        if (ret == -1 && (errno == EINTR || errno == EAGAIN)) continue;
        break;
    }
}

static PyObject*
spawn(PyObject *self UNUSED, PyObject *args) {
    PyObject *argv_p, *env_p;
    int master, slave, stdin_read_fd, stdin_write_fd, ready_read_fd, ready_write_fd;
    char *cwd, *exe;
    if (!PyArg_ParseTuple(args, "ssO!O!iiiiii", &exe, &cwd, &PyTuple_Type, &argv_p, &PyTuple_Type, &env_p, &master, &slave, &stdin_read_fd, &stdin_write_fd, &ready_read_fd, &ready_write_fd)) return NULL;
    char name[2048] = {0};
    if (ttyname_r(slave, name, sizeof(name) - 1) != 0) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    char **argv = serialize_string_tuple(argv_p);
    char **env = serialize_string_tuple(env_p);

#if PY_VERSION_HEX >= 0x03070000
    PyOS_BeforeFork();
#endif
    pid_t pid = fork();
    switch(pid) {
        case 0: {
            // child
#if PY_VERSION_HEX >= 0x03070000
            PyOS_AfterFork_Child();
#endif
            sigset_t signals = {0};
            struct sigaction act = {.sa_handler=SIG_DFL};
#define SA(which) { if (sigaction(which, &act, NULL) != 0) exit_on_err("sigaction() in child process failed"); }
            SA(SIGINT); SA(SIGTERM); SA(SIGCHLD);
#undef SA
            if (sigprocmask(SIG_SETMASK, &signals, NULL) != 0) exit_on_err("sigprocmask() in child process failed");
            // Use only signal-safe functions (man 7 signal-safety)
            if (chdir(cwd) != 0) { if (chdir("/") != 0) {} };  // ignore failure to chdir to /
            if (setsid() == -1) exit_on_err("setsid() in child process failed");

            // Establish the controlling terminal (see man 7 credentials)
            int tfd = safe_open(name, O_RDWR, 0);
            if (tfd == -1) exit_on_err("Failed to open controlling terminal");
#ifdef TIOCSCTTY
            // On BSD open() does not establish the controlling terminal
            if (ioctl(tfd, TIOCSCTTY, 0) == -1) exit_on_err("Failed to set controlling terminal with TIOCSCTTY");
#endif
            safe_close(tfd, __FILE__, __LINE__);

            // Redirect stdin/stdout/stderr to the pty
            if (dup2(slave, 1) == -1) exit_on_err("dup2() failed for fd number 1");
            if (dup2(slave, 2) == -1) exit_on_err("dup2() failed for fd number 2");
            if (stdin_read_fd > -1) {
                if (dup2(stdin_read_fd, 0) == -1) exit_on_err("dup2() failed for fd number 0");
                safe_close(stdin_read_fd, __FILE__, __LINE__);
                safe_close(stdin_write_fd, __FILE__, __LINE__);
            } else {
                if (dup2(slave, 0) == -1) exit_on_err("dup2() failed for fd number 0");
            }
            safe_close(slave, __FILE__, __LINE__);
            safe_close(master, __FILE__, __LINE__);

            // Wait for READY_SIGNAL which indicates kitty has setup the screen object
            safe_close(ready_write_fd, __FILE__, __LINE__);
            wait_for_terminal_ready(ready_read_fd);
            safe_close(ready_read_fd, __FILE__, __LINE__);

            // Close any extra fds inherited from parent
            for (int c = 3; c < 201; c++) safe_close(c, __FILE__, __LINE__);

            environ = env;
            // for some reason SIGPIPE is set to SIG_IGN, so reset it, needed by bash,
            // which does not reset signal handlers on its own
            signal(SIGPIPE, SIG_DFL);
            execvp(exe, argv);
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
        }
        case -1: {
#if PY_VERSION_HEX >= 0x03070000
            int saved_errno = errno;
            PyOS_AfterFork_Parent();
            errno = saved_errno;
#endif
            PyErr_SetFromErrno(PyExc_OSError);
            break;
        }
        default:
#if PY_VERSION_HEX >= 0x03070000
            PyOS_AfterFork_Parent();
#endif
            break;
    }
#undef exit_on_err
    free_string_tuple(argv);
    free_string_tuple(env);
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
