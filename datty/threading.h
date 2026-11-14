/*
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdio.h>
#include <pthread.h>
#if defined(__FreeBSD__) || defined(__OpenBSD__)
#define FREEBSD_SET_NAME
#endif
#if defined(__APPLE__)
// I can't figure out how to get pthread.h to include this definition on macOS. MACOSX_DEPLOYMENT_TARGET does not work.
extern int pthread_setname_np(const char *name);
#elif defined(FREEBSD_SET_NAME)
// Function has a different name on FreeBSD
void pthread_set_name_np(pthread_t tid, const char *name);
#else
// Need _GNU_SOURCE for pthread_setname_np on linux and that causes other issues on systems with old glibc
extern int pthread_setname_np(pthread_t, const char *name);
#endif

static inline void
set_thread_name(const char *name) {
    int ret;
#if defined(__APPLE__)
    ret = pthread_setname_np(name);
#elif defined(FREEBSD_SET_NAME)
    pthread_set_name_np(pthread_self(), name);
    ret = 0;
#else
    ret = pthread_setname_np(pthread_self(), name);
#endif
    if (ret != 0) perror("Failed to set thread name");
}
