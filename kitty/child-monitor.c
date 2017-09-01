/*
 * child-monitor.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <unistd.h>
#include <pthread.h>
#include <GLFW/glfw3.h>

#define EXTRA_FDS 2
#define MAX_CHILDREN 256

static void (*parse_func)(Screen*, PyObject*);

typedef struct {
    Screen *screen;
    bool needs_removal;
    int fd;
    unsigned long id;
} Child;

static const Child EMPTY_CHILD = {0};
#define FREE_CHILD(x) \
    Py_CLEAR((x).screen); x = EMPTY_CHILD;

#define XREF_CHILD(x, OP) OP(x.screen); 
#define INCREF_CHILD(x) XREF_CHILD(x, Py_INCREF)
#define DECREF_CHILD(x) XREF_CHILD(x, Py_DECREF)
#define screen_mutex(op, which) \
    pthread_mutex_##op(&screen->which##_buf_lock);
#define children_mutex(op) \
    pthread_mutex_##op(&children_lock);


static Child children[MAX_CHILDREN] = {{0}};
static Child scratch[MAX_CHILDREN] = {{0}};
static Child add_queue[MAX_CHILDREN] = {{0}};
static unsigned long dead_children[MAX_CHILDREN] = {0};
static size_t num_dead_children = 0;
static size_t add_queue_count = 0;
static struct pollfd fds[MAX_CHILDREN + EXTRA_FDS] = {{0}};
static pthread_mutex_t children_lock = {{0}};
static bool created = false, signal_received = false;
static uint8_t read_buf[READ_BUF_SZ];


// Main thread functions {{{

static PyObject *
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    ChildMonitor *self;
    PyObject *dump_callback, *death_notify, *update_screen;
    int wakeup_fd, signal_fd, ret;

    if (created) { PyErr_SetString(PyExc_RuntimeError, "Can have only a single ChildMonitor instance"); return NULL; }
    if (!PyArg_ParseTuple(args, "iiOOO", &wakeup_fd, &signal_fd, &death_notify, &update_screen, &dump_callback)) return NULL; 
    created = true;
    if ((ret = pthread_mutex_init(&children_lock, NULL)) != 0) {
        PyErr_Format(PyExc_RuntimeError, "Failed to create children_lock mutex: %s", strerror(ret));
        return NULL;
    }
    self = (ChildMonitor *)type->tp_alloc(type, 0);
    if (self == NULL) return PyErr_NoMemory();
    self->death_notify = death_notify; Py_INCREF(death_notify);
    self->update_screen = update_screen; Py_INCREF(self->update_screen);
    if (dump_callback != Py_None) {
        self->dump_callback = dump_callback; Py_INCREF(dump_callback);
        parse_func = parse_worker_dump;
    } else parse_func = parse_worker;
    self->count = 0; 
    fds[0].fd = wakeup_fd; fds[1].fd = signal_fd;
    fds[0].events = POLLIN; fds[1].events = POLLIN;

    return (PyObject*) self;
}

static void
dealloc(ChildMonitor* self) {
    pthread_mutex_destroy(&children_lock);
    Py_CLEAR(self->dump_callback);
    Py_CLEAR(self->death_notify);
    Py_CLEAR(self->update_screen);
    for (size_t i = 0; i < self->count; i++) {
        FREE_CHILD(children[i]);
    }
    Py_TYPE(self)->tp_free((PyObject*)self);
}


static PyObject *
add_child(ChildMonitor *self, PyObject *args) {
#define add_child_doc "add_child(id, fd, screen) -> Add a child."
    children_mutex(lock);
    if (self->count + add_queue_count >= MAX_CHILDREN) { PyErr_SetString(PyExc_ValueError, "Too many children"); children_mutex(unlock); return NULL; }
    add_queue[add_queue_count] = EMPTY_CHILD;
#define A(attr) &add_queue[add_queue_count].attr
    if (!PyArg_ParseTuple(args, "kiO", A(id), A(fd), A(screen))) {
        children_mutex(unlock);
        return NULL; 
    }
#undef A
    INCREF_CHILD(add_queue[add_queue_count]);
    add_queue_count++;
    children_mutex(unlock);
    Py_RETURN_NONE;
}

static PyObject *
needs_write(ChildMonitor *self, PyObject *args) {
#define needs_write_doc "needs_write(id, data) -> Queue data to be written to child."
    unsigned long id, sz;
    const char *data;
    if (!PyArg_ParseTuple(args, "ks#", &id, &data, &sz)) return NULL; 
    if (!sz) { Py_RETURN_NONE; }
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].id == id) { 
            Screen *screen = children[i].screen;
            screen_mutex(lock, write);
            uint8_t *buf = PyMem_RawRealloc(screen->write_buf, screen->write_buf_sz + sz);
            if (buf == NULL) PyErr_NoMemory();
            else {
                memcpy(buf + screen->write_buf_sz, data, sz);
                screen->write_buf = buf;
                screen->write_buf_sz += sz;
            }
            screen_mutex(unlock, write);
            break;
        }
    }
    children_mutex(unlock);
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

static PyObject *
shutdown(ChildMonitor *self) {
#define shutdown_doc "shutdown() -> Shutdown the monitor loop."
    self->shutting_down = true;
    Py_RETURN_NONE;
}

static PyObject *
parse_input(ChildMonitor *self) {
#define parse_input_doc "parse_input() -> Parse all available input that was read in the I/O thread."
    children_mutex(lock);
    while (num_dead_children) {
        PyObject *t = PyObject_CallFunction(self->death_notify, "k", dead_children[--num_dead_children]);
        if (t == NULL) PyErr_Print();
        else Py_DECREF(t);
    }

    size_t count = self->count;
    bool sr = signal_received;
    signal_received = false;
    for (size_t i = 0; i < count; i++) {
        scratch[i] = children[i];
        INCREF_CHILD(scratch[i]);
    }
    // TODO: Implement repaint delay here.
    children_mutex(unlock);
    for (size_t i = 0; i < count; i++) {
        if (!scratch[i].needs_removal) {
            Screen *screen = scratch[i].screen;
            screen_mutex(lock, read);
            if (screen->read_buf_sz) {
                parse_func(screen, self->dump_callback);
                screen->read_buf_sz = 0;
                PyObject *t = PyObject_CallFunction(self->update_screen, "k", scratch[i].id);
                if (t == NULL) PyErr_Print();
                else Py_DECREF(t);
            }
            screen_mutex(unlock, read);
        }
        DECREF_CHILD(scratch[i]);
    }
    if (sr) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject *
mark_for_close(ChildMonitor *self, PyObject *args) {
#define mark_for_close_doc "Mark a child to be removed from the child monitor"
    int fd;
    if (!PyArg_ParseTuple(args, "i", &fd)) return NULL;
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].fd == fd) {
            children[i].needs_removal = true;
            break;
        }
    }
    children_mutex(unlock);
    Py_RETURN_NONE;
}


// }}}


// I/O thread functions {{{

static inline void
add_children(ChildMonitor *self) {
    children_mutex(lock);
    for (; add_queue_count > 0 && self->count < MAX_CHILDREN;) {
        add_queue_count--;
        children[self->count] = add_queue[add_queue_count];
        fds[EXTRA_FDS + self->count].fd = add_queue[add_queue_count].fd;
        fds[EXTRA_FDS + self->count].events = POLLIN;
        INCREF_CHILD(children[self->count]);
        self->count++;
        DECREF_CHILD(add_queue[add_queue_count]);
    }
    children_mutex(unlock);
}

static inline bool
remove_children(ChildMonitor *self) {
    size_t count = 0; 
    children_mutex(lock);
    if (self->count == 0) goto end;
    for (ssize_t i = self->count - 1; i >= 0; i--) {
        if (children[i].needs_removal) {
            count++;
            close(fds[EXTRA_FDS + i].fd);
            FREE_CHILD(children[i]);            
            size_t num_to_right = self->count - 1 - i;
            if (num_to_right > 0) {
                memmove(children + i, children + i + 1, num_to_right * sizeof(Child));
            }
        }
    }
    self->count -= count;
end:
    children_mutex(unlock);
    return count ? true : false;
}


static inline bool
wait_for_read_buf(Screen *screen) {
    int c = 1000;
    do {
        screen_mutex(lock, read);
        if (screen->read_buf_sz == 0) return true;
        screen_mutex(unlock, read);
        struct timespec sleep_time = { .tv_sec = 0, .tv_nsec = 1000000 };
        nanosleep(&sleep_time, NULL);
    } while(--c > 0);
    return false;
}


static bool
read_bytes(int fd, Screen *screen) {
    Py_ssize_t len;

    while(true) {
        len = read(fd, read_buf, READ_BUF_SZ);
        if (len < 0) {
            if (errno == EINTR) continue;
            if (errno != EIO) perror("Call to read() from child fd failed");
            return false;
        }
        break;
    }
    if (UNLIKELY(len == 0)) return false;
    if (!wait_for_read_buf(screen)) {
        fprintf(stderr, "Screen->read_buf was not emptied after waiting a long time, discarding input.");
        return true;
    }
    memcpy(screen->read_buf, read_buf, len);
    screen->read_buf_sz = len;
    screen_mutex(unlock, read);
    return true;
}


static inline void
drain_wakeup(int fd) {
    while(true) {
        ssize_t len = read(fd, read_buf, READ_BUF_SZ);
        if (len < 0) {
            if (errno == EINTR) continue;
            if (errno != EIO) perror("Call to read() from wakeup fd failed");
            break;
        }
        break;
    }
}

static inline void
write_to_child(int fd, Screen *screen) {
    size_t written = 0;
    ssize_t ret = 0;
    screen_mutex(lock, write);
    while (written < screen->write_buf_sz) {
        ret = write(fd, screen->write_buf + written, screen->write_buf_sz - written);
        if (ret > 0) { written += ret; }
        else if (ret == 0) { 
            // could mean anything, ignore
            break;
        } else {
            if (errno == EINTR) continue;
            if (errno == EWOULDBLOCK || errno == EAGAIN) break;
            perror("Call to write() to child fd failed, discarding data.");
            written = screen->write_buf_sz;
        }
    }
    screen->write_buf_sz -= written;
    screen_mutex(unlock, write);
}

static PyObject *
loop(ChildMonitor *self) {
#define loop_doc "loop() -> The monitor loop."
    size_t i;
    int ret;
    bool has_more, data_received; 
    while (LIKELY(!self->shutting_down)) {
        data_received = false;
        remove_children(self);
        add_children(self);
        Py_BEGIN_ALLOW_THREADS;
        for (i = 0; i < self->count + EXTRA_FDS; i++) fds[i].revents = 0;
        for (i = 0; i < self->count; i++) fds[EXTRA_FDS + i].events = children[i].screen->write_buf_sz ? POLLOUT  | POLLIN : POLLIN;
        ret = poll(fds, self->count + EXTRA_FDS, -1);
        if (ret > 0) {
            if (fds[0].revents && POLLIN) drain_wakeup(fds[0].fd);
            if (fds[1].revents && POLLIN) { 
                data_received = true;
                children_mutex(lock);
                signal_received = true;
                children_mutex(unlock);
            }
            for (i = 0; i < self->count; i++) {
                if (fds[EXTRA_FDS + i].revents & (POLLIN | POLLHUP)) {
                    data_received = true;
                    has_more = read_bytes(fds[EXTRA_FDS + i].fd, children[i].screen);
                    if (!has_more) { 
                        children_mutex(lock);
                        children[i].needs_removal = true;
                        dead_children[num_dead_children++] = children[i].id;
                        children_mutex(unlock);
                    }
                }
                if (fds[EXTRA_FDS + i].revents & POLLOUT) {
                    write_to_child(children[i].fd, children[i].screen);
                }
            }
        } else if (ret < 0) {
            if (errno != EAGAIN && errno != EINTR) {
                perror("Call to poll() failed");
            }
        }
        Py_END_ALLOW_THREADS;
        if (data_received) glfwPostEmptyEvent();
    }
    for (i = 0; i < self->count; i++) children[i].needs_removal = true;
    remove_children(self);
    for (i = 0; i < EXTRA_FDS; i++) close(fds[i].fd);
    Py_RETURN_NONE;
}
// }}}

// Boilerplate {{{
static PyMethodDef methods[] = {
    METHOD(add_child, METH_VARARGS)
    METHOD(needs_write, METH_VARARGS)
    METHOD(loop, METH_NOARGS)
    METHOD(shutdown, METH_NOARGS)
    METHOD(parse_input, METH_NOARGS)
    METHOD(mark_for_close, METH_VARARGS)
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

