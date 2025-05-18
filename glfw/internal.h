//========================================================================
// GLFW 3.4 - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2002-2006 Marcus Geelnard
// Copyright (c) 2006-2019 Camilla Löwy <elmindreda@glfw.org>
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

#pragma once

#include "../kitty/monotonic.h"

#if defined(_GLFW_USE_CONFIG_H)
 #include "glfw_config.h"
#endif

#define arraysz(x) (sizeof(x)/sizeof(x[0]))
#define MAX(x, y) __extension__ ({ \
    __typeof__ (x) a = (x); __typeof__ (y) b = (y); \
        a > b ? a : b;})

#if defined(GLFW_INCLUDE_GLCOREARB) || \
    defined(GLFW_INCLUDE_ES1)       || \
    defined(GLFW_INCLUDE_ES2)       || \
    defined(GLFW_INCLUDE_ES3)       || \
    defined(GLFW_INCLUDE_ES31)      || \
    defined(GLFW_INCLUDE_ES32)      || \
    defined(GLFW_INCLUDE_NONE)      || \
    defined(GLFW_INCLUDE_GLEXT)     || \
    defined(GLFW_INCLUDE_GLU)       || \
    defined(GLFW_INCLUDE_VULKAN)    || \
    defined(GLFW_DLL)
 #error "You must not define any header option macros when compiling GLFW"
#endif

#define GLFW_INCLUDE_NONE
#include "glfw3.h"

#define EGL_PRESENT_OPAQUE_EXT 0x31df

#define _GLFW_INSERT_FIRST      0
#define _GLFW_INSERT_LAST       1

#define _GLFW_POLL_PRESENCE     0
#define _GLFW_POLL_AXES         1
#define _GLFW_POLL_BUTTONS      2
#define _GLFW_POLL_ALL          (_GLFW_POLL_AXES | _GLFW_POLL_BUTTONS)

#define _GLFW_MESSAGE_SIZE      1024

typedef unsigned long long GLFWid;

typedef struct _GLFWerror       _GLFWerror;
typedef struct _GLFWinitconfig  _GLFWinitconfig;
typedef struct _GLFWwndconfig   _GLFWwndconfig;
typedef struct _GLFWctxconfig   _GLFWctxconfig;
typedef struct _GLFWfbconfig    _GLFWfbconfig;
typedef struct _GLFWcontext     _GLFWcontext;
typedef struct _GLFWwindow      _GLFWwindow;
typedef struct _GLFWlibrary     _GLFWlibrary;
typedef struct _GLFWmonitor     _GLFWmonitor;
typedef struct _GLFWcursor      _GLFWcursor;
typedef struct _GLFWmapelement  _GLFWmapelement;
typedef struct _GLFWmapping     _GLFWmapping;
typedef struct _GLFWjoystick    _GLFWjoystick;
typedef struct _GLFWtls         _GLFWtls;
typedef struct _GLFWmutex       _GLFWmutex;

typedef void (* _GLFWmakecontextcurrentfun)(_GLFWwindow*);
typedef void (* _GLFWswapbuffersfun)(_GLFWwindow*);
typedef void (* _GLFWswapintervalfun)(int);
typedef int (* _GLFWextensionsupportedfun)(const char*);
typedef GLFWglproc (* _GLFWgetprocaddressfun)(const char*);
typedef void (* _GLFWdestroycontextfun)(_GLFWwindow*);

#define GL_VERSION 0x1F02
#define GL_NONE 0
#define GL_COLOR_BUFFER_BIT 0x00004000
#define GL_UNSIGNED_BYTE 0x1401
#define GL_EXTENSIONS 0x1F03
#define GL_NUM_EXTENSIONS 0x821d
#define GL_CONTEXT_FLAGS 0x821e
#define GL_CONTEXT_FLAG_FORWARD_COMPATIBLE_BIT 0x00000001
#define GL_CONTEXT_FLAG_DEBUG_BIT 0x00000002
#define GL_CONTEXT_PROFILE_MASK 0x9126
#define GL_CONTEXT_COMPATIBILITY_PROFILE_BIT 0x00000002
#define GL_CONTEXT_CORE_PROFILE_BIT 0x00000001
#define GL_RESET_NOTIFICATION_STRATEGY_ARB 0x8256
#define GL_LOSE_CONTEXT_ON_RESET_ARB 0x8252
#define GL_NO_RESET_NOTIFICATION_ARB 0x8261
#define GL_CONTEXT_RELEASE_BEHAVIOR 0x82fb
#define GL_CONTEXT_RELEASE_BEHAVIOR_FLUSH 0x82fc
#define GL_CONTEXT_FLAG_NO_ERROR_BIT_KHR 0x00000008

#define MAX(x, y) __extension__ ({ \
    __typeof__ (x) a = (x); __typeof__ (y) b = (y); \
        a > b ? a : b;})
#define MIN(x, y) __extension__ ({ \
    __typeof__ (x) a = (x); __typeof__ (y) b = (y); \
        a < b ? a : b;})

typedef int GLint;
typedef unsigned int GLuint;
typedef unsigned int GLenum;
typedef unsigned int GLbitfield;
typedef unsigned char GLubyte;

typedef void (APIENTRY * PFNGLCLEARPROC)(GLbitfield);
typedef const GLubyte* (APIENTRY * PFNGLGETSTRINGPROC)(GLenum);
typedef void (APIENTRY * PFNGLGETINTEGERVPROC)(GLenum,GLint*);
typedef const GLubyte* (APIENTRY * PFNGLGETSTRINGIPROC)(GLenum,GLuint);

#define VK_NULL_HANDLE 0

typedef void* VkInstance;
typedef void* VkPhysicalDevice;
typedef uint64_t VkSurfaceKHR;
typedef uint32_t VkFlags;
typedef uint32_t VkBool32;

typedef enum VkStructureType
{
    VK_STRUCTURE_TYPE_XLIB_SURFACE_CREATE_INFO_KHR = 1000004000,
    VK_STRUCTURE_TYPE_XCB_SURFACE_CREATE_INFO_KHR = 1000005000,
    VK_STRUCTURE_TYPE_WAYLAND_SURFACE_CREATE_INFO_KHR = 1000006000,
    VK_STRUCTURE_TYPE_WIN32_SURFACE_CREATE_INFO_KHR = 1000009000,
    VK_STRUCTURE_TYPE_MACOS_SURFACE_CREATE_INFO_MVK = 1000123000,
    VK_STRUCTURE_TYPE_METAL_SURFACE_CREATE_INFO_EXT = 1000217000,
    VK_STRUCTURE_TYPE_MAX_ENUM = 0x7FFFFFFF
} VkStructureType;

typedef enum VkResult
{
    VK_SUCCESS = 0,
    VK_NOT_READY = 1,
    VK_TIMEOUT = 2,
    VK_EVENT_SET = 3,
    VK_EVENT_RESET = 4,
    VK_INCOMPLETE = 5,
    VK_ERROR_OUT_OF_HOST_MEMORY = -1,
    VK_ERROR_OUT_OF_DEVICE_MEMORY = -2,
    VK_ERROR_INITIALIZATION_FAILED = -3,
    VK_ERROR_DEVICE_LOST = -4,
    VK_ERROR_MEMORY_MAP_FAILED = -5,
    VK_ERROR_LAYER_NOT_PRESENT = -6,
    VK_ERROR_EXTENSION_NOT_PRESENT = -7,
    VK_ERROR_FEATURE_NOT_PRESENT = -8,
    VK_ERROR_INCOMPATIBLE_DRIVER = -9,
    VK_ERROR_TOO_MANY_OBJECTS = -10,
    VK_ERROR_FORMAT_NOT_SUPPORTED = -11,
    VK_ERROR_SURFACE_LOST_KHR = -1000000000,
    VK_SUBOPTIMAL_KHR = 1000001003,
    VK_ERROR_OUT_OF_DATE_KHR = -1000001004,
    VK_ERROR_INCOMPATIBLE_DISPLAY_KHR = -1000003001,
    VK_ERROR_NATIVE_WINDOW_IN_USE_KHR = -1000000001,
    VK_ERROR_VALIDATION_FAILED_EXT = -1000011001,
    VK_RESULT_MAX_ENUM = 0x7FFFFFFF
} VkResult;

typedef struct VkAllocationCallbacks VkAllocationCallbacks;

typedef struct VkExtensionProperties
{
    char            extensionName[256];
    uint32_t        specVersion;
} VkExtensionProperties;

typedef void (APIENTRY * PFN_vkVoidFunction)(void);

#if defined(_GLFW_VULKAN_STATIC)
  PFN_vkVoidFunction vkGetInstanceProcAddr(VkInstance,const char*);
  VkResult vkEnumerateInstanceExtensionProperties(const char*,uint32_t*,VkExtensionProperties*);
#else
  typedef PFN_vkVoidFunction (APIENTRY * PFN_vkGetInstanceProcAddr)(VkInstance,const char*);
  typedef VkResult (APIENTRY * PFN_vkEnumerateInstanceExtensionProperties)(const char*,uint32_t*,VkExtensionProperties*);
  #define vkEnumerateInstanceExtensionProperties _glfw.vk.EnumerateInstanceExtensionProperties
  #define vkGetInstanceProcAddr _glfw.vk.GetInstanceProcAddr
#endif

#if defined(_GLFW_COCOA)
 #include "cocoa_platform.h"
#elif defined(_GLFW_WIN32)
 #include "win32_platform.h"
#elif defined(_GLFW_X11)
 #include "x11_platform.h"
#elif defined(_GLFW_WAYLAND)
 #include "wl_platform.h"
#elif defined(_GLFW_OSMESA)
 #include "null_platform.h"
#else
 #error "No supported window creation API selected"
#endif

#include "egl_context.h"
#include "osmesa_context.h"

#define remove_i_from_array(array, i, count) { \
    (count)--; \
    if ((i) < (count)) { \
        memmove((array) + (i), (array) + (i) + 1, sizeof((array)[0]) * ((count) - (i))); /* NOLINT(bugprone-sizeof-expression) */ \
    }}


// Constructs a version number string from the public header macros
#define _GLFW_CONCAT_VERSION(m, n, r) #m "." #n "." #r
#define _GLFW_MAKE_VERSION(m, n, r) _GLFW_CONCAT_VERSION(m, n, r)
#define _GLFW_VERSION_NUMBER _GLFW_MAKE_VERSION(GLFW_VERSION_MAJOR, \
                                                GLFW_VERSION_MINOR, \
                                                GLFW_VERSION_REVISION)

// Checks for whether the library has been initialized
#define _GLFW_REQUIRE_INIT()                         \
    if (!_glfw.initialized)                          \
    {                                                \
        _glfwInputError(GLFW_NOT_INITIALIZED, NULL); \
        return;                                      \
    }
#define _GLFW_REQUIRE_INIT_OR_RETURN(x)              \
    if (!_glfw.initialized)                          \
    {                                                \
        _glfwInputError(GLFW_NOT_INITIALIZED, NULL); \
        return x;                                    \
    }

// Swaps the provided pointers
#define _GLFW_SWAP_POINTERS(x, y) \
    do{                           \
        __typeof__(x) t;          \
        t = x;                    \
        x = y;                    \
        y = t;                    \
    }while(0)


// Suppress some pedantic warnings
#ifdef __clang__
#define START_ALLOW_CASE_RANGE _Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wpedantic\"")
#define END_ALLOW_CASE_RANGE _Pragma("clang diagnostic pop")
#define ALLOW_UNUSED_RESULT _Pragma("clang diagnostic push") _Pragma("clang diagnostic ignored \"-Wunused-result\"")
#define END_ALLOW_UNUSED_RESULT _Pragma("clang diagnostic pop")
#else
#define START_ALLOW_CASE_RANGE _Pragma("GCC diagnostic ignored \"-Wpedantic\"")
#define END_ALLOW_CASE_RANGE _Pragma("GCC diagnostic pop")
#define ALLOW_UNUSED_RESULT _Pragma("GCC diagnostic ignored \"-Wunused-result\"")
#define END_ALLOW_UNUSED_RESULT _Pragma("GCC diagnostic pop")
#endif

// dlsym that works with -Wpedantic
#define glfw_dlsym(dest, handle, name) do {*(void **)&(dest) = _glfw_dlsym(handle, name);}while (0)

// Mark function arguments as unused
#define UNUSED __attribute__ ((unused))

// Per-thread error structure
//
struct _GLFWerror
{
    _GLFWerror*     next;
    int             code;
    char            description[_GLFW_MESSAGE_SIZE];
};

// Initialization configuration
//
// Parameters relating to the initialization of the library
//
struct _GLFWinitconfig
{
    bool          hatButtons;
    int           angleType;
    bool          debugKeyboard;
    bool          debugRendering;
    struct {
        bool      menubar;
        bool      chdir;
    } ns;
    struct {
        bool ime;
    } wl;
};

// Window configuration
//
// Parameters relating to the creation of the window but not directly related
// to the framebuffer.  This is used to pass window creation parameters from
// shared code to the platform API.
//
struct _GLFWwndconfig
{
    int           width;
    int           height;
    const char*   title;
    bool          resizable;
    bool          visible;
    bool          decorated;
    bool          focused;
    bool          autoIconify;
    bool          floating;
    bool          maximized;
    bool          centerCursor;
    bool          focusOnShow;
    bool          mousePassthrough;
    bool          scaleToMonitor;
    int           blur_radius;
    struct {
        bool      retina;
        int       color_space;
        char      frameName[256];
    } ns;
    struct {
        char      className[256];
        char      instanceName[256];
    } x11;
    struct {
        char      appId[256], windowTag[256];
        uint32_t  bgcolor;
    } wl;
};

// Context configuration
//
// Parameters relating to the creation of the context but not directly related
// to the framebuffer.  This is used to pass context creation parameters from
// shared code to the platform API.
//
struct _GLFWctxconfig
{
    int           client;
    int           source;
    int           major;
    int           minor;
    bool          forward;
    bool          debug;
    bool          noerror;
    int           profile;
    int           robustness;
    int           release;
    _GLFWwindow*  share;
    struct {
        bool      offline;
    } nsgl;
};

// Framebuffer configuration
//
// This describes buffers and their sizes.  It also contains
// a platform-specific ID used to map back to the backend API object.
//
// It is used to pass framebuffer parameters from shared code to the platform
// API and also to enumerate and select available framebuffer configs.
//
struct _GLFWfbconfig
{
    int         redBits;
    int         greenBits;
    int         blueBits;
    int         alphaBits;
    int         depthBits;
    int         stencilBits;
    int         accumRedBits;
    int         accumGreenBits;
    int         accumBlueBits;
    int         accumAlphaBits;
    int         auxBuffers;
    bool        stereo;
    int         samples;
    bool        sRGB;
    bool        doublebuffer;
    bool        transparent;
    uintptr_t   handle;
};

// Context structure
//
struct _GLFWcontext
{
    int                 client;
    int                 source;
    int                 major, minor, revision;
    bool                forward, debug, noerror;
    int                 profile;
    int                 robustness;
    int                 release;

    PFNGLGETSTRINGIPROC GetStringi;
    PFNGLGETINTEGERVPROC GetIntegerv;
    PFNGLGETSTRINGPROC  GetString;

    _GLFWmakecontextcurrentfun  makeCurrent;
    _GLFWswapbuffersfun         swapBuffers;
    _GLFWswapintervalfun        swapInterval;
    _GLFWextensionsupportedfun  extensionSupported;
    _GLFWgetprocaddressfun      getProcAddress;
    _GLFWdestroycontextfun      destroy;

    // This is defined in the context API's context.h
    _GLFW_PLATFORM_CONTEXT_STATE
    // This is defined in egl_context.h
    _GLFWcontextEGL egl;
    // This is defined in osmesa_context.h
    _GLFWcontextOSMesa osmesa;
};

// Window and context structure
//
struct _GLFWwindow
{
    struct _GLFWwindow* next;

    // Window settings and state
    bool                resizable;
    bool                decorated;
    bool                autoIconify;
    bool                floating;
    bool                focusOnShow;
    bool                mousePassthrough;
    bool                shouldClose;
    void*               userPointer;
    GLFWid              id;
    GLFWvidmode         videoMode;
    _GLFWmonitor*       monitor;
    _GLFWcursor*        cursor;

    int                 minwidth, minheight;
    int                 maxwidth, maxheight;
    int                 numer, denom;
    int                 widthincr, heightincr;

    bool                stickyKeys;
    bool                stickyMouseButtons;
    bool                lockKeyMods;
    int                 cursorMode;
    char                mouseButtons[GLFW_MOUSE_BUTTON_LAST + 1];
    GLFWkeyevent        activated_keys[16];
    // Virtual cursor position when cursor is disabled
    double              virtualCursorPosX, virtualCursorPosY;
    bool                rawMouseMotion;

    _GLFWcontext        context;
#ifdef _GLFW_WAYLAND
    bool                swaps_disallowed;
#else
    const bool                swaps_disallowed;
#endif

    struct {
        GLFWwindowposfun        pos;
        GLFWwindowsizefun       size;
        GLFWwindowclosefun      close;
        GLFWwindowrefreshfun    refresh;
        GLFWwindowfocusfun      focus;
        GLFWwindowocclusionfun  occlusion;
        GLFWwindowiconifyfun    iconify;
        GLFWwindowmaximizefun   maximize;
        GLFWframebuffersizefun  fbsize;
        GLFWwindowcontentscalefun scale;
        GLFWmousebuttonfun      mouseButton;
        GLFWcursorposfun        cursorPos;
        GLFWcursorenterfun      cursorEnter;
        GLFWscrollfun           scroll;
        GLFWkeyboardfun         keyboard;
        GLFWdropfun             drop;
        GLFWliveresizefun       liveResize;
    } callbacks;

    // This is defined in the window API's platform.h
    _GLFW_PLATFORM_WINDOW_STATE;
};

// Monitor structure
//
struct _GLFWmonitor
{
    const char *name, *description;
    void*           userPointer;

    // Physical dimensions in millimeters.
    int             widthMM, heightMM;

    // The window whose video mode is current on this monitor
    _GLFWwindow*    window;

    GLFWvidmode*    modes;
    int             modeCount;
    GLFWvidmode     currentMode;

    GLFWgammaramp   originalRamp;
    GLFWgammaramp   currentRamp;

    // This is defined in the window API's platform.h
    _GLFW_PLATFORM_MONITOR_STATE;
};

// Cursor structure
//
struct _GLFWcursor
{
    _GLFWcursor*    next;

    // This is defined in the window API's platform.h
    _GLFW_PLATFORM_CURSOR_STATE;
};

// Gamepad mapping element structure
//
struct _GLFWmapelement
{
    uint8_t         type;
    uint8_t         index;
    int8_t          axisScale;
    int8_t          axisOffset;
};

// Gamepad mapping structure
//
struct _GLFWmapping
{
    char            name[128];
    char            guid[33];
    _GLFWmapelement buttons[15];
    _GLFWmapelement axes[6];
};

// Joystick structure
//
struct _GLFWjoystick
{
    bool            present;
    float*          axes;
    int             axisCount;
    unsigned char*  buttons;
    int             buttonCount;
    unsigned char*  hats;
    int             hatCount;
    char*           name;
    void*           userPointer;
    char            guid[33];
    _GLFWmapping*   mapping;

    // This is defined in the joystick API's joystick.h
    _GLFW_PLATFORM_JOYSTICK_STATE;
};

// Thread local storage structure
//
struct _GLFWtls
{
    // This is defined in the platform's thread.h
    _GLFW_PLATFORM_TLS_STATE;
};

// Mutex structure
//
struct _GLFWmutex
{
    // This is defined in the platform's thread.h
    _GLFW_PLATFORM_MUTEX_STATE;
};

typedef struct _GLFWClipboardData {
    const char** mime_types;
    size_t num_mime_types;
    GLFWclipboarditerfun get_data;
    GLFWClipboardType ctype;
} _GLFWClipboardData;

// Library global data
//
struct _GLFWlibrary
{
    bool                initialized;

    struct {
        _GLFWinitconfig init;
        _GLFWfbconfig   framebuffer;
        _GLFWwndconfig  window;
        _GLFWctxconfig  context;
        int             refreshRate;
    } hints;

    _GLFWClipboardData primary, clipboard;

    _GLFWerror*         errorListHead;
    _GLFWcursor*        cursorListHead;
    _GLFWwindow*        windowListHead;
    GLFWid              focusedWindowId;

    _GLFWmonitor**      monitors;
    int                 monitorCount;

    bool                joysticksInitialized;
    _GLFWjoystick       joysticks[GLFW_JOYSTICK_LAST + 1];
    _GLFWmapping*       mappings;
    int                 mappingCount;

    _GLFWtls            errorSlot;
    _GLFWtls            contextSlot;
    _GLFWmutex          errorLock;

    bool                ignoreOSKeyboardProcessing, keyboard_grabbed;

    struct {
        bool            available;
        void*           handle;
        char*           extensions[2];
#if !defined(_GLFW_VULKAN_STATIC)
        PFN_vkEnumerateInstanceExtensionProperties EnumerateInstanceExtensionProperties;
        PFN_vkGetInstanceProcAddr GetInstanceProcAddr;
#endif
        bool            KHR_surface;
#if defined(_GLFW_WIN32)
        bool            KHR_win32_surface;
#elif defined(_GLFW_COCOA)
        bool            MVK_macos_surface;
        bool            EXT_metal_surface;
#elif defined(_GLFW_X11)
        bool            KHR_xlib_surface;
        bool            KHR_xcb_surface;
#elif defined(_GLFW_WAYLAND)
        bool            KHR_wayland_surface;
#endif
    } vk;

    struct {
        GLFWmonitorfun  monitor;
        GLFWjoystickfun joystick;
        GLFWapplicationclosefun application_close;
        GLFWclipboardlostfun clipboard_lost;
        GLFWsystemcolorthemechangefun system_color_theme_change;
        GLFWdrawtextfun draw_text;
        GLFWcurrentselectionfun get_current_selection;
        GLFWhascurrentselectionfun has_current_selection;
        GLFWimecursorpositionfun get_ime_cursor_position;
    } callbacks;

    // This is defined in the window API's platform.h
    _GLFW_PLATFORM_LIBRARY_WINDOW_STATE;
    // This is defined in the context API's context.h
    _GLFW_PLATFORM_LIBRARY_CONTEXT_STATE
    // This is defined in the platform's joystick.h
    _GLFW_PLATFORM_LIBRARY_JOYSTICK_STATE
    // This is defined in egl_context.h
    _GLFWlibraryEGL egl;
    // This is defined in osmesa_context.h
    _GLFWlibraryOSMesa osmesa;
};

// Global state shared between compilation units of GLFW
//
extern _GLFWlibrary _glfw;

typedef struct GeometryRect { int x, y, width, height; } GeometryRect;
typedef struct MonitorGeometry {
    GeometryRect full, workarea;
} MonitorGeometry;

//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

int _glfwPlatformInit(bool*);
void _glfwPlatformTerminate(void);
const char* _glfwPlatformGetVersionString(void);

void _glfwPlatformGetCursorPos(_GLFWwindow* window, double* xpos, double* ypos);
void _glfwPlatformSetCursorPos(_GLFWwindow* window, double xpos, double ypos);
void _glfwPlatformSetCursorMode(_GLFWwindow* window, int mode);
void _glfwPlatformSetRawMouseMotion(_GLFWwindow *window, bool enabled);
bool _glfwPlatformRawMouseMotionSupported(void);
int _glfwPlatformCreateCursor(_GLFWcursor* cursor,
                              const GLFWimage* image, int xhot, int yhot, int count);
int _glfwPlatformCreateStandardCursor(_GLFWcursor* cursor, GLFWCursorShape shape);
void _glfwPlatformDestroyCursor(_GLFWcursor* cursor);
void _glfwPlatformSetCursor(_GLFWwindow* window, _GLFWcursor* cursor);

const char* _glfwPlatformGetNativeKeyName(int native_key);
int _glfwPlatformGetNativeKeyForKey(uint32_t key);

void _glfwPlatformFreeMonitor(_GLFWmonitor* monitor);
void _glfwPlatformGetMonitorPos(_GLFWmonitor* monitor, int* xpos, int* ypos);
void _glfwPlatformGetMonitorContentScale(_GLFWmonitor* monitor,
                                         float* xscale, float* yscale);
void _glfwPlatformGetMonitorWorkarea(_GLFWmonitor* monitor, int* xpos, int* ypos, int *width, int *height);
GLFWvidmode* _glfwPlatformGetVideoModes(_GLFWmonitor* monitor, int* count);
bool _glfwPlatformGetVideoMode(_GLFWmonitor* monitor, GLFWvidmode* mode);
bool _glfwPlatformGetGammaRamp(_GLFWmonitor* monitor, GLFWgammaramp* ramp);
void _glfwPlatformSetGammaRamp(_GLFWmonitor* monitor, const GLFWgammaramp* ramp);

void _glfwPlatformSetClipboard(GLFWClipboardType t);
void _glfwPlatformGetClipboard(GLFWClipboardType clipboard_type, const char* mime_type, GLFWclipboardwritedatafun write_data, void *object);

bool _glfwPlatformInitJoysticks(void);
void _glfwPlatformTerminateJoysticks(void);
int _glfwPlatformPollJoystick(_GLFWjoystick* js, int mode);
void _glfwPlatformUpdateGamepadGUID(char* guid);

int _glfwPlatformCreateWindow(_GLFWwindow* window, const _GLFWwndconfig* wndconfig, const _GLFWctxconfig* ctxconfig, const _GLFWfbconfig* fbconfig, const GLFWLayerShellConfig *lsc);
void _glfwPlatformDestroyWindow(_GLFWwindow* window);
void _glfwPlatformSetWindowTitle(_GLFWwindow* window, const char* title);
void _glfwPlatformSetWindowIcon(_GLFWwindow* window,
                                int count, const GLFWimage* images);
bool _glfwPlatformSetLayerShellConfig(_GLFWwindow* window, const GLFWLayerShellConfig *value);
const GLFWLayerShellConfig* _glfwPlatformGetLayerShellConfig(_GLFWwindow* window);
void _glfwPlatformGetWindowPos(_GLFWwindow* window, int* xpos, int* ypos);
void _glfwPlatformSetWindowPos(_GLFWwindow* window, int xpos, int ypos);
void _glfwPlatformGetWindowSize(_GLFWwindow* window, int* width, int* height);
void _glfwPlatformSetWindowSize(_GLFWwindow* window, int width, int height);
void _glfwPlatformSetWindowSizeLimits(_GLFWwindow* window,
                                      int minwidth, int minheight,
                                      int maxwidth, int maxheight);
void _glfwPlatformSetWindowAspectRatio(_GLFWwindow* window, int numer, int denom);
void _glfwPlatformSetWindowSizeIncrements(_GLFWwindow* window, int widthincr, int heightincr);
void _glfwPlatformGetFramebufferSize(_GLFWwindow* window, int* width, int* height);
void _glfwInputLiveResize(_GLFWwindow* window, bool started);
void _glfwPlatformGetWindowFrameSize(_GLFWwindow* window,
                                     int* left, int* top,
                                     int* right, int* bottom);
void _glfwPlatformGetWindowContentScale(_GLFWwindow* window,
                                        float* xscale, float* yscale);
monotonic_t _glfwPlatformGetDoubleClickInterval(_GLFWwindow* window);
void _glfwPlatformIconifyWindow(_GLFWwindow* window);
void _glfwPlatformRestoreWindow(_GLFWwindow* window);
void _glfwPlatformMaximizeWindow(_GLFWwindow* window);
void _glfwPlatformShowWindow(_GLFWwindow* window);
void _glfwPlatformHideWindow(_GLFWwindow* window);
void _glfwPlatformRequestWindowAttention(_GLFWwindow* window);
int _glfwPlatformWindowBell(_GLFWwindow* window);
void _glfwPlatformFocusWindow(_GLFWwindow* window);
void _glfwPlatformSetWindowMonitor(_GLFWwindow* window, _GLFWmonitor* monitor,
                                   int xpos, int ypos, int width, int height,
                                   int refreshRate);
bool _glfwPlatformToggleFullscreen(_GLFWwindow *w, unsigned int flags);
bool _glfwPlatformIsFullscreen(_GLFWwindow *w, unsigned int flags);
int _glfwPlatformWindowFocused(_GLFWwindow* window);
int _glfwPlatformWindowOccluded(_GLFWwindow* window);
int _glfwPlatformWindowIconified(_GLFWwindow* window);
int _glfwPlatformWindowVisible(_GLFWwindow* window);
int _glfwPlatformWindowMaximized(_GLFWwindow* window);
int _glfwPlatformWindowHovered(_GLFWwindow* window);
int _glfwPlatformFramebufferTransparent(_GLFWwindow* window);
float _glfwPlatformGetWindowOpacity(_GLFWwindow* window);
void _glfwPlatformSetWindowResizable(_GLFWwindow* window, bool enabled);
void _glfwPlatformSetWindowDecorated(_GLFWwindow* window, bool enabled);
void _glfwPlatformSetWindowFloating(_GLFWwindow* window, bool enabled);
void _glfwPlatformSetWindowMousePassthrough(_GLFWwindow* window, bool enabled);
void _glfwPlatformSetWindowOpacity(_GLFWwindow* window, float opacity);
void _glfwPlatformUpdateIMEState(_GLFWwindow *w, const GLFWIMEUpdateEvent *ev);
void _glfwPlatformChangeCursorTheme(void);

void _glfwPlatformPollEvents(void);
void _glfwPlatformWaitEvents(void);
void _glfwPlatformWaitEventsTimeout(monotonic_t timeout);
void _glfwPlatformPostEmptyEvent(void);

EGLenum _glfwPlatformGetEGLPlatform(EGLint** attribs);
EGLNativeDisplayType _glfwPlatformGetEGLNativeDisplay(void);
EGLNativeWindowType _glfwPlatformGetEGLNativeWindow(_GLFWwindow* window);

void _glfwPlatformGetRequiredInstanceExtensions(char** extensions);
int _glfwPlatformGetPhysicalDevicePresentationSupport(VkInstance instance,
                                                      VkPhysicalDevice device,
                                                      uint32_t queuefamily);
VkResult _glfwPlatformCreateWindowSurface(VkInstance instance,
                                          _GLFWwindow* window,
                                          const VkAllocationCallbacks* allocator,
                                          VkSurfaceKHR* surface);

bool _glfwPlatformCreateTls(_GLFWtls* tls);
void _glfwPlatformDestroyTls(_GLFWtls* tls);
void* _glfwPlatformGetTls(_GLFWtls* tls);
void _glfwPlatformSetTls(_GLFWtls* tls, void* value);

bool _glfwPlatformCreateMutex(_GLFWmutex* mutex);
void _glfwPlatformDestroyMutex(_GLFWmutex* mutex);
void _glfwPlatformLockMutex(_GLFWmutex* mutex);
void _glfwPlatformUnlockMutex(_GLFWmutex* mutex);


//////////////////////////////////////////////////////////////////////////
//////                         GLFW event API                       //////
//////////////////////////////////////////////////////////////////////////

void _glfwInputWindowFocus(_GLFWwindow* window, bool focused);
void _glfwInputWindowOcclusion(_GLFWwindow* window, bool occluded);
void _glfwInputWindowPos(_GLFWwindow* window, int xpos, int ypos);
void _glfwInputWindowSize(_GLFWwindow* window, int width, int height);
void _glfwInputFramebufferSize(_GLFWwindow* window, int width, int height);
void _glfwInputWindowContentScale(_GLFWwindow* window,
                                  float xscale, float yscale);
void _glfwInputWindowIconify(_GLFWwindow* window, bool iconified);
void _glfwInputWindowMaximize(_GLFWwindow* window, bool maximized);
void _glfwInputWindowDamage(_GLFWwindow* window);
void _glfwInputWindowCloseRequest(_GLFWwindow* window);
void _glfwInputWindowMonitor(_GLFWwindow* window, _GLFWmonitor* monitor);

void _glfwInputKeyboard(_GLFWwindow *window, GLFWkeyevent *ev);
void _glfwInputClipboardLost(GLFWClipboardType which);
void _glfwInputScroll(_GLFWwindow* window, double xoffset, double yoffset, int flags, int mods);
void _glfwInputMouseClick(_GLFWwindow* window, int button, int action, int mods);
void _glfwInputCursorPos(_GLFWwindow* window, double xpos, double ypos);
void _glfwInputCursorEnter(_GLFWwindow* window, bool entered);
int _glfwInputDrop(_GLFWwindow* window, const char *mime, const char *text, size_t sz);
void _glfwInputColorScheme(GLFWColorScheme, bool);
void _glfwPlatformInputColorScheme(GLFWColorScheme);
void _glfwInputJoystick(_GLFWjoystick* js, int event);
void _glfwInputJoystickAxis(_GLFWjoystick* js, int axis, float value);
void _glfwInputJoystickButton(_GLFWjoystick* js, int button, char value);
void _glfwInputJoystickHat(_GLFWjoystick* js, int hat, char value);

void _glfwInputMonitor(_GLFWmonitor* monitor, int action, int placement);
void _glfwInputMonitorWindow(_GLFWmonitor* monitor, _GLFWwindow* window);

#if defined(__GNUC__) || defined(__clang__)
void _glfwInputError(int code, const char* format, ...)
    __attribute__((format(printf, 2, 3)));
void _glfwDebug(const char* format, ...)
    __attribute__((format(printf, 1, 2)));
#else
void _glfwInputError(int code, const char* format, ...);
void _glfwDebug(const char* format, ...);
#endif

#ifdef DEBUG_EVENT_LOOP
#define EVDBG(...) _glfwDebug(__VA_ARGS__)
#else
#define EVDBG(...)
#endif

//////////////////////////////////////////////////////////////////////////
//////                       GLFW internal API                      //////
//////////////////////////////////////////////////////////////////////////

bool _glfwStringInExtensionString(const char* string, const char* extensions);
bool _glfwRefreshContextAttribs(_GLFWwindow* window,
                                    const _GLFWctxconfig* ctxconfig);
bool _glfwIsValidContextConfig(const _GLFWctxconfig* ctxconfig);

const GLFWvidmode* _glfwChooseVideoMode(_GLFWmonitor* monitor,
                                        const GLFWvidmode* desired);
int _glfwCompareVideoModes(const GLFWvidmode* first, const GLFWvidmode* second);
_GLFWmonitor* _glfwAllocMonitor(const char* name, int widthMM, int heightMM);
void _glfwFreeMonitor(_GLFWmonitor* monitor);
void _glfwAllocGammaArrays(GLFWgammaramp* ramp, unsigned int size);
void _glfwFreeGammaArrays(GLFWgammaramp* ramp);
void _glfwSplitBPP(int bpp, int* red, int* green, int* blue);

_GLFWjoystick* _glfwAllocJoystick(const char* name,
                                  const char* guid,
                                  int axisCount,
                                  int buttonCount,
                                  int hatCount);
void _glfwFreeJoystick(_GLFWjoystick* js);
const char* _glfwGetKeyName(int key);
void _glfwCenterCursorInContentArea(_GLFWwindow* window);

bool _glfwInitVulkan(int mode);
void _glfwTerminateVulkan(void);
const char* _glfwGetVulkanResultString(VkResult result);
_GLFWwindow* _glfwFocusedWindow(void);
_GLFWwindow* _glfwWindowForId(GLFWid id);
void _glfwPlatformRunMainLoop(GLFWtickcallback, void*);
void _glfwPlatformStopMainLoop(void);
unsigned long long _glfwPlatformAddTimer(monotonic_t interval, bool repeats, GLFWuserdatafun callback, void *callback_data, GLFWuserdatafun free_callback);
void _glfwPlatformUpdateTimer(unsigned long long timer_id, monotonic_t interval, bool enabled);
void _glfwPlatformRemoveTimer(unsigned long long timer_id);
int _glfwPlatformSetWindowBlur(_GLFWwindow* handle, int value);
MonitorGeometry _glfwPlatformGetMonitorGeometry(_GLFWmonitor* monitor);
bool _glfwPlatformGrabKeyboard(bool grab);

char* _glfw_strdup(const char* source);

void _glfw_free_clipboard_data(_GLFWClipboardData *cd);

#define debug_rendering(...) if (_glfw.hints.init.debugRendering) { timed_debug_print(__VA_ARGS__); }
#define debug_input(...) if (_glfw.hints.init.debugKeyboard) { timed_debug_print(__VA_ARGS__); }
