/*
 * timers.c
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "timers.h"
#include <float.h>

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
add_timer(EventLoopData *eld, const char *name, double interval, int enabled, timer_callback_func cb, void *cb_data, timer_cleanup_func cleanup) {
    if (eld->timers_count >= sizeof(eld->timers)/sizeof(eld->timers[0])) {
        fprintf(stderr, "Too many timers added\n");
        return 0;
    }
    Timer *t = eld->timers + eld->timers_count++;
    t->interval = interval;
    t->name = name;
    t->trigger_at = enabled ? monotonic() + interval : DBL_MAX;
    t->callback = cb;
    t->callback_data = cb_data;
    t->cleanup = cleanup;
    t->id = ++timer_counter;
    update_timers(eld);
    return t->id;
}


void
remove_timer(EventLoopData *eld, id_type timer_id) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].id == timer_id) {
            if (eld->timers[i].cleanup) eld->timers[i].cleanup(timer_id, eld->timers[i].callback_data);
            remove_i_from_array(eld->timers, i, eld->timers_count);
            update_timers(eld);
            break;
        }
    }
}

void
remove_all_timers(EventLoopData *eld) {
    while (eld->timers_count) {
        eld->timers_count--;
        if (eld->timers[eld->timers_count].cleanup) eld->timers[eld->timers_count].cleanup(eld->timers[eld->timers_count].id, eld->timers[eld->timers_count].callback_data);
    }
}

void
toggle_timer(EventLoopData *eld, id_type timer_id, int enabled) {
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
change_timer_interval(EventLoopData *eld, id_type timer_id, double interval) {
    for (nfds_t i = 0; i < eld->timers_count; i++) {
        if (eld->timers[i].id == timer_id) {
            eld->timers[i].interval = interval;
            break;
        }
    }
}


double
prepare_for_poll(EventLoopData *eld, double timeout) {
    if (!eld->timers_count || eld->timers[0].trigger_at == DBL_MAX) return timeout;
    double now = monotonic(), next_repeat_at = eld->timers[0].trigger_at;
    if (timeout < 0 || now + timeout > next_repeat_at) {
        timeout = next_repeat_at <= now ? 0 : next_repeat_at - now;
    }
    return timeout;
}

unsigned int
dispatch_timers(EventLoopData *eld) {
    if (!eld->timers_count || eld->timers[0].trigger_at == DBL_MAX) return 0;
    static struct { timer_callback_func func; id_type id; void* data; } dispatches[sizeof(eld->timers)/sizeof(eld->timers[0])];
    unsigned int num_dispatches = 0;
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
