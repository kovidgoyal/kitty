/*
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef void(*timer_callback_func)(id_type, void*);
typedef void(*timer_cleanup_func)(id_type, void*);

typedef struct {
    id_type id;
    double interval, trigger_at;
    timer_callback_func callback;
    timer_cleanup_func cleanup;
    void *callback_data;
    const char *name;
} Timer;


typedef struct {
    nfds_t timers_count;
    Timer timers[128];
} EventLoopData;


double prepare_for_poll(EventLoopData *eld, double timeout);
id_type add_timer(EventLoopData *eld, const char *name, double interval, int enabled, timer_callback_func cb, void *cb_data, timer_cleanup_func cleanup);
void remove_timer(EventLoopData *eld, id_type timer_id);
void remove_all_timers(EventLoopData *eld);
void toggle_time(EventLoopData *eld, id_type timer_id, int enabled);
void change_timer_interval(EventLoopData *eld, id_type timer_id, double interval);
unsigned int dispatch_timers(EventLoopData *eld);
