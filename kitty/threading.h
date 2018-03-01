/*
 * Copyright (C) 2018 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#ifdef __APPLE__
#include <pthread.h>
// I cant figure out how to get pthread.h to include this definition on macOS. MACOSX_DEPLOYMENT_TARGET does not work.
extern int pthread_setname_np(const char *name);
#else
// Need _GNU_SOURCE for pthread_setname_np on linux
#define _GNU_SOURCE
#include <pthread.h>
#undef _GNU_SOURCE
#endif
#include <stdio.h>

static inline void
set_thread_name(const char *name) {
    int ret = 0;
#ifdef __APPLE__
    ret = pthread_setname_np(name);
#else
    ret = pthread_setname_np(pthread_self(), name);
#endif
    if (ret != 0) perror("Failed to set thread name");
}
