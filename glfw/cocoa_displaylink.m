/*
 * cocoa_displaylink.m
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// On macOS 14 and newer CADisplayLink, obtained via [NSScreen displayLinkWithTarget:selector:]
// is used. It fires on the main thread run loop. CVDisplayLink is deprecated
// and is used only as a fallback on older macOS versions. Remove it once base
// macOS version is 14.
#pragma clang diagnostic ignored "-Wdeprecated-declarations"

#include "internal.h"
#include <CoreVideo/CVDisplayLink.h>
#include <QuartzCore/QuartzCore.h>
#include <os/lock.h>

#define DISPLAY_LINK_SHUTDOWN_CHECK_INTERVAL s_to_monotonic_t(30ll)
#define MAX_NUM_OF_DISPLAYS 256

typedef struct _GLFWDisplayLinkNS {
    // Either a CADisplayLink or a CVDisplayLinkRef depending on use_ca_display_link()
    CFTypeRef displayLink;
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

static inline os_unfair_lock *
lock_for_entry(_GLFWDisplayLinkNS *entry) {
    return &displayLinks.locks[index_for_entry(entry)];
}

static bool
use_ca_display_link(void) {
    static int ans = -1;
    if (ans < 0) {
        if (@available(macOS 14.0, *)) ans = 1;
        else ans = 0;
    }
    return ans == 1;
}

static void _glfwDispatchRenderFrame(void *);

static void
on_display_link_fired(_GLFWDisplayLinkNS *entry, bool on_main_thread) {
    os_unfair_lock *lock = lock_for_entry(entry);
    os_unfair_lock_lock(lock);
    const bool should_dispatch = entry->first_unserviced_render_frame_request_at && !entry->pending_dispatch;
    CGDirectDisplayID displayID = entry->displayID;
    if (should_dispatch) entry->pending_dispatch = true;
    os_unfair_lock_unlock(lock);
    if (should_dispatch) {
        if (on_main_thread) _glfwDispatchRenderFrame((void *)(uintptr_t)displayID);
        else dispatch_async_f(dispatch_get_main_queue(), (void *)(uintptr_t)displayID, _glfwDispatchRenderFrame);
    }
}

// CADisplayLink retains its target, so use a separate target object that
// holds no references to anything that needs releasing.
API_AVAILABLE(macos(14.0))
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
    on_display_link_fired(entry, true);
}
@end

static CVReturn
displayLinkCallback(
    CVDisplayLinkRef displayLink UNUSED,
    const CVTimeStamp *now UNUSED,
    const CVTimeStamp *outputTime UNUSED,
    CVOptionFlags flagsIn UNUSED,
    CVOptionFlags *flagsOut UNUSED,
    void *userInfo) {
    _GLFWDisplayLinkNS *entry = (_GLFWDisplayLinkNS *)userInfo;
    if (entry) on_display_link_fired(entry, false);
    return kCVReturnSuccess;
}

static NSScreen *
screen_for_display_id(CGDirectDisplayID displayID) {
    for (NSScreen *screen in [NSScreen screens]) {
        NSNumber *n = [screen deviceDescription][@"NSScreenNumber"];
        if (n && [n unsignedIntValue] == displayID) return screen;
    }
    return nil;
}

// Must be called with the lock for entry held
static void
create_display_link(_GLFWDisplayLinkNS *entry) {
    entry->displayLink = NULL;
    if (use_ca_display_link()) {
        if (@available(macOS 14.0, *)) {
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
                entry->displayLink = (CFTypeRef)[link retain];
            }
        }
    } else {
        CVDisplayLinkRef link = NULL;
        CVDisplayLinkCreateWithCGDisplay(entry->displayID, &link);
        if (link) {
            CVDisplayLinkSetOutputCallback(link, &displayLinkCallback, entry);
            entry->displayLink = link;
        }
    }
}

static void
link_start(CFTypeRef link) {
    if (use_ca_display_link()) {
        if (@available(macOS 14.0, *)) ((CADisplayLink *)link).paused = NO;
    } else CVDisplayLinkStart((CVDisplayLinkRef)link);
}

static void
link_stop(CFTypeRef link) {
    if (use_ca_display_link()) {
        if (@available(macOS 14.0, *)) ((CADisplayLink *)link).paused = YES;
    } else CVDisplayLinkStop((CVDisplayLinkRef)link);
}

static bool
link_is_running(CFTypeRef link) {
    if (use_ca_display_link()) {
        if (@available(macOS 14.0, *)) return !((CADisplayLink *)link).paused;
        return false;
    }
    return CVDisplayLinkIsRunning((CVDisplayLinkRef)link);
}

static void
link_retain(CFTypeRef link) { CFRetain(link); }

static void
link_release(CFTypeRef link) { CFRelease(link); }

// Stop the link and release the reference owned by an entry
static void
link_destroy(CFTypeRef link) {
    if (use_ca_display_link()) {
        // invalidate removes the link from the run loop and releases its target
        if (@available(macOS 14.0, *)) [(CADisplayLink *)link invalidate];
    } else CVDisplayLinkStop((CVDisplayLinkRef)link);
    link_release(link);
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
        CFTypeRef link = entry->displayLink;
        entry->displayLink = NULL;
        entry->displayID = (CGDirectDisplayID)0;
        entry->lastRenderFrameRequestedAt = 0;
        entry->first_unserviced_render_frame_request_at = 0;
        entry->pending_dispatch = false;
        os_unfair_lock_unlock(lock);
        if (link) link_destroy(link);
    }
    displayLinks.count = 0;
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
    create_display_link(entry);
    os_unfair_lock_unlock(lock);
    return idx;
}

static unsigned long long display_link_shutdown_timer = 0;

static void
_glfwShutdownDisplayLinks(unsigned long long timer_id UNUSED, void *user_data UNUSED) {
    display_link_shutdown_timer = 0;
    for (size_t i = 0; i < displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &displayLinks.entries[i];
        os_unfair_lock *lock = &displayLinks.locks[i];
        os_unfair_lock_lock(lock);
        CFTypeRef link = dl->displayLink;
        if (link) link_retain(link);
        dl->lastRenderFrameRequestedAt = 0;
        dl->first_unserviced_render_frame_request_at = 0;
        dl->pending_dispatch = false;
        os_unfair_lock_unlock(lock);
        if (link) {
            link_stop(link);
            link_release(link);
        }
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
    _GLFWDisplayLinkNS *dl = NULL;
    for (size_t i = 0; i < displayLinks.count; i++) {
        dl = &displayLinks.entries[i];
        bool need_start = false, need_stop = false, need_recreate = false;
        bool retain_link = false;
        CFTypeRef link = NULL;
        CFTypeRef new_link = NULL;
        bool new_link_retained = false;
        os_unfair_lock *lock = &displayLinks.locks[i];
        os_unfair_lock_lock(lock);
        if (dl->displayID == displayID && !dl->displayLink && use_ca_display_link()) {
            // NSScreen may not have been available when the link was first
            // created, for example, if AppKit had not yet caught up with a
            // display configuration change, so try again.
            create_display_link(dl);
        }
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
                if (!link_is_running(link)) {
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
        if (retain_link && link) link_retain(link);
        os_unfair_lock_unlock(lock);
        if (need_recreate && link) {
            link_destroy(link);
            os_unfair_lock_lock(lock);
            create_display_link(dl);
            new_link = dl->displayLink;
            if (new_link) {
                link_retain(new_link);
                new_link_retained = true;
            }
            dl->pending_dispatch = false;
            os_unfair_lock_unlock(lock);
            if (new_link) {
                if (!link_is_running(new_link)) link_start(new_link);
                if (new_link_retained) link_release(new_link);
            }
            _glfwInputError(GLFW_PLATFORM_ERROR, "Display link stuck possibly because of sleep/screensaver + Apple's incompetence, recreating.");
        } else {
            if (need_start && link) link_start(link);
            else if (need_stop && link) link_stop(link);
            if (retain_link && link) link_release(link);
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
            CFTypeRef link = dl->displayLink;
            if (link) link_retain(link);
            os_unfair_lock_unlock(lock);
            if (link) {
                if (!link_is_running(link)) link_start(link);
                link_release(link);
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
            w->ns.renderFrameCallback((GLFWwindow *)w);
        }
        w = w->next;
    }
    for (size_t i = 0; i < displayLinks.count; i++) {
        _GLFWDisplayLinkNS *dl = &displayLinks.entries[i];
        bool need_stop = false;
        CFTypeRef link = NULL;
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
            if (!any_pending_request && link && link_is_running(link)) {
                need_stop = true;
                link_retain(link);
                dl->lastRenderFrameRequestedAt = 0;
            }
        }
        os_unfair_lock_unlock(lock);
        if (need_stop && link) {
            link_stop(link);
            link_release(link);
        }
    }
}
