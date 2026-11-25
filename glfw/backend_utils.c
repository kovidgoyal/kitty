/*
 * backend_utils.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define _GNU_SOURCE
#include "backend_utils.h"
#include "internal.h"
#include "memfd.h"

#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <time.h>
#include <stdio.h>
#include <sys/mman.h>

#ifdef __NetBSD__
#define ppoll pollts
#endif

void
update_fds(EventLoopData *eld) {
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        Watch *w = eld->watches + i;
        // poll() ignores negative fds, so removed watches are not polled
        eld->fds[i].fd = w->removed ? -1 : w->fd;
        eld->fds[i].events = w->enabled && !w->removed ? w->events : 0;
    }
}


id_type
addWatch(EventLoopData *eld, int fd, int events, int enabled, watch_callback_func cb, void *cb_data) {
    if (eld->watches_count >= sizeof(eld->watches) / sizeof(eld->watches[0])) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Too many watches added");
        return 0;
    }
    static id_type watch_counter = 0;
    // Clear any revents left over from a previously removed watch, so that a
    // watch added after poll() returns, for example by a timer callback, is not
    // reported as ready
    eld->fds[eld->watches_count].revents = 0;
    Watch *w = eld->watches + eld->watches_count++;
    w->ready = 0;
    w->removed = false;
    w->fd = fd;
    w->events = events;
    w->enabled = enabled;
    w->callback = cb;
    w->callback_data = cb_data;
    w->id = ++watch_counter;
    update_fds(eld);
    return w->id;
}

void
removeWatch(EventLoopData *eld, id_type watch_id) {
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        Watch *w = eld->watches + i;
        if (w->id != watch_id) continue;
        if (w->removed) return;
        if (eld->defer_watch_removal) {
            // Removing would move watches that are yet to be dispatched out of
            // sync with the revents of their fds
            w->removed = true;
            w->ready = 0;
            eld->num_removed_watches++;
        } else remove_i_from_array(eld->watches, i, eld->watches_count);
        update_fds(eld);
        return;
    }
}

void
toggleWatch(EventLoopData *eld, id_type watch_id, int enabled) {
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        if (eld->watches[i].id == watch_id) {
            if (eld->watches[i].removed) break;
            if (eld->watches[i].enabled != enabled) {
                eld->watches[i].enabled = enabled;
                update_fds(eld);
            }
            break;
        }
    }
}

static id_type timer_counter = 0;

static int
compare_timers(const void *a_, const void *b_) {
    const Timer *a = (const Timer *)a_, *b = (const Timer *)b_;
    return (a->trigger_at > b->trigger_at) ? 1 : (a->trigger_at < b->trigger_at) ? -1 : 0;
}

static void
update_timers(EventLoopData *eld) {
    // While timer callbacks run the array must not be reordered, dispatchTimers() sorts it afterwards
    if (eld->calling_timers) return;
    if (eld->timers_count > 1) qsort(eld->timers, eld->timers_count, sizeof(eld->timers[0]), compare_timers);
}

// Timers live in a growable array. Capacity starts at MIN_TIMERS_CAPACITY,
// doubles when full and halves when less than a quarter is in use, but never
// drops below MIN_TIMERS_CAPACITY, so normal usage never reallocates.
#define MIN_TIMERS_CAPACITY 64u

static bool
resize_array(void **array, size_t *capacity, size_t new_capacity, size_t item_size) {
    void *n = realloc(*array, new_capacity * item_size);
    if (!n) return false;
    *array = n;
    *capacity = new_capacity;
    return true;
}

static bool
ensure_space_for_timer(EventLoopData *eld) {
    if (eld->timers_count < eld->timers_capacity) return true;
    const size_t new_capacity = MAX(MIN_TIMERS_CAPACITY, 2 * eld->timers_capacity);
    // Grow pending_timer_frees first so that it is never smaller than timers,
    // even if growing timers fails. Growing preserves the contents, so this is
    // safe even while dispatchTimers() is running the free callbacks.
    if (eld->pending_timer_frees_capacity < new_capacity &&
        !resize_array((void **)&eld->pending_timer_frees, &eld->pending_timer_frees_capacity, new_capacity, sizeof(eld->pending_timer_frees[0])))
        return false;
    return resize_array((void **)&eld->timers, &eld->timers_capacity, new_capacity, sizeof(eld->timers[0]));
}

static void
maybe_shrink_timers(EventLoopData *eld) {
    if (eld->timers_capacity > MIN_TIMERS_CAPACITY && eld->timers_count < eld->timers_capacity / 4) {
        // A failed shrink leaves the larger, still valid, array in place
        resize_array((void **)&eld->timers, &eld->timers_capacity, MAX(MIN_TIMERS_CAPACITY, eld->timers_capacity / 2), sizeof(eld->timers[0]));
    }
}

id_type
addTimer(
    EventLoopData *eld, const char *name, monotonic_t interval, int enabled, bool repeats, timer_callback_func cb, void *cb_data, GLFWuserdatafreefun free) {
    if (!ensure_space_for_timer(eld)) {
        _glfwInputError(GLFW_OUT_OF_MEMORY, "Out of memory adding timer: %s", name ? name : "unnamed");
        return 0;
    }
    Timer *t = eld->timers + eld->timers_count++;
    t->interval = interval;
    t->trigger_at = enabled ? monotonic() + interval : MONOTONIC_T_MAX;
    t->repeats = repeats;
    t->removed = false;
    t->callback = cb;
    t->callback_data = cb_data;
    t->free = free;
    t->id = ++timer_counter;
    update_timers(eld);
    return timer_counter;
}

static void
mark_timer_removed(EventLoopData *eld, Timer *t) {
    t->removed = true;
    eld->num_removed_timers++;
}

void
removeTimer(EventLoopData *eld, id_type timer_id) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        Timer *t = eld->timers + i;
        if (t->id != timer_id) continue;
        if (t->removed) return;
        if (eld->calling_timers) {
            // Removing would move timers that are yet to be dispatched
            mark_timer_removed(eld, t);
            return;
        }
        const Timer removed = *t;
        // Removing an item keeps the array sorted
        remove_i_from_array(eld->timers, i, eld->timers_count);
        maybe_shrink_timers(eld);
        // Called last as it can add or remove timers
        if (removed.free && removed.callback_data) removed.free(removed.id, removed.callback_data);
        return;
    }
}

void
removeAllTimers(EventLoopData *eld) {
    if (eld->calling_timers) {
        for (nfds_t i = 0; i < eld->timers_count; i++) {
            if (!eld->timers[i].removed) mark_timer_removed(eld, eld->timers + i);
        }
        return;
    }
    // Remove one timer at a time so that free callbacks that add or remove
    // timers see a consistent array
    while (eld->timers_count) {
        const Timer removed = eld->timers[--eld->timers_count];
        if (removed.free && removed.callback_data) removed.free(removed.id, removed.callback_data);
    }
    maybe_shrink_timers(eld);
}

void
toggleTimer(EventLoopData *eld, id_type timer_id, int enabled) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].id == timer_id) {
            if (eld->timers[i].removed) break;
            monotonic_t trigger_at = enabled ? (monotonic() + eld->timers[i].interval) : MONOTONIC_T_MAX;
            if (trigger_at != eld->timers[i].trigger_at) {
                eld->timers[i].trigger_at = trigger_at;
                update_timers(eld);
            }
            break;
        }
    }
}

void
changeTimerInterval(EventLoopData *eld, id_type timer_id, monotonic_t interval) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].id == timer_id) {
            if (!eld->timers[i].removed) eld->timers[i].interval = interval;
            break;
        }
    }
}


monotonic_t
prepareForPoll(EventLoopData *eld, monotonic_t timeout) {
    for (nfds_t i = 0; i < eld->watches_count; i++) eld->fds[i].revents = 0;
    if (!eld->timers_count || eld->timers[0].trigger_at == MONOTONIC_T_MAX) return timeout;
    monotonic_t now = monotonic(), next_repeat_at = eld->timers[0].trigger_at;
    if (timeout < 0 || now + timeout > next_repeat_at) { timeout = next_repeat_at <= now ? 0 : next_repeat_at - now; }
    return timeout;
}

static struct timespec
calc_time(monotonic_t nsec) {
    struct timespec result;
    result.tv_sec = nsec / (1000LL * 1000LL * 1000LL);
    result.tv_nsec = nsec % (1000LL * 1000LL * 1000LL);
    return result;
}

int
pollWithTimeout(struct pollfd *fds, nfds_t nfds, monotonic_t timeout) {
    struct timespec tv = calc_time(timeout);
    return ppoll(fds, nfds, &tv, NULL);
}

static void
dispatchEvents(EventLoopData *eld) {
    // Callbacks can add or remove watches. Removed watches are only marked as
    // such so that watches[i] and fds[i] stay in sync. Watches added during
    // dispatch are not dispatched as they were not polled.
    const nfds_t count = eld->watches_count;
    for (nfds_t i = 0; i < count; i++) {
        Watch *ww = eld->watches + i;
        const int revents = eld->fds[i].revents;
        if (!ww->removed && ww->enabled && (revents & ww->events)) {
            ww->ready = 1;
            if (ww->callback) ww->callback(ww->fd, revents, ww->callback_data);
        } else ww->ready = 0;
    }
}

static void
drop_removed_watches(EventLoopData *eld) {
    eld->defer_watch_removal = false;
    if (!eld->num_removed_watches) return;
    nfds_t dest = 0;
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        if (eld->watches[i].removed) continue;
        if (dest != i) eld->watches[dest] = eld->watches[i];
        dest++;
    }
    eld->watches_count = dest;
    eld->num_removed_watches = 0;
    update_fds(eld);
}

unsigned
dispatchTimers(EventLoopData *eld) {
    // Re-entrant calls are not supported, they would clobber pending_timer_frees
    if (eld->in_timer_dispatch || !eld->timers_count || eld->timers[0].trigger_at == MONOTONIC_T_MAX) return 0;
    // The array is sorted, so the due timers are at the start
    const monotonic_t now = monotonic();
    nfds_t num_due = 0;
    for (; num_due < eld->timers_count && eld->timers[num_due].trigger_at <= now; num_due++) {
        eld->timers[num_due].trigger_at = now + eld->timers[num_due].interval;
    }
    // Nothing changed, avoid sorting, this is called after every poll wakeup
    if (!num_due) return 0;
    eld->in_timer_dispatch = true;
    // Shrink here as pending_timer_frees must not be resized while it is in use below
    if (eld->pending_timer_frees_capacity > eld->timers_capacity) {
        resize_array((void **)&eld->pending_timer_frees, &eld->pending_timer_frees_capacity, eld->timers_capacity, sizeof(eld->pending_timer_frees[0]));
    }
    // Call the timers in place. While callbacks run, removed timers are only
    // marked, new timers are appended and nothing is sorted, so the due
    // timers stay at [0, num_due), even if the array is reallocated. This
    // means a timer removed by an earlier callback is never called.
    unsigned num_dispatched = 0;
    eld->num_removed_timers = 0;
    eld->calling_timers = true;
    for (nfds_t i = 0; i < num_due; i++) {
        const Timer t = eld->timers[i];
        // Skip timers removed or disabled by an earlier callback
        if (t.removed || t.trigger_at == MONOTONIC_T_MAX) continue;
        t.callback(t.id, t.callback_data);
        num_dispatched++;
        if (!t.repeats && !eld->timers[i].removed) mark_timer_removed(eld, eld->timers + i);
    }
    eld->calling_timers = false;
    // Drop the removed timers in a single pass, keeping the order of the rest,
    // and queue their free callbacks. pending_timer_frees is at least as large
    // as timers so it can hold them all.
    size_t num_frees = 0;
    if (eld->num_removed_timers) {
        nfds_t w = 0;
        for (nfds_t i = 0; i < eld->timers_count; i++) {
            const Timer *t = eld->timers + i;
            if (t->removed) {
                if (t->free && t->callback_data) eld->pending_timer_frees[num_frees++] = (TimerFree){t->free, t->id, t->callback_data};
            } else {
                if (w != i) eld->timers[w] = *t;
                w++;
            }
        }
        eld->timers_count = w;
        eld->num_removed_timers = 0;
    }
    update_timers(eld);
    maybe_shrink_timers(eld);
    // Free callbacks run last, with the array consistent, as they can add or
    // remove timers. Adding can grow, but never shrink, pending_timer_frees.
    for (size_t i = 0; i < num_frees; i++) {
        const TimerFree f = eld->pending_timer_frees[i];
        f.free(f.id, f.data);
    }
    eld->in_timer_dispatch = false;
    return num_dispatched;
}

static void
drain_wakeup_fd(int fd, EventLoopData *eld) {
    static char drain_buf[64];
    eld->wakeup_data_read = false;
    while (true) {
        ssize_t ret = read(fd, drain_buf, sizeof(drain_buf));
        if (ret < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (ret > 0) {
            eld->wakeup_data_read = true;
            continue;
        }
        break;
    }
}

static void
mark_wakep_fd_ready(int fd UNUSED, int events UNUSED, void *data) {
    ((EventLoopData *)(data))->wakeup_fd_ready = true;
}

static void
mark_key_repeat_fd_ready(int fd UNUSED, int events UNUSED, void *data) {
    ((EventLoopData *)(data))->key_repeat_fd_ready = true;
}


bool
initPollData(EventLoopData *eld, int display_fd) {
    if (!addWatch(eld, display_fd, POLLIN, 1, NULL, NULL)) return false;
#ifdef HAS_EVENT_FD
    eld->wakeupFd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    if (eld->wakeupFd == -1) return false;
    const int wakeup_fd = eld->wakeupFd;
#else
    if (pipe2(eld->wakeupFds, O_CLOEXEC | O_NONBLOCK) != 0) return false;
    const int wakeup_fd = eld->wakeupFds[0];
#endif
    if (!addWatch(eld, wakeup_fd, POLLIN, 1, mark_wakep_fd_ready, eld)) return false;

#ifdef HAS_TIMER_FD
    eld->key_repeat_fd = timerfd_create(CLOCK_MONOTONIC, TFD_NONBLOCK | TFD_CLOEXEC);
    if (eld->key_repeat_fd < 0) return false;
    const int key_repeat_fd = eld->key_repeat_fd;
#else
    if (pipe2(eld->key_repeat_fds, O_CLOEXEC | O_NONBLOCK) != 0) return false;
    const int key_repeat_fd = eld->key_repeat_fds[0];
#endif
#ifdef _GLFW_WAYLAND
    if (!addWatch(eld, key_repeat_fd, POLLIN, 1, mark_key_repeat_fd_ready, eld)) return false;
#else
    (void)key_repeat_fd;
    (void)mark_key_repeat_fd_ready;
#endif
    return true;
}

void
check_for_wakeup_events(EventLoopData *eld) {
#ifdef HAS_EVENT_FD
    int fd = eld->wakeupFd;
#else
    int fd = eld->wakeupFds[0];
#endif
    drain_wakeup_fd(fd, eld);
}

void
wakeupEventLoop(EventLoopData *eld) {
#ifdef HAS_EVENT_FD
    static const uint64_t value = 1;
    while (write(eld->wakeupFd, &value, sizeof value) < 0 && (errno == EINTR || errno == EAGAIN));
#else
    while (write(eld->wakeupFds[1], "w", 1) < 0 && (errno == EINTR || errno == EAGAIN));
#endif
}

static void
closeFds(int *fds, size_t count) {
    while (count--) {
        if (*fds > 0) {
            close(*fds);
            *fds = -1;
        }
        fds++;
    }
}

void
finalizePollData(EventLoopData *eld) {
    (void)closeFds;
    // Must not be called from a timer callback, as dispatchTimers() would
    // then use the freed arrays. glfw is only terminated after the main loop exits.
    removeAllTimers(eld);
    free(eld->timers);
    eld->timers = NULL;
    eld->timers_capacity = 0;
    free(eld->pending_timer_frees);
    eld->pending_timer_frees = NULL;
    eld->pending_timer_frees_capacity = 0;
#ifdef HAS_EVENT_FD
    close(eld->wakeupFd);
    eld->wakeupFd = -1;
#else
    closeFds(eld->wakeupFds, arraysz(eld->wakeupFds));
#endif
#ifdef HAS_TIMER_FD
    close(eld->key_repeat_fd);
    eld->key_repeat_fd = -1;
#else
    closeFds(eld->key_repeat_fds, arraysz(eld->key_repeat_fds));
#endif
}

static int
display_fd_ready(EventLoopData *eld) {
    // watches[0] is always the display fd. Errors count as ready: the display
    // callback must complete the read rather than cancel it, so that a
    // compositor disconnect is turned into a display error instead of a poll()
    // that keeps returning immediately forever.
    return eld->fds[0].revents & (POLLIN | POLLERR | POLLHUP | POLLNVAL);
}

int
pollForEvents(EventLoopData *eld, monotonic_t timeout, watch_callback_func display_callback) {
    int read_ok = 0;
    timeout = prepareForPoll(eld, timeout);
    EVDBG("pollForEvents final timeout: %.3f", monotonic_t_to_s_double(timeout));
    int result;
    monotonic_t end_time = monotonic() + timeout;
    eld->wakeup_fd_ready = false;
    eld->key_repeat_fd_ready = false;

    while (1) {
        if (timeout >= 0) {
            errno = 0;
            result = pollWithTimeout(eld->fds, eld->watches_count, timeout);
            int saved_errno = errno;
            // Callbacks below can remove watches
            eld->defer_watch_removal = true;
            if (display_callback) display_callback(result, display_fd_ready(eld), NULL);
            dispatchTimers(eld);
            if (result > 0) {
                dispatchEvents(eld);
                read_ok = eld->watches[0].ready;
            }
            drop_removed_watches(eld);
            if (result > 0) break;
            timeout = end_time - monotonic();
            if (timeout <= 0) break;
            if (result < 0 && (saved_errno == EINTR || saved_errno == EAGAIN)) continue;
            break;
        } else {
            errno = 0;
            result = poll(eld->fds, eld->watches_count, -1);
            int saved_errno = errno;
            // Callbacks below can remove watches
            eld->defer_watch_removal = true;
            if (display_callback) display_callback(result, display_fd_ready(eld), NULL);
            dispatchTimers(eld);
            if (result > 0) {
                dispatchEvents(eld);
                read_ok = eld->watches[0].ready;
            }
            drop_removed_watches(eld);
            if (result < 0 && (saved_errno == EINTR || saved_errno == EAGAIN)) continue;
            break;
        }
    }
    return read_ok;
}

// Duplicate a UTF-8 encoded string
// but cut it so that it has at most max_length bytes plus the null byte.
// This does not take combining characters into account.
GLFWAPI char *
utf_8_strndup(const char *source, size_t max_length) {
    if (!source) return NULL;
    size_t length = strnlen(source, max_length);
    if (length >= max_length) {
        for (length = max_length; length > 0; length--) {
            if ((source[length] & 0xC0) != 0x80) break;
        }
    }

    char *result = malloc(length + 1);
    memcpy(result, source, length);
    result[length] = 0;
    return result;
}

/*
 * Create a new, unique, anonymous file of the given size, and
 * return the file descriptor for it. The file descriptor is set
 * CLOEXEC. The file is immediately suitable for mmap()'ing
 * the given size at offset zero.
 *
 * The file should not have a permanent backing store like a disk,
 * but may have if XDG_RUNTIME_DIR is not properly implemented in OS.
 *
 * The file name is deleted from the file system.
 *
 * The file is suitable for buffer sharing between processes by
 * transmitting the file descriptor over Unix sockets using the
 * SCM_RIGHTS methods.
 *
 * posix_fallocate() is used to guarantee that disk space is available
 * for the file at the given size. If disk space is insufficient, errno
 * is set to ENOSPC. If posix_fallocate() is not supported, program may
 * receive SIGBUS on accessing mmap()'ed file contents instead.
 */
int
createAnonymousFile(off_t size) {
    int ret, fd = -1, shm_anon = 0;
#ifdef HAS_MEMFD_CREATE
    fd = glfw_memfd_create("glfw-shared", MFD_CLOEXEC | MFD_ALLOW_SEALING);
    if (fd < 0) return -1;
    // We can add this seal before calling posix_fallocate(), as the file
    // is currently zero-sized anyway.
    //
    // There is also no need to check for the return value, we couldn’t do
    // anything with it anyway.
    fcntl(fd, F_ADD_SEALS, F_SEAL_SHRINK | F_SEAL_SEAL);
#elif defined(SHM_ANON)
    fd = shm_open(SHM_ANON, O_RDWR | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    shm_anon = 1;
#else
    static const char template[] = "/glfw-shared-XXXXXX";
    const char *path;
    char *name;

    path = getenv("XDG_RUNTIME_DIR");
    if (!path) {
        errno = ENOENT;
        return -1;
    }

    name = calloc(strlen(path) + sizeof(template), 1);
    strcpy(name, path);
    strcat(name, template);

    fd = createTmpfileCloexec(name);

    free(name);

    if (fd < 0) return -1;
#endif
    // posix_fallocate does not work on SHM descriptors
    ret = shm_anon ? ftruncate(fd, size) : posix_fallocate(fd, 0, size);
    if (ret != 0) {
        close(fd);
        errno = ret;
        return -1;
    }
    return fd;
}

// Input event times from Wayland compositors and X servers are on the
// CLOCK_MONOTONIC clock, which is not the clock of monotonic(), so only the age
// of an event is used, measured against CLOCK_MONOTONIC. See
// MAX_INPUT_EVENT_AGE_SECONDS for implausible ages.
static monotonic_t
event_age_to_monotonic(monotonic_t age) {
    const monotonic_t now = monotonic();
    if (age < 0 || age > s_to_monotonic_t(MAX_INPUT_EVENT_AGE_SECONDS)) return now;
    return now - age;
}

// Converts an event time in milliseconds, which wraps at 32 bits, as used by
// wl_pointer, wl_touch and X11 events
monotonic_t
event_time_ms_to_monotonic(uint32_t time_ms) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return monotonic();
    const uint32_t now_ms = (uint32_t)((uint64_t)ts.tv_sec * 1000u + (uint64_t)ts.tv_nsec / 1000000u);
    return event_age_to_monotonic(ms_to_monotonic_t((monotonic_t)(uint32_t)(now_ms - time_ms)));
}

// Converts an event time in nanoseconds, as used by the input timestamps protocol
monotonic_t
event_time_ns_to_monotonic(uint64_t time_ns) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) return monotonic();
    const uint64_t now_ns = (uint64_t)ts.tv_sec * 1000000000u + (uint64_t)ts.tv_nsec;
    if (time_ns > now_ns) return monotonic();
    return event_age_to_monotonic((monotonic_t)(now_ns - time_ns));
}
