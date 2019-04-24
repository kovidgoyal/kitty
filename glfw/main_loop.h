/*
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "internal.h"

#ifndef GLFW_LOOP_BACKEND
#define GLFW_LOOP_BACKEND x11
#endif

static GLFWbool keep_going = GLFW_FALSE, tick_callback_requested = GLFW_FALSE;

void _glfwPlatformRequestTickCallback() {
    tick_callback_requested = GLFW_TRUE;
}

void _glfwPlatformStopMainLoop(void) {
    if (keep_going) {
        keep_going = GLFW_FALSE;
        _glfwPlatformPostEmptyEvent();
    }
}

void _glfwPlatformRunMainLoop(GLFWtickcallback callback, void* data) {
    keep_going = GLFW_TRUE;
    tick_callback_requested = GLFW_FALSE;
    while(keep_going) {
		EVDBG("tick_callback_requested: %d", tick_callback_requested);
        while (tick_callback_requested) {
            tick_callback_requested = GLFW_FALSE;
            callback(data);
        }
        _glfwPlatformWaitEvents();
    }
}

unsigned long long _glfwPlatformAddTimer(double interval, bool repeats, GLFWuserdatafreefun callback, void *callback_data, GLFWuserdatafreefun free_callback) {
    return addTimer(&_glfw.GLFW_LOOP_BACKEND.eventLoopData, "user timer", interval, 1, repeats, callback, callback_data, free_callback);
}

void _glfwPlatformRemoveTimer(unsigned long long timer_id) {
    removeTimer(&_glfw.GLFW_LOOP_BACKEND.eventLoopData, timer_id);
}

void _glfwPlatformUpdateTimer(unsigned long long timer_id, double interval, GLFWbool enabled) {
    changeTimerInterval(&_glfw.GLFW_LOOP_BACKEND.eventLoopData, timer_id, interval);
    toggleTimer(&_glfw.GLFW_LOOP_BACKEND.eventLoopData, timer_id, enabled);
}
