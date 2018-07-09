/*
 * backend_utils.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define _GNU_SOURCE
#include "backend_utils.h"

#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <float.h>
#include <time.h>

#ifdef __NetBSD__
#define ppoll pollts
#endif

static inline double
monotonic() {
    struct timespec ts = {0};
#ifdef CLOCK_HIGHRES
	clock_gettime(CLOCK_HIGHRES, &ts);
#elif CLOCK_MONOTONIC_RAW
	clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
#else
	clock_gettime(CLOCK_MONOTONIC, &ts);
#endif
	return (((double)ts.tv_nsec) / 1e9) + (double)ts.tv_sec;
}

void
update_fds(EventLoopData *eld) {
    eld->fds_count = 0;
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        Watch *w = eld->watches + i;
        if (w->enabled) {
            eld->fds[eld->fds_count].fd = w->fd;
            eld->fds[eld->fds_count].events = w->events;
            eld->fds_count++;
        }
    }
}

static id_type watch_counter = 0;

id_type
addWatch(EventLoopData *eld, int fd, int events, int enabled, watch_callback_func cb, void *cb_data) {
    if (eld->watches_count >= sizeof(eld->watches)/sizeof(eld->watches[0])) return 0;
    Watch *w = eld->watches + eld->watches_count++;
    w->fd = fd; w->events = events; w->enabled = enabled;
    w->callback = cb;
    w->callback_data = cb_data;
    w->id = ++watch_counter;
    update_fds(eld);
    return w->id;
}

#define removeX(which, item_id, update_func) {\
    for (nfds_t i = 0; i < eld->which##_count; i++) { \
        if (eld->which[i].id == item_id) { \
            eld->which##_count--; \
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

static inline void
update_timers(EventLoopData *eld) {
    if (eld->timers_count > 1) qsort(eld->timers, eld->timers_count, sizeof(eld->timers[0]), compare_timers);
}

id_type
addTimer(EventLoopData *eld, double interval, int enabled, timer_callback_func cb, void *cb_data) {
    if (eld->timers_count >= sizeof(eld->timers)/sizeof(eld->timers[0])) return 0;
    Timer *t = eld->timers + eld->timers_count++;
    t->interval = interval;
    t->trigger_at = enabled ? monotonic() + interval : DBL_MAX;
    t->callback = cb;
    t->callback_data = cb_data;
    t->id = ++timer_counter;
    update_timers(eld);
    return t->id;
}

void
removeTimer(EventLoopData *eld, id_type timer_id) {
    removeX(timers, timer_id, update_timers);
}

void
toggleTimer(EventLoopData *eld, id_type timer_id, int enabled) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].id == timer_id) {
            double trigger_at = enabled ? (monotonic() + eld->timers[i].interval) : DBL_MAX;
            if (trigger_at != eld->timers[i].trigger_at) {
                eld->timers[i].trigger_at = trigger_at;
                update_timers(eld);
            }
            break;
        }
    }
}

void
changeTimerInterval(EventLoopData *eld, id_type timer_id, double interval) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].id == timer_id) {
            eld->timers[i].interval = interval;
            break;
        }
    }
}


double
prepareForPoll(EventLoopData *eld, double timeout) {
    for (nfds_t i = 0; i < eld->fds_count; i++) eld->fds[i].revents = 0;
    if (!eld->timers_count || eld->timers[0].trigger_at == DBL_MAX) return timeout;
    double now = monotonic(), next_repeat_at = eld->timers[0].trigger_at;
    if (timeout < 0 || now + timeout > next_repeat_at) {
        timeout = next_repeat_at <= now ? 0 : next_repeat_at - now;
    }
    return timeout;
}

int
pollWithTimeout(struct pollfd *fds, nfds_t nfds, double timeout) {
    const long seconds = (long) timeout;
    const long nanoseconds = (long) ((timeout - seconds) * 1e9);
    struct timespec tv = { seconds, nanoseconds };
    return ppoll(fds, nfds, &tv, NULL);
}

static void
dispatchEvents(EventLoopData *eld) {
    for (unsigned w = 0, f = 0; f < eld->fds_count; f++) {
        while(eld->watches[w].fd != eld->fds[f].fd) w++;
        Watch *ww = eld->watches + w;
        if (eld->fds[f].revents & ww->events) {
            ww->ready = 1;
            if (ww->callback) ww->callback(ww->fd, eld->fds[f].revents, ww->callback_data);
        } else ww->ready = 0;
    }
}

unsigned
dispatchTimers(EventLoopData *eld) {
    if (!eld->timers_count || eld->timers[0].trigger_at == DBL_MAX) return 0;
    static struct { timer_callback_func func; id_type id; void* data; } dispatches[sizeof(eld->timers)/sizeof(eld->timers[0])];
    unsigned num_dispatches = 0;
    double now = monotonic();
    for (nfds_t i = 0; i < eld->timers_count && eld->timers[i].trigger_at <= now; i++) {
        eld->timers[i].trigger_at = now + eld->timers[i].interval;
        dispatches[num_dispatches].func = eld->timers[i].callback;
        dispatches[num_dispatches].id = eld->timers[i].id;
        dispatches[num_dispatches].data = eld->timers[i].callback_data;
        num_dispatches++;
    }
    // we dispatch separately so that the callbacks can modify timers
    for (unsigned i = 0; i < num_dispatches; i++) {
        dispatches[i].func(dispatches[i].id, dispatches[i].data);
    }
    if (num_dispatches) update_timers(eld);
    return num_dispatches;
}

static void
drain_wakeup_fd(int fd, int events, void* data) {
    static char drain_buf[64];
    while(read(fd, drain_buf, sizeof(drain_buf)) < 0 && errno == EINTR);
}

void
initPollData(EventLoopData *eld, int wakeup_fd, int display_fd) {
    addWatch(eld, display_fd, POLLIN, 1, NULL, NULL);
    addWatch(eld, wakeup_fd, POLLIN, 1, drain_wakeup_fd, NULL);
}


int
pollForEvents(EventLoopData *eld, double timeout) {
    int read_ok = 0;
    timeout = prepareForPoll(eld, timeout);
    int result;
    double end_time = monotonic() + timeout;

    while(1) {
        if (timeout >= 0) {
            result = pollWithTimeout(eld->fds, eld->fds_count, timeout);
            dispatchTimers(eld);
            if (result > 0) {
                dispatchEvents(eld);
                read_ok = eld->watches[0].ready;
                break;
            }
            timeout = end_time - monotonic();
            if (timeout <= 0) break;
            if (result < 0 && (errno == EINTR || errno == EAGAIN)) continue;
            break;
        } else {
            result = poll(eld->fds, eld->fds_count, -1);
            dispatchTimers(eld);
            if (result > 0) {
                dispatchEvents(eld);
                read_ok = eld->watches[0].ready;
            }
            if (result < 0 && (errno == EINTR || errno == EAGAIN)) continue;
            break;
        }
    }
    return read_ok;
}

void
closeFds(int *fds, size_t count) {
    while(count--) {
        if (*fds > 0) {
            close(*fds);
            *fds = -1;
        }
        fds++;
    }
}
