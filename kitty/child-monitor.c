/*
 * child-monitor.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Need _GNU_SOURCE for pthread_setname_np 
#define _GNU_SOURCE
#include <pthread.h>
#undef _GNU_SOURCE
#include "data-types.h"
#include <termios.h>
#include <unistd.h>
#include <float.h>
#include <fcntl.h>
#ifndef __APPLE__
#include <stropts.h>
#endif
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <signal.h>
#include <GLFW/glfw3.h>

#define EXTRA_FDS 2
#define MAX_CHILDREN 256

static void (*parse_func)(Screen*, PyObject*);

typedef struct {
    Screen *screen;
    bool needs_removal;
    int fd;
    unsigned long id;
    pid_t pid;
} Child;

static const Child EMPTY_CHILD = {0};
#define screen_mutex(op, which) \
    pthread_mutex_##op(&screen->which##_buf_lock);
#define children_mutex(op) \
    pthread_mutex_##op(&children_lock);


static Child children[MAX_CHILDREN] = {{0}};
static Child scratch[MAX_CHILDREN] = {{0}};
static Child add_queue[MAX_CHILDREN] = {{0}}, remove_queue[MAX_CHILDREN] = {{0}};
static unsigned long remove_notify[MAX_CHILDREN] = {0};
static size_t add_queue_count = 0, remove_queue_count = 0;
static struct pollfd fds[MAX_CHILDREN + EXTRA_FDS] = {{0}};
#ifdef __APPLE__
static pthread_mutex_t children_lock = {0};
#else
static pthread_mutex_t children_lock = {{0}};
#endif
static bool created = false, signal_received = false;
static uint8_t drain_buf[1024];
static int signal_fds[2], wakeup_fds[2];
static void *glfw_window_id = NULL;


// Main thread functions {{{

#define FREE_CHILD(x) \
    Py_CLEAR((x).screen); x = EMPTY_CHILD;

#define XREF_CHILD(x, OP) OP(x.screen); 
#define INCREF_CHILD(x) XREF_CHILD(x, Py_INCREF)
#define DECREF_CHILD(x) XREF_CHILD(x, Py_DECREF)

static void
handle_signal(int sig_num) {
    int save_err = errno;
    unsigned char byte = (unsigned char)sig_num;
    while(true) {
        ssize_t ret = write(signal_fds[1], &byte, 1);
        if (ret < 0 && errno == EINTR) continue;
        break;
    }
    errno = save_err;
}

static inline bool
self_pipe(int fds[2]) {
    int flags;
    flags = pipe(fds);
    if (flags != 0) return false;
    flags = fcntl(fds[0], F_GETFD);
    if (flags == -1) {  return false; }
    if (fcntl(fds[0], F_SETFD, flags | FD_CLOEXEC) == -1) { return false; }
    flags = fcntl(fds[0], F_GETFL);
    if (flags == -1) { return false; }
    if (fcntl(fds[0], F_SETFL, flags | O_NONBLOCK) == -1) { return false; }
    return true;
}

static PyObject *
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    ChildMonitor *self;
    PyObject *dump_callback, *death_notify, *update_screen, *timers, *wid, *render_func;
    int ret;
    double repaint_delay;

    if (created) { PyErr_SetString(PyExc_RuntimeError, "Can have only a single ChildMonitor instance"); return NULL; }
    if (!PyArg_ParseTuple(args, "dOOOOOO", &repaint_delay, &wid, &death_notify, &update_screen, &timers, &render_func, &dump_callback)) return NULL; 
    glfw_window_id = PyLong_AsVoidPtr(wid);
    created = true;
    if ((ret = pthread_mutex_init(&children_lock, NULL)) != 0) {
        PyErr_Format(PyExc_RuntimeError, "Failed to create children_lock mutex: %s", strerror(ret));
        return NULL;
    }
    if (!self_pipe(wakeup_fds)) return PyErr_SetFromErrno(PyExc_OSError);
    if (!self_pipe(signal_fds)) return PyErr_SetFromErrno(PyExc_OSError);
    if (signal(SIGINT, handle_signal) == SIG_ERR) return PyErr_SetFromErrno(PyExc_OSError);
    if (signal(SIGTERM, handle_signal) == SIG_ERR) return PyErr_SetFromErrno(PyExc_OSError);
    if (siginterrupt(SIGINT, false) != 0) return PyErr_SetFromErrno(PyExc_OSError);
    if (siginterrupt(SIGTERM, false) != 0) return PyErr_SetFromErrno(PyExc_OSError);
    self = (ChildMonitor *)type->tp_alloc(type, 0);
    if (self == NULL) return PyErr_NoMemory();
    self->death_notify = death_notify; Py_INCREF(death_notify);
    self->update_screen = update_screen; Py_INCREF(self->update_screen);
    self->render_func = render_func; Py_INCREF(self->render_func);
    self->timers = (Timers*)timers; Py_INCREF(timers);
    if (dump_callback != Py_None) {
        self->dump_callback = dump_callback; Py_INCREF(dump_callback);
        parse_func = parse_worker_dump;
    } else parse_func = parse_worker;
    self->count = 0; 
    fds[0].fd = wakeup_fds[0]; fds[1].fd = signal_fds[0];
    fds[0].events = POLLIN; fds[1].events = POLLIN;
    self->repaint_delay = repaint_delay;

    return (PyObject*) self;
}

static void
dealloc(ChildMonitor* self) {
    pthread_mutex_destroy(&children_lock);
    Py_CLEAR(self->dump_callback);
    Py_CLEAR(self->death_notify);
    Py_CLEAR(self->update_screen);
    Py_CLEAR(self->timers);
    Py_CLEAR(self->render_func);
    Py_TYPE(self)->tp_free((PyObject*)self);
    while (remove_queue_count) {
        remove_queue_count--;
        FREE_CHILD(remove_queue[remove_queue_count]);
    }
    while (add_queue_count) {
        add_queue_count--;
        FREE_CHILD(add_queue[add_queue_count]);
    }
    close(wakeup_fds[0]);
    close(wakeup_fds[1]);
    close(signal_fds[0]); 
    close(signal_fds[1]);
}

static void
wakeup_(int fd) {
    while(true) {
        ssize_t ret = write(fd, "w", 1);
        if (ret < 0) {
            if (errno == EINTR) continue;
            perror("Failed to write to wakeup fd with error");
        }
        break;
    }
}

static void* io_loop(void *data);

static PyObject *
start(ChildMonitor *self) {
#define start_doc "start() -> Start the I/O thread"
    int ret = pthread_create(&self->io_thread, NULL, io_loop, self);
    if (ret != 0) return PyErr_SetFromErrno(PyExc_OSError);
    Py_RETURN_NONE;
}

static PyObject *
join(ChildMonitor *self) {
#define join_doc "join() -> Wait for the I/O thread to finish"
    int ret = pthread_join(self->io_thread, NULL);
    if (ret != 0) return PyErr_SetFromErrno(PyExc_OSError);
    Py_RETURN_NONE;
}


static PyObject *
wakeup(ChildMonitor UNUSED *self) {
#define wakeup_doc "wakeup() -> wakeup the ChildMonitor I/O thread, forcing it to exit from poll() if it is waiting there."
    wakeup_(wakeup_fds[1]);
    Py_RETURN_NONE;
}

static PyObject *
add_child(ChildMonitor *self, PyObject *args) {
#define add_child_doc "add_child(id, fd, screen) -> Add a child."
    children_mutex(lock);
    if (self->count + add_queue_count >= MAX_CHILDREN) { PyErr_SetString(PyExc_ValueError, "Too many children"); children_mutex(unlock); return NULL; }
    add_queue[add_queue_count] = EMPTY_CHILD;
#define A(attr) &add_queue[add_queue_count].attr
    if (!PyArg_ParseTuple(args, "kiiO", A(id), A(pid), A(fd), A(screen))) {
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
    PyObject *found = Py_False;
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].id == id) { 
            found = Py_True;
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
    Py_INCREF(found);
    return found;
}

static PyObject *
shutdown(ChildMonitor *self) {
#define shutdown_doc "shutdown() -> Shutdown the monitor loop."
    signal(SIGINT, SIG_DFL);
    signal(SIGTERM, SIG_DFL);
    self->shutting_down = true;
    Py_RETURN_NONE;
}

static inline bool
do_parse(ChildMonitor *self, Screen *screen, unsigned long child_id) {
    bool updated = false;
    screen_mutex(lock, read);
    if (screen->read_buf_sz) {
        parse_func(screen, self->dump_callback);
        if (screen->read_buf_sz >= READ_BUF_SZ) wakeup_(wakeup_fds[1]);  // Ensure the read fd has POLLIN set
        screen->read_buf_sz = 0;
        updated = true;
    }
    screen_mutex(unlock, read);
    if (LIKELY(updated)) {
        PyObject *t = PyObject_CallFunction(self->update_screen, "k", child_id);
        if (t == NULL) PyErr_Print();
        else Py_DECREF(t);
    }
    return updated;
}
static double last_parse_at = -1000;

static void
parse_input(ChildMonitor *self) {
    // Parse all available input that was read in the I/O thread.
    size_t count = 0, remove_count = 0;
    double now = monotonic();
    double time_since_last_parse = now - last_parse_at; 
    bool parse_needed = time_since_last_parse >= self->repaint_delay ? true : false;
    children_mutex(lock);
    while (remove_queue_count) {
        remove_queue_count--; 
        remove_notify[remove_count] = remove_queue[remove_queue_count].id;
        remove_count++;
        FREE_CHILD(remove_queue[remove_queue_count]);
    }

    if (UNLIKELY(signal_received)) {
        glfwSetWindowShouldClose(glfw_window_id, true);
        glfwPostEmptyEvent();
    } else {
        if (parse_needed) {
            count = self->count;
            for (size_t i = 0; i < count; i++) {
                scratch[i] = children[i];
                INCREF_CHILD(scratch[i]);
            }
            last_parse_at = now;
        }
    }
    children_mutex(unlock);

    while(remove_count) {
        // must be done while no locks are held, since the locks are non-recursive and
        // the python function could call into other functions in this module
        remove_count--;
        PyObject *t = PyObject_CallFunction(self->death_notify, "k", remove_notify[remove_count]);
        if (t == NULL) PyErr_Print();
        else Py_DECREF(t);
    }

    for (size_t i = 0; i < count; i++) {
        if (!scratch[i].needs_removal) {
            do_parse(self, scratch[i].screen, scratch[i].id);
        }
        DECREF_CHILD(scratch[i]);
    }
    if (!parse_needed) {
        timers_add_if_before(self->timers, self->repaint_delay - time_since_last_parse, Py_None, NULL);
    } 
}

static PyObject *
mark_for_close(ChildMonitor *self, PyObject *args) {
#define mark_for_close_doc "Mark a child to be removed from the child monitor"
    unsigned long window_id;
    if (!PyArg_ParseTuple(args, "k", &window_id)) return NULL;
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].id == window_id) {
            children[i].needs_removal = true;
            break;
        }
    }
    children_mutex(unlock);
    Py_RETURN_NONE;
}

static inline bool
pty_resize(int fd, struct winsize *dim) {
    while(true) {
        if (ioctl(fd, TIOCSWINSZ, dim) == -1) {
            if (errno == EINTR) continue;
            if (errno != EBADF && errno != ENOTTY) {
                fprintf(stderr, "Failed to resize tty associated with fd: %d with error: %s", fd, strerror(errno));
                return false;
            }
        }
        break;
    }
    return true;
}

static PyObject *
resize_pty(ChildMonitor *self, PyObject *args) {
#define resize_pty_doc "Resize the pty associated with the specified child"
    unsigned long window_id;
    struct winsize dim;
    PyObject *found = Py_False;
    if (!PyArg_ParseTuple(args, "kHHHH", &window_id, &dim.ws_row, &dim.ws_col, &dim.ws_xpixel, &dim.ws_ypixel)) return NULL;
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].id == window_id) {
            found = Py_True;
            if (!pty_resize(children[i].fd, &dim)) PyErr_SetFromErrno(PyExc_OSError);
            break;
        }
    }
    children_mutex(unlock);
    if (PyErr_Occurred()) return NULL;
    Py_INCREF(found);
    return found;
}

bool
set_iutf8(int UNUSED fd, bool UNUSED on) {
#ifdef IUTF8
    struct termios attrs;
    if (tcgetattr(fd, &attrs) != 0) return false;
    if (on) attrs.c_iflag |= IUTF8;
    else attrs.c_iflag &= ~IUTF8;
    if (tcsetattr(fd, TCSANOW, &attrs) != 0) return false;
#endif
    return true;
}

static PyObject*
pyset_iutf8(ChildMonitor *self, PyObject *args) {
    unsigned long window_id;
    int on;
    PyObject *found = Py_False;
    if (!PyArg_ParseTuple(args, "kp", &window_id, &on)) return NULL;
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].id == window_id) {
            found = Py_True;
            if (!set_iutf8(fds[EXTRA_FDS + i].fd, on & 1)) PyErr_SetFromErrno(PyExc_OSError);
            break;
        }
    }
    children_mutex(unlock);
    if (PyErr_Occurred()) return NULL;
    Py_INCREF(found);
    return found;
}

#undef FREE_CHILD
#undef INCREF_CHILD
#undef DECREF_CHILD

static double last_render_at = -DBL_MAX;

static inline bool
render(ChildMonitor *self, double *timeout) {
    PyObject *ret;
    double now = monotonic();
    double time_since_last_render = now - last_render_at;
    if (time_since_last_render > self->repaint_delay) {
        ret = PyObject_CallFunctionObjArgs(self->render_func, NULL);
        if (ret == NULL) return false; 
        else Py_DECREF(ret);
        glfwSwapBuffers(glfw_window_id);
        last_render_at = now;
    } else {
        *timeout = self->repaint_delay - time_since_last_render;
    }
    return true;
}

static PyObject*
main_loop(ChildMonitor *self) {
#define main_loop_doc "The main thread loop"
    double timeout = 0, t;

    while (!glfwWindowShouldClose(glfw_window_id)) {
        if (!render(self, &timeout)) break;
        t = timers_timeout(self->timers);
        timeout = MIN(timeout, t);
        if (timeout < 0) glfwWaitEvents();
        else if (timeout > 0) glfwWaitEventsTimeout(timeout);
        timers_call(self->timers);
        parse_input(self);
    }
    Py_RETURN_NONE;
}

// }}}


// I/O thread functions {{{

static inline void
add_children(ChildMonitor *self) {
    for (; add_queue_count > 0 && self->count < MAX_CHILDREN;) {
        add_queue_count--;
        children[self->count] = add_queue[add_queue_count];
        add_queue[add_queue_count] = EMPTY_CHILD;
        fds[EXTRA_FDS + self->count].fd = children[self->count].fd;
        fds[EXTRA_FDS + self->count].events = POLLIN;
        self->count++;
    }
}


static inline void
hangup(pid_t pid) {
    errno = 0;
    pid_t pgid = getpgid(pid);
    if (errno == ESRCH) return;
    if (errno != 0) { perror("Failed to get process group id for child"); return; }
    if (killpg(pgid, SIGHUP) != 0) {
        if (errno != ESRCH) perror("Failed to kill child"); 
    }
}

static pid_t pid_buf[MAX_CHILDREN] = {0};
static size_t pid_buf_pos = 0;
static pthread_t reap_thread;

static inline void
set_thread_name(pthread_t UNUSED thread, const char *name) {
    int ret = 0;
#ifdef __APPLE__
    ret = pthread_setname_np(name);
#else
    ret = pthread_setname_np(thread, name);
#endif
    if (ret != 0) perror("Failed to set thread name");
}


static void*
reap(void *pid_p) {
#ifdef __APPLE__
    set_thread_name(reap_thread, "KittyReapChild");
#endif
    pid_t pid = *((pid_t*)pid_p);
    while(true) {
        pid_t ret = waitpid(pid, NULL, 0);
        if (ret != pid) {
            if (errno == EINTR) continue;
            fprintf(stderr, "Failed to reap child process with pid: %d with error: %s\n", pid, strerror(errno));
        }
        break;
    }
    return 0;
}

static inline void
cleanup_child(ssize_t i) {
    close(children[i].fd);
    hangup(children[i].pid);
    pid_buf[pid_buf_pos] = children[i].pid;
    if (waitpid(pid_buf[pid_buf_pos], NULL, WNOHANG) != pid_buf[pid_buf_pos]) {
        errno = 0;
        int ret = pthread_create(&reap_thread, NULL, reap, pid_buf + pid_buf_pos);
        if (ret != 0) perror("Failed to create thread to reap child");
        else {
#ifndef __APPLE__
            set_thread_name(reap_thread, "KittyReapChild");
#endif
        }
    }
    pid_buf_pos = (pid_buf_pos + 1) % MAX_CHILDREN;
}


static inline void
remove_children(ChildMonitor *self) {
    if (self->count > 0) {
        size_t count = 0; 
        for (ssize_t i = self->count - 1; i >= 0; i--) {
            if (children[i].needs_removal) {
                count++;
                cleanup_child(i);
                remove_queue[remove_queue_count] = children[i];
                remove_queue_count++;
                children[i] = EMPTY_CHILD;
                size_t num_to_right = self->count - 1 - i;
                if (num_to_right > 0) {
                    memmove(children + i, children + i + 1, num_to_right * sizeof(Child));
                }
            }
        }
        self->count -= count;
    }
}


static bool
read_bytes(int fd, Screen *screen) {
    ssize_t len;
    size_t available_buffer_space, orig_sz;

    screen_mutex(lock, read);
    orig_sz = screen->read_buf_sz;
    if (orig_sz >= READ_BUF_SZ) { screen_mutex(unlock, read); return true; }  // screen read buffer is full
    available_buffer_space = READ_BUF_SZ - orig_sz;
    screen_mutex(unlock, read);
    while(true) {
        len = read(fd, screen->read_buf + orig_sz, available_buffer_space);
        if (len < 0) {
            if (errno == EINTR) continue;
            if (errno != EIO) perror("Call to read() from child fd failed");
            return false;
        }
        break;
    }
    if (UNLIKELY(len == 0)) return false;
    screen_mutex(lock, read);
    if (orig_sz != screen->read_buf_sz) {
        // The other thread consumed some of the screen read buffer
        memmove(screen->read_buf + screen->read_buf_sz, screen->read_buf + orig_sz, len);
    }
    screen->read_buf_sz += len;
    screen_mutex(unlock, read);
    return true;
}


static inline void
drain_fd(int fd) {
    while(true) {
        ssize_t len = read(fd, drain_buf, sizeof(drain_buf));
        if (len < 0) {
            if (errno == EINTR) continue;
            if (errno != EIO) perror("Call to read() from drain fd failed");
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

static void*
io_loop(void *data) {
    // The I/O thread loop
    size_t i;
    int ret;
    bool has_more, data_received; 
    Screen *screen;
    ChildMonitor *self = (ChildMonitor*)data;
    set_thread_name(self->io_thread, "KittyChildMon");

    while (LIKELY(!self->shutting_down)) {
        children_mutex(lock);
        remove_children(self);
        add_children(self);
        children_mutex(unlock);
        data_received = false;
        for (i = 0; i < self->count + EXTRA_FDS; i++) fds[i].revents = 0;
        for (i = 0; i < self->count; i++) {
            screen = children[i].screen;
            screen_mutex(lock, read); screen_mutex(lock, write);
            fds[EXTRA_FDS + i].events = (screen->read_buf_sz < READ_BUF_SZ ? POLLIN : 0) | (screen->write_buf_sz ? POLLOUT  : 0);
            screen_mutex(unlock, read); screen_mutex(unlock, write);
        }
        ret = poll(fds, self->count + EXTRA_FDS, -1);
        if (ret > 0) {
            if (fds[0].revents && POLLIN) drain_fd(fds[0].fd);
            if (fds[1].revents && POLLIN) { 
                data_received = true;
                drain_fd(fds[1].fd);
                children_mutex(lock);
                signal_received = true;
                children_mutex(unlock);
            }
            for (i = 0; i < self->count; i++) {
                if (fds[EXTRA_FDS + i].revents & (POLLIN | POLLHUP)) {
                    data_received = true;
                    has_more = read_bytes(fds[EXTRA_FDS + i].fd, children[i].screen);
                    if (!has_more) { 
                        // child is dead
                        children_mutex(lock);
                        children[i].needs_removal = true;
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
        if (data_received) glfwPostEmptyEvent();
    }
    children_mutex(lock);
    for (i = 0; i < self->count; i++) children[i].needs_removal = true;
    remove_children(self);
    children_mutex(unlock);
    return 0;
}
// }}}

// Boilerplate {{{
static PyMethodDef methods[] = {
    METHOD(add_child, METH_VARARGS)
    METHOD(needs_write, METH_VARARGS)
    METHOD(start, METH_NOARGS)
    METHOD(join, METH_NOARGS)
    METHOD(wakeup, METH_NOARGS)
    METHOD(shutdown, METH_NOARGS)
    METHOD(main_loop, METH_NOARGS)
    METHOD(mark_for_close, METH_VARARGS)
    METHOD(resize_pty, METH_VARARGS)
    {"set_iutf8", (PyCFunction)pyset_iutf8, METH_VARARGS, ""},
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

