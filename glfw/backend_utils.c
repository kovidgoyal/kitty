/*
 * backend_utils.c
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define _GNU_SOURCE
#include "backend_utils.h"

#include <string.h>
#include <errno.h>

#ifdef __NetBSD__
#define ppoll pollts
#endif

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

void
addWatch(EventLoopData *eld, int fd, int events, int enabled, watch_callback_func cb, void *cb_data) {
    removeWatch(eld, fd);
    if (eld->watches_count >= sizeof(eld->watches)/sizeof(eld->watches[0])) return;
    Watch *w = eld->watches + eld->watches_count++;
    w->fd = fd; w->events = events; w->enabled = enabled;
    w->callback = cb;
    w->callback_data = cb_data;
    update_fds(eld);
}

void
removeWatch(EventLoopData *eld, int fd) {
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        if (eld->watches[i].fd == fd) {
            eld->watches_count--;
            if (i < eld->watches_count) {
                memmove(eld->watches + i, eld->watches + i + 1, sizeof(eld->watches[0]) * (eld->watches_count - i));
            }
            update_fds(eld);
            break;
        }
    }
}

void
toggleWatch(EventLoopData *eld, int fd, int enabled) {
    for (nfds_t i = 0; i < eld->watches_count; i++) {
        if (eld->watches[i].fd == fd) {
            if (eld->watches[i].enabled != enabled) {
                eld->watches[i].enabled = enabled;
                update_fds(eld);
            }
            break;
        }
    }
}

void
prepareForPoll(EventLoopData *eld) {
    for (nfds_t i = 0; i < eld->fds_count; i++) eld->fds[i].revents = 0;
}

int
pollWithTimeout(struct pollfd *fds, nfds_t nfds, double timeout) {
    const long seconds = (long) timeout;
    const long nanoseconds = (long) ((timeout - seconds) * 1e9);
    struct timespec tv = { seconds, nanoseconds };
    return ppoll(fds, nfds, &tv, NULL);
}

void
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
