
#include "data-types.h"
#include "glfw-wrapper.h"
#include <dlfcn.h>

static void* handle = NULL;

#define fail(msg, ...) { snprintf(buf, sizeof(buf), msg, __VA_ARGS__); return buf; }

const char*
load_glfw(const char* path) {
    static char buf[2048];
    handle = dlopen(path, RTLD_LAZY);
    if (handle == NULL) fail("Failed to dlopen %s with error: %s", path, dlerror());
    dlerror();

    *(void **) (&glfwInit_impl) = dlsym(handle, "glfwInit");
    if (glfwInit_impl == NULL) fail("Failed to load glfw function glfwInit with error: %s", dlerror());

    *(void **) (&glfwRunMainLoop_impl) = dlsym(handle, "glfwRunMainLoop");
    if (glfwRunMainLoop_impl == NULL) fail("Failed to load glfw function glfwRunMainLoop with error: %s", dlerror());

    *(void **) (&glfwStopMainLoop_impl) = dlsym(handle, "glfwStopMainLoop");
    if (glfwStopMainLoop_impl == NULL) fail("Failed to load glfw function glfwStopMainLoop with error: %s", dlerror());

    *(void **) (&glfwRequestTickCallback_impl) = dlsym(handle, "glfwRequestTickCallback");
    if (glfwRequestTickCallback_impl == NULL) fail("Failed to load glfw function glfwRequestTickCallback with error: %s", dlerror());

    *(void **) (&glfwAddTimer_impl) = dlsym(handle, "glfwAddTimer");
    if (glfwAddTimer_impl == NULL) fail("Failed to load glfw function glfwAddTimer with error: %s", dlerror());

    *(void **) (&glfwUpdateTimer_impl) = dlsym(handle, "glfwUpdateTimer");
    if (glfwUpdateTimer_impl == NULL) fail("Failed to load glfw function glfwUpdateTimer with error: %s", dlerror());

    *(void **) (&glfwRemoveTimer_impl) = dlsym(handle, "glfwRemoveTimer");
    if (glfwRemoveTimer_impl == NULL) fail("Failed to load glfw function glfwRemoveTimer with error: %s", dlerror());

    *(void **) (&glfwTerminate_impl) = dlsym(handle, "glfwTerminate");
    if (glfwTerminate_impl == NULL) fail("Failed to load glfw function glfwTerminate with error: %s", dlerror());

    *(void **) (&glfwInitHint_impl) = dlsym(handle, "glfwInitHint");
    if (glfwInitHint_impl == NULL) fail("Failed to load glfw function glfwInitHint with error: %s", dlerror());

    *(void **) (&glfwGetVersion_impl) = dlsym(handle, "glfwGetVersion");
    if (glfwGetVersion_impl == NULL) fail("Failed to load glfw function glfwGetVersion with error: %s", dlerror());

    *(void **) (&glfwGetVersionString_impl) = dlsym(handle, "glfwGetVersionString");
    if (glfwGetVersionString_impl == NULL) fail("Failed to load glfw function glfwGetVersionString with error: %s", dlerror());

    *(void **) (&glfwGetError_impl) = dlsym(handle, "glfwGetError");
    if (glfwGetError_impl == NULL) fail("Failed to load glfw function glfwGetError with error: %s", dlerror());

    *(void **) (&glfwSetErrorCallback_impl) = dlsym(handle, "glfwSetErrorCallback");
    if (glfwSetErrorCallback_impl == NULL) fail("Failed to load glfw function glfwSetErrorCallback with error: %s", dlerror());

    *(void **) (&glfwGetMonitors_impl) = dlsym(handle, "glfwGetMonitors");
    if (glfwGetMonitors_impl == NULL) fail("Failed to load glfw function glfwGetMonitors with error: %s", dlerror());

    *(void **) (&glfwGetPrimaryMonitor_impl) = dlsym(handle, "glfwGetPrimaryMonitor");
    if (glfwGetPrimaryMonitor_impl == NULL) fail("Failed to load glfw function glfwGetPrimaryMonitor with error: %s", dlerror());

    *(void **) (&glfwGetMonitorPos_impl) = dlsym(handle, "glfwGetMonitorPos");
    if (glfwGetMonitorPos_impl == NULL) fail("Failed to load glfw function glfwGetMonitorPos with error: %s", dlerror());

    *(void **) (&glfwGetMonitorWorkarea_impl) = dlsym(handle, "glfwGetMonitorWorkarea");
    if (glfwGetMonitorWorkarea_impl == NULL) fail("Failed to load glfw function glfwGetMonitorWorkarea with error: %s", dlerror());

    *(void **) (&glfwGetMonitorPhysicalSize_impl) = dlsym(handle, "glfwGetMonitorPhysicalSize");
    if (glfwGetMonitorPhysicalSize_impl == NULL) fail("Failed to load glfw function glfwGetMonitorPhysicalSize with error: %s", dlerror());

    *(void **) (&glfwGetMonitorContentScale_impl) = dlsym(handle, "glfwGetMonitorContentScale");
    if (glfwGetMonitorContentScale_impl == NULL) fail("Failed to load glfw function glfwGetMonitorContentScale with error: %s", dlerror());

    *(void **) (&glfwGetMonitorName_impl) = dlsym(handle, "glfwGetMonitorName");
    if (glfwGetMonitorName_impl == NULL) fail("Failed to load glfw function glfwGetMonitorName with error: %s", dlerror());

    *(void **) (&glfwSetMonitorUserPointer_impl) = dlsym(handle, "glfwSetMonitorUserPointer");
    if (glfwSetMonitorUserPointer_impl == NULL) fail("Failed to load glfw function glfwSetMonitorUserPointer with error: %s", dlerror());

    *(void **) (&glfwGetMonitorUserPointer_impl) = dlsym(handle, "glfwGetMonitorUserPointer");
    if (glfwGetMonitorUserPointer_impl == NULL) fail("Failed to load glfw function glfwGetMonitorUserPointer with error: %s", dlerror());

    *(void **) (&glfwSetMonitorCallback_impl) = dlsym(handle, "glfwSetMonitorCallback");
    if (glfwSetMonitorCallback_impl == NULL) fail("Failed to load glfw function glfwSetMonitorCallback with error: %s", dlerror());

    *(void **) (&glfwGetVideoModes_impl) = dlsym(handle, "glfwGetVideoModes");
    if (glfwGetVideoModes_impl == NULL) fail("Failed to load glfw function glfwGetVideoModes with error: %s", dlerror());

    *(void **) (&glfwGetVideoMode_impl) = dlsym(handle, "glfwGetVideoMode");
    if (glfwGetVideoMode_impl == NULL) fail("Failed to load glfw function glfwGetVideoMode with error: %s", dlerror());

    *(void **) (&glfwSetGamma_impl) = dlsym(handle, "glfwSetGamma");
    if (glfwSetGamma_impl == NULL) fail("Failed to load glfw function glfwSetGamma with error: %s", dlerror());

    *(void **) (&glfwGetGammaRamp_impl) = dlsym(handle, "glfwGetGammaRamp");
    if (glfwGetGammaRamp_impl == NULL) fail("Failed to load glfw function glfwGetGammaRamp with error: %s", dlerror());

    *(void **) (&glfwSetGammaRamp_impl) = dlsym(handle, "glfwSetGammaRamp");
    if (glfwSetGammaRamp_impl == NULL) fail("Failed to load glfw function glfwSetGammaRamp with error: %s", dlerror());

    *(void **) (&glfwDefaultWindowHints_impl) = dlsym(handle, "glfwDefaultWindowHints");
    if (glfwDefaultWindowHints_impl == NULL) fail("Failed to load glfw function glfwDefaultWindowHints with error: %s", dlerror());

    *(void **) (&glfwWindowHint_impl) = dlsym(handle, "glfwWindowHint");
    if (glfwWindowHint_impl == NULL) fail("Failed to load glfw function glfwWindowHint with error: %s", dlerror());

    *(void **) (&glfwWindowHintString_impl) = dlsym(handle, "glfwWindowHintString");
    if (glfwWindowHintString_impl == NULL) fail("Failed to load glfw function glfwWindowHintString with error: %s", dlerror());

    *(void **) (&glfwCreateWindow_impl) = dlsym(handle, "glfwCreateWindow");
    if (glfwCreateWindow_impl == NULL) fail("Failed to load glfw function glfwCreateWindow with error: %s", dlerror());

    *(void **) (&glfwDestroyWindow_impl) = dlsym(handle, "glfwDestroyWindow");
    if (glfwDestroyWindow_impl == NULL) fail("Failed to load glfw function glfwDestroyWindow with error: %s", dlerror());

    *(void **) (&glfwWindowShouldClose_impl) = dlsym(handle, "glfwWindowShouldClose");
    if (glfwWindowShouldClose_impl == NULL) fail("Failed to load glfw function glfwWindowShouldClose with error: %s", dlerror());

    *(void **) (&glfwSetWindowShouldClose_impl) = dlsym(handle, "glfwSetWindowShouldClose");
    if (glfwSetWindowShouldClose_impl == NULL) fail("Failed to load glfw function glfwSetWindowShouldClose with error: %s", dlerror());

    *(void **) (&glfwSetWindowTitle_impl) = dlsym(handle, "glfwSetWindowTitle");
    if (glfwSetWindowTitle_impl == NULL) fail("Failed to load glfw function glfwSetWindowTitle with error: %s", dlerror());

    *(void **) (&glfwSetWindowIcon_impl) = dlsym(handle, "glfwSetWindowIcon");
    if (glfwSetWindowIcon_impl == NULL) fail("Failed to load glfw function glfwSetWindowIcon with error: %s", dlerror());

    *(void **) (&glfwGetWindowPos_impl) = dlsym(handle, "glfwGetWindowPos");
    if (glfwGetWindowPos_impl == NULL) fail("Failed to load glfw function glfwGetWindowPos with error: %s", dlerror());

    *(void **) (&glfwSetWindowPos_impl) = dlsym(handle, "glfwSetWindowPos");
    if (glfwSetWindowPos_impl == NULL) fail("Failed to load glfw function glfwSetWindowPos with error: %s", dlerror());

    *(void **) (&glfwGetWindowSize_impl) = dlsym(handle, "glfwGetWindowSize");
    if (glfwGetWindowSize_impl == NULL) fail("Failed to load glfw function glfwGetWindowSize with error: %s", dlerror());

    *(void **) (&glfwSetWindowSizeLimits_impl) = dlsym(handle, "glfwSetWindowSizeLimits");
    if (glfwSetWindowSizeLimits_impl == NULL) fail("Failed to load glfw function glfwSetWindowSizeLimits with error: %s", dlerror());

    *(void **) (&glfwSetWindowAspectRatio_impl) = dlsym(handle, "glfwSetWindowAspectRatio");
    if (glfwSetWindowAspectRatio_impl == NULL) fail("Failed to load glfw function glfwSetWindowAspectRatio with error: %s", dlerror());

    *(void **) (&glfwSetWindowSize_impl) = dlsym(handle, "glfwSetWindowSize");
    if (glfwSetWindowSize_impl == NULL) fail("Failed to load glfw function glfwSetWindowSize with error: %s", dlerror());

    *(void **) (&glfwGetFramebufferSize_impl) = dlsym(handle, "glfwGetFramebufferSize");
    if (glfwGetFramebufferSize_impl == NULL) fail("Failed to load glfw function glfwGetFramebufferSize with error: %s", dlerror());

    *(void **) (&glfwGetWindowFrameSize_impl) = dlsym(handle, "glfwGetWindowFrameSize");
    if (glfwGetWindowFrameSize_impl == NULL) fail("Failed to load glfw function glfwGetWindowFrameSize with error: %s", dlerror());

    *(void **) (&glfwGetWindowContentScale_impl) = dlsym(handle, "glfwGetWindowContentScale");
    if (glfwGetWindowContentScale_impl == NULL) fail("Failed to load glfw function glfwGetWindowContentScale with error: %s", dlerror());

    *(void **) (&glfwGetDoubleClickInterval_impl) = dlsym(handle, "glfwGetDoubleClickInterval");
    if (glfwGetDoubleClickInterval_impl == NULL) fail("Failed to load glfw function glfwGetDoubleClickInterval with error: %s", dlerror());

    *(void **) (&glfwGetWindowOpacity_impl) = dlsym(handle, "glfwGetWindowOpacity");
    if (glfwGetWindowOpacity_impl == NULL) fail("Failed to load glfw function glfwGetWindowOpacity with error: %s", dlerror());

    *(void **) (&glfwSetWindowOpacity_impl) = dlsym(handle, "glfwSetWindowOpacity");
    if (glfwSetWindowOpacity_impl == NULL) fail("Failed to load glfw function glfwSetWindowOpacity with error: %s", dlerror());

    *(void **) (&glfwIconifyWindow_impl) = dlsym(handle, "glfwIconifyWindow");
    if (glfwIconifyWindow_impl == NULL) fail("Failed to load glfw function glfwIconifyWindow with error: %s", dlerror());

    *(void **) (&glfwRestoreWindow_impl) = dlsym(handle, "glfwRestoreWindow");
    if (glfwRestoreWindow_impl == NULL) fail("Failed to load glfw function glfwRestoreWindow with error: %s", dlerror());

    *(void **) (&glfwMaximizeWindow_impl) = dlsym(handle, "glfwMaximizeWindow");
    if (glfwMaximizeWindow_impl == NULL) fail("Failed to load glfw function glfwMaximizeWindow with error: %s", dlerror());

    *(void **) (&glfwShowWindow_impl) = dlsym(handle, "glfwShowWindow");
    if (glfwShowWindow_impl == NULL) fail("Failed to load glfw function glfwShowWindow with error: %s", dlerror());

    *(void **) (&glfwHideWindow_impl) = dlsym(handle, "glfwHideWindow");
    if (glfwHideWindow_impl == NULL) fail("Failed to load glfw function glfwHideWindow with error: %s", dlerror());

    *(void **) (&glfwFocusWindow_impl) = dlsym(handle, "glfwFocusWindow");
    if (glfwFocusWindow_impl == NULL) fail("Failed to load glfw function glfwFocusWindow with error: %s", dlerror());

    *(void **) (&glfwRequestWindowAttention_impl) = dlsym(handle, "glfwRequestWindowAttention");
    if (glfwRequestWindowAttention_impl == NULL) fail("Failed to load glfw function glfwRequestWindowAttention with error: %s", dlerror());

    *(void **) (&glfwWindowBell_impl) = dlsym(handle, "glfwWindowBell");
    if (glfwWindowBell_impl == NULL) fail("Failed to load glfw function glfwWindowBell with error: %s", dlerror());

    *(void **) (&glfwGetWindowMonitor_impl) = dlsym(handle, "glfwGetWindowMonitor");
    if (glfwGetWindowMonitor_impl == NULL) fail("Failed to load glfw function glfwGetWindowMonitor with error: %s", dlerror());

    *(void **) (&glfwSetWindowMonitor_impl) = dlsym(handle, "glfwSetWindowMonitor");
    if (glfwSetWindowMonitor_impl == NULL) fail("Failed to load glfw function glfwSetWindowMonitor with error: %s", dlerror());

    *(void **) (&glfwGetWindowAttrib_impl) = dlsym(handle, "glfwGetWindowAttrib");
    if (glfwGetWindowAttrib_impl == NULL) fail("Failed to load glfw function glfwGetWindowAttrib with error: %s", dlerror());

    *(void **) (&glfwSetWindowAttrib_impl) = dlsym(handle, "glfwSetWindowAttrib");
    if (glfwSetWindowAttrib_impl == NULL) fail("Failed to load glfw function glfwSetWindowAttrib with error: %s", dlerror());

    *(void **) (&glfwSetWindowUserPointer_impl) = dlsym(handle, "glfwSetWindowUserPointer");
    if (glfwSetWindowUserPointer_impl == NULL) fail("Failed to load glfw function glfwSetWindowUserPointer with error: %s", dlerror());

    *(void **) (&glfwGetWindowUserPointer_impl) = dlsym(handle, "glfwGetWindowUserPointer");
    if (glfwGetWindowUserPointer_impl == NULL) fail("Failed to load glfw function glfwGetWindowUserPointer with error: %s", dlerror());

    *(void **) (&glfwSetWindowPosCallback_impl) = dlsym(handle, "glfwSetWindowPosCallback");
    if (glfwSetWindowPosCallback_impl == NULL) fail("Failed to load glfw function glfwSetWindowPosCallback with error: %s", dlerror());

    *(void **) (&glfwSetWindowSizeCallback_impl) = dlsym(handle, "glfwSetWindowSizeCallback");
    if (glfwSetWindowSizeCallback_impl == NULL) fail("Failed to load glfw function glfwSetWindowSizeCallback with error: %s", dlerror());

    *(void **) (&glfwSetWindowCloseCallback_impl) = dlsym(handle, "glfwSetWindowCloseCallback");
    if (glfwSetWindowCloseCallback_impl == NULL) fail("Failed to load glfw function glfwSetWindowCloseCallback with error: %s", dlerror());

    *(void **) (&glfwSetWindowRefreshCallback_impl) = dlsym(handle, "glfwSetWindowRefreshCallback");
    if (glfwSetWindowRefreshCallback_impl == NULL) fail("Failed to load glfw function glfwSetWindowRefreshCallback with error: %s", dlerror());

    *(void **) (&glfwSetWindowFocusCallback_impl) = dlsym(handle, "glfwSetWindowFocusCallback");
    if (glfwSetWindowFocusCallback_impl == NULL) fail("Failed to load glfw function glfwSetWindowFocusCallback with error: %s", dlerror());

    *(void **) (&glfwSetWindowOcclusionCallback_impl) = dlsym(handle, "glfwSetWindowOcclusionCallback");
    if (glfwSetWindowOcclusionCallback_impl == NULL) fail("Failed to load glfw function glfwSetWindowOcclusionCallback with error: %s", dlerror());

    *(void **) (&glfwSetWindowIconifyCallback_impl) = dlsym(handle, "glfwSetWindowIconifyCallback");
    if (glfwSetWindowIconifyCallback_impl == NULL) fail("Failed to load glfw function glfwSetWindowIconifyCallback with error: %s", dlerror());

    *(void **) (&glfwSetWindowMaximizeCallback_impl) = dlsym(handle, "glfwSetWindowMaximizeCallback");
    if (glfwSetWindowMaximizeCallback_impl == NULL) fail("Failed to load glfw function glfwSetWindowMaximizeCallback with error: %s", dlerror());

    *(void **) (&glfwSetFramebufferSizeCallback_impl) = dlsym(handle, "glfwSetFramebufferSizeCallback");
    if (glfwSetFramebufferSizeCallback_impl == NULL) fail("Failed to load glfw function glfwSetFramebufferSizeCallback with error: %s", dlerror());

    *(void **) (&glfwSetWindowContentScaleCallback_impl) = dlsym(handle, "glfwSetWindowContentScaleCallback");
    if (glfwSetWindowContentScaleCallback_impl == NULL) fail("Failed to load glfw function glfwSetWindowContentScaleCallback with error: %s", dlerror());

    *(void **) (&glfwPostEmptyEvent_impl) = dlsym(handle, "glfwPostEmptyEvent");
    if (glfwPostEmptyEvent_impl == NULL) fail("Failed to load glfw function glfwPostEmptyEvent with error: %s", dlerror());

    *(void **) (&glfwGetInputMode_impl) = dlsym(handle, "glfwGetInputMode");
    if (glfwGetInputMode_impl == NULL) fail("Failed to load glfw function glfwGetInputMode with error: %s", dlerror());

    *(void **) (&glfwSetInputMode_impl) = dlsym(handle, "glfwSetInputMode");
    if (glfwSetInputMode_impl == NULL) fail("Failed to load glfw function glfwSetInputMode with error: %s", dlerror());

    *(void **) (&glfwGetKeyName_impl) = dlsym(handle, "glfwGetKeyName");
    if (glfwGetKeyName_impl == NULL) fail("Failed to load glfw function glfwGetKeyName with error: %s", dlerror());

    *(void **) (&glfwGetKeyScancode_impl) = dlsym(handle, "glfwGetKeyScancode");
    if (glfwGetKeyScancode_impl == NULL) fail("Failed to load glfw function glfwGetKeyScancode with error: %s", dlerror());

    *(void **) (&glfwGetKey_impl) = dlsym(handle, "glfwGetKey");
    if (glfwGetKey_impl == NULL) fail("Failed to load glfw function glfwGetKey with error: %s", dlerror());

    *(void **) (&glfwGetMouseButton_impl) = dlsym(handle, "glfwGetMouseButton");
    if (glfwGetMouseButton_impl == NULL) fail("Failed to load glfw function glfwGetMouseButton with error: %s", dlerror());

    *(void **) (&glfwGetCursorPos_impl) = dlsym(handle, "glfwGetCursorPos");
    if (glfwGetCursorPos_impl == NULL) fail("Failed to load glfw function glfwGetCursorPos with error: %s", dlerror());

    *(void **) (&glfwSetCursorPos_impl) = dlsym(handle, "glfwSetCursorPos");
    if (glfwSetCursorPos_impl == NULL) fail("Failed to load glfw function glfwSetCursorPos with error: %s", dlerror());

    *(void **) (&glfwCreateCursor_impl) = dlsym(handle, "glfwCreateCursor");
    if (glfwCreateCursor_impl == NULL) fail("Failed to load glfw function glfwCreateCursor with error: %s", dlerror());

    *(void **) (&glfwCreateStandardCursor_impl) = dlsym(handle, "glfwCreateStandardCursor");
    if (glfwCreateStandardCursor_impl == NULL) fail("Failed to load glfw function glfwCreateStandardCursor with error: %s", dlerror());

    *(void **) (&glfwDestroyCursor_impl) = dlsym(handle, "glfwDestroyCursor");
    if (glfwDestroyCursor_impl == NULL) fail("Failed to load glfw function glfwDestroyCursor with error: %s", dlerror());

    *(void **) (&glfwSetCursor_impl) = dlsym(handle, "glfwSetCursor");
    if (glfwSetCursor_impl == NULL) fail("Failed to load glfw function glfwSetCursor with error: %s", dlerror());

    *(void **) (&glfwSetKeyboardCallback_impl) = dlsym(handle, "glfwSetKeyboardCallback");
    if (glfwSetKeyboardCallback_impl == NULL) fail("Failed to load glfw function glfwSetKeyboardCallback with error: %s", dlerror());

    *(void **) (&glfwUpdateIMEState_impl) = dlsym(handle, "glfwUpdateIMEState");
    if (glfwUpdateIMEState_impl == NULL) fail("Failed to load glfw function glfwUpdateIMEState with error: %s", dlerror());

    *(void **) (&glfwSetMouseButtonCallback_impl) = dlsym(handle, "glfwSetMouseButtonCallback");
    if (glfwSetMouseButtonCallback_impl == NULL) fail("Failed to load glfw function glfwSetMouseButtonCallback with error: %s", dlerror());

    *(void **) (&glfwSetCursorPosCallback_impl) = dlsym(handle, "glfwSetCursorPosCallback");
    if (glfwSetCursorPosCallback_impl == NULL) fail("Failed to load glfw function glfwSetCursorPosCallback with error: %s", dlerror());

    *(void **) (&glfwSetCursorEnterCallback_impl) = dlsym(handle, "glfwSetCursorEnterCallback");
    if (glfwSetCursorEnterCallback_impl == NULL) fail("Failed to load glfw function glfwSetCursorEnterCallback with error: %s", dlerror());

    *(void **) (&glfwSetScrollCallback_impl) = dlsym(handle, "glfwSetScrollCallback");
    if (glfwSetScrollCallback_impl == NULL) fail("Failed to load glfw function glfwSetScrollCallback with error: %s", dlerror());

    *(void **) (&glfwSetDropCallback_impl) = dlsym(handle, "glfwSetDropCallback");
    if (glfwSetDropCallback_impl == NULL) fail("Failed to load glfw function glfwSetDropCallback with error: %s", dlerror());

    *(void **) (&glfwSetLiveResizeCallback_impl) = dlsym(handle, "glfwSetLiveResizeCallback");
    if (glfwSetLiveResizeCallback_impl == NULL) fail("Failed to load glfw function glfwSetLiveResizeCallback with error: %s", dlerror());

    *(void **) (&glfwJoystickPresent_impl) = dlsym(handle, "glfwJoystickPresent");
    if (glfwJoystickPresent_impl == NULL) fail("Failed to load glfw function glfwJoystickPresent with error: %s", dlerror());

    *(void **) (&glfwGetJoystickAxes_impl) = dlsym(handle, "glfwGetJoystickAxes");
    if (glfwGetJoystickAxes_impl == NULL) fail("Failed to load glfw function glfwGetJoystickAxes with error: %s", dlerror());

    *(void **) (&glfwGetJoystickButtons_impl) = dlsym(handle, "glfwGetJoystickButtons");
    if (glfwGetJoystickButtons_impl == NULL) fail("Failed to load glfw function glfwGetJoystickButtons with error: %s", dlerror());

    *(void **) (&glfwGetJoystickHats_impl) = dlsym(handle, "glfwGetJoystickHats");
    if (glfwGetJoystickHats_impl == NULL) fail("Failed to load glfw function glfwGetJoystickHats with error: %s", dlerror());

    *(void **) (&glfwGetJoystickName_impl) = dlsym(handle, "glfwGetJoystickName");
    if (glfwGetJoystickName_impl == NULL) fail("Failed to load glfw function glfwGetJoystickName with error: %s", dlerror());

    *(void **) (&glfwGetJoystickGUID_impl) = dlsym(handle, "glfwGetJoystickGUID");
    if (glfwGetJoystickGUID_impl == NULL) fail("Failed to load glfw function glfwGetJoystickGUID with error: %s", dlerror());

    *(void **) (&glfwSetJoystickUserPointer_impl) = dlsym(handle, "glfwSetJoystickUserPointer");
    if (glfwSetJoystickUserPointer_impl == NULL) fail("Failed to load glfw function glfwSetJoystickUserPointer with error: %s", dlerror());

    *(void **) (&glfwGetJoystickUserPointer_impl) = dlsym(handle, "glfwGetJoystickUserPointer");
    if (glfwGetJoystickUserPointer_impl == NULL) fail("Failed to load glfw function glfwGetJoystickUserPointer with error: %s", dlerror());

    *(void **) (&glfwJoystickIsGamepad_impl) = dlsym(handle, "glfwJoystickIsGamepad");
    if (glfwJoystickIsGamepad_impl == NULL) fail("Failed to load glfw function glfwJoystickIsGamepad with error: %s", dlerror());

    *(void **) (&glfwSetJoystickCallback_impl) = dlsym(handle, "glfwSetJoystickCallback");
    if (glfwSetJoystickCallback_impl == NULL) fail("Failed to load glfw function glfwSetJoystickCallback with error: %s", dlerror());

    *(void **) (&glfwUpdateGamepadMappings_impl) = dlsym(handle, "glfwUpdateGamepadMappings");
    if (glfwUpdateGamepadMappings_impl == NULL) fail("Failed to load glfw function glfwUpdateGamepadMappings with error: %s", dlerror());

    *(void **) (&glfwGetGamepadName_impl) = dlsym(handle, "glfwGetGamepadName");
    if (glfwGetGamepadName_impl == NULL) fail("Failed to load glfw function glfwGetGamepadName with error: %s", dlerror());

    *(void **) (&glfwGetGamepadState_impl) = dlsym(handle, "glfwGetGamepadState");
    if (glfwGetGamepadState_impl == NULL) fail("Failed to load glfw function glfwGetGamepadState with error: %s", dlerror());

    *(void **) (&glfwSetClipboardString_impl) = dlsym(handle, "glfwSetClipboardString");
    if (glfwSetClipboardString_impl == NULL) fail("Failed to load glfw function glfwSetClipboardString with error: %s", dlerror());

    *(void **) (&glfwGetClipboardString_impl) = dlsym(handle, "glfwGetClipboardString");
    if (glfwGetClipboardString_impl == NULL) fail("Failed to load glfw function glfwGetClipboardString with error: %s", dlerror());

    *(void **) (&glfwGetTime_impl) = dlsym(handle, "glfwGetTime");
    if (glfwGetTime_impl == NULL) fail("Failed to load glfw function glfwGetTime with error: %s", dlerror());

    *(void **) (&glfwSetTime_impl) = dlsym(handle, "glfwSetTime");
    if (glfwSetTime_impl == NULL) fail("Failed to load glfw function glfwSetTime with error: %s", dlerror());

    *(void **) (&glfwGetTimerValue_impl) = dlsym(handle, "glfwGetTimerValue");
    if (glfwGetTimerValue_impl == NULL) fail("Failed to load glfw function glfwGetTimerValue with error: %s", dlerror());

    *(void **) (&glfwGetTimerFrequency_impl) = dlsym(handle, "glfwGetTimerFrequency");
    if (glfwGetTimerFrequency_impl == NULL) fail("Failed to load glfw function glfwGetTimerFrequency with error: %s", dlerror());

    *(void **) (&glfwMakeContextCurrent_impl) = dlsym(handle, "glfwMakeContextCurrent");
    if (glfwMakeContextCurrent_impl == NULL) fail("Failed to load glfw function glfwMakeContextCurrent with error: %s", dlerror());

    *(void **) (&glfwGetCurrentContext_impl) = dlsym(handle, "glfwGetCurrentContext");
    if (glfwGetCurrentContext_impl == NULL) fail("Failed to load glfw function glfwGetCurrentContext with error: %s", dlerror());

    *(void **) (&glfwSwapBuffers_impl) = dlsym(handle, "glfwSwapBuffers");
    if (glfwSwapBuffers_impl == NULL) fail("Failed to load glfw function glfwSwapBuffers with error: %s", dlerror());

    *(void **) (&glfwSwapInterval_impl) = dlsym(handle, "glfwSwapInterval");
    if (glfwSwapInterval_impl == NULL) fail("Failed to load glfw function glfwSwapInterval with error: %s", dlerror());

    *(void **) (&glfwExtensionSupported_impl) = dlsym(handle, "glfwExtensionSupported");
    if (glfwExtensionSupported_impl == NULL) fail("Failed to load glfw function glfwExtensionSupported with error: %s", dlerror());

    *(void **) (&glfwGetProcAddress_impl) = dlsym(handle, "glfwGetProcAddress");
    if (glfwGetProcAddress_impl == NULL) fail("Failed to load glfw function glfwGetProcAddress with error: %s", dlerror());

    *(void **) (&glfwVulkanSupported_impl) = dlsym(handle, "glfwVulkanSupported");
    if (glfwVulkanSupported_impl == NULL) fail("Failed to load glfw function glfwVulkanSupported with error: %s", dlerror());

    *(void **) (&glfwGetRequiredInstanceExtensions_impl) = dlsym(handle, "glfwGetRequiredInstanceExtensions");
    if (glfwGetRequiredInstanceExtensions_impl == NULL) fail("Failed to load glfw function glfwGetRequiredInstanceExtensions with error: %s", dlerror());

    *(void **) (&glfwGetCocoaWindow_impl) = dlsym(handle, "glfwGetCocoaWindow");

    *(void **) (&glfwGetNSGLContext_impl) = dlsym(handle, "glfwGetNSGLContext");

    *(void **) (&glfwGetCocoaMonitor_impl) = dlsym(handle, "glfwGetCocoaMonitor");

    *(void **) (&glfwSetCocoaTextInputFilter_impl) = dlsym(handle, "glfwSetCocoaTextInputFilter");

    *(void **) (&glfwSetCocoaToggleFullscreenIntercept_impl) = dlsym(handle, "glfwSetCocoaToggleFullscreenIntercept");

    *(void **) (&glfwSetApplicationShouldHandleReopen_impl) = dlsym(handle, "glfwSetApplicationShouldHandleReopen");

    *(void **) (&glfwGetCocoaKeyEquivalent_impl) = dlsym(handle, "glfwGetCocoaKeyEquivalent");

    *(void **) (&glfwCocoaRequestRenderFrame_impl) = dlsym(handle, "glfwCocoaRequestRenderFrame");

    *(void **) (&glfwGetX11Display_impl) = dlsym(handle, "glfwGetX11Display");

    *(void **) (&glfwGetX11Window_impl) = dlsym(handle, "glfwGetX11Window");

    *(void **) (&glfwSetPrimarySelectionString_impl) = dlsym(handle, "glfwSetPrimarySelectionString");

    *(void **) (&glfwGetPrimarySelectionString_impl) = dlsym(handle, "glfwGetPrimarySelectionString");

    *(void **) (&glfwGetXKBScancode_impl) = dlsym(handle, "glfwGetXKBScancode");

    *(void **) (&glfwRequestWaylandFrameEvent_impl) = dlsym(handle, "glfwRequestWaylandFrameEvent");

    *(void **) (&glfwDBusUserNotify_impl) = dlsym(handle, "glfwDBusUserNotify");

    *(void **) (&glfwDBusSetUserNotificationHandler_impl) = dlsym(handle, "glfwDBusSetUserNotificationHandler");

    return NULL;
}

void
unload_glfw() {
    if (handle) { dlclose(handle); handle = NULL; }
}
