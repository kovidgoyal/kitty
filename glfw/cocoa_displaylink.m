/*
 * cocoa_displaylink.m
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Render frames are paced using CADisplayLink, obtained via
// [NSScreen displayLinkWithTarget:selector:]. It fires on the main thread run
// loop, as do all the functions in this file, so no locking is needed.

#include "internal.h"
#include <QuartzCore/QuartzCore.h>

#define DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL s_to_monotonic_t(30ll)
#define MAX_NUM_OF_DISPLAYS 256

typedef struct _GLFWDisplayLinkNS {
    CADisplayLink *displayLink;
    CGDirectDisplayID displayID;
    monotonic_t lastRenderFrameRequestedAt, first_unserviced_render_frame_request_at;
    // Whether the link being stuck has been reported since it last delivered a frame
    bool stuck_reported;
} _GLFWDisplayLinkNS;

static struct {
    _GLFWDisplayLinkNS entries[MAX_NUM_OF_DISPLAYS];
    size_t count;
} displayLinks = {0};

static void _glfwDispatchRenderFrame(CGDirectDisplayID displayID);

// CADisplayLink retains its target, so use a separate target object that
// holds no references to anything that needs releasing.
@interface GLFWDisplayLinkTarget : NSObject {
    _GLFWDisplayLinkNS *entry;
}
- (instancetype)initWithEntry:(_GLFWDisplayLinkNS *)e;
- (void)displayLinkFired:(CADisplayLink *)sender;
@end

@implementation GLFWDisplayLinkTarget
- (instancetype)initWithEntry:(_GLFWDisplayLinkNS *)e {
    self = [super init];
    if (self) entry = e;
    return self;
}

- (void)displayLinkFired:(CADisplayLink *)sender {
    (void)sender;
    if (entry->first_unserviced_render_frame_request_at) _glfwDispatchRenderFrame(entry->displayID);
}
@end

static NSScreen *
screen_for_display_id(CGDirectDisplayID displayID) {
    for (NSScreen *screen in [NSScreen screens]) {
        NSNumber *n = [screen deviceDescription][@"NSScreenNumber"];
        if (n && [n unsignedIntValue] == displayID) return screen;
    }
    return nil;
}

static void
create_display_link(_GLFWDisplayLinkNS *entry) {
    entry->displayLink = nil;
    @autoreleasepool {
        NSScreen *screen = screen_for_display_id(entry->displayID);
        if (!screen) return;
        GLFWDisplayLinkTarget *target = [[GLFWDisplayLinkTarget alloc] initWithEntry:entry];
        CADisplayLink *link = [screen displayLinkWithTarget:target selector:@selector(displayLinkFired:)];
        [target release];
        if (!link) return;
        link.paused = YES;
        // Use common modes so that frames are delivered during live resize and modal loops
        [link addToRunLoop:[NSRunLoop mainRunLoop] forMode:NSRunLoopCommonModes];
        entry->displayLink = [link retain];
    }
}

static void
link_start(CADisplayLink *link) {
    link.paused = NO;
}

static void
link_stop(CADisplayLink *link) {
    link.paused = YES;
}

static bool
link_is_running(CADisplayLink *link) {
    return !link.paused;
}

// Remove the link from the run loop and release the reference owned by an entry
static void
destroy_display_link(_GLFWDisplayLinkNS *entry) {
    CADisplayLink *link = entry->displayLink;
    entry->displayLink = nil;
    if (link) {
        // invalidate removes the link from the run loop and releases its target
        [link invalidate];
        [link release];
    }
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
        destroy_display_link(entry);
        entry->displayID = (CGDirectDisplayID)0;
        entry->lastRenderFrameRequestedAt = 0;
        entry->first_unserviced_render_frame_request_at = 0;
    }
    displayLinks.count = 0;
}

unsigned
_glfwCreateDisplayLink(CGDirectDisplayID displayID) {
    for (unsigned i = 0; i < displayLinks.count; i++) {
        if (displayLinks.entries[i].displayID == displayID) return i;
    }
    if (displayLinks.count >= MAX_NUM_OF_DISPLAYS) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Too many monitors cannot create display link");
        return displayLinks.count;
    }
    unsigned idx = displayLinks.count++;
    _GLFWDisplayLinkNS *entry = &displayLinks.entries[idx];
    memset(entry, 0, sizeof(entry[0]));
    entry->displayID = displayID;
    create_display_link(entry);
    return idx;
}

static unsigned long long display_link_shutdown_timer = 0;

static void
_glfwShutdownDisplayLinks(unsigned long long timer_id UNUSED, void *user_data UNUSED) {
    display_link_shutdown_timer = 0;
    for (size_t i = 0; i < displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &displayLinks.entries[i];
        dl->lastRenderFrameRequestedAt = 0;
        dl->first_unserviced_render_frame_request_at = 0;
        if (dl->displayLink) link_stop(dl->displayLink);
    }
}

void
_glfwRequestRenderFrame(_GLFWwindow *w) {
    CGDirectDisplayID displayID = displayIDForWindow(w);
    if (display_link_shutdown_timer) {
        _glfwPlatformUpdateTimer(display_link_shutdown_timer, DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL, true);
    } else {
        display_link_shutdown_timer = _glfwPlatformAddTimer(DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL, false, _glfwShutdownDisplayLinks, NULL, NULL);
    }
    monotonic_t now = glfwGetTime();
    bool found_display_link = false;
    for (size_t i = 0; i < displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &displayLinks.entries[i];
        if (dl->displayID == displayID) {
            found_display_link = true;
            // NSScreen may not have been available when the link was first
            // created, for example, if AppKit had not yet caught up with a
            // display configuration change, so try again.
            if (!dl->displayLink) create_display_link(dl);
            monotonic_t first_unserviced = dl->first_unserviced_render_frame_request_at;
            dl->lastRenderFrameRequestedAt = now;
            if (!first_unserviced) {
                dl->first_unserviced_render_frame_request_at = now;
                first_unserviced = now;
            }
            if (dl->displayLink) {
                if (!link_is_running(dl->displayLink)) link_start(dl->displayLink);
                else if (now - first_unserviced > s_to_monotonic_t(1ll)) {
                    dl->first_unserviced_render_frame_request_at = now;
                    destroy_display_link(dl);
                    create_display_link(dl);
                    if (dl->displayLink) link_start(dl->displayLink);
                    // The link is recreated every second while stuck, which can be for long
                    // periods, for example, while the display is asleep, so report it only once
                    if (!dl->stuck_reported) {
                        dl->stuck_reported = true;
                        _glfwInputError(GLFW_PLATFORM_ERROR, "Display link stuck possibly because of sleep/screensaver + Apple's incompetence, recreating.");
                    }
                }
            }
        } else if (dl->displayLink && dl->lastRenderFrameRequestedAt && now - dl->lastRenderFrameRequestedAt >= DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL) {
            dl->lastRenderFrameRequestedAt = 0;
            dl->first_unserviced_render_frame_request_at = 0;
            link_stop(dl->displayLink);
        }
    }
    if (!found_display_link) {
        unsigned idx = _glfwCreateDisplayLink(displayID);
        if (idx < displayLinks.count) {
            _GLFWDisplayLinkNS *dl = &displayLinks.entries[idx];
            dl->lastRenderFrameRequestedAt = now;
            dl->first_unserviced_render_frame_request_at = now;
            if (dl->displayLink && !link_is_running(dl->displayLink)) link_start(dl->displayLink);
        }
    }
}

static bool
has_pending_render_frame_request(CGDirectDisplayID displayID) {
    for (_GLFWwindow *w = _glfw.windowListHead; w; w = w->next) {
        if (w->ns.renderFrameRequested && displayID == displayIDForWindow(w)) return true;
    }
    return false;
}

static void
_glfwDispatchRenderFrame(CGDirectDisplayID displayID) {
    // Reset before calling the callbacks so that any render frame requests
    // they make are tracked as unserviced.
    for (size_t i = 0; i < displayLinks.count; i++) {
        if (displayLinks.entries[i].displayID == displayID) {
            displayLinks.entries[i].first_unserviced_render_frame_request_at = 0;
            displayLinks.entries[i].stuck_reported = false;
        }
    }
    for (_GLFWwindow *w = _glfw.windowListHead; w; w = w->next) {
        if (w->ns.renderFrameRequested && displayID == displayIDForWindow(w)) {
            w->ns.renderFrameRequested = false;
            w->ns.renderFrameCallback((GLFWwindow *)w);
        }
    }
    for (size_t i = 0; i < displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &displayLinks.entries[i];
        if (dl->displayID != displayID) continue;
        if (dl->displayLink && link_is_running(dl->displayLink) && !has_pending_render_frame_request(displayID)) {
            link_stop(dl->displayLink);
            dl->lastRenderFrameRequestedAt = 0;
        }
    }
}
