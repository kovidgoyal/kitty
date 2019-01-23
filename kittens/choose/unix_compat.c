/*
 * unix_compat.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "choose-data-types.h"
#include <unistd.h>
#include <pthread.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>

#ifdef __APPLE__
#ifndef _SC_NPROCESSORS_ONLN
#define _SC_NPROCESSORS_ONLN 58
#endif
#endif

int
cpu_count() {
    return sysconf(_SC_NPROCESSORS_ONLN);
}


void*
alloc_threads(size_t num_threads) {
    return calloc(num_threads, sizeof(pthread_t));
}

bool
start_thread(void* threads, size_t i, void *(*start_routine) (void *), void *arg) {
    int rc;
    if ((rc = pthread_create(((pthread_t*)threads) + i, NULL, start_routine, arg))) {
        fprintf(stderr, "Failed to create thread, with error: %s\n", strerror(rc));
        return false;
    }
    return true;
}

void
wait_for_thread(void *threads, size_t i) {
    pthread_join(((pthread_t*)(threads))[i], NULL);
}

void
free_threads(void *threads) {
    free(threads);
}
