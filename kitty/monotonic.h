/*
 * monotonic.h
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once


#include <stdint.h>

#define MONOTONIC_T_MAX INT64_MAX
#define MONOTONIC_T_MIN INT64_MIN
#define MONOTONIC_T_1e6 1000000ll
#define MONOTONIC_T_1e3 1000ll
#define MONOTONIC_T_1e9 1000000000ll

typedef int64_t monotonic_t;

static inline monotonic_t
s_double_to_monotonic_t(double time) {
    return (monotonic_t)(time * 1e9);
}

static inline monotonic_t
ms_double_to_monotonic_t(double time) {
    return (monotonic_t)(time * 1e6);
}

static inline monotonic_t
s_to_monotonic_t(monotonic_t time) {
    return time * MONOTONIC_T_1e9;
}

static inline monotonic_t
ms_to_monotonic_t(monotonic_t time) {
    return time * MONOTONIC_T_1e6;
}

static inline int
monotonic_t_to_ms(monotonic_t time) {
    return (int)(time / MONOTONIC_T_1e6);
}

static inline int
monotonic_t_to_ms_ceil(monotonic_t time) {
    return (int)((time + MONOTONIC_T_1e6 - 1) / MONOTONIC_T_1e6);
}

static inline int
monotonic_t_to_us(monotonic_t time) {
    return (int)(time / MONOTONIC_T_1e3);
}


static inline double
monotonic_t_to_s_double(monotonic_t time) {
    return ((double)time) / 1e9;
}

extern monotonic_t monotonic_start_time;
extern monotonic_t monotonic_(void);

static inline monotonic_t
monotonic(void) {
    return monotonic_() - monotonic_start_time;
}

static inline void
init_monotonic(void) {
    monotonic_start_time = monotonic_();
}

extern int timed_debug_print(const char *fmt, ...) __attribute__((format(printf, 1, 2)));

// The current time of the clock used by monotonic(). This is used by both the
// launcher and the fast_data_types module so that times can be compared.
#include <time.h>
static inline monotonic_t
monotonic_clock_now(void) {
    struct timespec ts = {0};
#ifdef CLOCK_HIGHRES
    clock_gettime(CLOCK_HIGHRES, &ts);
#elif CLOCK_MONOTONIC_RAW
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
#else
    clock_gettime(CLOCK_MONOTONIC, &ts);
#endif
    return ((monotonic_t)ts.tv_sec * MONOTONIC_T_1e9) + (monotonic_t)ts.tv_nsec;
}

#ifdef MONOTONIC_IMPLEMENTATION
#include <time.h>
#include <stdarg.h>
#include <stdio.h>
#include <string.h>

monotonic_t monotonic_start_time = 0;

monotonic_t
monotonic_(void) {
    return monotonic_clock_now();
}

int
timed_debug_print(const char *fmt, ...) {
    int result;
    static int starting_print = 1;
    if (starting_print) fprintf(stderr, "[%.3f] ", monotonic_t_to_s_double(monotonic()));
    va_list args;
    va_start(args, fmt);
    result = vfprintf(stderr, fmt, args);
    va_end(args);
    starting_print = fmt && strchr(fmt, '\n') != NULL;
    return result;
}
#endif
