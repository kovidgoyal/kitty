//========================================================================
// GLFW 3.3 macOS - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2002-2006 Marcus Geelnard
// Copyright (c) 2006-2016 Camilla Löwy <elmindreda@glfw.org>
//
// This software is provided 'as-is', without any express or implied
// warranty. In no event will the authors be held liable for any damages
// arising from the use of this software.
//
// Permission is granted to anyone to use this software for any purpose,
// including commercial applications, and to alter it and redistribute it
// freely, subject to the following restrictions:
//
// 1. The origin of this software must not be misrepresented; you must not
//    claim that you wrote the original software. If you use this software
//    in a product, an acknowledgment in the product documentation would
//    be appreciated but is not required.
//
// 2. Altered source versions must be plainly marked as such, and must not
//    be misrepresented as being the original software.
//
// 3. This notice may not be removed or altered from any source
//    distribution.
//
//========================================================================

#include "internal.h"

#include <stdlib.h>
#include <limits.h>
#include <math.h>

#include <IOKit/graphics/IOGraphicsLib.h>
#include <CoreVideo/CVBase.h>
#include <CoreVideo/CVDisplayLink.h>
#include <ApplicationServices/ApplicationServices.h>


// Get the name of the specified display, or NULL
//
static char* getDisplayName(CGDirectDisplayID displayID)
{
    io_iterator_t it;
    io_service_t service;
    CFDictionaryRef info;

    if (IOServiceGetMatchingServices(kIOMasterPortDefault,
                                     IOServiceMatching("IODisplayConnect"),
                                     &it) != 0)
    {
        // This may happen if a desktop Mac is running headless
        return NULL;
    }

    while ((service = IOIteratorNext(it)) != 0)
    {
        info = IODisplayCreateInfoDictionary(service,
                                             kIODisplayOnlyPreferredName);

        CFNumberRef vendorIDRef =
            CFDictionaryGetValue(info, CFSTR(kDisplayVendorID));
        CFNumberRef productIDRef =
            CFDictionaryGetValue(info, CFSTR(kDisplayProductID));
        if (!vendorIDRef || !productIDRef)
        {
            CFRelease(info);
            continue;
        }

        unsigned int vendorID, productID;
        CFNumberGetValue(vendorIDRef, kCFNumberIntType, &vendorID);
        CFNumberGetValue(productIDRef, kCFNumberIntType, &productID);

        if (CGDisplayVendorNumber(displayID) == vendorID &&
            CGDisplayModelNumber(displayID) == productID)
        {
            // Info dictionary is used and freed below
            break;
        }

        CFRelease(info);
    }

    IOObjectRelease(it);

    if (!service)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Cocoa: Failed to find service port for display");
        return NULL;
    }

    CFDictionaryRef names =
        CFDictionaryGetValue(info, CFSTR(kDisplayProductName));

    CFStringRef nameRef;

    if (!names || !CFDictionaryGetValueIfPresent(names, CFSTR("en_US"),
                                                 (const void**) &nameRef))
    {
        // This may happen if a desktop Mac is running headless
        CFRelease(info);
        return NULL;
    }

    const CFIndex size =
        CFStringGetMaximumSizeForEncoding(CFStringGetLength(nameRef),
                                          kCFStringEncodingUTF8);
    char* name = calloc(size + 1, 1);
    CFStringGetCString(nameRef, name, size, kCFStringEncodingUTF8);

    CFRelease(info);
    return name;
}

// Check whether the display mode should be included in enumeration
//
static GLFWbool modeIsGood(CGDisplayModeRef mode)
{
    uint32_t flags = CGDisplayModeGetIOFlags(mode);

    if (!(flags & kDisplayModeValidFlag) || !(flags & kDisplayModeSafeFlag))
        return GLFW_FALSE;
    if (flags & kDisplayModeInterlacedFlag)
        return GLFW_FALSE;
    if (flags & kDisplayModeStretchedFlag)
        return GLFW_FALSE;

#if MAC_OS_X_VERSION_MAX_ALLOWED <= 101100
    CFStringRef format = CGDisplayModeCopyPixelEncoding(mode);
    if (CFStringCompare(format, CFSTR(IO16BitDirectPixels), 0) &&
        CFStringCompare(format, CFSTR(IO32BitDirectPixels), 0))
    {
        CFRelease(format);
        return GLFW_FALSE;
    }

    CFRelease(format);
#endif /* MAC_OS_X_VERSION_MAX_ALLOWED */
    return GLFW_TRUE;
}

// Convert Core Graphics display mode to GLFW video mode
//
static GLFWvidmode vidmodeFromCGDisplayMode(CGDisplayModeRef mode,
                                            CVDisplayLinkRef link)
{
    GLFWvidmode result;
    result.width = (int) CGDisplayModeGetWidth(mode);
    result.height = (int) CGDisplayModeGetHeight(mode);
    result.refreshRate = (int) round(CGDisplayModeGetRefreshRate(mode));

    if (result.refreshRate == 0)
    {
        const CVTime time = CVDisplayLinkGetNominalOutputVideoRefreshPeriod(link);
        if (!(time.flags & kCVTimeIsIndefinite))
            result.refreshRate = (int) (time.timeScale / (double) time.timeValue);
    }

#if MAC_OS_X_VERSION_MAX_ALLOWED <= 101100
    CFStringRef format = CGDisplayModeCopyPixelEncoding(mode);
    if (CFStringCompare(format, CFSTR(IO16BitDirectPixels), 0) == 0)
    {
        result.redBits = 5;
        result.greenBits = 5;
        result.blueBits = 5;
    }
    else
#endif /* MAC_OS_X_VERSION_MAX_ALLOWED */
    {
        result.redBits = 8;
        result.greenBits = 8;
        result.blueBits = 8;
    }

#if MAC_OS_X_VERSION_MAX_ALLOWED <= 101100
    CFRelease(format);
#endif /* MAC_OS_X_VERSION_MAX_ALLOWED */
    return result;
}

// Starts reservation for display fading
//
static CGDisplayFadeReservationToken beginFadeReservation(void)
{
    CGDisplayFadeReservationToken token = kCGDisplayFadeReservationInvalidToken;

    if (CGAcquireDisplayFadeReservation(5, &token) == kCGErrorSuccess)
    {
        CGDisplayFade(token, 0.3,
                      kCGDisplayBlendNormal,
                      kCGDisplayBlendSolidColor,
                      0.0, 0.0, 0.0,
                      TRUE);
    }

    return token;
}

// Ends reservation for display fading
//
static void endFadeReservation(CGDisplayFadeReservationToken token)
{
    if (token != kCGDisplayFadeReservationInvalidToken)
    {
        CGDisplayFade(token, 0.5,
                      kCGDisplayBlendSolidColor,
                      kCGDisplayBlendNormal,
                      0.0, 0.0, 0.0,
                      FALSE);
        CGReleaseDisplayFadeReservation(token);
    }
}

// Finds and caches the NSScreen corresponding to the specified monitor
//
GLFWbool refreshMonitorScreen(_GLFWmonitor* monitor)
{
    if (monitor->ns.screen)
        return GLFW_TRUE;

     for (NSScreen* screen in [NSScreen screens])
    {
        NSNumber* displayID = [screen deviceDescription][@"NSScreenNumber"];

        // HACK: Compare unit numbers instead of display IDs to work around
        //       display replacement on machines with automatic graphics
        //       switching
        if (monitor->ns.unitNumber == CGDisplayUnitNumber([displayID unsignedIntValue]))
        {
            monitor->ns.screen = screen;
            return GLFW_TRUE;
        }
    }

     _glfwInputError(GLFW_PLATFORM_ERROR, "Cocoa: Failed to find a screen for monitor");
    return GLFW_FALSE;
}

//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

void _glfwClearDisplayLinks() {
    [_glfw.ns.displayLinks.lock lock];
    for (size_t i = 0; i < _glfw.ns.displayLinks.count; i++) {
        if (_glfw.ns.displayLinks.entries[i].displayLinkStarted) {
            CVDisplayLinkStop(_glfw.ns.displayLinks.entries[i].displayLink);
            _glfw.ns.displayLinks.entries[i].displayLinkStarted = GLFW_FALSE;
        }
        if (_glfw.ns.displayLinks.entries[i].displayLink) {
            CVDisplayLinkRelease(_glfw.ns.displayLinks.entries[i].displayLink);
            _glfw.ns.displayLinks.entries[i].displayLink = nil;
        }
    }
    _glfw.ns.displayLinks.count = 0;
    [_glfw.ns.displayLinks.lock unlock];
}

static CVReturn displayLinkCallback(
        CVDisplayLinkRef displayLink,
        const CVTimeStamp* now, const CVTimeStamp* outputTime,
        CVOptionFlags flagsIn, CVOptionFlags* flagsOut, void* userInfo)
{
    CGDirectDisplayID displayID = (CGDirectDisplayID)userInfo;
    [_glfw.ns.displayLinks.lock lock];
    GLFWbool notify = GLFW_FALSE;
    for (size_t i = 0; i < _glfw.ns.displayLinks.count; i++) {
        if (_glfw.ns.displayLinks.entries[i].displayID == displayID) {
            if (_glfw.ns.displayLinks.entries[i].renderFrameRequested) {
                notify = GLFW_TRUE;
                _glfw.ns.displayLinks.entries[i].renderFrameRequested = GLFW_FALSE;
            }
            break;
        }
    }
    [_glfw.ns.displayLinks.lock unlock];
    if (notify) {
        NSNumber *arg = [NSNumber numberWithUnsignedInt:displayID];
        [NSApp performSelectorOnMainThread:@selector(render_frame_received:) withObject:arg waitUntilDone:NO];
        [arg release];
    }
    return kCVReturnSuccess;
}

static inline void createDisplayLink(CGDirectDisplayID displayID) {
    [_glfw.ns.displayLinks.lock lock];
    if (_glfw.ns.displayLinks.count >= sizeof(_glfw.ns.displayLinks.entries)/sizeof(_glfw.ns.displayLinks.entries[0]) - 1) return;
    for (size_t i = 0; i < _glfw.ns.displayLinks.count; i++) {
        if (_glfw.ns.displayLinks.entries[i].displayID == displayID) return;
    }
    _GLFWDisplayLinkNS *entry = &_glfw.ns.displayLinks.entries[_glfw.ns.displayLinks.count++];
    memset(entry, 0, sizeof(_GLFWDisplayLinkNS));
    entry->displayID = displayID;
    CVDisplayLinkCreateWithCGDisplay(displayID, &entry->displayLink);
    CVDisplayLinkSetOutputCallback(entry->displayLink, &displayLinkCallback, (void*)(uintptr_t)displayID);
    [_glfw.ns.displayLinks.lock unlock];
}

// Poll for changes in the set of connected monitors
//
void _glfwPollMonitorsNS(void)
{
    uint32_t i, j, displayCount, disconnectedCount;
    CGDirectDisplayID* displays;
    _GLFWmonitor** disconnected = NULL;

    CGGetOnlineDisplayList(0, NULL, &displayCount);
    displays = calloc(displayCount, sizeof(CGDirectDisplayID));
    CGGetOnlineDisplayList(displayCount, displays, &displayCount);
    _glfwClearDisplayLinks();

    for (i = 0;  i < _glfw.monitorCount;  i++)
        _glfw.monitors[i]->ns.screen = nil;

    disconnectedCount = _glfw.monitorCount;
    if (disconnectedCount)
    {
        disconnected = calloc(_glfw.monitorCount, sizeof(_GLFWmonitor*));
        memcpy(disconnected,
               _glfw.monitors,
               _glfw.monitorCount * sizeof(_GLFWmonitor*));
    }

    for (i = 0;  i < displayCount;  i++)
    {
        _GLFWmonitor* monitor;
        const uint32_t unitNumber = CGDisplayUnitNumber(displays[i]);

        if (CGDisplayIsAsleep(displays[i]))
            continue;

        for (j = 0;  j < disconnectedCount;  j++)
        {
            // HACK: Compare unit numbers instead of display IDs to work around
            //       display replacement on machines with automatic graphics
            //       switching
            if (disconnected[j] && disconnected[j]->ns.unitNumber == unitNumber)
            {
                disconnected[j] = NULL;
                break;
            }
        }

        const CGSize size = CGDisplayScreenSize(displays[i]);
        char* name = getDisplayName(displays[i]);
        if (!name)
            name = _glfw_strdup("Unknown");

        monitor = _glfwAllocMonitor(name, size.width, size.height);
        monitor->ns.displayID  = displays[i];
        monitor->ns.unitNumber = unitNumber;
        createDisplayLink(monitor->ns.displayID);

        free(name);

        _glfwInputMonitor(monitor, GLFW_CONNECTED, _GLFW_INSERT_LAST);
    }

    for (i = 0;  i < disconnectedCount;  i++)
    {
        if (disconnected[i])
            _glfwInputMonitor(disconnected[i], GLFW_DISCONNECTED, 0);
    }

    free(disconnected);
    free(displays);
}

// Change the current video mode
//
void _glfwSetVideoModeNS(_GLFWmonitor* monitor, const GLFWvidmode* desired)
{
    CFArrayRef modes;
    CFIndex count, i;
    CVDisplayLinkRef link;
    CGDisplayModeRef native = NULL;
    GLFWvidmode current;
    const GLFWvidmode* best;

    best = _glfwChooseVideoMode(monitor, desired);
    _glfwPlatformGetVideoMode(monitor, &current);
    if (_glfwCompareVideoModes(&current, best) == 0)
        return;

    CVDisplayLinkCreateWithCGDisplay(monitor->ns.displayID, &link);

    modes = CGDisplayCopyAllDisplayModes(monitor->ns.displayID, NULL);
    count = CFArrayGetCount(modes);

    for (i = 0;  i < count;  i++)
    {
        CGDisplayModeRef dm = (CGDisplayModeRef) CFArrayGetValueAtIndex(modes, i);
        if (!modeIsGood(dm))
            continue;

        const GLFWvidmode mode = vidmodeFromCGDisplayMode(dm, link);
        if (_glfwCompareVideoModes(best, &mode) == 0)
        {
            native = dm;
            break;
        }
    }

    if (native)
    {
        if (monitor->ns.previousMode == NULL)
            monitor->ns.previousMode = CGDisplayCopyDisplayMode(monitor->ns.displayID);

        CGDisplayFadeReservationToken token = beginFadeReservation();
        CGDisplaySetDisplayMode(monitor->ns.displayID, native, NULL);
        endFadeReservation(token);
    }

    CFRelease(modes);
    CVDisplayLinkRelease(link);
}

// Restore the previously saved (original) video mode
//
void _glfwRestoreVideoModeNS(_GLFWmonitor* monitor)
{
    if (monitor->ns.previousMode)
    {
        CGDisplayFadeReservationToken token = beginFadeReservation();
        CGDisplaySetDisplayMode(monitor->ns.displayID,
                                monitor->ns.previousMode, NULL);
        endFadeReservation(token);

        CGDisplayModeRelease(monitor->ns.previousMode);
        monitor->ns.previousMode = NULL;
    }
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

void _glfwPlatformFreeMonitor(_GLFWmonitor* monitor)
{
}

void _glfwPlatformGetMonitorPos(_GLFWmonitor* monitor, int* xpos, int* ypos)
{
    @autoreleasepool {

    const CGRect bounds = CGDisplayBounds(monitor->ns.displayID);

    if (xpos)
        *xpos = (int) bounds.origin.x;
    if (ypos)
        *ypos = (int) bounds.origin.y;

    } // autoreleasepool
}

void _glfwPlatformGetMonitorContentScale(_GLFWmonitor* monitor,
                                         float* xscale, float* yscale)
{
    @autoreleasepool {

    if (!refreshMonitorScreen(monitor))
        return;

    const NSRect points = [monitor->ns.screen frame];
    const NSRect pixels = [monitor->ns.screen convertRectToBacking:points];

    if (xscale)
        *xscale = (float) (pixels.size.width / points.size.width);
    if (yscale)
        *yscale = (float) (pixels.size.height / points.size.height);

    } // autoreleasepool
}

void _glfwPlatformGetMonitorWorkarea(_GLFWmonitor* monitor, int* xpos, int* ypos, int *width, int *height)
{
    @autoreleasepool {

    if (!refreshMonitorScreen(monitor))
        return;

    const NSRect frameRect = [monitor->ns.screen visibleFrame];

    if (xpos)
        *xpos = frameRect.origin.x;
    if (ypos)
        *ypos = _glfwTransformYNS(frameRect.origin.y + frameRect.size.height - 1);
    if (width)
        *width = frameRect.size.width;
    if (height)
        *height = frameRect.size.height;

    } // autoreleasepool
}

GLFWvidmode* _glfwPlatformGetVideoModes(_GLFWmonitor* monitor, int* count)
{
    @autoreleasepool {

    CFArrayRef modes;
    CFIndex found, i, j;
    GLFWvidmode* result;
    CVDisplayLinkRef link;

    *count = 0;

    CVDisplayLinkCreateWithCGDisplay(monitor->ns.displayID, &link);

    modes = CGDisplayCopyAllDisplayModes(monitor->ns.displayID, NULL);
    found = CFArrayGetCount(modes);
    result = calloc(found, sizeof(GLFWvidmode));

    for (i = 0;  i < found;  i++)
    {
        CGDisplayModeRef dm = (CGDisplayModeRef) CFArrayGetValueAtIndex(modes, i);
        if (!modeIsGood(dm))
            continue;

        const GLFWvidmode mode = vidmodeFromCGDisplayMode(dm, link);

        for (j = 0;  j < *count;  j++)
        {
            if (_glfwCompareVideoModes(result + j, &mode) == 0)
                break;
        }

        // Skip duplicate modes
        if (i < *count)
            continue;

        (*count)++;
        result[*count - 1] = mode;
    }

    CFRelease(modes);
    CVDisplayLinkRelease(link);
    return result;

    } // autoreleasepool
}

void _glfwPlatformGetVideoMode(_GLFWmonitor* monitor, GLFWvidmode *mode)
{
    @autoreleasepool {

    CGDisplayModeRef displayMode;
    CVDisplayLinkRef link;

    CVDisplayLinkCreateWithCGDisplay(monitor->ns.displayID, &link);

    displayMode = CGDisplayCopyDisplayMode(monitor->ns.displayID);
    *mode = vidmodeFromCGDisplayMode(displayMode, link);
    CGDisplayModeRelease(displayMode);

    CVDisplayLinkRelease(link);

    } // autoreleasepool
}

GLFWbool _glfwPlatformGetGammaRamp(_GLFWmonitor* monitor, GLFWgammaramp* ramp)
{
    @autoreleasepool {

    uint32_t i, size = CGDisplayGammaTableCapacity(monitor->ns.displayID);
    CGGammaValue* values = calloc(size * 3, sizeof(CGGammaValue));

    CGGetDisplayTransferByTable(monitor->ns.displayID,
                                size,
                                values,
                                values + size,
                                values + size * 2,
                                &size);

    _glfwAllocGammaArrays(ramp, size);

    for (i = 0; i < size; i++)
    {
        ramp->red[i]   = (unsigned short) (values[i] * 65535);
        ramp->green[i] = (unsigned short) (values[i + size] * 65535);
        ramp->blue[i]  = (unsigned short) (values[i + size * 2] * 65535);
    }

    free(values);
    return GLFW_TRUE;

    } // autoreleasepool
}

void _glfwPlatformSetGammaRamp(_GLFWmonitor* monitor, const GLFWgammaramp* ramp)
{
    @autoreleasepool {

    int i;
    CGGammaValue* values = calloc(ramp->size * 3, sizeof(CGGammaValue));

    for (i = 0;  i < ramp->size;  i++)
    {
        values[i]                  = ramp->red[i] / 65535.f;
        values[i + ramp->size]     = ramp->green[i] / 65535.f;
        values[i + ramp->size * 2] = ramp->blue[i] / 65535.f;
    }

    CGSetDisplayTransferByTable(monitor->ns.displayID,
                                ramp->size,
                                values,
                                values + ramp->size,
                                values + ramp->size * 2);

    free(values);

    } // autoreleasepool
}


//////////////////////////////////////////////////////////////////////////
//////                        GLFW native API                       //////
//////////////////////////////////////////////////////////////////////////

GLFWAPI CGDirectDisplayID glfwGetCocoaMonitor(GLFWmonitor* handle)
{
    _GLFWmonitor* monitor = (_GLFWmonitor*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(kCGNullDirectDisplay);
    return monitor->ns.displayID;
}
