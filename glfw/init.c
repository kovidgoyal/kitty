//========================================================================
// GLFW 3.4 - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2002-2006 Marcus Geelnard
// Copyright (c) 2006-2018 Camilla Löwy <elmindreda@glfw.org>
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
// Please use C89 style variable declarations in this file because VS 2010
//========================================================================

#include "internal.h"
#include "mappings.h"

#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <stdarg.h>


// The global variables below comprise all mutable global data in GLFW
//
// Any other global variable is a bug

// Global state shared between compilation units of GLFW
//
_GLFWlibrary _glfw = { false };

// These are outside of _glfw so they can be used before initialization and
// after termination
//
static _GLFWerror _glfwMainThreadError;
static GLFWerrorfun _glfwErrorCallback;
static _GLFWinitconfig _glfwInitHints = {
    .hatButtons = true,
    .angleType = GLFW_ANGLE_PLATFORM_TYPE_NONE,
    .debugKeyboard = false,
    .debugRendering = false,
    .ns = {
        .menubar = true,  // macOS menu bar
        .chdir = true   // macOS bundle chdir
    },
    .wl = {
        .ime = true,  // Wayland IME support
    },
};

// Terminate the library
//
static void terminate(void)
{
    int i;

    memset(&_glfw.callbacks, 0, sizeof(_glfw.callbacks));
    _glfw_free_clipboard_data(&_glfw.clipboard);
    _glfw_free_clipboard_data(&_glfw.primary);

    while (_glfw.windowListHead)
        glfwDestroyWindow((GLFWwindow*) _glfw.windowListHead);

    while (_glfw.cursorListHead)
        glfwDestroyCursor((GLFWcursor*) _glfw.cursorListHead);

    for (i = 0;  i < _glfw.monitorCount;  i++)
    {
        _GLFWmonitor* monitor = _glfw.monitors[i];
        if (monitor->originalRamp.size)
            _glfwPlatformSetGammaRamp(monitor, &monitor->originalRamp);
        _glfwFreeMonitor(monitor);
    }

    free(_glfw.monitors);
    _glfw.monitors = NULL;
    _glfw.monitorCount = 0;

    free(_glfw.mappings);
    _glfw.mappings = NULL;
    _glfw.mappingCount = 0;

    _glfwTerminateVulkan();
    _glfwPlatformTerminateJoysticks();
    _glfwPlatformTerminate();

    _glfw.initialized = false;

    while (_glfw.errorListHead)
    {
        _GLFWerror* error = _glfw.errorListHead;
        _glfw.errorListHead = error->next;
        free(error);
    }

    _glfwPlatformDestroyTls(&_glfw.contextSlot);
    _glfwPlatformDestroyTls(&_glfw.errorSlot);
    _glfwPlatformDestroyMutex(&_glfw.errorLock);

    memset(&_glfw, 0, sizeof(_glfw));
}


//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

char* _glfw_strdup(const char* source)
{
    const size_t length = strlen(source);
    char* result = malloc(length + 1);
    memcpy(result, source, length);
    result[length] = 0;
    return result;
}


//////////////////////////////////////////////////////////////////////////
//////                         GLFW event API                       //////
//////////////////////////////////////////////////////////////////////////

// Notifies shared code of an error
//
void _glfwInputError(int code, const char* format, ...)
{
    _GLFWerror* error;
    char description[_GLFW_MESSAGE_SIZE];

    if (format)
    {
        va_list vl;

        va_start(vl, format);
        vsnprintf(description, sizeof(description), format, vl);
        va_end(vl);

        description[sizeof(description) - 1] = '\0';
    }
    else
    {
        if (code == GLFW_NOT_INITIALIZED)
            strcpy(description, "The GLFW library is not initialized");
        else if (code == GLFW_NO_CURRENT_CONTEXT)
            strcpy(description, "There is no current context");
        else if (code == GLFW_INVALID_ENUM)
            strcpy(description, "Invalid argument for enum parameter");
        else if (code == GLFW_INVALID_VALUE)
            strcpy(description, "Invalid value for parameter");
        else if (code == GLFW_OUT_OF_MEMORY)
            strcpy(description, "Out of memory");
        else if (code == GLFW_API_UNAVAILABLE)
            strcpy(description, "The requested API is unavailable");
        else if (code == GLFW_VERSION_UNAVAILABLE)
            strcpy(description, "The requested API version is unavailable");
        else if (code == GLFW_PLATFORM_ERROR)
            strcpy(description, "A platform-specific error occurred");
        else if (code == GLFW_FORMAT_UNAVAILABLE)
            strcpy(description, "The requested format is unavailable");
        else if (code == GLFW_NO_WINDOW_CONTEXT)
            strcpy(description, "The specified window has no context");
        else if (code == GLFW_FEATURE_UNAVAILABLE)
            strcpy(description, "The requested feature cannot be implemented for this platform");
        else if (code == GLFW_FEATURE_UNIMPLEMENTED)
            strcpy(description, "The requested feature has not yet been implemented for this platform");
        else
            strcpy(description, "ERROR: UNKNOWN GLFW ERROR");
    }

    if (_glfw.initialized)
    {
        error = _glfwPlatformGetTls(&_glfw.errorSlot);
        if (!error)
        {
            error = calloc(1, sizeof(_GLFWerror));
            _glfwPlatformSetTls(&_glfw.errorSlot, error);
            _glfwPlatformLockMutex(&_glfw.errorLock);
            error->next = _glfw.errorListHead;
            _glfw.errorListHead = error;
            _glfwPlatformUnlockMutex(&_glfw.errorLock);
        }
    }
    else
        error = &_glfwMainThreadError;

    error->code = code;
    strcpy(error->description, description);

    if (_glfwErrorCallback)
        _glfwErrorCallback(code, description);
}

void
_glfwDebug(const char *format, ...) {
    if (format)
    {
        va_list vl;

        fprintf(stderr, "[%.3f] ", monotonic_t_to_s_double(monotonic()));
        va_start(vl, format);
        vfprintf(stderr, format, vl);
        va_end(vl);
        fprintf(stderr, "\n");
    }

}

//////////////////////////////////////////////////////////////////////////
//////                        GLFW public API                       //////
//////////////////////////////////////////////////////////////////////////

GLFWAPI int glfwInit(monotonic_t start_time, bool *supports_window_occlusion)
{
    *supports_window_occlusion = false;
    if (_glfw.initialized)
        return true;
    monotonic_start_time = start_time;

    memset(&_glfw, 0, sizeof(_glfw));
    _glfw.hints.init = _glfwInitHints;
    _glfw.ignoreOSKeyboardProcessing = false;

    if (!_glfwPlatformInit(supports_window_occlusion))
    {
        terminate();
        return false;
    }

    if (!_glfwPlatformCreateMutex(&_glfw.errorLock) ||
        !_glfwPlatformCreateTls(&_glfw.errorSlot) ||
        !_glfwPlatformCreateTls(&_glfw.contextSlot))
    {
        terminate();
        return false;
    }

    _glfwPlatformSetTls(&_glfw.errorSlot, &_glfwMainThreadError);

    _glfw.initialized = true;

    glfwDefaultWindowHints();

    {
        int i;

        for (i = 0;  _glfwDefaultMappings[i];  i++)
        {
            if (!glfwUpdateGamepadMappings(_glfwDefaultMappings[i]))
            {
                terminate();
                return false;
            }
        }
    }

    return true;
}

GLFWAPI void glfwTerminate(void)
{
    if (!_glfw.initialized)
        return;

    terminate();
}

GLFWAPI void glfwInitHint(int hint, int value)
{
    switch (hint)
    {
        case GLFW_JOYSTICK_HAT_BUTTONS:
            _glfwInitHints.hatButtons = value;
            return;
        case GLFW_ANGLE_PLATFORM_TYPE:
            _glfwInitHints.angleType = value;
            return;
        case GLFW_DEBUG_KEYBOARD:
            _glfwInitHints.debugKeyboard = value;
            return;
        case GLFW_DEBUG_RENDERING:
            _glfwInitHints.debugRendering = value;
            return;
        case GLFW_COCOA_CHDIR_RESOURCES:
            _glfwInitHints.ns.chdir = value;
            return;
        case GLFW_COCOA_MENUBAR:
            _glfwInitHints.ns.menubar = value;
            return;
        case GLFW_WAYLAND_IME:
            _glfwInitHints.wl.ime = value;
            return;
    }

    _glfwInputError(GLFW_INVALID_ENUM,
                    "Invalid init hint 0x%08X", hint);
}

GLFWAPI void glfwGetVersion(int* major, int* minor, int* rev)
{
    if (major != NULL)
        *major = GLFW_VERSION_MAJOR;
    if (minor != NULL)
        *minor = GLFW_VERSION_MINOR;
    if (rev != NULL)
        *rev = GLFW_VERSION_REVISION;
}

GLFWAPI const char* glfwGetVersionString(void)
{
    return _glfwPlatformGetVersionString();
}

GLFWAPI int glfwGetError(const char** description)
{
    _GLFWerror* error;
    int code = GLFW_NO_ERROR;

    if (description)
        *description = NULL;

    if (_glfw.initialized)
        error = _glfwPlatformGetTls(&_glfw.errorSlot);
    else
        error = &_glfwMainThreadError;

    if (error)
    {
        code = error->code;
        error->code = GLFW_NO_ERROR;
        if (description && code)
            *description = error->description;
    }

    return code;
}

GLFWAPI GLFWerrorfun glfwSetErrorCallback(GLFWerrorfun cbfun)
{
    _GLFW_SWAP_POINTERS(_glfwErrorCallback, cbfun);
    return cbfun;
}


GLFWAPI void glfwRunMainLoop(GLFWtickcallback callback, void *data)
{
    _GLFW_REQUIRE_INIT();
    _glfwPlatformRunMainLoop(callback, data);
}

GLFWAPI void glfwStopMainLoop(void) {
    _GLFW_REQUIRE_INIT();
    _glfwPlatformStopMainLoop();
}

GLFWAPI unsigned long long glfwAddTimer(
        monotonic_t interval, bool repeats, GLFWuserdatafun callback,
        void *callback_data, GLFWuserdatafun free_callback)
{
    return _glfwPlatformAddTimer(interval, repeats, callback, callback_data, free_callback);
}

GLFWAPI void glfwUpdateTimer(unsigned long long timer_id, monotonic_t interval, bool enabled) {
    _glfwPlatformUpdateTimer(timer_id, interval, enabled);
}

GLFWAPI void glfwRemoveTimer(unsigned long long timer_id) {
    _glfwPlatformRemoveTimer(timer_id);
}

GLFWAPI GLFWapplicationclosefun glfwSetApplicationCloseCallback(GLFWapplicationclosefun cbfun)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    _GLFW_SWAP_POINTERS(_glfw.callbacks.application_close, cbfun);
    return cbfun;
}

GLFWAPI GLFWsystemcolorthemechangefun glfwSetSystemColorThemeChangeCallback(GLFWsystemcolorthemechangefun cbfun)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    _GLFW_SWAP_POINTERS(_glfw.callbacks.system_color_theme_change, cbfun);
    return cbfun;
}

GLFWAPI GLFWclipboardlostfun glfwSetClipboardLostCallback(GLFWclipboardlostfun cbfun)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    _GLFW_SWAP_POINTERS(_glfw.callbacks.clipboard_lost, cbfun);
    return cbfun;
}


GLFWAPI GLFWdrawtextfun glfwSetDrawTextFunction(GLFWdrawtextfun cbfun)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    _GLFW_SWAP_POINTERS(_glfw.callbacks.draw_text, cbfun);
    return cbfun;
}

GLFWAPI GLFWcurrentselectionfun glfwSetCurrentSelectionCallback(GLFWcurrentselectionfun cbfun)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    _GLFW_SWAP_POINTERS(_glfw.callbacks.get_current_selection, cbfun);
    return cbfun;
}

GLFWAPI GLFWhascurrentselectionfun glfwSetHasCurrentSelectionCallback(GLFWhascurrentselectionfun cbfun)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    _GLFW_SWAP_POINTERS(_glfw.callbacks.has_current_selection, cbfun);
    return cbfun;
}

GLFWAPI GLFWimecursorpositionfun glfwSetIMECursorPositionCallback(GLFWimecursorpositionfun cbfun)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    _GLFW_SWAP_POINTERS(_glfw.callbacks.get_ime_cursor_position, cbfun);
    return cbfun;
}
