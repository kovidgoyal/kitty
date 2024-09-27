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

#define DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL s_to_monotonic_t(30ll)

typedef struct _GLFWDisplayLinkNS
{
    CVDisplayLinkRef displayLink;
    CGDirectDisplayID displayID;
    monotonic_t lastRenderFrameRequestedAt, first_unserviced_render_frame_request_at;
} _GLFWDisplayLinkNS;

static struct {
    _GLFWDisplayLinkNS entries[256];
    size_t count;
} displayLinks = {0};

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
        if (displayLinks.entries[i].displayLink) {
            CVDisplayLinkStop(displayLinks.entries[i].displayLink);
            CVDisplayLinkRelease(displayLinks.entries[i].displayLink);
        }
    }
    memset(displayLinks.entries, 0, sizeof(_GLFWDisplayLinkNS) * displayLinks.count);
    displayLinks.count = 0;
}

static CVReturn
displayLinkCallback(
        CVDisplayLinkRef displayLink UNUSED,
        const CVTimeStamp* now UNUSED, const CVTimeStamp* outputTime UNUSED,
        CVOptionFlags flagsIn UNUSED, CVOptionFlags* flagsOut UNUSED, void* userInfo) {
    CGDirectDisplayID displayID = (uintptr_t)userInfo;
    NSNumber *arg = [NSNumber numberWithUnsignedInt:displayID];
    [NSApp performSelectorOnMainThread:@selector(render_frame_received:) withObject:arg waitUntilDone:NO];
    [arg release];
    return kCVReturnSuccess;
}

static void
_glfw_create_cv_display_link(_GLFWDisplayLinkNS *entry) {
    CVDisplayLinkCreateWithCGDisplay(entry->displayID, &entry->displayLink);
    CVDisplayLinkSetOutputCallback(entry->displayLink, &displayLinkCallback, (void*)(uintptr_t)entry->displayID);
}

unsigned
_glfwCreateDisplayLink(CGDirectDisplayID displayID) {
    if (displayLinks.count >= arraysz(displayLinks.entries) - 1) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Too many monitors cannot create display link");
        return displayLinks.count;
    }
    for (unsigned i = 0; i < displayLinks.count; i++) {
        // already created in this run
        if (displayLinks.entries[i].displayID == displayID) return i;
    }
    _GLFWDisplayLinkNS *entry = &displayLinks.entries[displayLinks.count++];
    memset(entry, 0, sizeof(_GLFWDisplayLinkNS));
    entry->displayID = displayID;
    _glfw_create_cv_display_link(entry);
    return displayLinks.count - 1;
}

static unsigned long long display_link_shutdown_timer = 0;

static void
_glfwShutdownCVDisplayLink(unsigned long long timer_id UNUSED, void *user_data UNUSED) {
    display_link_shutdown_timer = 0;
    for (size_t i = 0; i < displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &displayLinks.entries[i];
        if (dl->displayLink) CVDisplayLinkStop(dl->displayLink);
        dl->lastRenderFrameRequestedAt = 0;
        dl->first_unserviced_render_frame_request_at = 0;
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
        if (dl->displayID == displayID) {
            found_display_link = true;
            dl->lastRenderFrameRequestedAt = now;
            if (!dl->first_unserviced_render_frame_request_at) dl->first_unserviced_render_frame_request_at = now;
            if (!CVDisplayLinkIsRunning(dl->displayLink)) CVDisplayLinkStart(dl->displayLink);
            else if (now - dl->first_unserviced_render_frame_request_at > s_to_monotonic_t(1ll)) {
                // display link is stuck need to recreate it because Apple can't even
                // get a simple timer right
                CVDisplayLinkRelease(dl->displayLink); dl->displayLink = nil;
                dl->first_unserviced_render_frame_request_at = now;
                _glfw_create_cv_display_link(dl);
                _glfwInputError(GLFW_PLATFORM_ERROR,
                    "CVDisplayLink stuck possibly because of sleep/screensaver + Apple's incompetence, recreating.");
                if (!CVDisplayLinkIsRunning(dl->displayLink)) CVDisplayLinkStart(dl->displayLink);
            }
        } else if (dl->displayLink && dl->lastRenderFrameRequestedAt && now - dl->lastRenderFrameRequestedAt >= DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL) {
            CVDisplayLinkStop(dl->displayLink);
            dl->lastRenderFrameRequestedAt = 0;
            dl->first_unserviced_render_frame_request_at = 0;
        }
    }
    if (!found_display_link) {
        unsigned idx = _glfwCreateDisplayLink(displayID);
        if (idx < displayLinks.count) {
            dl = &displayLinks.entries[idx];
            dl->lastRenderFrameRequestedAt = now;
            dl->first_unserviced_render_frame_request_at = now;
            if (!CVDisplayLinkIsRunning(dl->displayLink)) CVDisplayLinkStart(dl->displayLink);
        }
    }
}

void
_glfwDispatchRenderFrame(CGDirectDisplayID displayID) {
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
        if (dl->displayID == displayID) {
            dl->first_unserviced_render_frame_request_at = 0;
        }
    }
}


