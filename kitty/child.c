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

#define EXTRA_ENV_BUFFER_SIZE 64

static char**
serialize_string_tuple(PyObject *src, Py_ssize_t extra) {
    const Py_ssize_t sz = PyTuple_GET_SIZE(src);
    size_t required_size = sizeof(char*) * (1 + sz + extra);
    required_size += extra * EXTRA_ENV_BUFFER_SIZE;
    void *block = calloc(required_size, 1);
    if (!block) { PyErr_NoMemory(); return NULL; }
    char **ans = block;
    for (Py_ssize_t i = 0; i < sz; i++) {
        PyObject *x = PyTuple_GET_ITEM(src, i);
        if (!PyUnicode_Check(x)) { free(block); PyErr_SetString(PyExc_TypeError, "string tuple must have only strings"); return NULL; }
        ans[i] = (char*)PyUnicode_AsUTF8(x);
        if (!ans[i]) { free(block); return NULL; }
    }
    return ans;
}

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
    PyObject *argv_p, *env_p, *handled_signals_p, *pass_fds;
    int master, slave, stdin_read_fd, stdin_write_fd, ready_read_fd, ready_write_fd, forward_stdio;
    const char *kitten_exe;
    char *cwd, *exe;
    if (!PyArg_ParseTuple(args, "ssO!O!iiiiiiO!spO!", &exe, &cwd, &PyTuple_Type, &argv_p, &PyTuple_Type, &env_p, &master, &slave, &stdin_read_fd, &stdin_write_fd, &ready_read_fd, &ready_write_fd, &PyTuple_Type, &handled_signals_p, &kitten_exe, &forward_stdio, &PyTuple_Type, &pass_fds)) return NULL;
    char name[2048] = {0};
    if (ttyname_r(slave, name, sizeof(name) - 1) != 0) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    char **argv = serialize_string_tuple(argv_p, 0);
    if (!argv) return NULL;
    char **env = serialize_string_tuple(env_p, 1);
    if (!env) { free(argv); return NULL; }
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
            if (chdir(cwd) != 0) {
                if (access(".", X_OK) != 0) { // existing cwd does not exist or dont have permissions for it
                    if (chdir("/") != 0) {} // ignore failure to chdir to /
                }
            };
            if (setsid() == -1) exit_on_err("setsid() in child process failed");

            // Establish the controlling terminal (see man 7 credentials)
            int tfd = safe_open(name, O_RDWR | O_CLOEXEC, 0);
            if (tfd == -1) exit_on_err("Failed to open controlling terminal");
            // On BSD open() does not establish the controlling terminal
            if (ioctl(tfd, TIOCSCTTY, 0) == -1) exit_on_err("Failed to set controlling terminal with TIOCSCTTY");
            safe_close(tfd, __FILE__, __LINE__);

            fd_set passed_fds; FD_ZERO(&passed_fds); bool has_preserved_fds = false;
            if (forward_stdio) {
                int fd = safe_dup(STDOUT_FILENO);
                if (fd < 0) exit_on_err("dup() failed for forwarded STDOUT");
                FD_SET(fd, &passed_fds);
                size_t s = PyTuple_GET_SIZE(env_p);
                env[s] = (char*)(env + (s + 2));
                snprintf(env[s], EXTRA_ENV_BUFFER_SIZE, "KITTY_STDIO_FORWARDED=%d", fd);
                fd = safe_dup(STDERR_FILENO);
                if (fd < 0) exit_on_err("dup() failed for forwarded STDERR");
                FD_SET(fd, &passed_fds);
                has_preserved_fds = true;
            }

            for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(pass_fds); i++) {
                PyObject *pfd = PyTuple_GET_ITEM(pass_fds, i);
                if (!PyLong_Check(pfd)) exit_on_err("pass_fds must contain only integers");
                int fd = PyLong_AsLong(pfd);
                if (fd > -1 && fd < FD_SETSIZE) {
                    FD_SET(fd, &passed_fds);
                    has_preserved_fds = true;
                }
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
            if (has_preserved_fds) { for (int c = 3; c < 256; c++) { if (!FD_ISSET(c, &passed_fds)) safe_close(c, __FILE__, __LINE__); } }
            else for (int c = 3; c < 256; c++) { safe_close(c, __FILE__, __LINE__); }

            extern char **environ;
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
    PyModule_AddIntMacro(module, CLD_KILLED);
    PyModule_AddIntMacro(module, CLD_STOPPED);
    PyModule_AddIntMacro(module, CLD_EXITED);
    PyModule_AddIntMacro(module, CLD_CONTINUED);
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
