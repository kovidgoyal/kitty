/*
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "internal.h"
#include <stdatomic.h>

#ifndef GLFW_LOOP_BACKEND
#define GLFW_LOOP_BACKEND x11
#endif

static volatile atomic_int keep_going = 0, tick_callback_requested = 0;

void _glfwPlatformRequestTickCallback() {
    EVDBG("tick_callback requested");
    tick_callback_requested = 1;
}

void _glfwPlatformStopMainLoop(void) {
    if (keep_going) {
        keep_going = 0;
        _glfwPlatformPostEmptyEvent();
    }
}

static inline void
dispatch_tick_callbacks(GLFWtickcallback tick_callback, void *data) {
    while (tick_callback_requested) {
        EVDBG("Calling tick callback");
        tick_callback_requested = 0;
        tick_callback(data);
    }
}

void _glfwPlatformRunMainLoop(GLFWtickcallback tick_callback, void* data) {
    keep_going = 1;
    tick_callback_requested = 0;
    while(keep_going) {
        EVDBG("loop tick, tick_callback_requested: %d", tick_callback_requested);
        dispatch_tick_callbacks(tick_callback, data);
        _glfwPlatformWaitEvents();
    }
    EVDBG("main loop exiting");
}

unsigned long long _glfwPlatformAddTimer(double interval, bool repeats, GLFWuserdatafreefun callback, void *callback_data, GLFWuserdatafreefun free_callback) {
    return addTimer(&_glfw.GLFW_LOOP_BACKEND.eventLoopData, "user timer", interval, 1, repeats, callback, callback_data, free_callback);
}

void _glfwPlatformRemoveTimer(unsigned long long timer_id) {
    removeTimer(&_glfw.GLFW_LOOP_BACKEND.eventLoopData, timer_id);
}

void _glfwPlatformUpdateTimer(unsigned long long timer_id, double interval, bool enabled) {
    changeTimerInterval(&_glfw.GLFW_LOOP_BACKEND.eventLoopData, timer_id, interval);
    toggleTimer(&_glfw.GLFW_LOOP_BACKEND.eventLoopData, timer_id, enabled);
}
