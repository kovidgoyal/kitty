/*
 * child-monitor.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "state.h"
#include "threading.h"
#include "screen.h"
#include "fonts.h"
#include "charsets.h"
#include <termios.h>
#include <unistd.h>
#include <float.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <signal.h>
#include <sys/socket.h>
extern PyTypeObject Screen_Type;

#define EXTRA_FDS 2
#ifndef MSG_NOSIGNAL
// Apple does not implement MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif
#define USE_RENDER_FRAMES (global_state.has_render_frames && OPT(sync_to_monitor))

static void (*parse_func)(Screen*, PyObject*, double);

typedef struct {
    char *data;
    size_t sz;
    int fd;
} Message;

typedef struct {
    PyObject_HEAD

    PyObject *dump_callback, *update_screen, *death_notify;
    unsigned int count;
    bool shutting_down;
    pthread_t io_thread, talk_thread;

    int talk_fd, listen_fd;
    Message *messages;
    size_t messages_capacity, messages_count;
} ChildMonitor;


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
#define peer_mutex(op) \
    pthread_mutex_##op(&talk_data.peer_lock);



static Child children[MAX_CHILDREN] = {{0}};
static Child scratch[MAX_CHILDREN] = {{0}};
static Child add_queue[MAX_CHILDREN] = {{0}}, remove_queue[MAX_CHILDREN] = {{0}};
static unsigned long remove_notify[MAX_CHILDREN] = {0};
static size_t add_queue_count = 0, remove_queue_count = 0;
static struct pollfd fds[MAX_CHILDREN + EXTRA_FDS] = {{0}};
static pthread_mutex_t children_lock;
static bool kill_signal_received = false;
static ChildMonitor *the_monitor = NULL;
static uint8_t drain_buf[1024];
static int signal_fds[2], wakeup_fds[2];


typedef struct {
    pid_t pid;
    int status;
} ReapedPID;

static pid_t monitored_pids[256] = {0};
static size_t monitored_pids_count = 0;
static ReapedPID reaped_pids[arraysz(monitored_pids)] = {{0}};
static size_t reaped_pids_count = 0;



// Main thread functions {{{

#define FREE_CHILD(x) \
    Py_CLEAR((x).screen); x = EMPTY_CHILD;

#define XREF_CHILD(x, OP) OP(x.screen);
#define INCREF_CHILD(x) XREF_CHILD(x, Py_INCREF)
#define DECREF_CHILD(x) XREF_CHILD(x, Py_DECREF)

// The max time (in secs) to wait for events from the window system
// before ticking over the main loop. Negative values mean wait forever.
static double maximum_wait = -1.0;

static inline void
set_maximum_wait(double val) {
    if (val >= 0 && (val < maximum_wait || maximum_wait < 0)) maximum_wait = val;
}

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
#ifdef __APPLE__
    int flags;
    flags = pipe(fds);
    if (flags != 0) return false;
    for (int i = 0; i < 2; i++) {
        flags = fcntl(fds[i], F_GETFD);
        if (flags == -1) {  return false; }
        if (fcntl(fds[i], F_SETFD, flags | FD_CLOEXEC) == -1) { return false; }
        flags = fcntl(fds[i], F_GETFL);
        if (flags == -1) { return false; }
        if (fcntl(fds[i], F_SETFL, flags | O_NONBLOCK) == -1) { return false; }
    }
    return true;
#else
    return pipe2(fds, O_CLOEXEC | O_NONBLOCK) == 0;
#endif
}


static PyObject *
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    ChildMonitor *self;
    PyObject *dump_callback, *death_notify;
    int talk_fd = -1, listen_fd = -1;
    int ret;

    if (the_monitor) { PyErr_SetString(PyExc_RuntimeError, "Can have only a single ChildMonitor instance"); return NULL; }
    if (!PyArg_ParseTuple(args, "OO|ii", &death_notify, &dump_callback, &talk_fd, &listen_fd)) return NULL;
    if ((ret = pthread_mutex_init(&children_lock, NULL)) != 0) {
        PyErr_Format(PyExc_RuntimeError, "Failed to create children_lock mutex: %s", strerror(ret));
        return NULL;
    }
    if (!self_pipe(wakeup_fds)) return PyErr_SetFromErrno(PyExc_OSError);
    if (!self_pipe(signal_fds)) return PyErr_SetFromErrno(PyExc_OSError);
    struct sigaction act = {.sa_handler=handle_signal};
#define SA(which) { if (sigaction(which, &act, NULL) != 0) return PyErr_SetFromErrno(PyExc_OSError); if (siginterrupt(which, false) != 0) return PyErr_SetFromErrno(PyExc_OSError);}
    SA(SIGINT); SA(SIGTERM); SA(SIGCHLD);
#undef SA
    self = (ChildMonitor *)type->tp_alloc(type, 0);
    self->talk_fd = talk_fd;
    self->listen_fd = listen_fd;
    if (self == NULL) return PyErr_NoMemory();
    self->death_notify = death_notify; Py_INCREF(death_notify);
    if (dump_callback != Py_None) {
        self->dump_callback = dump_callback; Py_INCREF(dump_callback);
        parse_func = parse_worker_dump;
    } else parse_func = parse_worker;
    self->count = 0;
    fds[0].fd = wakeup_fds[0]; fds[1].fd = signal_fds[0];
    fds[0].events = POLLIN; fds[1].events = POLLIN;
    the_monitor = self;

    return (PyObject*) self;
}

static void
dealloc(ChildMonitor* self) {
    pthread_mutex_destroy(&children_lock);
    Py_CLEAR(self->dump_callback);
    Py_CLEAR(self->death_notify);
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

void
wakeup_io_loop(bool in_signal_handler) {
    while(true) {
        ssize_t ret = write(wakeup_fds[1], "w", 1);
        if (ret < 0) {
            if (errno == EINTR) continue;
            if (!in_signal_handler) perror("Failed to write to wakeup fd with error");
        }
        break;
    }
}

static void* io_loop(void *data);
static void* talk_loop(void *data);
static void send_response(int fd, const char *msg, size_t msg_sz);
static void wakeup_talk_loop(bool);
static bool talk_thread_started = false;

static PyObject *
start(PyObject *s, PyObject *a UNUSED) {
#define start_doc "start() -> Start the I/O thread"
    ChildMonitor *self = (ChildMonitor*)s;
    if (self->talk_fd > -1 || self->listen_fd > -1) {
        if (pthread_create(&self->talk_thread, NULL, talk_loop, self) != 0) return PyErr_SetFromErrno(PyExc_OSError);
        talk_thread_started = true;
    }
    int ret = pthread_create(&self->io_thread, NULL, io_loop, self);
    if (ret != 0) return PyErr_SetFromErrno(PyExc_OSError);

    Py_RETURN_NONE;
}


static PyObject *
wakeup(PYNOARG) {
#define wakeup_doc "wakeup() -> wakeup the ChildMonitor I/O thread, forcing it to exit from poll() if it is waiting there."
    wakeup_io_loop(false);
    Py_RETURN_NONE;
}

static PyObject *
add_child(ChildMonitor *self, PyObject *args) {
#define add_child_doc "add_child(id, pid, fd, screen) -> Add a child."
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
    wakeup_io_loop(false);
    Py_RETURN_NONE;
}

bool
schedule_write_to_child(unsigned long id, unsigned int num, ...) {
    ChildMonitor *self = the_monitor;
    bool found = false;
    const char *data;
    size_t sz = 0;
    va_list ap;
    va_start(ap, num);
    for (unsigned int i = 0; i < num; i++) {
        data = va_arg(ap, const char*);
        sz += va_arg(ap, size_t);
    }
    va_end(ap);
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].id == id) {
            found = true;
            Screen *screen = children[i].screen;
            screen_mutex(lock, write);
            size_t space_left = screen->write_buf_sz - screen->write_buf_used;
            if (space_left < sz) {
                if (screen->write_buf_used + sz > 100 * 1024 * 1024) {
                    log_error("Too much data being sent to child with id: %lu, ignoring it", id);
                    screen_mutex(unlock, write);
                    break;
                }
                screen->write_buf_sz = screen->write_buf_used + sz;
                screen->write_buf = PyMem_RawRealloc(screen->write_buf, screen->write_buf_sz);
                if (screen->write_buf == NULL) { fatal("Out of memory."); }
            }
            va_start(ap, num);
            for (unsigned int i = 0; i < num; i++) {
                data = va_arg(ap, const char*);
                size_t dsz = va_arg(ap, size_t);
                memcpy(screen->write_buf + screen->write_buf_used, data, dsz);
                screen->write_buf_used += dsz;
            }
            va_end(ap);
            if (screen->write_buf_sz > BUFSIZ && screen->write_buf_used < BUFSIZ) {
                screen->write_buf_sz = BUFSIZ;
                screen->write_buf = PyMem_RawRealloc(screen->write_buf, screen->write_buf_sz);
                if (screen->write_buf == NULL) { fatal("Out of memory."); }
            }
            if (screen->write_buf_used) wakeup_io_loop(false);
            screen_mutex(unlock, write);
            break;
        }
    }
    children_mutex(unlock);
    return found;
}

static PyObject *
needs_write(ChildMonitor UNUSED *self, PyObject *args) {
#define needs_write_doc "needs_write(id, data) -> Queue data to be written to child."
    unsigned long id, sz;
    const char *data;
    if (!PyArg_ParseTuple(args, "ks#", &id, &data, &sz)) return NULL;
    if (schedule_write_to_child(id, 1, data, (size_t)sz)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject *
shutdown_monitor(ChildMonitor *self, PyObject *a UNUSED) {
#define shutdown_monitor_doc "shutdown_monitor() -> Shutdown the monitor loop."
    signal(SIGINT, SIG_DFL);
    signal(SIGTERM, SIG_DFL);
    signal(SIGCHLD, SIG_DFL);
    self->shutting_down = true;
    wakeup_talk_loop(false);
    wakeup_io_loop(false);
    int ret = pthread_join(self->io_thread, NULL);
    if (ret != 0) return PyErr_Format(PyExc_OSError, "Failed to join() I/O thread with error: %s", strerror(ret));
    if (talk_thread_started) {
        ret = pthread_join(self->talk_thread, NULL);
        if (ret != 0) return PyErr_Format(PyExc_OSError, "Failed to join() talk thread with error: %s", strerror(ret));
    }
    talk_thread_started = false;
    Py_RETURN_NONE;
}

static inline void
do_parse(ChildMonitor *self, Screen *screen, double now) {
    screen_mutex(lock, read);
    if (screen->read_buf_sz || screen->pending_mode.used) {
        double time_since_new_input = now - screen->new_input_at;
        if (time_since_new_input >= OPT(input_delay)) {
            bool read_buf_full = screen->read_buf_sz >= READ_BUF_SZ;
            parse_func(screen, self->dump_callback, now);
            if (read_buf_full) wakeup_io_loop(false);  // Ensure the read fd has POLLIN set
            screen->new_input_at = 0;
            if (screen->pending_mode.activated_at) {
                double time_since_pending = MAX(0, now - screen->pending_mode.activated_at);
                set_maximum_wait(screen->pending_mode.wait_time - time_since_pending);
            }
        } else set_maximum_wait(OPT(input_delay) - time_since_new_input);
    }
    screen_mutex(unlock, read);
}

static void
parse_input(ChildMonitor *self) {
    // Parse all available input that was read in the I/O thread.
    size_t count = 0, remove_count = 0;
    double now = monotonic();
    PyObject *msg = NULL;
    children_mutex(lock);
    while (remove_queue_count) {
        remove_queue_count--;
        remove_notify[remove_count] = remove_queue[remove_queue_count].id;
        remove_count++;
        FREE_CHILD(remove_queue[remove_queue_count]);
    }

    if (UNLIKELY(self->messages_count)) {
        msg = PyTuple_New(self->messages_count);
        if (msg) {
            for (size_t i = 0; i < self->messages_count; i++) {
                Message *m = self->messages + i;
                PyTuple_SET_ITEM(msg, i, Py_BuildValue("y#i", m->data, (int)m->sz, m->fd));
                free(m->data); m->data = NULL; m->sz = 0;
            }
            self->messages_count = 0;
        } else fatal("Out of memory");
    }

    if (UNLIKELY(kill_signal_received)) {
        global_state.terminate = true;
    } else {
        count = self->count;
        for (size_t i = 0; i < count; i++) {
            scratch[i] = children[i];
            INCREF_CHILD(scratch[i]);
        }
    }
    children_mutex(unlock);
    if (msg) {
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(msg); i++) {
            PyObject *resp = PyObject_CallMethod(global_state.boss, "peer_message_received", "O", PyTuple_GET_ITEM(PyTuple_GET_ITEM(msg, i), 0));
            int peer_fd = (int)PyLong_AsLong(PyTuple_GET_ITEM(PyTuple_GET_ITEM(msg, i), 1));
            if (resp && PyBytes_Check(resp)) send_response(peer_fd, PyBytes_AS_STRING(resp), PyBytes_GET_SIZE(resp));
            else { send_response(peer_fd, NULL, 0); if (!resp) PyErr_Print(); }
            Py_CLEAR(resp);
        }
        Py_CLEAR(msg);
    }

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
            do_parse(self, scratch[i].screen, now);
        }
        DECREF_CHILD(scratch[i]);
    }
}

static inline void
mark_child_for_close(ChildMonitor *self, id_type window_id) {
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].id == window_id) {
            children[i].needs_removal = true;
            break;
        }
    }
    children_mutex(unlock);
    wakeup_io_loop(false);
}


static PyObject *
mark_for_close(ChildMonitor *self, PyObject *args) {
#define mark_for_close_doc "Mark a child to be removed from the child monitor"
    id_type window_id;
    if (!PyArg_ParseTuple(args, "K", &window_id)) return NULL;
    mark_child_for_close(self, window_id);
    Py_RETURN_NONE;
}

static inline bool
pty_resize(int fd, struct winsize *dim) {
    while(true) {
        if (ioctl(fd, TIOCSWINSZ, dim) == -1) {
            if (errno == EINTR) continue;
            if (errno != EBADF && errno != ENOTTY) {
                log_error("Failed to resize tty associated with fd: %d with error: %s", fd, strerror(errno));
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
    int fd = -1;
    if (!PyArg_ParseTuple(args, "kHHHH", &window_id, &dim.ws_row, &dim.ws_col, &dim.ws_xpixel, &dim.ws_ypixel)) return NULL;
    children_mutex(lock);
#define FIND(queue, count) { \
    for (size_t i = 0; i < count; i++) { \
        if (queue[i].id == window_id) { \
            fd = queue[i].fd; \
            break; \
        } \
    }}
    FIND(children, self->count);
    if (fd == -1) FIND(add_queue, add_queue_count);
    if (fd != -1) {
        if (!pty_resize(fd, &dim)) PyErr_SetFromErrno(PyExc_OSError);
    } else log_error("Failed to send resize signal to child with id: %lu (children count: %u) (add queue: %zu)", window_id, self->count, add_queue_count);
    children_mutex(unlock);
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
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

extern void cocoa_update_title(PyObject*);

static inline void
collect_cursor_info(CursorRenderInfo *ans, Window *w, double now, OSWindow *os_window) {
    ScreenRenderData *rd = &w->render_data;
    Cursor *cursor = rd->screen->cursor;
    ans->x = cursor->x; ans->y = cursor->y;
    ans->is_visible = false;
    if (rd->screen->scrolled_by || !screen_is_cursor_visible(rd->screen)) return;
    double time_since_start_blink = now - os_window->cursor_blink_zero_time;
    bool cursor_blinking = OPT(cursor_blink_interval) > 0 && os_window->is_focused && (OPT(cursor_stop_blinking_after) == 0 || time_since_start_blink <= OPT(cursor_stop_blinking_after));
    bool do_draw_cursor = true;
    if (cursor_blinking) {
        int t = (int)(time_since_start_blink * 1000);
        int d = (int)(OPT(cursor_blink_interval) * 1000);
        int n = t / d;
        do_draw_cursor = n % 2 == 0 ? true : false;
        double bucket = (n + 1) * d;
        double delay = (bucket / 1000.0) - time_since_start_blink;
        set_maximum_wait(delay);
    }
    if (!do_draw_cursor) { ans->is_visible = false; return; }
    ans->is_visible = true;
    ColorProfile *cp = rd->screen->color_profile;
    ans->shape = cursor->shape ? cursor->shape : OPT(cursor_shape);
    ans->color = colorprofile_to_color(cp, cp->overridden.cursor_color, cp->configured.cursor_color);
    ans->is_focused = os_window->is_focused;
}

static inline bool
update_window_title(Window *w, OSWindow *os_window) {
    if (w->title && w->title != os_window->window_title) {
        os_window->window_title = w->title;
        Py_INCREF(os_window->window_title);
        set_os_window_title(os_window, PyUnicode_AsUTF8(w->title));
#ifdef __APPLE__
        if (os_window->is_focused && OPT(macos_show_window_title_in_menubar)) cocoa_update_title(w->title);
#endif
        return true;
    }
    return false;
}

static inline bool
prepare_to_render_os_window(OSWindow *os_window, double now, unsigned int *active_window_id, color_type *active_window_bg, unsigned int *num_visible_windows) {
#define TD os_window->tab_bar_render_data
    bool needs_render = os_window->needs_render;
    os_window->needs_render = false;
    if (TD.screen && os_window->num_tabs >= OPT(tab_bar_min_tabs)) {
        if (!os_window->tab_bar_data_updated) {
            call_boss(update_tab_bar_data, "K", os_window->id);
            os_window->tab_bar_data_updated = true;
        }
        if (send_cell_data_to_gpu(TD.vao_idx, 0, TD.xstart, TD.ystart, TD.dx, TD.dy, TD.screen, os_window)) needs_render = true;
    }
    if (OPT(mouse_hide_wait) > 0 && !is_mouse_hidden(os_window)) {
        if (now - os_window->last_mouse_activity_at >= OPT(mouse_hide_wait)) hide_mouse(os_window);
        else set_maximum_wait(OPT(mouse_hide_wait) - now + os_window->last_mouse_activity_at);
    }
    Tab *tab = os_window->tabs + os_window->active_tab;
    *active_window_bg = OPT(background);
    for (unsigned int i = 0; i < tab->num_windows; i++) {
        Window *w = tab->windows + i;
#define WD w->render_data
        if (w->visible && WD.screen) {
            *num_visible_windows += 1;
            if (w->last_drag_scroll_at > 0) {
                if (now - w->last_drag_scroll_at >= 0.02) {
                    if (drag_scroll(w, os_window)) {
                        w->last_drag_scroll_at = now;
                        set_maximum_wait(0.02);
                        needs_render = true;
                    } else w->last_drag_scroll_at = 0;
                } else set_maximum_wait(now - w->last_drag_scroll_at);
            }
            bool is_active_window = i == tab->active_window;
            if (is_active_window) {
                *active_window_id = w->id;
                collect_cursor_info(&WD.screen->cursor_render_info, w, now, os_window);
                if (w->cursor_visible_at_last_render != WD.screen->cursor_render_info.is_visible || w->last_cursor_x != WD.screen->cursor_render_info.x || w->last_cursor_y != WD.screen->cursor_render_info.y || w->last_cursor_shape != WD.screen->cursor_render_info.shape) needs_render = true;
                update_window_title(w, os_window);
                *active_window_bg = colorprofile_to_color(WD.screen->color_profile, WD.screen->color_profile->overridden.default_bg, WD.screen->color_profile->configured.default_bg);
            } else WD.screen->cursor_render_info.is_visible = false;
            if (send_cell_data_to_gpu(WD.vao_idx, WD.gvao_idx, WD.xstart, WD.ystart, WD.dx, WD.dy, WD.screen, os_window)) needs_render = true;
            if (WD.screen->start_visual_bell_at != 0) needs_render = true;
        }
    }
    return needs_render;
}

static inline void
render_os_window(OSWindow *os_window, double now, unsigned int active_window_id, color_type active_window_bg, unsigned int num_visible_windows) {
    // ensure all pixels are cleared to background color at least once in every buffer
    if (os_window->clear_count++ < 3) blank_os_window(os_window);
    Tab *tab = os_window->tabs + os_window->active_tab;
    BorderRects *br = &tab->border_rects;
    draw_borders(br->vao_idx, br->num_border_rects, br->rect_buf, br->is_dirty, os_window->viewport_width, os_window->viewport_height, active_window_bg, num_visible_windows, os_window);
    if (TD.screen && os_window->num_tabs >= OPT(tab_bar_min_tabs)) draw_cells(TD.vao_idx, 0, TD.xstart, TD.ystart, TD.dx, TD.dy, TD.screen, os_window, true, false);
    for (unsigned int i = 0; i < tab->num_windows; i++) {
        Window *w = tab->windows + i;
        if (w->visible && WD.screen) {
            bool is_active_window = i == tab->active_window;
            draw_cells(WD.vao_idx, WD.gvao_idx, WD.xstart, WD.ystart, WD.dx, WD.dy, WD.screen, os_window, is_active_window, true);
            if (WD.screen->start_visual_bell_at != 0) {
                double bell_left = global_state.opts.visual_bell_duration - (now - WD.screen->start_visual_bell_at);
                set_maximum_wait(bell_left);
            }
            w->cursor_visible_at_last_render = WD.screen->cursor_render_info.is_visible; w->last_cursor_x = WD.screen->cursor_render_info.x; w->last_cursor_y = WD.screen->cursor_render_info.y; w->last_cursor_shape = WD.screen->cursor_render_info.shape;
        }
    }
    swap_window_buffers(os_window);
    br->is_dirty = false;
    os_window->last_active_tab = os_window->active_tab; os_window->last_num_tabs = os_window->num_tabs; os_window->last_active_window_id = active_window_id;
    os_window->focused_at_last_render = os_window->is_focused;
    os_window->is_damaged = false;
    if (USE_RENDER_FRAMES) request_frame_render(os_window);
#undef WD
#undef TD
}

static inline void
update_os_window_title(OSWindow *os_window) {
    Tab *tab = os_window->tabs + os_window->active_tab;
    if (tab->num_windows) {
        Window *w = tab->windows + tab->active_window;
        update_window_title(w, os_window);
    }
}

static void
draw_resizing_text(OSWindow *w) {
    char text[32] = {0};
    unsigned int width = w->live_resize.width, height = w->live_resize.height;
    snprintf(text, sizeof(text), "%u x %u cells", width / w->fonts_data->cell_width, height / w->fonts_data->cell_height);
    StringCanvas rendered = render_simple_text(w->fonts_data, text);
    if (rendered.canvas) {
        draw_centered_alpha_mask(w->gvao_idx, width, height, rendered.width, rendered.height, rendered.canvas);
        free(rendered.canvas);
    }
}

static inline void
render(double now) {
    double time_since_last_render = now - last_render_at;
    if (time_since_last_render < OPT(repaint_delay)) {
        set_maximum_wait(OPT(repaint_delay) - time_since_last_render);
        return;
    }

    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (!w->num_tabs) continue;
        if (!should_os_window_be_rendered(w)) {
            update_os_window_title(w);
            continue;
        }
        if (USE_RENDER_FRAMES && w->render_state != RENDER_FRAME_READY) {
            if (w->render_state == RENDER_FRAME_NOT_REQUESTED) request_frame_render(w);
            continue;
        }
        make_os_window_context_current(w);
        if (w->live_resize.in_progress) {
            blank_os_window(w);
            draw_resizing_text(w);
            swap_window_buffers(w);
            if (USE_RENDER_FRAMES) request_frame_render(w);
            continue;
        }
        bool needs_render = w->is_damaged;
        if (w->viewport_size_dirty) {
            w->clear_count = 0;
            update_surface_size(w->viewport_width, w->viewport_height, w->offscreen_texture_id);
            w->viewport_size_dirty = false;
            needs_render = true;
        }
        unsigned int active_window_id = 0, num_visible_windows = 0;
        color_type active_window_bg = 0;
        if (!w->fonts_data) { log_error("No fonts data found for window id: %llu", w->id); continue; }
        if (prepare_to_render_os_window(w, now, &active_window_id, &active_window_bg, &num_visible_windows)) needs_render = true;
        if (w->last_active_window_id != active_window_id || w->last_active_tab != w->active_tab || w->focused_at_last_render != w->is_focused) needs_render = true;
        if (needs_render) render_os_window(w, now, active_window_id, active_window_bg, num_visible_windows);
    }
    last_render_at = now;
#undef TD
}


typedef struct { int fd; uint8_t *buf; size_t sz; } ThreadWriteData;

static inline ThreadWriteData*
alloc_twd(size_t sz) {
    ThreadWriteData *data = malloc(sizeof(ThreadWriteData));
    if (data != NULL) {
        data->sz = sz;
        data->buf = malloc(sz);
        if (data->buf == NULL) { free(data); data = NULL; }
    }
    return data;
}

static inline void
free_twd(ThreadWriteData *x) {
    if (x != NULL) free(x->buf);
    free(x);
}

static PyObject*
monitor_pid(PyObject *self UNUSED, PyObject *args) {
    long pid;
    bool ok = true;
    if (!PyArg_ParseTuple(args, "l", &pid)) return NULL;
    children_mutex(lock);
    if (monitored_pids_count >= arraysz(monitored_pids)) {
        PyErr_SetString(PyExc_RuntimeError, "Too many monitored pids");
        ok = false;
    } else {
        monitored_pids[monitored_pids_count++] = pid;
    }
    children_mutex(unlock);
    if (!ok) return NULL;
    Py_RETURN_NONE;
}

static inline void
report_reaped_pids() {
    children_mutex(lock);
    if (reaped_pids_count) {
        for (size_t i = 0; i < reaped_pids_count; i++) {
            call_boss(on_monitored_pid_death, "ii", (int)reaped_pids[i].pid, reaped_pids[i].status);
        }
        reaped_pids_count = 0;
    }
    children_mutex(unlock);
}

static void*
thread_write(void *x) {
    ThreadWriteData *data = (ThreadWriteData*)x;
    set_thread_name("KittyWriteStdin");
    FILE *f = fdopen(data->fd, "w");
    if (fwrite(data->buf, 1, data->sz, f) != data->sz) {
        log_error("Failed to write all data");
    }
    fclose(f);
    free_twd(data);
    return 0;
}

PyObject*
cm_thread_write(PyObject UNUSED *self, PyObject *args) {
    static pthread_t thread;
    int fd;
    Py_ssize_t sz;
    const char *buf;
    if (!PyArg_ParseTuple(args, "is#", &fd, &buf, &sz)) return NULL;
    ThreadWriteData *data = alloc_twd(sz);
    if (data == NULL) return PyErr_NoMemory();
    data->fd = fd;
    memcpy(data->buf, buf, data->sz);
    int ret = pthread_create(&thread, NULL, thread_write, data);
    if (ret != 0) { free_twd(data); return PyErr_SetFromErrno(PyExc_OSError); }
    Py_RETURN_NONE;
}

static void
python_timer_callback(id_type timer_id, void *data) {
    PyObject *callback = (PyObject*)data;
    unsigned long long id = timer_id;
    PyObject *ret = PyObject_CallFunction(callback, "K", id);
    if (ret == NULL) PyErr_Print();
    else Py_DECREF(ret);
}

static void
python_timer_cleanup(id_type timer_id UNUSED, void *data) {
    if (data) Py_DECREF((PyObject*)data);
}

static PyObject*
add_python_timer(PyObject *self UNUSED, PyObject *args) {
    PyObject *callback;
    double interval;
    int repeats = 1;
    if (!PyArg_ParseTuple(args, "Od|p", &callback, &interval, &repeats)) return NULL;
    unsigned long long timer_id = add_main_loop_timer(interval, repeats ? true: false, python_timer_callback, callback, python_timer_cleanup);
    Py_INCREF(callback);
    return Py_BuildValue("K", timer_id);
}

static PyObject*
remove_python_timer(PyObject *self UNUSED, PyObject *args) {
    unsigned long long timer_id;
    if (!PyArg_ParseTuple(args, "K", &timer_id)) return NULL;
    remove_main_loop_timer(timer_id);
    Py_RETURN_NONE;
}


static inline void
process_pending_resizes(double now) {
    global_state.has_pending_resizes = false;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (w->live_resize.in_progress) {
            bool update_viewport = false;
            if (w->live_resize.from_os_notification) {
                if (w->live_resize.os_says_resize_complete || (now - w->live_resize.last_resize_event_at) > 1) update_viewport = true;
            } else {
                if (now - w->live_resize.last_resize_event_at >= RESIZE_DEBOUNCE_TIME) update_viewport = true;
                else {
                    global_state.has_pending_resizes = true;
                    set_maximum_wait(RESIZE_DEBOUNCE_TIME - now + w->live_resize.last_resize_event_at);
                }
            }
            if (update_viewport) {
                static const LiveResizeInfo empty = {0};
                update_os_window_viewport(w, true);
                w->live_resize = empty;
            }
        }
    }
}

static inline void
close_all_windows() {
    for (size_t w = 0; w < global_state.num_os_windows; w++) mark_os_window_for_close(&global_state.os_windows[w], true);
}

static inline bool
process_pending_closes(ChildMonitor *self) {
    global_state.has_pending_closes = false;
    bool has_open_windows = false;
    for (size_t w = global_state.num_os_windows; w > 0; w--) {
        OSWindow *os_window = global_state.os_windows + w - 1;
        if (should_os_window_close(os_window)) {
            destroy_os_window(os_window);
            call_boss(on_os_window_closed, "Kii", os_window->id, os_window->window_width, os_window->window_height);
            for (size_t t=0; t < os_window->num_tabs; t++) {
                Tab *tab = os_window->tabs + t;
                for (size_t w = 0; w < tab->num_windows; w++) mark_child_for_close(self, tab->windows[w].id);
            }
            remove_os_window(os_window->id);
        } else has_open_windows = true;
    }
#ifdef __APPLE__
    if (!OPT(macos_quit_when_last_window_closed)) {
        if (!has_open_windows && !application_quit_requested()) has_open_windows = true;
    }
#endif
    return has_open_windows;
}

#ifdef __APPLE__
// If we create new OS windows during wait_events(), using global menu actions
// via the mouse causes a crash because of the way autorelease pools work in
// glfw/cocoa. So we use a flag instead.
static unsigned int cocoa_pending_actions = 0;
static char *cocoa_pending_actions_wd = NULL;

void
set_cocoa_pending_action(CocoaPendingAction action, const char *wd) {
    if (wd) {
        if (cocoa_pending_actions_wd) free(cocoa_pending_actions_wd);
        cocoa_pending_actions_wd = strdup(wd);
    }
    cocoa_pending_actions |= action;
    // The main loop may be blocking on the event queue, if e.g. unfocused.
    // Unjam it so the pending action is processed right now.
    wakeup_main_loop();
}
#endif

static void process_global_state(void *data);

static void
do_state_check(id_type timer_id UNUSED, void *data) {
    ChildMonitor *self = data;
    process_global_state(self);
}

static id_type state_check_timer = 0;

static void
process_global_state(void *data) {
    ChildMonitor *self = data;
    maximum_wait = -1;
    bool state_check_timer_enabled = false;

    double now = monotonic();
    if (global_state.has_pending_resizes) process_pending_resizes(now);
    render(now);
#ifdef __APPLE__
        if (cocoa_pending_actions) {
            if (cocoa_pending_actions & PREFERENCES_WINDOW) { call_boss(edit_config_file, NULL); }
            if (cocoa_pending_actions & NEW_OS_WINDOW) { call_boss(new_os_window, NULL); }
            if (cocoa_pending_actions_wd) {
                if (cocoa_pending_actions & NEW_OS_WINDOW_WITH_WD) { call_boss(new_os_window_with_wd, "s", cocoa_pending_actions_wd); }
                if (cocoa_pending_actions & NEW_TAB_WITH_WD) { call_boss(new_tab_with_wd, "s", cocoa_pending_actions_wd); }
                free(cocoa_pending_actions_wd);
                cocoa_pending_actions_wd = NULL;
            }
            cocoa_pending_actions = 0;
        }
#endif
    parse_input(self);
    if (global_state.terminate) {
        global_state.terminate = false;
        close_all_windows();
#ifdef __APPLE__
        request_application_quit();
#endif
    }
    report_reaped_pids();
    bool has_open_windows = true;
    if (global_state.has_pending_closes) has_open_windows = process_pending_closes(self);
    if (has_open_windows) {
        if (maximum_wait >= 0) {
            if (maximum_wait == 0) request_tick_callback();
            else state_check_timer_enabled = true;
        }
    } else {
        stop_main_loop();
    }
    update_main_loop_timer(state_check_timer, MAX(0, maximum_wait), state_check_timer_enabled);
}

static PyObject*
main_loop(ChildMonitor *self, PyObject *a UNUSED) {
#define main_loop_doc "The main thread loop"
    state_check_timer = add_main_loop_timer(1000, true, do_state_check, self, NULL);
    run_main_loop(process_global_state, self);
#ifdef __APPLE__
    if (cocoa_pending_actions_wd) { free(cocoa_pending_actions_wd); cocoa_pending_actions_wd = NULL; }
#endif
    if (PyErr_Occurred()) return NULL;
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


static inline void
cleanup_child(ssize_t i) {
    close(children[i].fd);
    hangup(children[i].pid);
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
                fds[EXTRA_FDS + i].fd = -1;
                size_t num_to_right = self->count - 1 - i;
                if (num_to_right > 0) {
                    memmove(children + i, children + i + 1, num_to_right * sizeof(Child));
                    memmove(fds + EXTRA_FDS + i, fds + EXTRA_FDS + i + 1, num_to_right * sizeof(struct pollfd));
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
            if (errno == EINTR || errno == EAGAIN) continue;
            if (errno != EIO) perror("Call to read() from child fd failed");
            return false;
        }
        break;
    }
    if (UNLIKELY(len == 0)) return false;

    screen_mutex(lock, read);
    if (screen->new_input_at == 0) screen->new_input_at = monotonic();
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
read_signals(int fd, bool *kill_signal, bool *child_died) {
    static char buf[256];
    while(true) {
        ssize_t len = read(fd, buf, sizeof(buf));
        if (len < 0) {
            if (errno == EINTR) continue;
            if (errno != EIO) perror("Call to read() from read_signals() failed");
            break;
        }
        for (ssize_t i = 0; i < len; i++) {
            switch(buf[i]) {
                case SIGCHLD:
                    *child_died = true; break;
                case SIGINT:
                case SIGTERM:
                    *kill_signal = true; break;
                default:
                    break;
            }
        }
        break;
    }
}

static inline void
mark_child_for_removal(ChildMonitor *self, pid_t pid) {
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].pid == pid) {
            children[i].needs_removal = true;
            break;
        }
    }
    children_mutex(unlock);
}

static inline void
mark_monitored_pids(pid_t pid, int status) {
    children_mutex(lock);
    for (ssize_t i = monitored_pids_count - 1; i >= 0; i--) {
        if (pid == monitored_pids[i]) {
            if (reaped_pids_count < arraysz(reaped_pids)) {
                reaped_pids[reaped_pids_count].status = status;
                reaped_pids[reaped_pids_count++].pid = pid;
            }
            remove_i_from_array(monitored_pids, (size_t)i, monitored_pids_count);
        }
    }
    children_mutex(unlock);
}

static inline void
reap_children(ChildMonitor *self, bool enable_close_on_child_death) {
    int status;
    pid_t pid;
    (void)self;
    while(true) {
        pid = waitpid(-1, &status, WNOHANG);
        if (pid == -1) {
            if (errno != EINTR) break;
        } else if (pid > 0) {
            if (enable_close_on_child_death) mark_child_for_removal(self, pid);
            mark_monitored_pids(pid, status);
        } else break;
    }
}

static inline void
write_to_child(int fd, Screen *screen) {
    size_t written = 0;
    ssize_t ret = 0;
    screen_mutex(lock, write);
    while (written < screen->write_buf_used) {
        ret = write(fd, screen->write_buf + written, screen->write_buf_used - written);
        if (ret > 0) { written += ret; }
        else if (ret == 0) {
            // could mean anything, ignore
            break;
        } else {
            if (errno == EINTR) continue;
            if (errno == EWOULDBLOCK || errno == EAGAIN) break;
            perror("Call to write() to child fd failed, discarding data.");
            written = screen->write_buf_used;
        }
    }
    if (written) {
        screen->write_buf_used -= written;
        if (screen->write_buf_used) {
            memmove(screen->write_buf, screen->write_buf + written, screen->write_buf_used);
        }
    }
    screen_mutex(unlock, write);
}

static void*
io_loop(void *data) {
    // The I/O thread loop
    size_t i;
    int ret;
    bool has_more, data_received, has_pending_wakeups = false;
    double last_main_loop_wakeup_at = -1, now = -1;
    Screen *screen;
    ChildMonitor *self = (ChildMonitor*)data;
    set_thread_name("KittyChildMon");

    while (LIKELY(!self->shutting_down)) {
        children_mutex(lock);
        remove_children(self);
        add_children(self);
        children_mutex(unlock);
        data_received = false;
        for (i = 0; i < self->count + EXTRA_FDS; i++) fds[i].revents = 0;
        for (i = 0; i < self->count; i++) {
            screen = children[i].screen;
            /* printf("i:%lu id:%lu fd: %d read_buf_sz: %lu write_buf_used: %lu\n", i, children[i].id, children[i].fd, screen->read_buf_sz, screen->write_buf_used); */
            screen_mutex(lock, read); screen_mutex(lock, write);
            fds[EXTRA_FDS + i].events = (screen->read_buf_sz < READ_BUF_SZ ? POLLIN : 0) | (screen->write_buf_used ? POLLOUT  : 0);
            screen_mutex(unlock, read); screen_mutex(unlock, write);
        }
        if (has_pending_wakeups) {
            now = monotonic();
            double time_delta = OPT(input_delay) - (now - last_main_loop_wakeup_at);
            if (time_delta >= 0) ret = poll(fds, self->count + EXTRA_FDS, (int)ceil(1000 * time_delta));
            else ret = 0;
        } else {
            ret = poll(fds, self->count + EXTRA_FDS, -1);
        }
        if (ret > 0) {
            if (fds[0].revents && POLLIN) drain_fd(fds[0].fd); // wakeup
            if (fds[1].revents && POLLIN) {
                data_received = true;
                bool kill_signal = false, child_died = false;
                read_signals(fds[1].fd, &kill_signal, &child_died);
                if (kill_signal) { children_mutex(lock); kill_signal_received = true; children_mutex(unlock); }
                if (child_died) reap_children(self, OPT(close_on_child_death));
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
                if (fds[EXTRA_FDS + i].revents & POLLNVAL) {
                    // fd was closed
                    children_mutex(lock);
                    children[i].needs_removal = true;
                    children_mutex(unlock);
                    log_error("The child %lu had its fd unexpectedly closed", children[i].id);
                }
            }
#ifdef DEBUG_POLL_EVENTS
            for (i = 0; i < self->count + EXTRA_FDS; i++) {
#define P(w) if (fds[i].revents & w) printf("i:%lu %s\n", i, #w);
                P(POLLIN); P(POLLPRI); P(POLLOUT); P(POLLERR); P(POLLHUP); P(POLLNVAL);
#undef P
            }
#endif
        } else if (ret < 0) {
            if (errno != EAGAIN && errno != EINTR) {
                perror("Call to poll() failed");
            }
        }
#define WAKEUP { wakeup_main_loop(); last_main_loop_wakeup_at = now; has_pending_wakeups = false; }
        // we only wakeup the main loop after input_delay as wakeup is an expensive operation
        // on some platforms, such as cocoa
        if (data_received) {
            if ((now = monotonic()) - last_main_loop_wakeup_at > OPT(input_delay)) WAKEUP
            else has_pending_wakeups = true;
        } else {
            if (has_pending_wakeups && (now = monotonic()) - last_main_loop_wakeup_at > OPT(input_delay)) WAKEUP
        }
    }
#undef WAKEUP
    children_mutex(lock);
    for (i = 0; i < self->count; i++) children[i].needs_removal = true;
    remove_children(self);
    children_mutex(unlock);
    return 0;
}
// }}}

// {{{ Talk thread functions

typedef struct {
    char *data;
    size_t capacity, used;
    int fd;
    bool finished, close_socket;
} PeerReadData;
static PeerReadData empty_prd = {.fd = -1, 0};

typedef struct {
    char *data;
    size_t sz, pos;
    int fd;
    bool finished;
} PeerWriteData;
static PeerWriteData empty_pwd = {.fd = -1, 0};

typedef struct {
    size_t num_listen_fds, num_talk_fds, num_reads, num_writes, num_queued_writes;
    size_t fds_capacity, reads_capacity, writes_capacity, queued_writes_capacity;
    struct pollfd *fds;
    PeerReadData *reads;
    PeerWriteData *writes;
    PeerWriteData *queued_writes;
    int wakeup_fds[2];
    pthread_mutex_t peer_lock;
} TalkData;

static TalkData talk_data = {0};
typedef struct pollfd PollFD;
#define PEER_LIMIT 256
#define nuke_socket(s) { shutdown(s, SHUT_RDWR); close(s); }

static inline bool
accept_peer(int listen_fd, bool shutting_down) {
    int peer = accept(listen_fd, NULL, NULL);
    if (UNLIKELY(peer == -1)) {
        if (errno == EINTR) return true;
        if (!shutting_down) perror("accept() on talk socket failed!");
        return false;
    }
    size_t fd_idx = talk_data.num_listen_fds + talk_data.num_talk_fds;
    if (fd_idx < PEER_LIMIT && talk_data.reads_capacity < PEER_LIMIT) {
        ensure_space_for(&talk_data, fds, PollFD, fd_idx + 1, fds_capacity, 8, false);
        talk_data.fds[fd_idx].fd = peer; talk_data.fds[fd_idx].events = POLLIN;
        ensure_space_for(&talk_data, reads, PeerReadData, talk_data.num_reads + 1, reads_capacity, 8, false);
        talk_data.reads[talk_data.num_reads] = empty_prd; talk_data.reads[talk_data.num_reads++].fd = peer;
        talk_data.num_talk_fds++;
    } else {
        log_error("Too many peers want to talk, ignoring one.");
        nuke_socket(peer);
    }
    return true;
}

static inline bool
read_from_peer(ChildMonitor *self, int s) {
    bool read_finished = false;
    for (size_t i = 0; i < talk_data.num_reads; i++) {
        PeerReadData *rd = talk_data.reads + i;
#define failed(msg) { read_finished = true; log_error("%s", msg); rd->finished = true; rd->close_socket = true; break; }
        if (rd->fd == s) {
            if (rd->used >= rd->capacity) {
                if (rd->capacity >= 1024 * 1024) failed("Ignoring too large message from peer");
                rd->capacity = MAX(8192, rd->capacity * 2);
                rd->data = realloc(rd->data, rd->capacity);
                if (!rd->data) failed("Out of memory");
            }
            ssize_t n = recv(s, rd->data + rd->used, rd->capacity - rd->used, 0);
            if (n == 0) {
                read_finished = true; rd->finished = true;
                children_mutex(lock);
                ensure_space_for(self, messages, Message, self->messages_count + 1, messages_capacity, 16, true);
                Message *m = self->messages + self->messages_count++;
                m->data = rd->data; rd->data = NULL; m->sz = rd->used; m->fd = s;
                children_mutex(unlock);
                wakeup_main_loop();
            } else if (n < 0) {
                if (errno != EINTR) {
                    perror("Error reading from talk peer");
                    failed("");
                }
            } else rd->used += n;
            break;
        }
    }
#undef failed
    return read_finished;
}

static inline bool
write_to_peer(int fd) {
    bool write_finished = false;
    for (size_t i = 0; i < talk_data.num_writes; i++) {
        PeerWriteData *wd = talk_data.writes + i;
#define failed(msg) { write_finished = true; log_error("%s", msg); wd->finished = true; break; }
        if (wd->fd == fd) {
            ssize_t n = send(fd, wd->data + wd->pos, wd->sz - wd->pos, MSG_NOSIGNAL);
            if (n == 0) { failed("send() to peer failed to send any data"); }
            else if (n < 0) {
                if (errno != EINTR) { perror("write() to peer socket failed with error"); failed(""); }
            } else {
                wd->pos += n;
                if (wd->pos >= wd->sz) { write_finished = true; wd->finished = true; }
            }
            break;
        }

    }
#undef failed
    return write_finished;
}

static inline void
remove_poll_fd(int fd) {
    size_t count = talk_data.num_talk_fds + talk_data.num_listen_fds;
    for (size_t i = talk_data.num_listen_fds; i < count; i++) {
        struct pollfd *pfd = talk_data.fds + i;
        if (pfd->fd == fd) {
            size_t num_to_right = count - 1 - i;
            if (num_to_right) memmove(talk_data.fds + i, talk_data.fds + i + 1, num_to_right * sizeof(struct pollfd));
            talk_data.num_talk_fds--;
            break;
        }
    }
}

static inline void
prune_finished_reads() {
    if (!talk_data.num_reads) return;
    for (ssize_t i = talk_data.num_reads - 1; i >= 0; i--) {
        PeerReadData *rd = talk_data.reads + i;
        if (rd->finished) {
            remove_poll_fd(rd->fd);
            if (rd->close_socket) { nuke_socket(rd->fd); }
            else shutdown(rd->fd, SHUT_RD);
            free(rd->data);
            ssize_t num_to_right = talk_data.num_reads - 1 - i;
            if (num_to_right > 0) memmove(talk_data.reads + i, talk_data.reads + i + 1, num_to_right * sizeof(PeerReadData));
            else talk_data.reads[i] = empty_prd;
            talk_data.num_reads--;
        }
    }
}

static inline void
prune_finished_writes() {
    if (!talk_data.num_writes) return;
    for (ssize_t i = talk_data.num_writes - 1; i >= 0; i--) {
        PeerWriteData *wd = talk_data.writes + i;
        if (wd->finished) {
            remove_poll_fd(wd->fd);
            shutdown(wd->fd, SHUT_WR); close(wd->fd);
            free(wd->data);
            ssize_t num_to_right = talk_data.num_writes - 1 - i;
            if (num_to_right > 0) memmove(talk_data.writes + i, talk_data.writes + i + 1, num_to_right * sizeof(PeerWriteData));
            else talk_data.writes[i] = empty_pwd;
            talk_data.num_writes--;
        }
    }
}

static void
wakeup_talk_loop(bool in_signal_handler) {
    if (talk_data.wakeup_fds[1] <= 0) return;
    while(true) {
        ssize_t ret = write(talk_data.wakeup_fds[1], "w", 1);
        if (ret < 0) {
            if (errno == EINTR) continue;
            if (!in_signal_handler) perror("Failed to write to talk wakeup fd with error");
        }
        break;
    }
}

static inline void
move_queued_writes() {
    while (talk_data.num_queued_writes) {
        PeerWriteData *src = talk_data.queued_writes + --talk_data.num_queued_writes;
        size_t fd_idx = talk_data.num_listen_fds + talk_data.num_talk_fds;
        if (fd_idx < PEER_LIMIT && talk_data.num_writes < PEER_LIMIT) {
            ensure_space_for(&talk_data, fds, PollFD, fd_idx + 1, fds_capacity, 8, false);
            talk_data.fds[fd_idx].fd = src->fd; talk_data.fds[fd_idx].events = POLLOUT;
            ensure_space_for(&talk_data, writes, PeerWriteData, talk_data.num_writes + 1, writes_capacity, 8, false);
            talk_data.writes[talk_data.num_writes++] = *src;
            talk_data.num_talk_fds++;
        } else {
            log_error("Cannot send response to peer, too many peers");
            free(src->data); nuke_socket(src->fd);
        }
        *src = empty_pwd;
    }
}

static void*
talk_loop(void *data) {
    // The talk thread loop

    ChildMonitor *self = (ChildMonitor*)data;
    set_thread_name("KittyPeerMon");
    if ((pthread_mutex_init(&talk_data.peer_lock, NULL)) != 0) { perror("Failed to create peer mutex"); return 0; }
    if (!self_pipe(talk_data.wakeup_fds)) { perror("Failed to create wakeup fds for talk thread"); return 0; }
    ensure_space_for(&talk_data, fds, PollFD, 8, fds_capacity, 8, false);
#define add_listener(which) \
    if (self->which > -1) { \
        talk_data.fds[talk_data.num_listen_fds].fd = self->which; talk_data.fds[talk_data.num_listen_fds++].events = POLLIN; \
    }
    add_listener(talk_fd); add_listener(listen_fd);
#undef add_listener
    talk_data.fds[talk_data.num_listen_fds].fd = talk_data.wakeup_fds[0]; talk_data.fds[talk_data.num_listen_fds++].events = POLLIN;

    while (LIKELY(!self->shutting_down)) {
        for (size_t i = 0; i < talk_data.num_listen_fds + talk_data.num_talk_fds; i++) { talk_data.fds[i].revents = 0; }
        int ret = poll(talk_data.fds, talk_data.num_listen_fds + talk_data.num_talk_fds, -1);
        if (ret > 0) {
            bool has_finished_reads = false, has_finished_writes = false;
            for (size_t i = 0; i < talk_data.num_listen_fds - 1; i++) {
                if (talk_data.fds[i].revents & POLLIN) {if (!accept_peer(talk_data.fds[i].fd, self->shutting_down)) goto end; }
            }
            if (talk_data.fds[talk_data.num_listen_fds - 1].revents & POLLIN) drain_fd(talk_data.fds[talk_data.num_listen_fds - 1].fd);  // wakeup
            for (size_t i = talk_data.num_listen_fds; i < talk_data.num_talk_fds + talk_data.num_listen_fds; i++) {
                if (talk_data.fds[i].revents & (POLLIN | POLLHUP)) { if (read_from_peer(self, talk_data.fds[i].fd)) has_finished_reads = true; }
                if (talk_data.fds[i].revents & POLLOUT) { if (write_to_peer(talk_data.fds[i].fd)) has_finished_writes = true; }
            }
            if (has_finished_reads) prune_finished_reads();
            if (has_finished_writes) prune_finished_writes();
            peer_mutex(lock);
            if (talk_data.num_queued_writes) move_queued_writes();
            peer_mutex(unlock);
        } else if (ret < 0) { if (errno != EAGAIN && errno != EINTR) perror("poll() on talk fds failed"); }
    }
end:
    close(talk_data.wakeup_fds[0]); close(talk_data.wakeup_fds[1]);
    free(talk_data.fds); free(talk_data.reads); free(talk_data.writes); free(talk_data.queued_writes);
    return 0;
}

static inline bool
add_peer_writer(int fd, const char* msg, size_t msg_sz) {
    bool ok = false;
    peer_mutex(lock);
    if (talk_data.num_queued_writes < PEER_LIMIT) {
        ensure_space_for(&talk_data, queued_writes, PeerWriteData, talk_data.num_queued_writes + 1, queued_writes_capacity, 8, false);
        talk_data.queued_writes[talk_data.num_queued_writes] = empty_pwd;
        talk_data.queued_writes[talk_data.num_queued_writes].data = malloc(msg_sz);
        if (talk_data.queued_writes[talk_data.num_queued_writes].data) {
            memcpy(talk_data.queued_writes[talk_data.num_queued_writes].data, msg, msg_sz);
            talk_data.queued_writes[talk_data.num_queued_writes].sz = msg_sz;
            talk_data.queued_writes[talk_data.num_queued_writes++].fd = fd;
            ok = true;
        }
    } else log_error("Cannot send response to peer, too many peers");
    peer_mutex(unlock);
    return ok;
}

static void
send_response(int fd, const char *msg, size_t msg_sz) {
    if (msg == NULL) { shutdown(fd, SHUT_WR); close(fd); return; }
    if (!add_peer_writer(fd, msg, msg_sz)) { shutdown(fd, SHUT_WR); close(fd); }
    else wakeup_talk_loop(false);
}

// }}}

// Boilerplate {{{
static PyMethodDef methods[] = {
    METHOD(add_child, METH_VARARGS)
    METHOD(needs_write, METH_VARARGS)
    METHOD(start, METH_NOARGS)
    METHOD(wakeup, METH_NOARGS)
    METHOD(shutdown_monitor, METH_NOARGS)
    METHOD(main_loop, METH_NOARGS)
    METHOD(mark_for_close, METH_VARARGS)
    METHOD(resize_pty, METH_VARARGS)
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



static PyObject*
safe_pipe(PYNOARG) {
    int fds[2] = {0};
    if (!self_pipe(fds)) return PyErr_SetFromErrno(PyExc_OSError);
    return Py_BuildValue("ii", fds[0], fds[1]);
}

static PyMethodDef module_methods[] = {
    METHODB(safe_pipe, METH_NOARGS),
    {"add_timer", (PyCFunction)add_python_timer, METH_VARARGS, ""},
    {"remove_timer", (PyCFunction)remove_python_timer, METH_VARARGS, ""},
    METHODB(monitor_pid, METH_VARARGS),
    {"set_iutf8", (PyCFunction)pyset_iutf8, METH_VARARGS, ""},
    {NULL}  /* Sentinel */
};

bool
init_child_monitor(PyObject *module) {
    if (PyType_Ready(&ChildMonitor_Type) < 0) return false;
    if (PyModule_AddObject(module, "ChildMonitor", (PyObject *)&ChildMonitor_Type) != 0) return false;
    Py_INCREF(&ChildMonitor_Type);
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}

// }}}
