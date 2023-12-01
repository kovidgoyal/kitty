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

#ifdef __NetBSD__
#define ppoll pollts
#endif

void
update_fds(EventLoopData *eld) {
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        Watch *w = eld->watches + i;
        eld->fds[i].fd = w->fd;
        eld->fds[i].events = w->enabled ? w->events : 0;
    }
}

static id_type watch_counter = 0;

id_type
addWatch(EventLoopData *eld, const char* name, int fd, int events, int enabled, watch_callback_func cb, void *cb_data) {
    if (eld->watches_count >= sizeof(eld->watches)/sizeof(eld->watches[0])) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Too many watches added");
        return 0;
    }
    Watch *w = eld->watches + eld->watches_count++;
    w->name = name;
    w->fd = fd; w->events = events; w->enabled = enabled;
    w->callback = cb;
    w->callback_data = cb_data;
    w->free = NULL;
    w->id = ++watch_counter;
    update_fds(eld);
    return w->id;
}

#define removeX(which, item_id, update_func) {\
    for (nfds_t i = 0; i < eld->which##_count; i++) { \
        if (eld->which[i].id == item_id) { \
            eld->which##_count--; \
            if (eld->which[i].callback_data && eld->which[i].free) { \
                eld->which[i].free(eld->which[i].id, eld->which[i].callback_data); \
                eld->which[i].callback_data = NULL; eld->which[i].free = NULL; \
            } \
            if (i < eld->which##_count) { \
                memmove(eld->which + i, eld->which + i + 1, sizeof(eld->which[0]) * (eld->which##_count - i)); \
            } \
            update_func(eld); break; \
}}}

void
removeWatch(EventLoopData *eld, id_type watch_id) {
    removeX(watches, watch_id, update_fds);
}

void
toggleWatch(EventLoopData *eld, id_type watch_id, int enabled) {
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        if (eld->watches[i].id == watch_id) {
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
    const Timer *a = (const Timer*)a_, *b = (const Timer*)b_;
    return (a->trigger_at > b->trigger_at) ? 1 : (a->trigger_at < b->trigger_at) ? -1 : 0;
}

static void
update_timers(EventLoopData *eld) {
    if (eld->timers_count > 1) qsort(eld->timers, eld->timers_count, sizeof(eld->timers[0]), compare_timers);
}

id_type
addTimer(EventLoopData *eld, const char *name, monotonic_t interval, int enabled, bool repeats, timer_callback_func cb, void *cb_data, GLFWuserdatafreefun free) {
    if (eld->timers_count >= sizeof(eld->timers)/sizeof(eld->timers[0])) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Too many timers added");
        return 0;
    }
    Timer *t = eld->timers + eld->timers_count++;
    t->interval = interval;
    t->name = name;
    t->trigger_at = enabled ? monotonic() + interval : MONOTONIC_T_MAX;
    t->repeats = repeats;
    t->callback = cb;
    t->callback_data = cb_data;
    t->free = free;
    t->id = ++timer_counter;
    update_timers(eld);
    return timer_counter;
}

void
removeTimer(EventLoopData *eld, id_type timer_id) {
    removeX(timers, timer_id, update_timers);
}

void
removeAllTimers(EventLoopData *eld) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].free && eld->timers[i].callback_data) eld->timers[i].free(eld->timers[i].id, eld->timers[i].callback_data);
    }
    eld->timers_count = 0;
}

void
toggleTimer(EventLoopData *eld, id_type timer_id, int enabled) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].id == timer_id) {
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
            eld->timers[i].interval = interval;
            break;
        }
    }
}


monotonic_t
prepareForPoll(EventLoopData *eld, monotonic_t timeout) {
    for (nfds_t i = 0; i < eld->watches_count; i++) eld->fds[i].revents = 0;
    if (!eld->timers_count || eld->timers[0].trigger_at == MONOTONIC_T_MAX) return timeout;
    monotonic_t now = monotonic(), next_repeat_at = eld->timers[0].trigger_at;
    if (timeout < 0 || now + timeout > next_repeat_at) {
        timeout = next_repeat_at <= now ? 0 : next_repeat_at - now;
    }
    return timeout;
}

static struct timespec
calc_time(monotonic_t nsec) {
    struct timespec result;
    result.tv_sec  = nsec / (1000LL * 1000LL * 1000LL);
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
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        Watch *ww = eld->watches + i;
        struct pollfd *pfd = eld->fds + i;
        if (pfd->revents & ww->events) {
            ww->ready = 1;
            if (ww->callback) ww->callback(ww->fd, pfd->revents, ww->callback_data);
        } else ww->ready = 0;
    }
}

unsigned
dispatchTimers(EventLoopData *eld) {
    if (!eld->timers_count || eld->timers[0].trigger_at == MONOTONIC_T_MAX) return 0;
    static struct { timer_callback_func func; id_type id; void* data; bool repeats; } dispatches[sizeof(eld->timers)/sizeof(eld->timers[0])];
    unsigned num_dispatches = 0;
    monotonic_t now = monotonic();
    for (nfds_t i = 0; i < eld->timers_count && eld->timers[i].trigger_at <= now; i++) {
        eld->timers[i].trigger_at = now + eld->timers[i].interval;
        dispatches[num_dispatches].func = eld->timers[i].callback;
        dispatches[num_dispatches].id = eld->timers[i].id;
        dispatches[num_dispatches].data = eld->timers[i].callback_data;
        dispatches[num_dispatches].repeats = eld->timers[i].repeats;
        num_dispatches++;
    }
    // we dispatch separately so that the callbacks can modify timers
    for (unsigned i = 0; i < num_dispatches; i++) {
        dispatches[i].func(dispatches[i].id, dispatches[i].data);
        if (!dispatches[i].repeats) {
            removeTimer(eld, dispatches[i].id);
        }
    }
    if (num_dispatches) update_timers(eld);
    return num_dispatches;
}

static void
drain_wakeup_fd(int fd, EventLoopData* eld) {
    static char drain_buf[64];
    eld->wakeup_data_read = false;
    while(true) {
        ssize_t ret = read(fd, drain_buf, sizeof(drain_buf));
        if (ret < 0) {
            if (errno == EINTR) continue;
            break;
        }
        if (ret > 0) { eld->wakeup_data_read = true; continue; }
        break;
    }
}

static void
mark_wakep_fd_ready(int fd UNUSED, int events UNUSED, void *data) {
    ((EventLoopData*)(data))->wakeup_fd_ready = true;
}

bool
initPollData(EventLoopData *eld, int display_fd) {
    if (!addWatch(eld, "display", display_fd, POLLIN, 1, NULL, NULL)) return false;
#ifdef HAS_EVENT_FD
    eld->wakeupFd = eventfd(0, EFD_CLOEXEC | EFD_NONBLOCK);
    if (eld->wakeupFd == -1) return false;
    const int wakeup_fd = eld->wakeupFd;
#else
    if (pipe2(eld->wakeupFds, O_CLOEXEC | O_NONBLOCK) != 0) return false;
    const int wakeup_fd = eld->wakeupFds[0];
#endif
    if (!addWatch(eld, "wakeup", wakeup_fd, POLLIN, 1, mark_wakep_fd_ready, eld)) return false;
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

#ifndef HAS_EVENT_FD
static void
closeFds(int *fds, size_t count) {
    while(count--) {
        if (*fds > 0) {
            close(*fds);
            *fds = -1;
        }
        fds++;
    }
}
#endif

void
finalizePollData(EventLoopData *eld) {
#ifdef HAS_EVENT_FD
    close(eld->wakeupFd); eld->wakeupFd = -1;
#else
    closeFds(eld->wakeupFds, arraysz(eld->wakeupFds));
#endif
}

int
pollForEvents(EventLoopData *eld, monotonic_t timeout, watch_callback_func display_callback) {
    int read_ok = 0;
    timeout = prepareForPoll(eld, timeout);
    EVDBG("pollForEvents final timeout: %.3f", monotonic_t_to_s_double(timeout));
    int result;
    monotonic_t end_time = monotonic() + timeout;
    eld->wakeup_fd_ready = false;

    while(1) {
        if (timeout >= 0) {
            errno = 0;
            result = pollWithTimeout(eld->fds, eld->watches_count, timeout);
            int saved_errno = errno;
            if (display_callback) display_callback(result, eld->fds[0].revents && eld->watches[0].events, NULL);
            dispatchTimers(eld);
            if (result > 0) {
                dispatchEvents(eld);
                read_ok = eld->watches[0].ready;
                break;
            }
            timeout = end_time - monotonic();
            if (timeout <= 0) break;
            if (result < 0 && (saved_errno == EINTR || saved_errno == EAGAIN)) continue;
            break;
        } else {
            errno = 0;
            result = poll(eld->fds, eld->watches_count, -1);
            int saved_errno = errno;
            if (display_callback) display_callback(result, eld->fds[0].revents && eld->watches[0].events, NULL);
            dispatchTimers(eld);
            if (result > 0) {
                dispatchEvents(eld);
                read_ok = eld->watches[0].ready;
            }
            if (result < 0 && (saved_errno == EINTR || saved_errno == EAGAIN)) continue;
            break;
        }
    }
    return read_ok;
}

// Duplicate a UTF-8 encoded string
// but cut it so that it has at most max_length bytes plus the null byte.
// This does not take combining characters into account.
GLFWAPI char* utf_8_strndup(const char* source, size_t max_length) {
    if (!source) return NULL;
    size_t length = strnlen(source, max_length);
    if (length >= max_length) {
        for (length = max_length; length > 0; length--) {
            if ((source[length] & 0xC0) != 0x80) break;
        }
    }

    char* result = malloc(length + 1);
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
int createAnonymousFile(off_t size) {
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
    const char* path;
    char* name;

    path = getenv("XDG_RUNTIME_DIR");
    if (!path)
    {
        errno = ENOENT;
        return -1;
    }

    name = calloc(strlen(path) + sizeof(template), 1);
    strcpy(name, path);
    strcat(name, template);

    fd = createTmpfileCloexec(name);

    free(name);

    if (fd < 0)
        return -1;
#endif
    // posix_fallocate does not work on SHM descriptors
    ret = shm_anon ? ftruncate(fd, size) : posix_fallocate(fd, 0, size);
    if (ret != 0)
    {
        close(fd);
        errno = ret;
        return -1;
    }
    return fd;
}
