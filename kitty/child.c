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

static char**
serialize_string_tuple(PyObject *src) {
    Py_ssize_t sz = PyTuple_GET_SIZE(src);

    char **ans = calloc(sz + 1, sizeof(char*));
    if (!ans) fatal("Out of memory");
    for (Py_ssize_t i = 0; i < sz; i++) {
        const char *pysrc = PyUnicode_AsUTF8(PyTuple_GET_ITEM(src, i));
        if (!pysrc) {
            PyErr_Clear();
            RAII_PyObject(u8, PyUnicode_AsEncodedString(PyTuple_GET_ITEM(src, i), "UTF-8", "ignore"));
            if (!u8) { PyErr_Print(); fatal("couldn't parse command line"); }
            ans[i] = calloc(PyBytes_GET_SIZE(u8) + 1, sizeof(char));
            if (ans[i] == NULL) fatal("Out of memory");
            memcpy(ans[i], PyBytes_AS_STRING(u8), PyBytes_GET_SIZE(u8));
        } else {
            size_t len = strlen(pysrc);
            ans[i] = calloc(len + 1, sizeof(char));
            if (ans[i] == NULL) fatal("Out of memory");
            memcpy(ans[i], pysrc, len);
        }
    }
    return ans;
}

static void
free_string_tuple(char** data) {
    size_t i = 0;
    while(data[i]) free(data[i++]);
    free(data);
}

extern char **environ;

static void
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

static void
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
    PyObject *argv_p, *env_p, *handled_signals_p;
    int master, slave, stdin_read_fd, stdin_write_fd, ready_read_fd, ready_write_fd, forward_stdio;
    const char *kitten_exe;
    char *cwd, *exe;
    if (!PyArg_ParseTuple(args, "ssO!O!iiiiiiO!sp", &exe, &cwd, &PyTuple_Type, &argv_p, &PyTuple_Type, &env_p, &master, &slave, &stdin_read_fd, &stdin_write_fd, &ready_read_fd, &ready_write_fd, &PyTuple_Type, &handled_signals_p, &kitten_exe, &forward_stdio)) return NULL;
    char name[2048] = {0};
    if (ttyname_r(slave, name, sizeof(name) - 1) != 0) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    char **argv = serialize_string_tuple(argv_p);
    char **env = serialize_string_tuple(env_p);
    int handled_signals[16] = {0}, num_handled_signals = MIN((int)arraysz(handled_signals), PyTuple_GET_SIZE(handled_signals_p));
    for (Py_ssize_t i = 0; i < num_handled_signals; i++) handled_signals[i] = PyLong_AsLong(PyTuple_GET_ITEM(handled_signals_p, i));

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
            const struct sigaction act = {.sa_handler=SIG_DFL};

#define SA(which)  if (sigaction(which, &act, NULL) != 0) exit_on_err("sigaction() in child process failed");
            for (int si = 0; si < num_handled_signals; si++) { SA(handled_signals[si]); }
            // See _Py_RestoreSignals in signalmodule.c for a list of signals python nukes
#ifdef SIGPIPE
            SA(SIGPIPE)
#endif
#ifdef SIGXFSZ
            SA(SIGXFSZ);
#endif
#ifdef SIGXFZ
            SA(SIGXFZ);
#endif
#undef SA
            sigset_t signals; sigemptyset(&signals);
            if (sigprocmask(SIG_SETMASK, &signals, NULL) != 0) exit_on_err("sigprocmask() in child process failed");
            // Use only signal-safe functions (man 7 signal-safety)
            if (chdir(cwd) != 0) { if (chdir("/") != 0) {} };  // ignore failure to chdir to /
            if (setsid() == -1) exit_on_err("setsid() in child process failed");

            // Establish the controlling terminal (see man 7 credentials)
            int tfd = safe_open(name, O_RDWR | O_CLOEXEC, 0);
            if (tfd == -1) exit_on_err("Failed to open controlling terminal");
            // On BSD open() does not establish the controlling terminal
            if (ioctl(tfd, TIOCSCTTY, 0) == -1) exit_on_err("Failed to set controlling terminal with TIOCSCTTY");
            safe_close(tfd, __FILE__, __LINE__);

            int min_closed_fd = 3;
            if (forward_stdio) {
                if (safe_dup2(STDOUT_FILENO, min_closed_fd++) == -1) exit_on_err("dup2() failed for forwarded fd 1");
                if (safe_dup2(STDERR_FILENO, min_closed_fd++) == -1) exit_on_err("dup2() failed for forwarded fd 2");
            }
            // Redirect stdin/stdout/stderr to the pty
            if (safe_dup2(slave, STDOUT_FILENO) == -1) exit_on_err("dup2() failed for fd number 1");
            if (safe_dup2(slave, STDERR_FILENO) == -1) exit_on_err("dup2() failed for fd number 2");
            if (stdin_read_fd > -1) {
                if (safe_dup2(stdin_read_fd, STDIN_FILENO) == -1) exit_on_err("dup2() failed for fd number 0");
                safe_close(stdin_read_fd, __FILE__, __LINE__);
                safe_close(stdin_write_fd, __FILE__, __LINE__);
            } else {
                if (safe_dup2(slave, STDIN_FILENO) == -1) exit_on_err("dup2() failed for fd number 0");
            }
            safe_close(slave, __FILE__, __LINE__);
            safe_close(master, __FILE__, __LINE__);

            // Wait for READY_SIGNAL which indicates kitty has setup the screen object
            safe_close(ready_write_fd, __FILE__, __LINE__);
            wait_for_terminal_ready(ready_read_fd);
            safe_close(ready_read_fd, __FILE__, __LINE__);

            // Close any extra fds inherited from parent
            for (int c = min_closed_fd; c < 201; c++) safe_close(c, __FILE__, __LINE__);

            environ = env;
            execvp(exe, argv);
            // Report the failure and exec kitten instead, so that we are not left
            // with a forked but not exec'ed process
            write_to_stderr("Failed to launch child: ");
            write_to_stderr(exe);
            write_to_stderr("\nWith error: ");
            write_to_stderr(strerror(errno));
            write_to_stderr("\n");
            execlp(kitten_exe, "kitten", "__hold_till_enter__", NULL);
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

#ifdef __APPLE__
#include <crt_externs.h>
#else
extern char **environ;
#endif

static PyObject*
clearenv_py(PyObject *self UNUSED, PyObject *args UNUSED) {
#ifdef __APPLE__
    char **e = *_NSGetEnviron();
    if (e) *e = NULL;
#else
    if (environ) *environ = NULL;
#endif
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    METHODB(spawn, METH_VARARGS),
    {"clearenv", clearenv_py, METH_NOARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_child(PyObject *module) {
    PyModule_AddIntMacro(module, CLD_KILLED);
    PyModule_AddIntMacro(module, CLD_STOPPED);
    PyModule_AddIntMacro(module, CLD_EXITED);
    PyModule_AddIntMacro(module, CLD_CONTINUED);
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
