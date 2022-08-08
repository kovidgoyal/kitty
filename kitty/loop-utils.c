/*
 * loop-utils.c
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "loop-utils.h"
#include "safe-wrappers.h"

#ifndef HAS_SIGNAL_FD
static int signal_write_fd = -1;

static void
handle_signal(int sig_num UNUSED, siginfo_t *si, void *ucontext UNUSED) {
    int save_err = errno;
    char *buf = (char*)si;
    size_t sz = sizeof(siginfo_t);
    while (signal_write_fd != -1 && sz) {
        // as long as sz is less than PIPE_BUF write will either write all or return -1 with EAGAIN
        // so we are guaranteed atomic writes
        ssize_t ret = write(signal_write_fd, buf, sz);
        if (ret <= 0) {
            if (errno == EINTR) continue;
            break;
        }
        sz -= ret;
        buf += ret;
    }
    errno = save_err;
}
#endif

static bool
init_signal_handlers(LoopData *ld) {
    ld->signal_read_fd = -1;
    sigemptyset(&ld->signals);
    for (size_t i = 0; i < ld->num_handled_signals; i++) sigaddset(&ld->signals, ld->handled_signals[i]);
#ifdef HAS_SIGNAL_FD
    if (ld->num_handled_signals) {
        if (sigprocmask(SIG_BLOCK, &ld->signals, NULL) == -1) return false;
        ld->signal_read_fd = signalfd(-1, &ld->signals, SFD_NONBLOCK | SFD_CLOEXEC);
        if (ld->signal_read_fd == -1) return false;
    }
#else
    ld->signal_fds[0] = -1; ld->signal_fds[1] = -1;
    if (ld->num_handled_signals) {
        if (!self_pipe(ld->signal_fds, true)) return false;
        signal_write_fd = ld->signal_fds[1];
        ld->signal_read_fd = ld->signal_fds[0];
        struct sigaction act = {.sa_sigaction=handle_signal, .sa_flags=SA_SIGINFO | SA_RESTART, .sa_mask = ld->signals};
        for (size_t i = 0; i < ld->num_handled_signals; i++) { if (sigaction(ld->handled_signals[i], &act, NULL) != 0) return false; }
    }
#endif
    return true;
}

bool
init_loop_data(LoopData *ld, ...) {
    ld->num_handled_signals = 0;
    va_list valist;
    va_start(valist, ld);
    while (true) {
        int sig = va_arg(valist, int);
        if (!sig) break;
        ld->handled_signals[ld->num_handled_signals++] = sig;
    }
    va_end(valist);
#ifdef HAS_EVENT_FD
    ld->wakeup_read_fd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    if (ld->wakeup_read_fd < 0) return false;
#else
    if (!self_pipe(ld->wakeup_fds, true)) return false;
    ld->wakeup_read_fd = ld->wakeup_fds[0];
#endif
    return init_signal_handlers(ld);
}

#define CLOSE(which, idx) if (ld->which[idx] > -1) { safe_close(ld->which[idx], __FILE__, __LINE__); ld->which[idx] = -1; }

static void
remove_signal_handlers(LoopData *ld) {
#ifndef HAS_SIGNAL_FD
    signal_write_fd = -1;
    CLOSE(signal_fds, 0); CLOSE(signal_fds, 1);
#endif
    if (ld->signal_read_fd > -1) {
#ifdef HAS_SIGNAL_FD
        safe_close(ld->signal_read_fd, __FILE__, __LINE__);
        sigprocmask(SIG_UNBLOCK, &ld->signals, NULL);
#endif
        for (size_t i = 0; i < ld->num_handled_signals; i++) signal(ld->num_handled_signals, SIG_DFL);
    }
    ld->signal_read_fd = -1;
    ld->num_handled_signals = 0;
}

void
free_loop_data(LoopData *ld) {
#ifndef HAS_EVENT_FD
    CLOSE(wakeup_fds, 0); CLOSE(wakeup_fds, 1);
#endif
#undef CLOSE
#ifdef HAS_EVENT_FD
    safe_close(ld->wakeup_read_fd, __FILE__, __LINE__);
#endif
    ld->wakeup_read_fd = -1;
    remove_signal_handlers(ld);
}


void
wakeup_loop(LoopData *ld, bool in_signal_handler, const char *loop_name) {
    while(true) {
#ifdef HAS_EVENT_FD
        static const int64_t value = 1;
        ssize_t ret = write(ld->wakeup_read_fd, &value, sizeof value);
#else
        ssize_t ret = write(ld->wakeup_fds[1], "w", 1);
#endif
        if (ret < 0) {
            if (errno == EINTR) continue;
            if (!in_signal_handler) log_error("Failed to write to %s wakeup fd with error: %s", loop_name, strerror(errno));
        }
        break;
    }
}


void
read_signals(int fd, handle_signal_func callback, void *data) {
#ifdef HAS_SIGNAL_FD
    static struct signalfd_siginfo fdsi[32];
    siginfo_t si;
    while (true) {
        ssize_t s = read(fd, &fdsi, sizeof(fdsi));
        if (s < 0) {
            if (errno == EINTR) continue;
            if (errno == EAGAIN) break;
            log_error("Call to read() from read_signals() failed with error: %s", strerror(errno));
            break;
        }
        if (s == 0) break;
        size_t num_signals = s / sizeof(struct signalfd_siginfo);
        if (num_signals == 0 || num_signals * sizeof(struct signalfd_siginfo) != (size_t)s) {
            log_error("Incomplete signal read from signalfd");
            break;
        }
        for (size_t i = 0; i < num_signals; i++) {
            si.si_signo = fdsi[i].ssi_signo;
            si.si_code = fdsi[i].ssi_code;
            si.si_pid = fdsi[i].ssi_pid;
            si.si_uid = fdsi[i].ssi_uid;
            si.si_addr = (void*)(uintptr_t)fdsi[i].ssi_addr;
            si.si_status = fdsi[i].ssi_status;
            si.si_value.sival_int = fdsi[i].ssi_int;
            if (!callback(&si, data)) break;
        }
    }
#else
    static char buf[sizeof(siginfo_t) * 8];
    static size_t buf_pos = 0;
    while(true) {
        ssize_t len = read(fd, buf + buf_pos, sizeof(buf) - buf_pos);
        if (len < 0) {
            if (errno == EINTR) continue;
            if (errno != EWOULDBLOCK && errno != EAGAIN) log_error("Call to read() from read_signals() failed with error: %s", strerror(errno));
            break;
        }
        buf_pos += len;
        bool keep_going = true;
        while (keep_going && buf_pos >= sizeof(siginfo_t)) {
            keep_going = callback((siginfo_t*)buf, data);
            buf_pos -= sizeof(siginfo_t);
            memmove(buf, buf + sizeof(siginfo_t), buf_pos);
        }
        if (len == 0) break;
    }
#endif
}

static LoopData python_loop_data = {0};

static PyObject*
init_signal_handlers_py(PyObject *self UNUSED, PyObject *args) {
    if (python_loop_data.num_handled_signals) { PyErr_SetString(PyExc_RuntimeError, "signal handlers already initialized"); return NULL; }
#ifndef HAS_SIGNAL_FD
    if (signal_write_fd > -1) { PyErr_SetString(PyExc_RuntimeError, "signal handlers already initialized"); return NULL; }
#endif
    for (Py_ssize_t i = 0; i < MIN(PyTuple_GET_SIZE(args), (Py_ssize_t)arraysz(python_loop_data.handled_signals)); i++) {
        python_loop_data.handled_signals[python_loop_data.num_handled_signals++] = PyLong_AsLong(PyTuple_GET_ITEM(args, i));
    }
    if (!init_signal_handlers(&python_loop_data)) return PyErr_SetFromErrno(PyExc_OSError);
#ifdef HAS_SIGNAL_FD
    return Py_BuildValue("ii", python_loop_data.signal_read_fd, -1);
#else
    return Py_BuildValue("ii", python_loop_data.signal_fds[0], python_loop_data.signal_fds[1]);
#endif
}

static PyTypeObject SigInfoType;
static PyStructSequence_Field sig_info_fields[] = {
    {"si_signo", "Signal number"}, {"si_code", "Signal code"}, {"si_pid", "Sending Process id"},
    {"si_uid", "Real user id of sending process"}, {"si_addr", "Address of faulting instruction as int"},
    {"si_status", "Exit value or signal"}, {"sival_int", "Signal value as int"}, {"sival_ptr", "Signal value as pointer int"},
    {NULL, NULL}
};
static PyStructSequence_Desc sig_info_desc = {"SigInfo", NULL, sig_info_fields, 6};

static bool
handle_signal_callback_py(const siginfo_t* siginfo, void *data) {
    if (PyErr_Occurred()) return false;
    PyObject *callback = data;
    PyObject *ans = PyStructSequence_New(&SigInfoType);
    int pos = 0;
#define S(x) { PyObject *t = x; if (t) { PyStructSequence_SET_ITEM(ans, pos, x); } else { Py_CLEAR(ans); return false; } pos++; }
    if (ans) {
        S(PyLong_FromLong((long)siginfo->si_signo));
        S(PyLong_FromLong((long)siginfo->si_code));
        S(PyLong_FromLong((long)siginfo->si_pid));
        S(PyLong_FromLong((long)siginfo->si_uid));
        S(PyLong_FromVoidPtr(siginfo->si_addr));
        S(PyLong_FromLong((long)siginfo->si_status));
        S(PyLong_FromLong((long)siginfo->si_value.sival_int));
        S(PyLong_FromVoidPtr(siginfo->si_value.sival_ptr));
        PyObject *ret = PyObject_CallFunctionObjArgs(callback, ans, NULL);
        Py_CLEAR(ans); Py_CLEAR(ret);
    }
    return (PyErr_Occurred()) ? false : true;
#undef S
}

static PyObject*
read_signals_py(PyObject *self UNUSED, PyObject *args) {
    int fd; PyObject *callback;
    if (!PyArg_ParseTuple(args, "iO", &fd, &callback)) return NULL;
    if (!PyCallable_Check(callback)) { PyErr_SetString(PyExc_TypeError, "callback must be callable"); return NULL; }
    read_signals(fd, handle_signal_callback_py, callback);
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}


static PyObject*
remove_signal_handlers_py(PyObject *self UNUSED, PyObject *args UNUSED) {
    if (python_loop_data.num_handled_signals) {
        remove_signal_handlers(&python_loop_data);
    }
    Py_RETURN_NONE;
}

static PyMethodDef methods[] = {
    {"install_signal_handlers", init_signal_handlers_py, METH_VARARGS, "Initialize an fd to read signals from" },
    {"read_signals", read_signals_py, METH_VARARGS, "Read pending signals from the specified fd" },
    {"remove_signal_handlers", remove_signal_handlers_py, METH_NOARGS, "Remove signal handlers" },
    { NULL, NULL, 0, NULL },
};

bool
init_loop_utils(PyObject *module) {
    if (PyStructSequence_InitType2(&SigInfoType, &sig_info_desc) != 0) return false;
    Py_INCREF((PyObject *) &SigInfoType);
    PyModule_AddObject(module, "SigInfo", (PyObject *) &SigInfoType);

    return PyModule_AddFunctions(module, methods) == 0;
}
