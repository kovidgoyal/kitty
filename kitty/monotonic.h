/*
 * monotonic.h
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once


#include <stdint.h>
#include <time.h>

#define MONOTONIC_T_MAX INT64_MAX
#define MONOTONIC_T_MIN INT64_MIN

typedef int64_t monotonic_t;

static inline monotonic_t calc_nano_time(struct timespec time) {
    int64_t result = (monotonic_t)time.tv_sec;
    result *= 1000LL;
    result *= 1000LL;
    result *= 1000LL;
    result += (monotonic_t)time.tv_nsec;
    return result;
}

static inline struct timespec calc_time(monotonic_t nsec) {
    struct timespec result;
    result.tv_sec  = nsec / (1000LL * 1000LL * 1000LL);
    result.tv_nsec = nsec % (1000LL * 1000LL * 1000LL);
    return result;
}

static inline monotonic_t s_double_to_monotonic_t(double time) {
    time *= 1000.0;
    time *= 1000.0;
    time *= 1000.0;
    return (monotonic_t)time;
}

static inline monotonic_t ms_double_to_monotonic_t(double time) {
    time *= 1000.0;
    time *= 1000.0;
    return (monotonic_t)time;
}

static inline monotonic_t s_to_monotonic_t(monotonic_t time) {
    return time * 1000ll * 1000ll * 1000ll;
}

static inline monotonic_t ms_to_monotonic_t(monotonic_t time) {
    return time * 1000ll * 1000ll;
}

static inline int monotonic_t_to_ms(monotonic_t time) {
    return (int)(time / 1000ll / 1000ll);
}

static inline double monotonic_t_to_s_double(monotonic_t time) {
    return (double)time / 1000.0 / 1000.0 / 1000.0;
}

#ifdef MONOTONIC_START_MODULE
monotonic_t monotonic_start_time = 0;
#else
extern monotonic_t monotonic_start_time;
#endif


static inline monotonic_t monotonic_(void) {
    struct timespec ts = {0};
#ifdef CLOCK_HIGHRES
    clock_gettime(CLOCK_HIGHRES, &ts);
#elif CLOCK_MONOTONIC_RAW
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
#else
    clock_gettime(CLOCK_MONOTONIC, &ts);
#endif
    return calc_nano_time(ts);
}

static inline monotonic_t monotonic(void) {
	return monotonic_() - monotonic_start_time;
}

static inline void init_monotonic(void) {
	monotonic_start_time = monotonic_();
}
