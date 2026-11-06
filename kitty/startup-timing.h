/*
 * startup-timing.h
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

// Printing of the time taken by the phases of startup, for --debug-startup.
// Times are from monotonic_clock_now() and are printed relative to when the
// process started. Must only be called from the main thread, work done in
// other threads is reported with startup_timing_thread(). Printing stops
// after the first frame is presented.

#include "monotonic.h"
#include <stdbool.h>

bool startup_timing_enabled(void);
void startup_timing(const char *fmt, ...) __attribute__((format(printf, 1, 2)));
// Report work done in a thread between start and end
void startup_timing_thread(const char *name, monotonic_t start, monotonic_t end);
// Called when a frame is presented, reports the first one and stops printing
void startup_timing_frame_presented(void);
