//========================================================================
// GLFW 3.4 macOS - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2009-2019 Camilla Löwy <elmindreda@glfw.org>
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

#include <stdint.h>
#include <dlfcn.h>

#include <Carbon/Carbon.h>
#if defined(__OBJC__)
#import <Cocoa/Cocoa.h>
#else
typedef void* id;
#endif

// NOTE: Many Cocoa enum values have been renamed and we need to build across
//       SDK versions where one is unavailable or the other deprecated
//       We use the newer names in code and these macros to handle compatibility
#if MAC_OS_X_VERSION_MAX_ALLOWED < 101200
 #define NSBitmapFormatAlphaNonpremultiplied NSAlphaNonpremultipliedBitmapFormat
 #define NSEventMaskAny NSAnyEventMask
 #define NSEventMaskKeyUp NSKeyUpMask
 #define NSEventModifierFlagCapsLock NSAlphaShiftKeyMask
 #define NSEventModifierFlagCommand NSCommandKeyMask
 #define NSEventModifierFlagControl NSControlKeyMask
 #define NSEventModifierFlagDeviceIndependentFlagsMask NSDeviceIndependentModifierFlagsMask
 #define NSEventModifierFlagOption NSAlternateKeyMask
 #define NSEventModifierFlagShift NSShiftKeyMask
 #define NSEventTypeApplicationDefined NSApplicationDefined
 #define NSWindowStyleMaskBorderless NSBorderlessWindowMask
 #define NSWindowStyleMaskClosable NSClosableWindowMask
 #define NSWindowStyleMaskMiniaturizable NSMiniaturizableWindowMask
 #define NSWindowStyleMaskResizable NSResizableWindowMask
 #define NSWindowStyleMaskTitled NSTitledWindowMask
#endif

#if (MAC_OS_X_VERSION_MAX_ALLOWED < 101400)
 #define NSPasteboardTypeFileURL NSFilenamesPboardType
 #define NSBitmapFormatAlphaNonpremultiplied NSAlphaNonpremultipliedBitmapFormat
 #define NSPasteboardTypeString NSStringPboardType
 #define NSOpenGLContextParameterSurfaceOpacity NSOpenGLCPSurfaceOpacity
#endif

#define debug_key(...) if (_glfw.hints.init.debugKeyboard) { fprintf(stderr, __VA_ARGS__); fflush(stderr); }

typedef int (* GLFWcocoatextinputfilterfun)(int,int,unsigned int, unsigned long);
typedef bool (* GLFWapplicationshouldhandlereopenfun)(int);
typedef bool (* GLFWhandleurlopen)(const char*);
typedef void (* GLFWapplicationwillfinishlaunchingfun)(bool);
typedef bool (* GLFWcocoatogglefullscreenfun)(GLFWwindow*);
typedef void (* GLFWcocoarenderframefun)(GLFWwindow*);

typedef VkFlags VkMacOSSurfaceCreateFlagsMVK;
typedef VkFlags VkMetalSurfaceCreateFlagsEXT;

typedef struct VkMacOSSurfaceCreateInfoMVK
{
    VkStructureType                 sType;
    const void*                     pNext;
    VkMacOSSurfaceCreateFlagsMVK    flags;
    const void*                     pView;
} VkMacOSSurfaceCreateInfoMVK;

typedef struct VkMetalSurfaceCreateInfoEXT
{
    VkStructureType                 sType;
    const void*                     pNext;
    VkMetalSurfaceCreateFlagsEXT    flags;
    const void*                     pLayer;
} VkMetalSurfaceCreateInfoEXT;

typedef VkResult (APIENTRY *PFN_vkCreateMacOSSurfaceMVK)(VkInstance,const VkMacOSSurfaceCreateInfoMVK*,const VkAllocationCallbacks*,VkSurfaceKHR*);
typedef VkResult (APIENTRY *PFN_vkCreateMetalSurfaceEXT)(VkInstance,const VkMetalSurfaceCreateInfoEXT*,const VkAllocationCallbacks*,VkSurfaceKHR*);

#include "posix_thread.h"
#include "cocoa_joystick.h"
#include "nsgl_context.h"

#define _glfw_dlopen(name) dlopen(name, RTLD_LAZY | RTLD_LOCAL)
#define _glfw_dlclose(handle) dlclose(handle)
#define _glfw_dlsym(handle, name) dlsym(handle, name)

#define _GLFW_PLATFORM_WINDOW_STATE         _GLFWwindowNS  ns
#define _GLFW_PLATFORM_LIBRARY_WINDOW_STATE _GLFWlibraryNS ns
#define _GLFW_PLATFORM_LIBRARY_TIMER_STATE  _GLFWtimerNS   ns
#define _GLFW_PLATFORM_MONITOR_STATE        _GLFWmonitorNS ns
#define _GLFW_PLATFORM_CURSOR_STATE         _GLFWcursorNS  ns

// HIToolbox.framework pointer typedefs
#define kTISPropertyUnicodeKeyLayoutData _glfw.ns.tis.kPropertyUnicodeKeyLayoutData
typedef TISInputSourceRef (*PFN_TISCopyCurrentKeyboardLayoutInputSource)(void);
#define TISCopyCurrentKeyboardLayoutInputSource _glfw.ns.tis.CopyCurrentKeyboardLayoutInputSource
typedef void* (*PFN_TISGetInputSourceProperty)(TISInputSourceRef,CFStringRef);
#define TISGetInputSourceProperty _glfw.ns.tis.GetInputSourceProperty
typedef UInt8 (*PFN_LMGetKbdType)(void);
#define LMGetKbdType _glfw.ns.tis.GetKbdType


// Cocoa-specific per-window data
//
typedef struct _GLFWwindowNS
{
    id              object;
    id              delegate;
    id              view;
    id              layer;

    bool            maximized;
    bool            retina;
    bool            in_traditional_fullscreen;
    bool            in_fullscreen_transition;
    bool            titlebar_hidden;
    unsigned long   pre_full_screen_style_mask;

    // Cached window properties to filter out duplicate events
    int             width, height;
    int             fbWidth, fbHeight;
    float           xscale, yscale;
    int             blur_radius;

    // The total sum of the distances the cursor has been warped
    // since the last cursor motion event was processed
    // This is kept to counteract Cocoa doing the same internally
    double          cursorWarpDeltaX, cursorWarpDeltaY;

    // The text input filter callback
    GLFWcocoatextinputfilterfun textInputFilterCallback;
    // The toggle fullscreen intercept callback
    GLFWcocoatogglefullscreenfun toggleFullscreenCallback;
    // Dead key state
    UInt32 deadKeyState;

    // Layer shell windows
    struct {
        bool is_active;
        GLFWLayerShellConfig config;
    } layer_shell;

    // Whether a render frame has been requested for this window
    bool renderFrameRequested;
    GLFWcocoarenderframefun renderFrameCallback;
    // update cursor after switching desktops with Mission Control
    bool delayed_cursor_update_requested;
    GLFWcocoarenderframefun resizeCallback;
} _GLFWwindowNS;

// Cocoa-specific global data
//
typedef struct _GLFWlibraryNS
{
    CGEventSourceRef    eventSource;
    id                  delegate;
    bool                finishedLaunching;
    bool                cursorHidden;
    TISInputSourceRef   inputSource;
    IOHIDManagerRef     hidManager;
    id                  unicodeData;
    id                  helper;
    id                  keyUpMonitor, keyDownMonitor, flagsChangedMonitor;
    id                  appleSettings;
    id                  nibObjects;

    char                keyName[64];
    char                text[512];
    CGPoint             cascadePoint;
    // Where to place the cursor when re-enabled
    double              restoreCursorPosX, restoreCursorPosY;
    // The window whose disabled cursor mode is active
    _GLFWwindow*        disabledCursorWindow;
    pid_t           previous_front_most_application;

    struct {
        CFBundleRef     bundle;
        PFN_TISCopyCurrentKeyboardLayoutInputSource CopyCurrentKeyboardLayoutInputSource;
        PFN_TISGetInputSourceProperty GetInputSourceProperty;
        PFN_LMGetKbdType GetKbdType;
        CFStringRef     kPropertyUnicodeKeyLayoutData;
    } tis;

    // the callback to handle url open events
    GLFWhandleurlopen url_open_callback;

} _GLFWlibraryNS;

// Cocoa-specific per-monitor data
//
typedef struct _GLFWmonitorNS
{
    CGDirectDisplayID   displayID;
    CGDisplayModeRef    previousMode;
    uint32_t            unitNumber;
    id                  screen;
    double              fallbackRefreshRate;

} _GLFWmonitorNS;

// Cocoa-specific per-cursor data
//
typedef struct _GLFWcursorNS
{
    id              object;

} _GLFWcursorNS;

// Cocoa-specific global timer data
//
typedef struct _GLFWtimerNS
{
    uint64_t        frequency;

} _GLFWtimerNS;

void _glfwPollMonitorsNS(void);
void _glfwSetVideoModeNS(_GLFWmonitor* monitor, const GLFWvidmode* desired);
void _glfwRestoreVideoModeNS(_GLFWmonitor* monitor);

float _glfwTransformYNS(float y);

void* _glfwLoadLocalVulkanLoaderNS(void);


// display links
void _glfwClearDisplayLinks(void);
void _glfwRestartDisplayLinks(void);
unsigned _glfwCreateDisplayLink(CGDirectDisplayID);
void _glfwDispatchRenderFrame(CGDirectDisplayID);
void _glfwRequestRenderFrame(_GLFWwindow *w);

// event loop
void _glfwDispatchTickCallback(void);
void _glfwCocoaPostEmptyEvent(void);

uint32_t vk_to_unicode_key_with_current_layout(uint16_t keycode);
