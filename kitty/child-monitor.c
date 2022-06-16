/*
 * child-monitor.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "loop-utils.h"
#include "safe-wrappers.h"
#include "state.h"
#include "threading.h"
#include "screen.h"
#include "fonts.h"
#include "charsets.h"
#include "monotonic.h"
#include <termios.h>
#include <unistd.h>
#include <float.h>
#include <fcntl.h>
#include <sys/ioctl.h>
#include <sys/wait.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <signal.h>
extern PyTypeObject Screen_Type;

#if defined(__APPLE__) || defined(__OpenBSD__)
#define NO_SIGQUEUE 1
#endif

#ifdef DEBUG_EVENT_LOOP
#define EVDBG(...) log_event(__VA_ARGS__)
#else
#define EVDBG(...)
#endif

#define EXTRA_FDS 3
#ifndef MSG_NOSIGNAL
// Apple does not implement MSG_NOSIGNAL
#define MSG_NOSIGNAL 0
#endif
#define USE_RENDER_FRAMES (global_state.has_render_frames && OPT(sync_to_monitor))

static void (*parse_func)(Screen*, PyObject*, monotonic_t);

typedef struct {
    char *data;
    size_t sz;
    id_type peer_id;
} Message;

typedef struct {
    PyObject_HEAD

    PyObject *dump_callback, *update_screen, *death_notify;
    unsigned int count;
    bool shutting_down;
    pthread_t io_thread, talk_thread;

    int talk_fd, listen_fd, prewarm_fd;
    Message *messages;
    size_t messages_capacity, messages_count;
    LoopData io_loop_data;
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
#define talk_mutex(op) \
    pthread_mutex_##op(&talk_lock);


static Child children[MAX_CHILDREN] = {{0}};
static Child scratch[MAX_CHILDREN] = {{0}};
static Child add_queue[MAX_CHILDREN] = {{0}}, remove_queue[MAX_CHILDREN] = {{0}}, remove_notify[MAX_CHILDREN] = {{0}};
static size_t add_queue_count = 0, remove_queue_count = 0;
static struct pollfd children_fds[MAX_CHILDREN + EXTRA_FDS] = {{0}};
static pthread_mutex_t children_lock, talk_lock;
static bool kill_signal_received = false, reload_config_signal_received = false;
static ChildMonitor *the_monitor = NULL;

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

// The max time to wait for events from the window system
// before ticking over the main loop. Negative values mean wait forever.
static monotonic_t maximum_wait = -1;

static void
set_maximum_wait(monotonic_t val) {
    if (val >= 0 && (val < maximum_wait || maximum_wait < 0)) maximum_wait = val;
}

static PyObject *
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    ChildMonitor *self;
    PyObject *dump_callback, *death_notify;
    int talk_fd = -1, listen_fd = -1, prewarm_fd = -1;
    int ret;

    if (the_monitor) { PyErr_SetString(PyExc_RuntimeError, "Can have only a single ChildMonitor instance"); return NULL; }
    if (!PyArg_ParseTuple(args, "OO|iii", &death_notify, &dump_callback, &talk_fd, &listen_fd, &prewarm_fd)) return NULL;
    if ((ret = pthread_mutex_init(&children_lock, NULL)) != 0) {
        PyErr_Format(PyExc_RuntimeError, "Failed to create children_lock mutex: %s", strerror(ret));
        return NULL;
    }
    if ((ret = pthread_mutex_init(&talk_lock, NULL)) != 0) {
        PyErr_Format(PyExc_RuntimeError, "Failed to create talk_lock mutex: %s", strerror(ret));
        return NULL;
    }
    self = (ChildMonitor *)type->tp_alloc(type, 0);
    if (!init_loop_data(&self->io_loop_data, SIGINT, SIGHUP, SIGTERM, SIGCHLD, SIGUSR1, SIGUSR2, 0)) return PyErr_SetFromErrno(PyExc_OSError);
    self->talk_fd = talk_fd;
    self->listen_fd = listen_fd;
    self->prewarm_fd = prewarm_fd;
    if (self == NULL) return PyErr_NoMemory();
    self->death_notify = death_notify; Py_INCREF(death_notify);
    if (dump_callback != Py_None) {
        self->dump_callback = dump_callback; Py_INCREF(dump_callback);
        parse_func = parse_worker_dump;
    } else parse_func = parse_worker;
    self->count = 0;
    children_fds[0].fd = self->io_loop_data.wakeup_read_fd; children_fds[1].fd = self->io_loop_data.signal_read_fd;
    children_fds[2].fd = self->prewarm_fd;
    children_fds[0].events = POLLIN; children_fds[1].events = POLLIN; children_fds[2].events = POLLIN;
    the_monitor = self;

    return (PyObject*) self;
}

static void
dealloc(ChildMonitor* self) {
    if (self->messages) {
        for (size_t i = 0; i < self->messages_count; i++) free(self->messages[i].data);
        free(self->messages); self->messages = NULL;
        self->messages_count = 0; self->messages_capacity = 0;
    }
    pthread_mutex_destroy(&children_lock);
    pthread_mutex_destroy(&talk_lock);
    Py_CLEAR(self->dump_callback);
    Py_CLEAR(self->death_notify);
    while (remove_queue_count) {
        remove_queue_count--;
        FREE_CHILD(remove_queue[remove_queue_count]);
    }
    while (add_queue_count) {
        add_queue_count--;
        FREE_CHILD(add_queue[add_queue_count]);
    }
    free_loop_data(&self->io_loop_data);
    safe_close(self->prewarm_fd, __FILE__, __LINE__); self->prewarm_fd = -1;
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
handled_signals(ChildMonitor *self, PyObject *args UNUSED) {
    PyObject *ans = PyTuple_New(self->io_loop_data.num_handled_signals);
    if (ans) {
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(ans); i++) {
            PyTuple_SET_ITEM(ans, i, PyLong_FromLong((long)self->io_loop_data.handled_signals[i]));
        }
    }
    return ans;
}

static void
wakeup_io_loop(ChildMonitor *self, bool in_signal_handler) {
    wakeup_loop(&self->io_loop_data, in_signal_handler, "io_loop");
}

static void* io_loop(void *data);
static void* talk_loop(void *data);
static void send_response_to_peer(id_type peer_id, const char *msg, size_t msg_sz);
static void wakeup_talk_loop(bool);
static bool talk_thread_started = false;

static PyObject *
start(PyObject *s, PyObject *a UNUSED) {
#define start_doc "start() -> Start the I/O thread"
    ChildMonitor *self = (ChildMonitor*)s;
    int ret;
    if (self->talk_fd > -1 || self->listen_fd > -1) {
        if ((ret = pthread_create(&self->talk_thread, NULL, talk_loop, self)) != 0) {
            return PyErr_Format(PyExc_OSError, "Failed to start talk thread with error: %s", strerror(ret));
        }
        talk_thread_started = true;
    }
    ret = pthread_create(&self->io_thread, NULL, io_loop, self);
    if (ret != 0) return PyErr_Format(PyExc_OSError, "Failed to start I/O thread with error: %s", strerror(ret));

    Py_RETURN_NONE;
}

static PyObject *
wakeup(ChildMonitor *self, PyObject *args UNUSED) {
#define wakeup_doc "wakeup() -> wakeup the ChildMonitor I/O thread, forcing it to exit from poll() if it is waiting there."
    wakeup_io_loop(self, false);
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
    wakeup_io_loop(self, false);
    Py_RETURN_NONE;
}

#define schedule_write_to_child_generic(id, num, va_start, get_next_arg, va_end) \
    ChildMonitor *self = the_monitor; \
    bool found = false; \
    const char *data; \
    size_t szval, sz = 0; \
    va_start(ap, num); \
    for (unsigned int i = 0; i < num; i++) { \
        get_next_arg(ap); \
        sz += szval; \
    } \
    va_end(ap); \
    children_mutex(lock); \
    for (size_t i = 0; i < self->count; i++) { \
        if (children[i].id == id) { \
            Screen *screen = children[i].screen; \
            screen_mutex(lock, write); \
            size_t space_left = screen->write_buf_sz - screen->write_buf_used; \
            if (space_left < sz) { \
                if (screen->write_buf_used + sz > 100 * 1024 * 1024) { \
                    log_error("Too much data being sent to child with id: %lu, ignoring it", id); \
                    screen_mutex(unlock, write); \
                    break; \
                } \
                screen->write_buf_sz = screen->write_buf_used + sz; \
                screen->write_buf = PyMem_RawRealloc(screen->write_buf, screen->write_buf_sz); \
                if (screen->write_buf == NULL) { fatal("Out of memory."); } \
            } \
            found = true; \
            va_start(ap, num); \
            for (unsigned int i = 0; i < num; i++) { \
                get_next_arg(ap); \
                memcpy(screen->write_buf + screen->write_buf_used, data, szval); \
                screen->write_buf_used += szval; \
            } \
            va_end(ap); \
            if (screen->write_buf_sz > BUFSIZ && screen->write_buf_used < BUFSIZ) { \
                screen->write_buf_sz = BUFSIZ; \
                screen->write_buf = PyMem_RawRealloc(screen->write_buf, screen->write_buf_sz); \
                if (screen->write_buf == NULL) { fatal("Out of memory."); } \
            } \
            if (screen->write_buf_used) wakeup_io_loop(self, false); \
            screen_mutex(unlock, write); \
            break; \
        } \
    } \
    children_mutex(unlock); \
    return found;

bool
schedule_write_to_child(unsigned long id, unsigned int num, ...) {
    va_list ap;
#define get_next_arg(ap) data = va_arg(ap, const char*); szval = va_arg(ap, size_t);
    schedule_write_to_child_generic(id, num, va_start, get_next_arg, va_end);
#undef get_next_arg
}

bool
schedule_write_to_child_python(unsigned long id, const char *prefix, PyObject *ap, const char *suffix) {
    if (!PyTuple_Check(ap)) return false;
    bool has_prefix = prefix && prefix[0], has_suffix = suffix && suffix[0];
    const size_t extra = (has_prefix ? 1 : 0) + (has_suffix ? 1 : 0);
    size_t num = PyTuple_GET_SIZE(ap) + extra;
    Py_ssize_t pidx;
#define py_start(ap, num) pidx = 0;
#define py_end(ap) pidx = 0;
#define get_next_arg(ap) { \
    size_t pidxf = pidx++; \
    if (pidxf == 0 && has_prefix) { data = prefix; szval = strlen(prefix); } \
    else { \
        if (has_prefix) pidxf--; \
        if (has_suffix && pidxf >= (size_t)PyTuple_GET_SIZE(ap)) { data = suffix; szval = strlen(suffix); } \
        else { \
            PyObject *t = PyTuple_GET_ITEM(ap, pidxf); \
            if (PyBytes_Check(t)) { data = PyBytes_AS_STRING(t); szval = PyBytes_GET_SIZE(t); } \
            else { \
                Py_ssize_t usz; \
                data = PyUnicode_AsUTF8AndSize(t, &usz); szval = usz; \
                if (!data) fatal("Failed to convert object to bytes in schedule_write_to_child_python"); \
            } \
        } \
    } \
}
    schedule_write_to_child_generic(id, num, py_start, get_next_arg, py_end);
#undef py_start
#undef py_end
#undef get_next_arg
}

static PyObject *
needs_write(ChildMonitor UNUSED *self, PyObject *args) {
#define needs_write_doc "needs_write(id, data) -> Queue data to be written to child."
    unsigned long id;
    Py_buffer buf;
    if (!PyArg_ParseTuple(args, "ky*", &id, &buf)) return NULL;
    if (schedule_write_to_child(id, 1, buf.buf, (size_t)buf.len)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject *
shutdown_monitor(ChildMonitor *self, PyObject *a UNUSED) {
#define shutdown_monitor_doc "shutdown_monitor() -> Shutdown the monitor loop."
    self->shutting_down = true;
    wakeup_talk_loop(false);
    wakeup_io_loop(self, false);
    int ret = pthread_join(self->io_thread, NULL);
    if (ret != 0) return PyErr_Format(PyExc_OSError, "Failed to join() I/O thread with error: %s", strerror(ret));
    if (talk_thread_started) {
        ret = pthread_join(self->talk_thread, NULL);
        if (ret != 0) return PyErr_Format(PyExc_OSError, "Failed to join() talk thread with error: %s", strerror(ret));
    }
    talk_thread_started = false;
    Py_RETURN_NONE;
}

static bool
do_parse(ChildMonitor *self, Screen *screen, monotonic_t now, bool flush) {
    bool input_read = false;
    screen_mutex(lock, read);
    if (screen->read_buf_sz || screen->pending_mode.used) {
        monotonic_t time_since_new_input = now - screen->new_input_at;
        if (flush || time_since_new_input >= OPT(input_delay)) {
            bool read_buf_full = screen->read_buf_sz >= READ_BUF_SZ;
            input_read = true;
            parse_func(screen, self->dump_callback, now);
            if (read_buf_full) wakeup_io_loop(self, false);  // Ensure the read fd has POLLIN set
            screen->new_input_at = 0;
            if (screen->pending_mode.activated_at) {
                monotonic_t time_since_pending = MAX(0, now - screen->pending_mode.activated_at);
                set_maximum_wait(screen->pending_mode.wait_time - time_since_pending);
            }
        } else set_maximum_wait(OPT(input_delay) - time_since_new_input);
    }
    screen_mutex(unlock, read);
    return input_read;
}

static bool
parse_input(ChildMonitor *self) {
    // Parse all available input that was read in the I/O thread.
    size_t count = 0, remove_count = 0;
    bool input_read = false, reload_config_called = false;
    monotonic_t now = monotonic();
    children_mutex(lock);
    while (remove_queue_count) {
        remove_queue_count--;
        remove_notify[remove_count] = remove_queue[remove_queue_count];
        INCREF_CHILD(remove_notify[remove_count]);
        remove_count++;
        FREE_CHILD(remove_queue[remove_queue_count]);
    }

    if (UNLIKELY(kill_signal_received || reload_config_signal_received)) {
        if (kill_signal_received) {
            global_state.quit_request = IMPERATIVE_CLOSE_REQUESTED;
            global_state.has_pending_closes = true;
            request_tick_callback();
            kill_signal_received = false;
        }
        else if (reload_config_signal_received) {
            reload_config_signal_received = false;
            reload_config_called = true;
        }
    } else {
        count = self->count;
        for (size_t i = 0; i < count; i++) {
            scratch[i] = children[i];
            INCREF_CHILD(scratch[i]);
        }
    }
    children_mutex(unlock);

    Message *msgs = NULL;
    size_t msgs_count = 0;
    talk_mutex(lock);
    if (UNLIKELY(self->messages_count)) {
        msgs = malloc(sizeof(Message) * self->messages_count);
        if (msgs) {
            memcpy(msgs, self->messages, sizeof(Message) * self->messages_count);
            msgs_count = self->messages_count;
        }
        memset(self->messages, 0, sizeof(Message) * self->messages_capacity);
        self->messages_count = 0;
    }
    talk_mutex(unlock);

    if (msgs_count) {
        for (size_t i = 0; i < msgs_count; i++) {
            Message *msg = msgs + i;
            PyObject *resp = NULL;
            if (msg->data) {
                resp = PyObject_CallMethod(global_state.boss, "peer_message_received", "y#K", msg->data, (int)msg->sz, msg->peer_id);
                free(msg->data);
                if (!resp) PyErr_Print();
            }
            if (resp) {
                if (PyBytes_Check(resp)) send_response_to_peer(msg->peer_id, PyBytes_AS_STRING(resp), PyBytes_GET_SIZE(resp));
                else if (resp == Py_None || resp == Py_True) send_response_to_peer(msg->peer_id, NULL, 0);
                Py_CLEAR(resp);
            } else send_response_to_peer(msg->peer_id, NULL, 0);
        }
        free(msgs); msgs = NULL;
    }

    while(remove_count) {
        // must be done while no locks are held, since the locks are non-recursive and
        // the python function could call into other functions in this module
        remove_count--;
        if (remove_notify[remove_count].screen) do_parse(self, remove_notify[remove_count].screen, now, true);
        PyObject *t = PyObject_CallFunction(self->death_notify, "k", remove_notify[remove_count].id);
        if (t == NULL) PyErr_Print();
        else Py_DECREF(t);
        FREE_CHILD(remove_notify[remove_count]);
    }

    for (size_t i = 0; i < count; i++) {
        if (!scratch[i].needs_removal) {
            if (do_parse(self, scratch[i].screen, now, false)) input_read = true;
        }
        DECREF_CHILD(scratch[i]);
    }
    if (reload_config_called) {
        call_boss(load_config_file, "");
    }
    return input_read;
}

static void
mark_child_for_close(ChildMonitor *self, id_type window_id) {
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].id == window_id) {
            children[i].needs_removal = true;
            break;
        }
    }
    children_mutex(unlock);
    wakeup_io_loop(self, false);
}


static PyObject *
mark_for_close(ChildMonitor *self, PyObject *args) {
#define mark_for_close_doc "Mark a child to be removed from the child monitor"
    id_type window_id;
    if (!PyArg_ParseTuple(args, "K", &window_id)) return NULL;
    mark_child_for_close(self, window_id);
    Py_RETURN_NONE;
}

static bool
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
    id_type window_id;
    int on;
    PyObject *found = Py_False;
    if (!PyArg_ParseTuple(args, "Kp", &window_id, &on)) return NULL;
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].id == window_id) {
            found = Py_True;
            if (!set_iutf8(children_fds[EXTRA_FDS + i].fd, on & 1)) PyErr_SetFromErrno(PyExc_OSError);
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

static bool
cursor_needs_render(Window *w) {
    return w->cursor_visible_at_last_render != w->render_data.screen->cursor_render_info.is_visible || w->last_cursor_x != w->render_data.screen->cursor_render_info.x || w->last_cursor_y != w->render_data.screen->cursor_render_info.y || w->last_cursor_shape != w->render_data.screen->cursor_render_info.shape;
}

static bool
collect_cursor_info(CursorRenderInfo *ans, Window *w, monotonic_t now, OSWindow *os_window) {
    ScreenRenderData *rd = &w->render_data;
    Cursor *cursor = rd->screen->cursor;
    ans->x = cursor->x; ans->y = cursor->y;
    ans->is_visible = false;
    if (rd->screen->scrolled_by || !screen_is_cursor_visible(rd->screen)) return cursor_needs_render(w);
    monotonic_t time_since_start_blink = now - os_window->cursor_blink_zero_time;
    bool cursor_blinking = OPT(cursor_blink_interval) > 0 && !cursor->non_blinking && os_window->is_focused && (OPT(cursor_stop_blinking_after) == 0 || time_since_start_blink <= OPT(cursor_stop_blinking_after));
    bool do_draw_cursor = true;
    if (cursor_blinking) {
        int t = monotonic_t_to_ms(time_since_start_blink);
        int d = monotonic_t_to_ms(OPT(cursor_blink_interval));
        int n = t / d;
        do_draw_cursor = n % 2 == 0 ? true : false;
        monotonic_t bucket = ms_to_monotonic_t((monotonic_t)(n + 1) * d);
        monotonic_t delay = bucket - time_since_start_blink;
        set_maximum_wait(delay);
    }
    if (!do_draw_cursor) { ans->is_visible = false; return cursor_needs_render(w); }
    ans->is_visible = true;
    ans->shape = cursor->shape ? cursor->shape : OPT(cursor_shape);
    ans->is_focused = os_window->is_focused;
    return cursor_needs_render(w);
}

static void
change_menubar_title(PyObject *title UNUSED) {
#ifdef __APPLE__
    static PyObject *current_title = NULL;
    if (title != current_title) {
        current_title = title;
        if (title && OPT(macos_show_window_title_in) & MENUBAR) update_menu_bar_title(title);
    }
#endif
}

static bool
prepare_to_render_os_window(OSWindow *os_window, monotonic_t now, unsigned int *active_window_id, color_type *active_window_bg, unsigned int *num_visible_windows, bool *all_windows_have_same_bg, bool scan_for_animated_images) {
#define TD os_window->tab_bar_render_data
    bool needs_render = os_window->needs_render;
    os_window->needs_render = false;
    if (TD.screen && os_window->num_tabs >= OPT(tab_bar_min_tabs)) {
        if (OPT(tab_bar_always_update) || !os_window->tab_bar_data_updated) {
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
    *all_windows_have_same_bg = true;
    *num_visible_windows = 0;
    color_type first_window_bg = 0;
    for (unsigned int i = 0; i < tab->num_windows; i++) {
        Window *w = tab->windows + i;
#define WD w->render_data
        if (w->visible && WD.screen) {
            *num_visible_windows += 1;
            color_type window_bg = colorprofile_to_color(WD.screen->color_profile, WD.screen->color_profile->overridden.default_bg, WD.screen->color_profile->configured.default_bg).rgb;
            if (*num_visible_windows == 1) first_window_bg = window_bg;
            if (first_window_bg != window_bg) *all_windows_have_same_bg = false;
            if (w->last_drag_scroll_at > 0) {
                if (now - w->last_drag_scroll_at >= ms_to_monotonic_t(20ll)) {
                    if (drag_scroll(w, os_window)) {
                        w->last_drag_scroll_at = now;
                        set_maximum_wait(ms_to_monotonic_t(20ll));
                        needs_render = true;
                    } else w->last_drag_scroll_at = 0;
                } else set_maximum_wait(now - w->last_drag_scroll_at);
            }
            bool is_active_window = i == tab->active_window;
            if (is_active_window) {
                *active_window_id = w->id;
                if (collect_cursor_info(&WD.screen->cursor_render_info, w, now, os_window)) needs_render = true;
                WD.screen->cursor_render_info.is_focused = os_window->is_focused;
                set_os_window_title_from_window(w, os_window);
                *active_window_bg = window_bg;
            } else {
                if (WD.screen->render_unfocused_cursor) {
                    if (collect_cursor_info(&WD.screen->cursor_render_info, w, now, os_window)) needs_render = true;
                    WD.screen->cursor_render_info.is_focused = false;
                } else {
                    WD.screen->cursor_render_info.is_visible = false;
                }
            }
            if (scan_for_animated_images) {
                monotonic_t min_gap;
                if (scan_active_animations(WD.screen->grman, now, &min_gap, true)) needs_render = true;
                if (min_gap < MONOTONIC_T_MAX) {
                    global_state.check_for_active_animated_images = true;
                    set_maximum_wait(min_gap);
                }
            }
            if (send_cell_data_to_gpu(WD.vao_idx, WD.gvao_idx, WD.xstart, WD.ystart, WD.dx, WD.dy, WD.screen, os_window)) needs_render = true;
            if (WD.screen->start_visual_bell_at != 0) needs_render = true;
        }
    }
    return needs_render;
}

static void
render_os_window(OSWindow *os_window, unsigned int active_window_id, color_type active_window_bg, unsigned int num_visible_windows, bool all_windows_have_same_bg) {
    // ensure all pixels are cleared to background color at least once in every buffer
    if (os_window->clear_count++ < 3) blank_os_window(os_window);
    Tab *tab = os_window->tabs + os_window->active_tab;
    BorderRects *br = &tab->border_rects;
    bool static_live_resize_in_progress = os_window->live_resize.in_progress && OPT(resize_draw_strategy) == RESIZE_DRAW_STATIC;
    float x_ratio = 1, y_ratio = 1;
    if (static_live_resize_in_progress) {
        x_ratio = (float) os_window->viewport_width / (float) os_window->live_resize.width;
        y_ratio = (float) os_window->viewport_height / (float) os_window->live_resize.height;
    }
    if (!static_live_resize_in_progress) {
        draw_borders(br->vao_idx, br->num_border_rects, br->rect_buf, br->is_dirty, os_window->viewport_width, os_window->viewport_height, active_window_bg, num_visible_windows, all_windows_have_same_bg, os_window);
        br->is_dirty = false;
    }
    if (TD.screen && os_window->num_tabs >= OPT(tab_bar_min_tabs)) draw_cells(TD.vao_idx, 0, &TD, x_ratio, y_ratio, os_window, true, false, NULL);
    for (unsigned int i = 0; i < tab->num_windows; i++) {
        Window *w = tab->windows + i;
        if (w->visible && WD.screen) {
            bool is_active_window = i == tab->active_window;
            draw_cells(WD.vao_idx, WD.gvao_idx, &WD, x_ratio, y_ratio, os_window, is_active_window, true, w);
            if (WD.screen->start_visual_bell_at != 0) {
                set_maximum_wait(OPT(repaint_delay));
            }
            w->cursor_visible_at_last_render = WD.screen->cursor_render_info.is_visible; w->last_cursor_x = WD.screen->cursor_render_info.x; w->last_cursor_y = WD.screen->cursor_render_info.y; w->last_cursor_shape = WD.screen->cursor_render_info.shape;
        }
    }
    swap_window_buffers(os_window);
    os_window->last_active_tab = os_window->active_tab; os_window->last_num_tabs = os_window->num_tabs; os_window->last_active_window_id = active_window_id;
    os_window->focused_at_last_render = os_window->is_focused;
    os_window->is_damaged = false;
    if (USE_RENDER_FRAMES) request_frame_render(os_window);
#undef WD
#undef TD
}

static void
draw_resizing_text(OSWindow *w) {
    char text[32] = {0};
    unsigned int width = w->live_resize.width, height = w->live_resize.height;
    snprintf(text, sizeof(text), "%u x %u cells", width / w->fonts_data->cell_width, height / w->fonts_data->cell_height);
    StringCanvas rendered = render_simple_text(w->fonts_data, text);
    if (rendered.canvas) {
        draw_centered_alpha_mask(w, width, height, rendered.width, rendered.height, rendered.canvas);
        free(rendered.canvas);
    }
}

static bool
no_render_frame_received_recently(OSWindow *w, monotonic_t now, monotonic_t max_wait) {
    bool ans = now - w->last_render_frame_received_at > max_wait;
    if (ans && global_state.debug_rendering) {
        if (global_state.is_wayland) {
            log_error("No render frame received in %.2f seconds", monotonic_t_to_s_double(max_wait));
        } else  {
            log_error("No render frame received in %.2f seconds, re-requesting at: %f", monotonic_t_to_s_double(max_wait), monotonic_t_to_s_double(now));
        }
    }
    return ans;
}

static void
render(monotonic_t now, bool input_read) {
    EVDBG("input_read: %d, check_for_active_animated_images: %d", input_read, global_state.check_for_active_animated_images);
    static monotonic_t last_render_at = MONOTONIC_T_MIN;
    monotonic_t time_since_last_render = last_render_at == MONOTONIC_T_MIN ? OPT(repaint_delay) : now - last_render_at;
    if (!input_read && time_since_last_render < OPT(repaint_delay)) {
        set_maximum_wait(OPT(repaint_delay) - time_since_last_render);
        return;
    }

    const bool scan_for_animated_images = global_state.check_for_active_animated_images;
    global_state.check_for_active_animated_images = false;

    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        w->render_calls++;
        if (!w->num_tabs) continue;
        if (!should_os_window_be_rendered(w)) {
            update_os_window_title(w);
            if (w->is_focused) change_menubar_title(w->window_title);
            continue;
        }
        if (USE_RENDER_FRAMES && w->render_state != RENDER_FRAME_READY) {
            if (w->render_state == RENDER_FRAME_NOT_REQUESTED || no_render_frame_received_recently(w, now, ms_to_monotonic_t(250ll))) request_frame_render(w);
            continue;
        }
        make_os_window_context_current(w);
        if (w->live_resize.in_progress && OPT(resize_draw_strategy) >= RESIZE_DRAW_BLANK) {
            blank_os_window(w);
            if (OPT(resize_draw_strategy) == RESIZE_DRAW_SIZE) draw_resizing_text(w);
            swap_window_buffers(w);
            if (USE_RENDER_FRAMES) request_frame_render(w);
            continue;
        }
        if (w->live_resize.in_progress && OPT(resize_draw_strategy) == RESIZE_DRAW_STATIC) blank_os_window(w);
        bool needs_render = w->is_damaged || w->live_resize.in_progress;
        if (w->viewport_size_dirty) {
            w->clear_count = 0;
            update_surface_size(w->viewport_width, w->viewport_height, w->offscreen_texture_id);
            w->viewport_size_dirty = false;
            needs_render = true;
        }
        unsigned int active_window_id = 0, num_visible_windows = 0;
        bool all_windows_have_same_bg;
        color_type active_window_bg = 0;
        if (!w->fonts_data) { log_error("No fonts data found for window id: %llu", w->id); continue; }
        if (prepare_to_render_os_window(w, now, &active_window_id, &active_window_bg, &num_visible_windows, &all_windows_have_same_bg, scan_for_animated_images)) needs_render = true;
        if (w->last_active_window_id != active_window_id || w->last_active_tab != w->active_tab || w->focused_at_last_render != w->is_focused) needs_render = true;
        if (w->render_calls < 3 && w->bgimage && w->bgimage->texture_id) needs_render = true;
        if (needs_render) render_os_window(w, active_window_id, active_window_bg, num_visible_windows, all_windows_have_same_bg);
        if (w->is_focused) change_menubar_title(w->window_title);
    }
    last_render_at = now;
#undef TD
}


typedef struct { int fd; uint8_t *buf; size_t sz; } ThreadWriteData;

static ThreadWriteData*
alloc_twd(size_t sz) {
    ThreadWriteData *data = calloc(1, sizeof(ThreadWriteData));
    if (data != NULL) {
        data->sz = sz;
        data->buf = malloc(sz);
        if (data->buf == NULL) { free(data); data = NULL; }
    }
    return data;
}

static void
free_twd(ThreadWriteData *x) {
    if (x != NULL) free(x->buf);
    free(x);
}

static PyObject*
sig_queue(PyObject *self UNUSED, PyObject *args) {
    int pid, signal, value;
    if (!PyArg_ParseTuple(args, "iii", &pid, &signal, &value)) return NULL;
#ifdef NO_SIGQUEUE
    if (kill(pid, signal) != 0) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
#else
    union sigval v;
    v.sival_int = value;
    if (sigqueue(pid, signal, v) != 0) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
#endif
    Py_RETURN_NONE;
}

static PyObject*
monitor_pid(PyObject *self UNUSED, PyObject *args) {
    int pid;
    bool ok = true;
    if (!PyArg_ParseTuple(args, "i", &pid)) return NULL;
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

static void
report_reaped_pids(void) {
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
    int flags = fcntl(data->fd, F_GETFL, 0);
    if (flags == -1) { free_twd(data); return 0; }
    flags &= ~O_NONBLOCK;
    fcntl(data->fd, F_SETFL, flags);
    size_t pos = 0;
    while (pos < data->sz) {
        errno = 0;
        ssize_t nbytes = write(data->fd, data->buf + pos, data->sz - pos);
        if (nbytes < 0) {
            if (errno == EAGAIN || errno == EINTR) continue;
            break;
        }
        if (nbytes == 0) break;
        pos += nbytes;
    }
    if (pos < data->sz) {
        log_error("Failed to write all data to STDIN of child process with error: %s", strerror(errno));
    }
    safe_close(data->fd, __FILE__, __LINE__);
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
    if (ret != 0) { safe_close(fd, __FILE__, __LINE__); free_twd(data); return PyErr_Format(PyExc_OSError, "Failed to start write thread with error: %s", strerror(ret)); }
    pthread_detach(thread);
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
    unsigned long long timer_id = add_main_loop_timer(s_double_to_monotonic_t(interval), repeats ? true: false, python_timer_callback, callback, python_timer_cleanup);
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


static void
process_pending_resizes(monotonic_t now) {
    global_state.has_pending_resizes = false;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (w->live_resize.in_progress) {
            bool update_viewport = false;
            if (w->live_resize.from_os_notification) {
                if (w->live_resize.os_says_resize_complete || (now - w->live_resize.last_resize_event_at) > 1) update_viewport = true;
            } else {
                monotonic_t debounce_time = OPT(resize_debounce_time);
                // if more than one resize event has occurred, wait at least 0.2 secs
                // before repainting, to avoid rapid transitions between the cells banner
                // and the normal screen
                if (w->live_resize.num_of_resize_events > 1 && OPT(resize_draw_strategy) == RESIZE_DRAW_SIZE) debounce_time = MAX(ms_to_monotonic_t(200ll), debounce_time);
                if (now - w->live_resize.last_resize_event_at >= debounce_time) update_viewport = true;
                else {
                    global_state.has_pending_resizes = true;
                    set_maximum_wait(OPT(resize_debounce_time) - now + w->live_resize.last_resize_event_at);
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

static void
close_os_window(ChildMonitor *self, OSWindow *os_window) {
    int w = os_window->window_width, h = os_window->window_height;
    if (os_window->before_fullscreen.is_set && is_os_window_fullscreen(os_window)) {
        w = os_window->before_fullscreen.w; h = os_window->before_fullscreen.h;
    }
    destroy_os_window(os_window);
    call_boss(on_os_window_closed, "Kii", os_window->id, w, h);
    for (size_t t=0; t < os_window->num_tabs; t++) {
        Tab *tab = os_window->tabs + t;
        for (size_t w = 0; w < tab->num_windows; w++) mark_child_for_close(self, tab->windows[w].id);
    }
    remove_os_window(os_window->id);
}

static bool
process_pending_closes(ChildMonitor *self) {
    if (global_state.quit_request == CONFIRMABLE_CLOSE_REQUESTED) {
        call_boss(quit, "");
    }
    if (global_state.quit_request == IMPERATIVE_CLOSE_REQUESTED) {
        for (size_t w = 0; w < global_state.num_os_windows; w++) global_state.os_windows[w].close_request = IMPERATIVE_CLOSE_REQUESTED;
    }
    bool has_open_windows = false;
    for (size_t w = global_state.num_os_windows; w > 0; w--) {
        OSWindow *os_window = global_state.os_windows + w - 1;
        switch(os_window->close_request) {
            case NO_CLOSE_REQUESTED:
                has_open_windows = true;
                break;
            case CONFIRMABLE_CLOSE_REQUESTED:
                os_window->close_request = CLOSE_BEING_CONFIRMED;
                call_boss(confirm_os_window_close, "K", os_window->id);
                if (os_window->close_request == IMPERATIVE_CLOSE_REQUESTED) {
                    close_os_window(self, os_window);
                } else has_open_windows = true;
                break;
            case CLOSE_BEING_CONFIRMED:
                has_open_windows = true;
                break;
            case IMPERATIVE_CLOSE_REQUESTED:
                close_os_window(self, os_window);
                break;
        }
    }
    global_state.has_pending_closes = false;
#ifdef __APPLE__
    if (!OPT(macos_quit_when_last_window_closed)) {
        if (!has_open_windows && global_state.quit_request != IMPERATIVE_CLOSE_REQUESTED) has_open_windows = true;
    }
#endif
    return !has_open_windows;
}

#ifdef __APPLE__
// If we create new OS windows during wait_events(), using global menu actions
// via the mouse causes a crash because of the way autorelease pools work in
// glfw/cocoa. So we use a flag instead.
static bool cocoa_pending_actions[NUM_COCOA_PENDING_ACTIONS] = {0};
static bool has_cocoa_pending_actions = false;
typedef struct {
    char* wd;
    char **open_urls;
    size_t open_urls_count;
    size_t open_urls_capacity;
} CocoaPendingActionsData;
static CocoaPendingActionsData cocoa_pending_actions_data = {0};

void
set_cocoa_pending_action(CocoaPendingAction action, const char *data) {
    if (data) {
        if (action == LAUNCH_URLS) {
            ensure_space_for(&cocoa_pending_actions_data, open_urls, char*, cocoa_pending_actions_data.open_urls_count + 8, open_urls_capacity, 8, true);
            cocoa_pending_actions_data.open_urls[cocoa_pending_actions_data.open_urls_count++] = strdup(data);
        } else {
            if (cocoa_pending_actions_data.wd) free(cocoa_pending_actions_data.wd);
            cocoa_pending_actions_data.wd = strdup(data);
        }
    }
    cocoa_pending_actions[action] = true;
    has_cocoa_pending_actions = true;
    // The main loop may be blocking on the event queue, if e.g. unfocused.
    // Unjam it so the pending action is processed right now.
    wakeup_main_loop();
}

static void
process_cocoa_pending_actions(void) {
    if (cocoa_pending_actions[PREFERENCES_WINDOW]) { call_boss(edit_config_file, NULL); }
    if (cocoa_pending_actions[NEW_OS_WINDOW]) { call_boss(new_os_window, NULL); }
    if (cocoa_pending_actions[CLOSE_OS_WINDOW]) { call_boss(close_os_window, NULL); }
    if (cocoa_pending_actions[CLOSE_TAB]) { call_boss(close_tab, NULL); }
    if (cocoa_pending_actions[NEW_TAB]) { call_boss(new_tab, NULL); }
    if (cocoa_pending_actions[NEXT_TAB]) { call_boss(next_tab, NULL); }
    if (cocoa_pending_actions[PREVIOUS_TAB]) { call_boss(previous_tab, NULL); }
    if (cocoa_pending_actions[DETACH_TAB]) { call_boss(detach_tab, NULL); }
    if (cocoa_pending_actions[NEW_WINDOW]) { call_boss(new_window, NULL); }
    if (cocoa_pending_actions[CLOSE_WINDOW]) { call_boss(close_window, NULL); }
    if (cocoa_pending_actions[RESET_TERMINAL]) { call_boss(clear_terminal, "sO", "reset", Py_True ); }
    if (cocoa_pending_actions[CLEAR_TERMINAL_AND_SCROLLBACK]) { call_boss(clear_terminal, "sO", "to_cursor", Py_True ); }
    if (cocoa_pending_actions[RELOAD_CONFIG]) { call_boss(load_config_file, NULL); }
    if (cocoa_pending_actions[TOGGLE_MACOS_SECURE_KEYBOARD_ENTRY]) { call_boss(toggle_macos_secure_keyboard_entry, NULL); }
    if (cocoa_pending_actions[TOGGLE_FULLSCREEN]) { call_boss(toggle_fullscreen, NULL); }
    if (cocoa_pending_actions[OPEN_KITTY_WEBSITE]) { call_boss(open_kitty_website, NULL); }
    if (cocoa_pending_actions_data.wd) {
        if (cocoa_pending_actions[NEW_OS_WINDOW_WITH_WD]) { call_boss(new_os_window_with_wd, "sO", cocoa_pending_actions_data.wd, Py_True); }
        if (cocoa_pending_actions[NEW_TAB_WITH_WD]) { call_boss(new_tab_with_wd, "sO", cocoa_pending_actions_data.wd, Py_True); }
        free(cocoa_pending_actions_data.wd);
        cocoa_pending_actions_data.wd = NULL;
    }
    if (cocoa_pending_actions_data.open_urls_count) {
        for (unsigned cpa = 0; cpa < cocoa_pending_actions_data.open_urls_count; cpa++) {
            if (cocoa_pending_actions_data.open_urls[cpa]) {
                call_boss(launch_urls, "s", cocoa_pending_actions_data.open_urls[cpa]);
                free(cocoa_pending_actions_data.open_urls[cpa]);
                cocoa_pending_actions_data.open_urls[cpa] = NULL;
            }
        }
        cocoa_pending_actions_data.open_urls_count = 0;
    }
    memset(cocoa_pending_actions, 0, sizeof(cocoa_pending_actions));
    has_cocoa_pending_actions = false;

}
#endif

static void process_global_state(void *data);

static void
do_state_check(id_type timer_id UNUSED, void *data) {
    EVDBG("State check timer fired");
    process_global_state(data);
}

static id_type state_check_timer = 0;

static void
process_global_state(void *data) {
    EVDBG("Processing global state");
    ChildMonitor *self = data;
    maximum_wait = -1;
    bool state_check_timer_enabled = false;
    bool input_read = false;

    monotonic_t now = monotonic();
    if (global_state.has_pending_resizes) {
        process_pending_resizes(now);
        input_read = true;
    }
    if (parse_input(self)) input_read = true;
    render(now, input_read);
#ifdef __APPLE__
    if (has_cocoa_pending_actions) {
        process_cocoa_pending_actions();
        maximum_wait = 0;  // ensure loop ticks again so that the actions side effects are performed immediately
    }
#endif
    report_reaped_pids();
    bool should_quit = false;
    if (global_state.has_pending_closes) should_quit = process_pending_closes(self);
    if (should_quit) {
        stop_main_loop();
    } else {
        if (maximum_wait >= 0) {
            if (maximum_wait == 0) request_tick_callback();
            else state_check_timer_enabled = true;
        }
    }
    update_main_loop_timer(state_check_timer, MAX(0, maximum_wait), state_check_timer_enabled);
}

static PyObject*
main_loop(ChildMonitor *self, PyObject *a UNUSED) {
#define main_loop_doc "The main thread loop"
    state_check_timer = add_main_loop_timer(1000, true, do_state_check, self, NULL);
    run_main_loop(process_global_state, self);
#ifdef __APPLE__
    if (cocoa_pending_actions_data.wd) { free(cocoa_pending_actions_data.wd); cocoa_pending_actions_data.wd = NULL; }
    if (cocoa_pending_actions_data.open_urls) {
        for (unsigned cpa = 0; cpa < cocoa_pending_actions_data.open_urls_count; cpa++) {
            if (cocoa_pending_actions_data.open_urls[cpa]) free(cocoa_pending_actions_data.open_urls[cpa]);
        }
        free(cocoa_pending_actions_data.open_urls); cocoa_pending_actions_data.open_urls = NULL;
    }
#endif
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

// }}}

// I/O thread functions {{{

static void
add_children(ChildMonitor *self) {
    for (; add_queue_count > 0 && self->count < MAX_CHILDREN;) {
        add_queue_count--;
        children[self->count] = add_queue[add_queue_count];
        add_queue[add_queue_count] = EMPTY_CHILD;
        children_fds[EXTRA_FDS + self->count].fd = children[self->count].fd;
        children_fds[EXTRA_FDS + self->count].events = POLLIN;
        self->count++;
    }
}


static void
hangup(pid_t pid) {
    errno = 0;
    pid_t pgid = getpgid(pid);
    if (errno == ESRCH) return;
    if (errno != 0) { perror("Failed to get process group id for child"); return; }
    if (killpg(pgid, SIGHUP) != 0) {
        if (errno != ESRCH) perror("Failed to kill child");
    }
}


static void
cleanup_child(ssize_t i) {
    safe_close(children[i].fd, __FILE__, __LINE__);
    hangup(children[i].pid);
}


static void
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
                children_fds[EXTRA_FDS + i].fd = -1;
                size_t num_to_right = self->count - 1 - i;
                if (num_to_right > 0) {
                    memmove(children + i, children + i + 1, num_to_right * sizeof(Child));
                    memmove(children_fds + EXTRA_FDS + i, children_fds + EXTRA_FDS + i + 1, num_to_right * sizeof(struct pollfd));
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


typedef struct { bool kill_signal, child_died, reload_config; } SignalSet;

static bool
handle_signal(const siginfo_t *siginfo, void *data) {
    SignalSet *ss = data;
    switch(siginfo->si_signo) {
        case SIGINT:
        case SIGTERM:
        case SIGHUP:
            ss->kill_signal = true;
            break;
        case SIGCHLD:
            ss->child_died = true;
            break;
        case SIGUSR1:
            ss->reload_config = true;
            break;
        case SIGUSR2:
            log_error("Received SIGUSR2: %d\n", siginfo->si_value.sival_int);
            break;
        default:
            break;
    }
    return true;
}

static void
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

static void
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

static void
reap_prewarmed_children(ChildMonitor *self, int fd, bool enable_close_on_child_death) {
    static char buf[256];
    static size_t buf_pos = 0;
    while(true) {
        ssize_t len = read(fd, buf + buf_pos, sizeof(buf) - buf_pos);
        if (len < 0) {
            if (errno == EINTR) continue;
            if (errno != EIO && errno != EAGAIN) log_error("Call to read() from reap_prewarmed_children() failed with error: %s", strerror(errno));
            break;
        }
        buf_pos += len;
        char *nl;
        while (buf_pos > 1 && (nl = memchr(buf, '\n', buf_pos)) != NULL) {
            size_t sz = nl - buf + 1;
            if (enable_close_on_child_death) {
                *nl = 0;
                int pid = atoi(buf);
                if (pid) mark_child_for_removal(self, pid);
            }
            memmove(buf, buf + sz, sz);
            buf_pos -= sz;
        }
        if (len == 0) break;
    }

}

static void
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

static void
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
    monotonic_t last_main_loop_wakeup_at = -1, now = -1;
    Screen *screen;
    ChildMonitor *self = (ChildMonitor*)data;
    set_thread_name("KittyChildMon");

    while (LIKELY(!self->shutting_down)) {
        children_mutex(lock);
        remove_children(self);
        add_children(self);
        children_mutex(unlock);
        data_received = false;
        for (i = 0; i < self->count + EXTRA_FDS; i++) children_fds[i].revents = 0;
        for (i = 0; i < self->count; i++) {
            screen = children[i].screen;
            /* printf("i:%lu id:%lu fd: %d read_buf_sz: %lu write_buf_used: %lu\n", i, children[i].id, children[i].fd, screen->read_buf_sz, screen->write_buf_used); */
            screen_mutex(lock, read); screen_mutex(lock, write);
            children_fds[EXTRA_FDS + i].events = (screen->read_buf_sz < READ_BUF_SZ ? POLLIN : 0) | (screen->write_buf_used ? POLLOUT  : 0);
            screen_mutex(unlock, read); screen_mutex(unlock, write);
        }
        if (has_pending_wakeups) {
            now = monotonic();
            monotonic_t time_delta = OPT(input_delay) - (now - last_main_loop_wakeup_at);
            if (time_delta >= 0) ret = poll(children_fds, self->count + EXTRA_FDS, monotonic_t_to_ms(time_delta));
            else ret = 0;
        } else {
            ret = poll(children_fds, self->count + EXTRA_FDS, -1);
        }
        if (ret > 0) {
            if (children_fds[0].revents && POLLIN) drain_fd(children_fds[0].fd); // wakeup
            if (children_fds[1].revents && POLLIN) {
                SignalSet ss = {0};
                data_received = true;
                read_signals(children_fds[1].fd, handle_signal, &ss);
                if (ss.kill_signal || ss.reload_config) {
                    children_mutex(lock);
                    if (ss.kill_signal) kill_signal_received = true;
                    if (ss.reload_config) reload_config_signal_received = true;
                    children_mutex(unlock);
                }
                if (ss.child_died) reap_children(self, OPT(close_on_child_death));
            }
            if (children_fds[2].revents && POLLIN) {
                reap_prewarmed_children(self, children_fds[2].fd, OPT(close_on_child_death));
            }
            for (i = 0; i < self->count; i++) {
                if (children_fds[EXTRA_FDS + i].revents & (POLLIN | POLLHUP)) {
                    data_received = true;
                    has_more = read_bytes(children_fds[EXTRA_FDS + i].fd, children[i].screen);
                    if (!has_more) {
                        // child is dead
                        children_mutex(lock);
                        children[i].needs_removal = true;
                        children_mutex(unlock);
                    }
                }
                if (children_fds[EXTRA_FDS + i].revents & POLLOUT) {
                    write_to_child(children[i].fd, children[i].screen);
                }
                if (children_fds[EXTRA_FDS + i].revents & POLLNVAL) {
                    // fd was closed
                    children_mutex(lock);
                    children[i].needs_removal = true;
                    children_mutex(unlock);
                    log_error("The child %lu had its fd unexpectedly closed", children[i].id);
                }
            }
#ifdef DEBUG_POLL_EVENTS
            for (i = 0; i < self->count + EXTRA_FDS; i++) {
#define P(w) if (children_fds[i].revents & w) printf("i:%lu %s\n", i, #w);
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
    id_type id;
    size_t num_of_unresponded_messages_sent_to_main_thread, fd_array_idx;
    bool finished_reading;
    int fd;
    struct {
        char *data;
        size_t capacity, used, command_end;
        bool finished;
    } read;
    struct {
        char *data;
        size_t capacity, used;
        bool failed;
    } write;
} Peer;
static id_type peer_id_counter = 0;

typedef struct {
    size_t num_peers, peers_capacity;
    Peer *peers;
    LoopData loop_data;
} TalkData;
static TalkData talk_data = {0};

typedef struct pollfd PollFD;
#define PEER_LIMIT 256
#define nuke_socket(s) { shutdown(s, SHUT_RDWR); safe_close(s, __FILE__, __LINE__); }

static bool
accept_peer(int listen_fd, bool shutting_down) {
    int peer = accept(listen_fd, NULL, NULL);
    if (UNLIKELY(peer == -1)) {
        if (errno == EINTR) return true;
        if (!shutting_down) perror("accept() on talk socket failed!");
        return false;
    }
    if (talk_data.num_peers < PEER_LIMIT) {
        ensure_space_for(&talk_data, peers, Peer, talk_data.num_peers + 8, peers_capacity, 8, false);
        Peer *p = talk_data.peers + talk_data.num_peers++;
        memset(p, 0, sizeof(Peer));
        p->fd = peer; p->id = ++peer_id_counter;
        if (!p->id) p->id = ++peer_id_counter;
    } else {
        log_error("Too many peers want to talk, ignoring one.");
        nuke_socket(peer);
    }
    return true;
}

static void
free_peer(Peer *peer) {
    free(peer->read.data); peer->read.data = NULL;
    free(peer->write.data); peer->write.data = NULL;
    if (peer->fd > -1) { nuke_socket(peer->fd); peer->fd = -1; }
}

#define KITTY_CMD_PREFIX "\x1bP@kitty-cmd{"

static void
queue_peer_message(ChildMonitor *self, Peer *peer) {
    talk_mutex(lock);
    ensure_space_for(self, messages, Message, self->messages_count + 16, messages_capacity, 16, true);
    Message *m = self->messages + self->messages_count++;
    memset(m, 0, sizeof(Message));
    if (peer->read.used) {
        m->data = malloc(peer->read.used);
        if (m->data) {
            memcpy(m->data, peer->read.data, peer->read.used);
            m->sz = peer->read.used;
        }
    }
    m->peer_id = peer->id;
    peer->num_of_unresponded_messages_sent_to_main_thread++;
    talk_mutex(unlock);
    wakeup_main_loop();
}

static bool
has_complete_peer_command(Peer *peer) {
    peer->read.command_end = 0;
    if (peer->read.used > sizeof(KITTY_CMD_PREFIX) && memcmp(peer->read.data, KITTY_CMD_PREFIX, sizeof(KITTY_CMD_PREFIX)-1) == 0) {
        for (size_t i = sizeof(KITTY_CMD_PREFIX)-1; i < peer->read.used - 1; i++) {
            if (peer->read.data[i] == 0x1b && peer->read.data[i+1] == '\\') {
                peer->read.command_end = i + 2;
                break;
            }
        }
    }
    return peer->read.command_end ? true : false;
}


static void
dispatch_peer_command(ChildMonitor *self, Peer *peer) {
    if (peer->read.command_end) {
        size_t used = peer->read.used;
        peer->read.used = peer->read.command_end;
        queue_peer_message(self, peer);
        peer->read.used = used;
        if (peer->read.used > peer->read.command_end) {
            peer->read.used -= peer->read.command_end;
            memmove(peer->read.data, peer->read.data + peer->read.command_end, peer->read.used);
        } else peer->read.used = 0;
        peer->read.command_end = 0;
    }
}

static void
read_from_peer(ChildMonitor *self, Peer *peer) {
#define failed(msg) { log_error("Reading from peer failed: %s", msg); shutdown(peer->fd, SHUT_RD); peer->read.finished = true; return; }
    if (peer->read.used >= peer->read.capacity) {
        if (peer->read.capacity >= 64 * 1024) failed("Ignoring too large message from peer");
        peer->read.capacity = MAX(8192u, peer->read.capacity * 2);
        peer->read.data = realloc(peer->read.data, peer->read.capacity);
        if (!peer->read.data) failed("Out of memory");
    }
    ssize_t n = recv(peer->fd, peer->read.data + peer->read.used, peer->read.capacity - peer->read.used, 0);
    if (n == 0) {
        peer->read.finished = true;
        shutdown(peer->fd, SHUT_RD);
        while (has_complete_peer_command(peer)) dispatch_peer_command(self, peer);
        queue_peer_message(self, peer);
        free(peer->read.data); peer->read.data = NULL;
        peer->read.used = 0; peer->read.capacity = 0;
    } else if (n < 0) {
        if (errno != EINTR) failed(strerror(errno));
    } else {
        peer->read.used += n;
        while (has_complete_peer_command(peer)) dispatch_peer_command(self, peer);
    }
#undef failed
}

static void
write_to_peer(Peer *peer) {
    talk_mutex(lock);
    ssize_t n = send(peer->fd, peer->write.data, peer->write.used, MSG_NOSIGNAL);
    if (n == 0) { log_error("send() to peer failed to send any data"); peer->write.used = 0; peer->write.failed = true; }
    else if (n < 0) {
        if (errno != EINTR) { log_error("write() to peer socket failed with error: %s", strerror(errno)); peer->write.used = 0; peer->write.failed = true; }
    } else {
        if ((size_t)n > peer->write.used) memmove(peer->write.data, peer->write.data + n, peer->write.used - n);
        peer->write.used -= n;
    }
    talk_mutex(unlock);
}

static void
wakeup_talk_loop(bool in_signal_handler) {
    if (talk_thread_started) wakeup_loop(&talk_data.loop_data, in_signal_handler, "talk_loop");
}


static void
prune_peers(void) {
    for (size_t idx = talk_data.num_peers; idx-- > 0;) {
        Peer *p = talk_data.peers + idx;
        if (p->read.finished && !p->num_of_unresponded_messages_sent_to_main_thread && !p->write.used) {
            free_peer(p);
            remove_i_from_array(talk_data.peers, idx, talk_data.num_peers);
        }
    }
}

static void*
talk_loop(void *data) {
    // The talk thread loop
    ChildMonitor *self = (ChildMonitor*)data;
    set_thread_name("KittyPeerMon");
    if (!init_loop_data(&talk_data.loop_data, 0)) { log_error("Failed to create wakeup fd for talk thread with error: %s", strerror(errno)); }
    PollFD fds[PEER_LIMIT + 8] = {{0}};
    size_t num_listen_fds = 0, num_peer_fds = 0;
#define add_listener(which) \
    if (self->which > -1) { \
        fds[num_listen_fds].fd = self->which; fds[num_listen_fds++].events = POLLIN; \
    }
    add_listener(talk_fd); add_listener(listen_fd);
#undef add_listener
    fds[num_listen_fds].fd = talk_data.loop_data.wakeup_read_fd; fds[num_listen_fds++].events = POLLIN;

    while (LIKELY(!self->shutting_down)) {
        num_peer_fds = 0;
        if (talk_data.num_peers > 0) {
            talk_mutex(lock);
            prune_peers();
            for (size_t i = 0; i < talk_data.num_peers; i++) {
                Peer *p = talk_data.peers + i;
                if (!p->read.finished || p->write.used) {
                    p->fd_array_idx = num_listen_fds + num_peer_fds++;
                    fds[p->fd_array_idx].fd = p->fd;
                    fds[p->fd_array_idx].revents = 0;
                    int flags = 0;
                    if (!p->read.finished) flags |= POLLIN;
                    if (p->write.used) flags |= POLLOUT;
                    fds[p->fd_array_idx].events = flags;
                } else p->fd_array_idx = 0;
            }
            talk_mutex(unlock);
        }
        for (size_t i = 0; i < num_listen_fds; i++) fds[i].revents = 0;
        int ret = poll(fds, num_listen_fds + num_peer_fds, -1);
        if (ret > 0) {
            for (size_t i = 0; i < num_listen_fds - 1; i++) {
                if (fds[i].revents & POLLIN) {
                    if (!accept_peer(fds[i].fd, self->shutting_down)) goto end;
                }
            }
            if (fds[num_listen_fds - 1].revents & POLLIN) {
                drain_fd(fds[num_listen_fds - 1].fd);  // wakeup
            }
            for (size_t k = 0; k < talk_data.num_peers; k++) {
                Peer *p = talk_data.peers + k;
                if (p->fd_array_idx) {
                    if (fds[p->fd_array_idx].revents & (POLLIN | POLLHUP)) read_from_peer(self, p);
                    if (fds[p->fd_array_idx].revents & POLLOUT) write_to_peer(p);
                    if (fds[p->fd_array_idx].revents & POLLNVAL) {
                        p->read.finished = true;
                        p->write.failed = true; p->write.used = 0;
                    }
                    break;
                }
            }
        } else if (ret < 0) { if (errno != EAGAIN && errno != EINTR) perror("poll() on talk fds failed"); }
    }
end:
    free_loop_data(&talk_data.loop_data);
    for (size_t i = 0; i < talk_data.num_peers; i++) free_peer(talk_data.peers + i);
    free(talk_data.peers);
    return 0;
}

static void
send_response_to_peer(id_type peer_id, const char *msg, size_t msg_sz) {
    bool wakeup = false;
    talk_mutex(lock);
    for (size_t i = 0; i < talk_data.num_peers; i++) {
        Peer *peer = talk_data.peers + i;
        if (peer->id == peer_id) {
            if (peer->num_of_unresponded_messages_sent_to_main_thread) peer->num_of_unresponded_messages_sent_to_main_thread--;
            if (!peer->write.failed) {
                if (peer->write.capacity - peer->write.used < msg_sz) {
                    void *data = realloc(peer->write.data, peer->write.capacity + msg_sz);
                    if (data) {
                        peer->write.data = data;
                        peer->write.capacity += msg_sz;
                    } else fatal("Out of memory");
                }
                if (msg) memcpy(peer->write.data + peer->write.used, msg, msg_sz);
                peer->write.used += msg_sz;
            }
            wakeup = true;
            break;
        }
    }
    talk_mutex(unlock);
    if (wakeup) wakeup_talk_loop(false);
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
    METHODB(handled_signals, METH_NOARGS),
    {"set_iutf8_winid", (PyCFunction)pyset_iutf8, METH_VARARGS, ""},
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
safe_pipe(PyObject *self UNUSED, PyObject *args) {
    int nonblock = 1;
    if (!PyArg_ParseTuple(args, "|p", &nonblock)) return NULL;
    int fds[2] = {0};
    if (!self_pipe(fds, nonblock)) return PyErr_SetFromErrno(PyExc_OSError);
    return Py_BuildValue("ii", fds[0], fds[1]);
}

static PyObject*
cocoa_set_menubar_title(PyObject *self UNUSED, PyObject *args UNUSED) {
#ifdef __APPLE__
    PyObject *title = NULL;
    if (!PyArg_ParseTuple(args, "U", &title)) return NULL;
    change_menubar_title(title);
#endif
    Py_RETURN_NONE;
}

static PyObject*
send_data_to_peer(PyObject *self UNUSED, PyObject *args) {
    char * msg; Py_ssize_t sz;
    unsigned long long peer_id;
    if (!PyArg_ParseTuple(args, "Ks#", &peer_id, &msg, &sz)) return NULL;
    send_response_to_peer(peer_id, msg, sz);
    Py_RETURN_NONE;
}

static PyObject *
random_unix_socket(PyObject *self UNUSED, PyObject *args UNUSED) {
#ifndef SO_PASSCRED
    errno = ENOTSUP;
    return PyErr_SetFromErrno(PyExc_OSError);
#else
	int fd, optval = 1;
	struct sockaddr_un bind_addr = {.sun_family=AF_UNIX};
	fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return PyErr_SetFromErrno(PyExc_OSError);
	if (setsockopt(fd, SOL_SOCKET, SO_PASSCRED, &optval, sizeof optval) != 0) goto fail;
	if (bind(fd, (struct sockaddr *)&bind_addr, sizeof(sa_family_t)) != 0) goto fail;
    return PyLong_FromLong((long)fd);
fail:
    safe_close(fd, __FILE__, __LINE__);
    return PyErr_SetFromErrno(PyExc_OSError);
#endif
}

static PyMethodDef module_methods[] = {
    METHODB(safe_pipe, METH_VARARGS),
    METHODB(random_unix_socket, METH_NOARGS),
    {"add_timer", (PyCFunction)add_python_timer, METH_VARARGS, ""},
    {"remove_timer", (PyCFunction)remove_python_timer, METH_VARARGS, ""},
    METHODB(monitor_pid, METH_VARARGS),
    METHODB(send_data_to_peer, METH_VARARGS),
    METHODB(cocoa_set_menubar_title, METH_VARARGS),
    {"sigqueue", (PyCFunction)sig_queue, METH_VARARGS, ""},
    {NULL}  /* Sentinel */
};

bool
init_child_monitor(PyObject *module) {
    if (PyType_Ready(&ChildMonitor_Type) < 0) return false;
    if (PyModule_AddObject(module, "ChildMonitor", (PyObject *)&ChildMonitor_Type) != 0) return false;
    Py_INCREF(&ChildMonitor_Type);
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
#ifdef NO_SIGQUEUE
    PyModule_AddIntConstant(module, "has_sigqueue", 0);
#else
    PyModule_AddIntConstant(module, "has_sigqueue", 1);
#endif
    return true;
}

// }}}
