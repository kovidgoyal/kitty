/*
 * Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdio.h>
#include <signal.h>
#include <stdlib.h>
#include <unistd.h>

#if __has_include(<execinfo.h>)
#include <execinfo.h>

static inline void
print_stack_trace(void) {
    void *array[256];
    size_t size;

    // get void*'s for all entries on the stack
    size = backtrace(array, 256);

    // print out all the frames to stderr
    backtrace_symbols_fd(array, size, STDERR_FILENO);
}
#else
static inline void
print_stack_trace(void) {
    fprintf(stderr, "Stack trace functionality not available.\n");
}
#endif
