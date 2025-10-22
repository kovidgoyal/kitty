/*
 * cocoa_displaylink.m
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// CVDisplayLink is deprecated replace with CADisplayLink via [NSScreen displayLink] once base macOS version is 14
#pragma clang diagnostic ignored "-Wdeprecated-declarations"

#include "internal.h"
#include <CoreVideo/CVDisplayLink.h>
#include <os/lock.h>

#define DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL s_to_monotonic_t(30ll)
#define MAX_NUM_OF_DISPLAYS 256

typedef struct _GLFWDisplayLinkNS
{
    CVDisplayLinkRef displayLink;
    CGDirectDisplayID displayID;
    monotonic_t lastRenderFrameRequestedAt, first_unserviced_render_frame_request_at;
    bool pending_dispatch;
} _GLFWDisplayLinkNS;

static struct {
    _GLFWDisplayLinkNS entries[MAX_NUM_OF_DISPLAYS];
    os_unfair_lock locks[MAX_NUM_OF_DISPLAYS];
    bool locks_initialized[MAX_NUM_OF_DISPLAYS];
    size_t count;
} displayLinks = {0};

static inline size_t
index_for_entry(_GLFWDisplayLinkNS *entry) {
    return (size_t)(entry - displayLinks.entries);
}

static inline os_unfair_lock*
lock_for_entry(_GLFWDisplayLinkNS *entry) {
    return &displayLinks.locks[index_for_entry(entry)];
}

static CGDirectDisplayID
displayIDForWindow(_GLFWwindow *w) {
    NSWindow *nw = w->ns.object;
    NSDictionary *dict = [nw.screen deviceDescription];
    NSNumber *displayIDns = dict[@"NSScreenNumber"];
    if (displayIDns) return [displayIDns unsignedIntValue];
    return (CGDirectDisplayID)-1;
}

void
_glfwClearDisplayLinks(void) {
    for (size_t i = 0; i < displayLinks.count; i++) {
        _GLFWDisplayLinkNS *entry = &displayLinks.entries[i];
        os_unfair_lock *lock = &displayLinks.locks[i];
        os_unfair_lock_lock(lock);
        CVDisplayLinkRef link = entry->displayLink;
        entry->displayLink = NULL;
        entry->displayID = (CGDirectDisplayID)0;
        entry->lastRenderFrameRequestedAt = 0;
        entry->first_unserviced_render_frame_request_at = 0;
        entry->pending_dispatch = false;
        os_unfair_lock_unlock(lock);
        if (link) {
            CVDisplayLinkStop(link);
            CVDisplayLinkRelease(link);
        }
    }
    displayLinks.count = 0;
}

static void _glfwDispatchRenderFrame(void *);

static CVReturn
displayLinkCallback(
        CVDisplayLinkRef displayLink UNUSED,
        const CVTimeStamp* now UNUSED, const CVTimeStamp* outputTime UNUSED,
        CVOptionFlags flagsIn UNUSED, CVOptionFlags* flagsOut UNUSED, void* userInfo) {
    _GLFWDisplayLinkNS *entry = (_GLFWDisplayLinkNS *)userInfo;
    if (entry) {
        os_unfair_lock *lock = lock_for_entry(entry);
        os_unfair_lock_lock(lock);
        const bool should_dispatch = entry->first_unserviced_render_frame_request_at &&
            !entry->pending_dispatch;
        CGDirectDisplayID displayID = entry->displayID;
        if (should_dispatch) entry->pending_dispatch = true;
        os_unfair_lock_unlock(lock);
        if (should_dispatch) dispatch_async_f(dispatch_get_main_queue(), (void*)(uintptr_t)displayID, _glfwDispatchRenderFrame);
    }
    return kCVReturnSuccess;
}

static void
_glfw_create_cv_display_link(_GLFWDisplayLinkNS *entry) {
    CVDisplayLinkCreateWithCGDisplay(entry->displayID, &entry->displayLink);
    if (entry->displayLink) CVDisplayLinkSetOutputCallback(entry->displayLink, &displayLinkCallback, entry);
}

unsigned
_glfwCreateDisplayLink(CGDirectDisplayID displayID) {
    for (unsigned i = 0; i < displayLinks.count; i++) {
        os_unfair_lock *existing_lock = &displayLinks.locks[i];
        os_unfair_lock_lock(existing_lock);
        const bool already_created = displayLinks.entries[i].displayID == displayID;
        os_unfair_lock_unlock(existing_lock);
        if (already_created) return i;
    }
    if (displayLinks.count >= MAX_NUM_OF_DISPLAYS) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Too many monitors cannot create display link");
        return displayLinks.count;
    }
    unsigned idx = displayLinks.count;
    _GLFWDisplayLinkNS *entry = &displayLinks.entries[idx];
    if (!displayLinks.locks_initialized[idx]) {
        displayLinks.locks[idx] = OS_UNFAIR_LOCK_INIT;
        displayLinks.locks_initialized[idx] = true;
    }
    os_unfair_lock *lock = &displayLinks.locks[idx];
    os_unfair_lock_lock(lock);
    memset(entry, 0, sizeof(entry[0]));
    entry->displayID = displayID;
    displayLinks.count++;
    _glfw_create_cv_display_link(entry);
    os_unfair_lock_unlock(lock);
    return idx;
}

static unsigned long long display_link_shutdown_timer = 0;

static void
_glfwShutdownCVDisplayLink(unsigned long long timer_id UNUSED, void *user_data UNUSED) {
    display_link_shutdown_timer = 0;
    for (size_t i = 0; i < displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &displayLinks.entries[i];
        os_unfair_lock *lock = &displayLinks.locks[i];
        os_unfair_lock_lock(lock);
        CVDisplayLinkRef link = dl->displayLink;
        if (link) CVDisplayLinkRetain(link);
        dl->lastRenderFrameRequestedAt = 0;
        dl->first_unserviced_render_frame_request_at = 0;
        dl->pending_dispatch = false;
        os_unfair_lock_unlock(lock);
        if (link) {
            CVDisplayLinkStop(link);
            CVDisplayLinkRelease(link);
        }
    }
}

void
_glfwRequestRenderFrame(_GLFWwindow *w) {
    CGDirectDisplayID displayID = displayIDForWindow(w);
    if (display_link_shutdown_timer) {
        _glfwPlatformUpdateTimer(display_link_shutdown_timer, DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL, true);
    } else {
        display_link_shutdown_timer = _glfwPlatformAddTimer(DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL, false, _glfwShutdownCVDisplayLink, NULL, NULL);
    }
    monotonic_t now = glfwGetTime();
    bool found_display_link = false;
    _GLFWDisplayLinkNS *dl = NULL;
    for (size_t i = 0; i < displayLinks.count; i++) {
        dl = &displayLinks.entries[i];
        bool need_start = false, need_stop = false, need_recreate = false;
        bool retain_link = false;
        CVDisplayLinkRef link = NULL;
        CVDisplayLinkRef new_link = NULL;
        bool new_link_retained = false;
        os_unfair_lock *lock = &displayLinks.locks[i];
        os_unfair_lock_lock(lock);
        link = dl->displayLink;
        if (dl->displayID == displayID) {
            found_display_link = true;
            monotonic_t first_unserviced = dl->first_unserviced_render_frame_request_at;
            dl->lastRenderFrameRequestedAt = now;
            if (!first_unserviced) {
                dl->first_unserviced_render_frame_request_at = now;
                first_unserviced = now;
            }
            dl->pending_dispatch = false;
            if (link) {
                if (!CVDisplayLinkIsRunning(link)) {
                    need_start = true;
                    retain_link = true;
                } else if (now - first_unserviced > s_to_monotonic_t(1ll)) {
                    need_recreate = true;
                    dl->first_unserviced_render_frame_request_at = now;
                    dl->displayLink = NULL;
                }
            }
        } else if (link && dl->lastRenderFrameRequestedAt && now - dl->lastRenderFrameRequestedAt >= DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL) {
            need_stop = true;
            retain_link = true;
            dl->lastRenderFrameRequestedAt = 0;
            dl->first_unserviced_render_frame_request_at = 0;
            dl->pending_dispatch = false;
        }
        if (retain_link && link) CVDisplayLinkRetain(link);
        os_unfair_lock_unlock(lock);
        if (need_recreate && link) {
            CVDisplayLinkStop(link);
            CVDisplayLinkRelease(link);
            os_unfair_lock_lock(lock);
            _glfw_create_cv_display_link(dl);
            new_link = dl->displayLink;
            if (new_link) {
                CVDisplayLinkRetain(new_link);
                new_link_retained = true;
            }
            dl->pending_dispatch = false;
            os_unfair_lock_unlock(lock);
            if (new_link) {
                if (!CVDisplayLinkIsRunning(new_link)) CVDisplayLinkStart(new_link);
                if (new_link_retained) CVDisplayLinkRelease(new_link);
            }
            _glfwInputError(GLFW_PLATFORM_ERROR,
                "CVDisplayLink stuck possibly because of sleep/screensaver + Apple's incompetence, recreating.");
        } else {
            if (need_start && link) CVDisplayLinkStart(link);
            else if (need_stop && link) CVDisplayLinkStop(link);
            if (retain_link && link) CVDisplayLinkRelease(link);
        }
    }
    if (!found_display_link) {
        unsigned idx = _glfwCreateDisplayLink(displayID);
        if (idx < displayLinks.count) {
            dl = &displayLinks.entries[idx];
            os_unfair_lock *lock = &displayLinks.locks[idx];
            os_unfair_lock_lock(lock);
            dl->lastRenderFrameRequestedAt = now;
            dl->first_unserviced_render_frame_request_at = now;
            dl->pending_dispatch = false;
            CVDisplayLinkRef link = dl->displayLink;
            if (link) CVDisplayLinkRetain(link);
            os_unfair_lock_unlock(lock);
            if (link) {
                if (!CVDisplayLinkIsRunning(link)) CVDisplayLinkStart(link);
                CVDisplayLinkRelease(link);
            }
        }
    }
}

static void
_glfwDispatchRenderFrame(void *passed_in_data) {
    CGDirectDisplayID displayID = (uintptr_t)passed_in_data;
    _GLFWwindow *w = _glfw.windowListHead;
    while (w) {
        if (w->ns.renderFrameRequested && displayID == displayIDForWindow(w)) {
            w->ns.renderFrameRequested = false;
            w->ns.renderFrameCallback((GLFWwindow*)w);
        }
        w = w->next;
    }
    for (size_t i = 0; i < displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &displayLinks.entries[i];
        bool need_stop = false;
        CVDisplayLinkRef link = NULL;
        os_unfair_lock *lock = &displayLinks.locks[i];
        os_unfair_lock_lock(lock);
        if (dl->displayID == displayID) {
            dl->first_unserviced_render_frame_request_at = 0;
            dl->pending_dispatch = false;
            bool any_pending_request = false;
            _GLFWwindow *window = _glfw.windowListHead;
            while (window) {
                if (window->ns.renderFrameRequested && displayID == displayIDForWindow(window)) {
                    any_pending_request = true;
                    break;
                }
                window = window->next;
            }
            link = dl->displayLink;
            if (!any_pending_request && link && CVDisplayLinkIsRunning(link)) {
                need_stop = true;
                CVDisplayLinkRetain(link);
                dl->lastRenderFrameRequestedAt = 0;
            }
        }
        os_unfair_lock_unlock(lock);
        if (need_stop && link) {
            CVDisplayLinkStop(link);
            CVDisplayLinkRelease(link);
        }
    }
}
