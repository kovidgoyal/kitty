/*
 * child-monitor.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

#define EXTRA_FDS 2

static bool (*read_func)(int, Screen*, PyObject*);

static PyObject *
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    ChildMonitor *self;
    PyObject *wakeup_func, *signal_func, *dump_callback;
    Timers *timers;
    int wakeup_fd, signal_fd;
    double delay;

    if (!PyArg_ParseTuple(args, "iOiOOdO", &wakeup_fd, &wakeup_func, &signal_fd, &signal_func, &timers, &delay, &dump_callback)) return NULL; 
    self = (ChildMonitor *)type->tp_alloc(type, 0);
    if (self == NULL) return PyErr_NoMemory();
    self->wakeup_func = wakeup_func; Py_INCREF(wakeup_func);
    self->signal_func = signal_func; Py_INCREF(signal_func);
    self->timers = timers; Py_INCREF(timers);
    if (dump_callback != Py_None) {
        self->dump_callback = dump_callback; Py_INCREF(dump_callback);
        read_func = read_bytes_dump;
    } else read_func = read_bytes;
    self->count = 0; self->children = NULL;
    self->fds = (struct pollfd*)PyMem_Calloc(EXTRA_FDS, sizeof(struct pollfd));
    self->repaint_delay = delay;
    if (self->fds == NULL) { Py_CLEAR(self); return PyErr_NoMemory(); }
    self->fds[0].fd = wakeup_fd; self->fds[1].fd = signal_fd;
    self->fds[0].events = POLLIN; self->fds[0].events = POLLIN;

    return (PyObject*) self;
}

#define FREE_CHILD(x) \
    Py_CLEAR((x).screen); Py_CLEAR((x).on_exit); Py_CLEAR((x).write_func); Py_CLEAR((x).update_screen);

static void
dealloc(ChildMonitor* self) {
    Py_CLEAR(self->wakeup_func); Py_CLEAR(self->signal_func); Py_CLEAR(self->timers); Py_CLEAR(self->dump_callback);
    for (size_t i = 0; i < self->count; i++) {
        FREE_CHILD(self->children[i]);
    }
    PyMem_Free(self->fds); PyMem_Free(self->children);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

#define COPY_CHILD(src, dest) \
    dest.screen = src.screen; dest.on_exit = src.on_exit; dest.write_func = src.write_func; dest.needs_write = src.needs_write; dest.update_screen = src.update_screen

#define COPY_POLL_FD(src, dest) \
    dest.fd = src.fd; dest.events = src.events;

static PyObject *
add_child(ChildMonitor *self, PyObject *args) {
#define add_child_doc "add_child(fd, screen, on_exit, write_func, update_screen) -> Add a child."
    int fd;
    PyObject *on_exit, *write_func, *update_screen;
    Screen *screen;
    if (!PyArg_ParseTuple(args, "iOOOO", &fd, &screen, &on_exit, &write_func, &update_screen)) return NULL; 

    Child *children = (Child*)PyMem_Calloc(self->count + 1, sizeof(Child));
    struct pollfd *fds = (struct pollfd*)PyMem_Calloc(EXTRA_FDS + 1 + self->count, sizeof(struct pollfd));
    if (children == NULL || fds == NULL) { PyMem_Free(children); PyMem_Free(fds); return PyErr_NoMemory();}
    for (size_t i = 0; i < self->count; i++) {
        COPY_CHILD(self->children[i], children[i]);
    }
    for (size_t i = 0; i < self->count + EXTRA_FDS; i++) {
        COPY_POLL_FD(self->fds[i], fds[i]);
    }
    fds[EXTRA_FDS + self->count].fd = fd;
    fds[EXTRA_FDS + self->count].events = POLLIN;
#define ADDATTR(x) children[self->count].x = x; Py_INCREF(x);
    ADDATTR(screen); ADDATTR(on_exit); ADDATTR(write_func); ADDATTR(update_screen);
    self->count++;
    PyMem_Free(self->fds); PyMem_Free(self->children);
    self->fds = fds; self->children = children;
    Py_RETURN_NONE;
}
 
static PyObject *
remove_child(ChildMonitor *self, PyObject *pyfd) {
#define remove_child_doc "remove_child(fd) -> Remove a child."
    size_t i; bool found = false;
    int fd = (int)PyLong_AsLong(pyfd);
    for (i = 0; i < self->count; i++) {
        if (self->fds[EXTRA_FDS + i].fd == fd) { found = true; break; }
    }
    if (!found) { Py_RETURN_FALSE; }
    Child *children = self->count > 1 ? (Child*)PyMem_Calloc(self->count - 1, sizeof(Child)) : NULL;
    struct pollfd *fds = (struct pollfd*)PyMem_Calloc(EXTRA_FDS + self->count - 1, sizeof(struct pollfd));
    if ((self->count > 1 && children == NULL) || fds == NULL) { PyMem_Free(children); PyMem_Free(fds); return PyErr_NoMemory();}
    for (size_t s = 0, d = 0; s < self->count; s++) {
        if (s != i) {
            COPY_CHILD(self->children[s], children[d]);
            COPY_POLL_FD(self->fds[s + EXTRA_FDS], fds[d + EXTRA_FDS]);
            d++;
        } else {
            FREE_CHILD(self->children[s]);            
        }
    }
    for (i = 0; i < EXTRA_FDS; i++) {
        COPY_POLL_FD(self->fds[i], fds[i]);
    }
    self->count--;
    PyMem_Free(self->fds); PyMem_Free(self->children);
    self->fds = fds; self->children = children;
    Py_RETURN_TRUE;
}

static PyObject *
needs_write(ChildMonitor *self, PyObject *args) {
#define needs_write_doc "needs_write(fd, yesno) -> Mark a child as needing write or not."
    int fd, yesno;
    if (!PyArg_ParseTuple(args, "ip", &fd, &yesno)) return NULL; 
    for (size_t i = 0; i < self->count; i++) {
        if (self->fds[EXTRA_FDS + i].fd == fd) { 
            self->children[i].needs_write = (bool)yesno;
            Py_RETURN_TRUE;
        }
    }
    Py_RETURN_FALSE;
}

static PyObject *
loop(ChildMonitor *self) {
#define loop_doc "loop() -> The monitor loop."
    size_t i;
    int ret, timeout;
    bool has_more; 
    PyObject *t;
    while (LIKELY(!self->shutting_down)) {
        for (i = 0; i < self->count + EXTRA_FDS; i++) self->fds[i].revents = 0;
        for (i = EXTRA_FDS; i < EXTRA_FDS + self->count; i++) self->fds[i].events = self->children[i - EXTRA_FDS].needs_write ? POLLOUT  | POLLIN : POLLIN;
        timeout = (int)(timers_timeout(self->timers) * 1000);
        // Sub-millisecond interval will become 0, so round up to 1ms as this is the resolution of poll()
        if (timeout == 0) timeout = 1;
        Py_BEGIN_ALLOW_THREADS;
        ret = poll(self->fds, self->count + EXTRA_FDS, timeout);
        Py_END_ALLOW_THREADS;
        if (ret > 0) {
#define PYCALL(x) t = PyObject_CallObject(x, NULL); if (t == NULL) PyErr_Print(); else Py_DECREF(t);
            if (self->fds[0].revents && POLLIN) { PYCALL(self->wakeup_func); }
            if (self->fds[1].revents && POLLIN) { PYCALL(self->signal_func); }
            for (i = 0; i < self->count; i++) {
                if (self->fds[EXTRA_FDS + i].revents & (POLLIN | POLLHUP)) {
                    has_more = read_func(self->fds[EXTRA_FDS + i].fd, self->children[i].screen, self->dump_callback);
                    if (!has_more) { PYCALL(self->children[i].on_exit); }
                }
                if (self->fds[EXTRA_FDS + i].revents & POLLOUT) {
                    PYCALL(self->children[i].write_func);
                }
            }
        } else if (ret < 0) {
            if (errno != EAGAIN && errno != EINTR) {
                perror("Call to poll() failed");
            }
            continue;
        }
        timers_call(self->timers);
        for (i = 0; i < self->count; i++) {
            if (self->children[i].screen->change_tracker->dirty) {
                if (!timers_add_if_missing(self->timers, self->repaint_delay, self->children[i].update_screen, NULL)) PyErr_Print();
                // update_screen() is responsible for clearing the dirty indication
            }
        }
    }
    Py_RETURN_NONE;
}


static PyObject *
shutdown(ChildMonitor *self) {
#define shutdown_doc "shutdown() -> Shutdown the monitor loop."
    self->shutting_down = true;
    Py_RETURN_NONE;
}

// Boilerplate {{{
static PyMethodDef methods[] = {
    METHOD(add_child, METH_VARARGS)
    METHOD(remove_child, METH_O)
    METHOD(needs_write, METH_VARARGS)
    METHOD(loop, METH_NOARGS)
    METHOD(shutdown, METH_NOARGS)
    {NULL}  /* Sentinel */
};


PyTypeObject ChildMonitor_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.ChildMonitor",
    .tp_basicsize = sizeof(ChildMonitor),
    .tp_dealloc = (destructor)dealloc, 
    .tp_flags = Py_TPFLAGS_DEFAULT,        
    .tp_doc = "ChildMonitor",
    .tp_methods = methods,
    .tp_new = new,                
};


INIT_TYPE(ChildMonitor)
// }}}

