/*
 * child-monitor.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#ifdef __APPLE__
#include <pthread.h>
// I cant figure out how to get pthread.h to include this definition on macOS. MACOSX_DEPLOYMENT_TARGET does not work.
extern int pthread_setname_np(const char *name);
#else
// Need _GNU_SOURCE for pthread_setname_np on linux
#define _GNU_SOURCE
#include <pthread.h>
#undef _GNU_SOURCE
#endif
#include "state.h"
#include "screen.h"
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

static void (*parse_func)(Screen*, PyObject*);

typedef struct {
    char *data;
    size_t sz;
} Message;

typedef struct {
    PyObject_HEAD

    PyObject *dump_callback, *update_screen, *death_notify;
    unsigned int count;
    bool shutting_down;
    pthread_t io_thread, talk_thread;

    int talk_fd;
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


static Child children[MAX_CHILDREN] = {{0}};
static Child scratch[MAX_CHILDREN] = {{0}};
static Child add_queue[MAX_CHILDREN] = {{0}}, remove_queue[MAX_CHILDREN] = {{0}};
static unsigned long remove_notify[MAX_CHILDREN] = {0};
static size_t add_queue_count = 0, remove_queue_count = 0;
static struct pollfd fds[MAX_CHILDREN + EXTRA_FDS] = {{0}};
static pthread_mutex_t children_lock;
static bool signal_received = false;
static ChildMonitor *the_monitor = NULL;
static uint8_t drain_buf[1024];
static int signal_fds[2], wakeup_fds[2];


static inline void
set_thread_name(const char *name) {
    int ret = 0;
#ifdef __APPLE__
    ret = pthread_setname_np(name);
#else
    ret = pthread_setname_np(pthread_self(), name);
#endif
    if (ret != 0) perror("Failed to set thread name");
}


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
    PyObject *dump_callback, *death_notify;
    int talk_fd = -1;
    int ret;

    if (the_monitor) { PyErr_SetString(PyExc_RuntimeError, "Can have only a single ChildMonitor instance"); return NULL; }
    if (!PyArg_ParseTuple(args, "OO|i", &death_notify, &dump_callback, &talk_fd)) return NULL;
    if ((ret = pthread_mutex_init(&children_lock, NULL)) != 0) {
        PyErr_Format(PyExc_RuntimeError, "Failed to create children_lock mutex: %s", strerror(ret));
        return NULL;
    }
    if (!self_pipe(wakeup_fds)) return PyErr_SetFromErrno(PyExc_OSError);
    if (!self_pipe(signal_fds)) return PyErr_SetFromErrno(PyExc_OSError);
    struct sigaction act = {.sa_handler=handle_signal};
    if (sigaction(SIGINT, &act, NULL) != 0) return PyErr_SetFromErrno(PyExc_OSError);
    if (sigaction(SIGTERM, &act, NULL) != 0) return PyErr_SetFromErrno(PyExc_OSError);
    if (siginterrupt(SIGINT, false) != 0) return PyErr_SetFromErrno(PyExc_OSError);
    if (siginterrupt(SIGTERM, false) != 0) return PyErr_SetFromErrno(PyExc_OSError);
    self = (ChildMonitor *)type->tp_alloc(type, 0);
    self->talk_fd = talk_fd;
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

static PyObject *
start(ChildMonitor *self) {
#define start_doc "start() -> Start the I/O thread"
    if (self->talk_fd > -1) {
        if (pthread_create(&self->talk_thread, NULL, talk_loop, self) != 0) return PyErr_SetFromErrno(PyExc_OSError);
    }
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
schedule_write_to_child(unsigned long id, const char *data, size_t sz) {
    ChildMonitor *self = the_monitor;
    bool found = false;
    children_mutex(lock);
    for (size_t i = 0; i < self->count; i++) {
        if (children[i].id == id) {
            found = true;
            Screen *screen = children[i].screen;
            screen_mutex(lock, write);
            size_t space_left = screen->write_buf_sz - screen->write_buf_used;
            if (space_left < sz) {
                if (screen->write_buf_used + sz > 100 * 1024 * 1024) {
                    fprintf(stderr, "Too much data being sent to child with id: %lu, ignoring it\n", id);
                    screen_mutex(unlock, write);
                    break;
                }
                screen->write_buf_sz = screen->write_buf_used + sz;
                screen->write_buf = PyMem_RawRealloc(screen->write_buf, screen->write_buf_sz);
                if (screen->write_buf == NULL) { fatal("Out of memory."); }
            }
            memcpy(screen->write_buf + screen->write_buf_used, data, sz);
            screen->write_buf_used += sz;
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
    if (schedule_write_to_child(id, data, sz)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

static PyObject *
shutdown_monitor(ChildMonitor *self) {
#define shutdown_monitor_doc "shutdown_monitor() -> Shutdown the monitor loop."
    signal(SIGINT, SIG_DFL);
    signal(SIGTERM, SIG_DFL);
    self->shutting_down = true;
    Py_RETURN_NONE;
}

static inline void
do_parse(ChildMonitor *self, Screen *screen, double now) {
    screen_mutex(lock, read);
    if (screen->read_buf_sz) {
        double time_since_new_input = now - screen->new_input_at;
        if (time_since_new_input >= OPT(input_delay)) {
            parse_func(screen, self->dump_callback);
            if (screen->read_buf_sz >= READ_BUF_SZ) wakeup_io_loop(false);  // Ensure the read fd has POLLIN set
            screen->read_buf_sz = 0;
            screen->new_input_at = 0;
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
                PyTuple_SET_ITEM(msg, i, PyBytes_FromStringAndSize(m->data, m->sz));
                free(m->data); m->data = NULL; m->sz = 0;
            }
            self->messages_count = 0;
        } else fatal("Out of memory");
    }

    if (UNLIKELY(signal_received)) {
        global_state.close_all_windows = true;
    } else {
        count = self->count;
        for (size_t i = 0; i < count; i++) {
            scratch[i] = children[i];
            INCREF_CHILD(scratch[i]);
        }
    }
    children_mutex(unlock);
    if (msg) {
        call_boss(peer_messages_received, "(O)", msg);
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
    } else fprintf(stderr, "Failed to send resize signal to child with id: %lu (children count: %u) (add queue: %zu)\n", window_id, self->count, add_queue_count);
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

static inline double
cursor_width(double w, bool vert, OSWindow *os_window) {
    double dpi = vert ? global_state.logical_dpi_x : global_state.logical_dpi_y;
    double ans = w * dpi / 72.0;  // as pixels
    double factor = 2.0 / (vert ? os_window->viewport_width : os_window->viewport_height);
    return ans * factor;
}

extern void cocoa_update_title(PyObject*);

static inline void
collect_cursor_info(CursorRenderInfo *ans, Window *w, double now, OSWindow *os_window) {
    ScreenRenderData *rd = &w->render_data;
    Cursor *cursor = rd->screen->cursor;
    ans->x = cursor->x; ans->y = cursor->y;
    ans->is_visible = false;
    if (rd->screen->scrolled_by || !screen_is_cursor_visible(rd->screen)) return;
    double time_since_start_blink = now - os_window->cursor_blink_zero_time;
    bool cursor_blinking = OPT(cursor_blink_interval) > 0 && os_window->is_focused && time_since_start_blink <= OPT(cursor_stop_blinking_after) ? true : false;
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
    if (ans->shape == CURSOR_BLOCK && ans->is_focused) return;
    double left = rd->xstart + cursor->x * rd->dx;
    double top = rd->ystart - cursor->y * rd->dy;
    unsigned long mult = MAX(1, screen_current_char_width(rd->screen));
    double right = left + (ans->shape == CURSOR_BEAM ? cursor_width(1.5, true, os_window) : rd->dx * mult);
    double bottom = top - rd->dy;
	switch (ans->shape) {
        case CURSOR_UNDERLINE:
            top = bottom + cursor_width(2.0, false, os_window);
            break;
        case CURSOR_BLOCK:
            top -= 2.0 / os_window->viewport_height;  // 1px adjustment for width of line
            break;
        default:
            break;
	}
    ans->left = left; ans->right = right; ans->top = top; ans->bottom = bottom;
}

static inline bool
update_window_title(Window *w, OSWindow *os_window) {
    if (w->title && w->title != os_window->window_title) {
        os_window->window_title = w->title;
        Py_INCREF(os_window->window_title);
        set_os_window_title(os_window, PyUnicode_AsUTF8(w->title));
#ifdef __APPLE__
        if (os_window->is_focused) cocoa_update_title(w->title);
#endif
        return true;
    }
    return false;
}

static PyObject*
simple_render_screen(PyObject UNUSED *self, PyObject *args) {
#define simple_render_screen_doc "Render a Screen object, with no cursor"
    Screen *screen;
    float xstart, ystart, dx, dy;
    static ssize_t vao_idx = -1, gvao_idx = -1;
    if (vao_idx == -1) vao_idx = create_cell_vao();
    if (gvao_idx == -1) gvao_idx = create_graphics_vao();
    if (!PyArg_ParseTuple(args, "O!ffff", &Screen_Type, &screen, &xstart, &ystart, &dx, &dy)) return NULL;
    draw_cells(vao_idx, gvao_idx, xstart, ystart, dx, dy, screen, current_os_window(), true);
    Py_RETURN_NONE;
}

static inline bool
prepare_to_render_os_window(OSWindow *os_window, double now, unsigned int *active_window_id) {
#define TD os_window->tab_bar_render_data
    bool needs_render = false;
    if (TD.screen && os_window->num_tabs > 1) {
        if (send_cell_data_to_gpu(TD.vao_idx, 0, TD.xstart, TD.ystart, TD.dx, TD.dy, TD.screen, os_window)) needs_render = true;
    }
    if (OPT(mouse_hide_wait) > 0 && now - os_window->last_mouse_activity_at > OPT(mouse_hide_wait)) hide_mouse(os_window);
    Tab *tab = os_window->tabs + os_window->active_tab;
    for (unsigned int i = 0; i < tab->num_windows; i++) {
        Window *w = tab->windows + i;
#define WD w->render_data
        if (w->visible && WD.screen) {
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
                update_window_title(w, os_window);
            } else WD.screen->cursor_render_info.is_visible = false;
            if (send_cell_data_to_gpu(WD.vao_idx, WD.gvao_idx, WD.xstart, WD.ystart, WD.dx, WD.dy, WD.screen, os_window)) needs_render = true;
            if (WD.screen->start_visual_bell_at != 0) needs_render = true;
        }
    }
    return needs_render;
}

static inline void
render_os_window(OSWindow *os_window, double now, unsigned int active_window_id) {
    Tab *tab = os_window->tabs + os_window->active_tab;
    BorderRects *br = &tab->border_rects;
    draw_borders(br->vao_idx, br->num_border_rects, br->rect_buf, br->is_dirty, os_window->viewport_width, os_window->viewport_height);
    bool needs_vsync = false;
    if (TD.screen && os_window->num_tabs > 1) draw_cells(TD.vao_idx, 0, TD.xstart, TD.ystart, TD.dx, TD.dy, TD.screen, os_window, true);
    for (unsigned int i = 0; i < tab->num_windows; i++) {
        Window *w = tab->windows + i;
        if (w->visible && WD.screen) {
            bool is_active_window = i == tab->active_window;
            draw_cells(WD.vao_idx, WD.gvao_idx, WD.xstart, WD.ystart, WD.dx, WD.dy, WD.screen, os_window, is_active_window);
            if (is_active_window && WD.screen->cursor_render_info.is_visible && (!WD.screen->cursor_render_info.is_focused || WD.screen->cursor_render_info.shape != CURSOR_BLOCK)) {
                draw_cursor(&WD.screen->cursor_render_info, os_window->is_focused);
            }
            if (WD.screen->start_visual_bell_at != 0) {
                double bell_left = global_state.opts.visual_bell_duration - (now - WD.screen->start_visual_bell_at);
                set_maximum_wait(bell_left);
            }
            if (!needs_vsync && (WD.screen->render_activity.large_change || WD.screen->render_activity.chars_written > 100)) needs_vsync = true;
            WD.screen->render_activity.large_change = false; WD.screen->render_activity.chars_written = 0;
        }
    }
    swap_window_buffers(os_window, needs_vsync);
    br->is_dirty = false;
    os_window->last_active_tab = os_window->active_tab; os_window->last_num_tabs = os_window->num_tabs; os_window->last_active_window_id = active_window_id;
    os_window->focused_at_last_render = os_window->is_focused;
    os_window->is_damaged = false;
#undef WD
#undef TD
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
        if (!w->num_tabs || !should_os_window_be_rendered(w)) continue;
        bool needs_render = w->is_focused || w->is_damaged;
        make_os_window_context_current(w);
        if (w->viewport_size_dirty) {
            w->clear_count = 0;
            update_surface_size(w->viewport_width, w->viewport_height, w->offscreen_texture_id);
            w->viewport_size_dirty = false;
            needs_render = true;
        }
        unsigned int active_window_id = 0;
        if (prepare_to_render_os_window(w, now, &active_window_id)) needs_render = true;
        if (w->last_active_window_id != active_window_id || w->last_active_tab != w->active_tab || w->focused_at_last_render != w->is_focused) needs_render = true;
        if (needs_render) render_os_window(w, now, active_window_id);
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

static void*
thread_write(void *x) {
    ThreadWriteData *data = (ThreadWriteData*)x;
    set_thread_name("KittyWriteStdin");
    FILE *f = fdopen(data->fd, "w");
    if (fwrite(data->buf, 1, data->sz, f) != data->sz) {
        fprintf(stderr, "Failed to write all data\n");
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

static inline void
wait_for_events() {
    event_loop_wait(maximum_wait);
    maximum_wait = -1;
}

static inline void
process_pending_resizes(double now) {
    global_state.has_pending_resizes = false;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *w = global_state.os_windows + i;
        if (w->has_pending_resizes) {
            if (now - w->last_resize_event_at >= RESIZE_DEBOUNCE_TIME) update_os_window_viewport(w, true);
            else {
                global_state.has_pending_resizes = true;
                set_maximum_wait(RESIZE_DEBOUNCE_TIME - now + w->last_resize_event_at);
            }
        }
    }
}

static PyObject*
main_loop(ChildMonitor *self) {
#define main_loop_doc "The main thread loop"
    bool has_open_windows = true;

    while (has_open_windows) {
        double now = monotonic();
        if (global_state.has_pending_resizes) process_pending_resizes(now);
        render(now);
        wait_for_events();
        parse_input(self);
        if (global_state.close_all_windows) {
            for (size_t w = 0; w < global_state.num_os_windows; w++) mark_os_window_for_close(&global_state.os_windows[w], true);
            global_state.close_all_windows = false;
        }
        has_open_windows = false;
        for (size_t w = global_state.num_os_windows; w > 0; w--) {
            OSWindow *os_window = global_state.os_windows + w - 1;
            if (should_os_window_close(os_window)) {
                destroy_os_window(os_window);
                call_boss(on_os_window_closed, "Kii", os_window->id, os_window->viewport_width, os_window->viewport_height);
                for (size_t t=0; t < os_window->num_tabs; t++) {
                    Tab *tab = os_window->tabs + t;
                    for (size_t w = 0; w < tab->num_windows; w++) mark_child_for_close(self, tab->windows[w].id);
                }
                remove_os_window(os_window->id);
            } else has_open_windows = true;
        }
    }
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
            if (errno == EINTR) continue;
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
    screen->write_buf_used -= written;
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
        ret = poll(fds, self->count + EXTRA_FDS, -1);
        if (ret > 0) {
            if (fds[0].revents && POLLIN) drain_fd(fds[0].fd); // wakeup
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
                if (fds[EXTRA_FDS + i].revents & POLLNVAL) {
                    // fd was closed
                    children_mutex(lock);
                    children[i].needs_removal = true;
                    children_mutex(unlock);
                    fprintf(stderr, "The child %lu had its fd unexpectedly closed\n", children[i].id);
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
        if (data_received) wakeup_main_loop();
    }
    children_mutex(lock);
    for (i = 0; i < self->count; i++) children[i].needs_removal = true;
    remove_children(self);
    children_mutex(unlock);
    return 0;
}
// }}}

// {{{ Talk thread functions

static inline void
handle_peer(ChildMonitor *self, int s) {
    size_t bufsz = 0;
    char *buf = NULL;
    size_t buf_used = 0;

    while(true) {
        if (buf_used >= bufsz) {
            bufsz = MAX(1024, bufsz) * 2;
            if (bufsz > 1024 * 1024) return;
            buf = realloc(buf, bufsz);
            if (buf == NULL) return;
        }
        ssize_t n = recv(s, buf + buf_used, bufsz - buf_used, 0);
        if (n == 0) break;
        if (n < 0) {
            if (errno == EINTR) continue;
            perror("Error reading from talk peer");
            break;
        }
        buf_used += n;
    }
    if (buf_used) {
        children_mutex(lock);
        ensure_space_for(self, messages, Message, self->messages_count + 1, messages_capacity, 16, true);
        Message *m = self->messages + self->messages_count++;
        m->data = buf; m->sz = buf_used;
        children_mutex(unlock);
        wakeup_main_loop();
    } else free(buf);
}

static void*
talk_loop(void *data) {
    // The I/O thread loop

    ChildMonitor *self = (ChildMonitor*)data;
    set_thread_name("KittyTalkMon");

    while (LIKELY(!self->shutting_down)) {
        int peer = accept(self->talk_fd, NULL, NULL);
        if (peer == -1) {
            if (errno == EINTR) continue;
            if (!self->shutting_down) perror("accept() on talk socket failed!");
            break;
        }
        handle_peer(self, peer);
        shutdown(peer, SHUT_RDWR);
        close(peer);
    }
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
    METHOD(shutdown_monitor, METH_NOARGS)
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

static PyMethodDef module_methods[] = {
    METHOD(simple_render_screen, METH_VARARGS)
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
