//========================================================================
// GLFW 3.3 Wayland - www.glfw.org
//------------------------------------------------------------------------
// Copyright (c) 2014 Jonas Ådahl <jadahl@gmail.com>
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

#include <wayland-client.h>
#include <dlfcn.h>
#include <poll.h>

typedef VkFlags VkWaylandSurfaceCreateFlagsKHR;

typedef struct VkWaylandSurfaceCreateInfoKHR
{
    VkStructureType                 sType;
    const void*                     pNext;
    VkWaylandSurfaceCreateFlagsKHR  flags;
    struct wl_display*              display;
    struct wl_surface*              surface;
} VkWaylandSurfaceCreateInfoKHR;

typedef VkResult (APIENTRY *PFN_vkCreateWaylandSurfaceKHR)(VkInstance,const VkWaylandSurfaceCreateInfoKHR*,const VkAllocationCallbacks*,VkSurfaceKHR*);
typedef VkBool32 (APIENTRY *PFN_vkGetPhysicalDeviceWaylandPresentationSupportKHR)(VkPhysicalDevice,uint32_t,struct wl_display*);

#include "posix_thread.h"
#include "posix_time.h"
#ifdef __linux__
#include "linux_joystick.h"
#else
#include "null_joystick.h"
#endif
#include "backend_utils.h"
#include "xkb_glfw.h"
#include "egl_context.h"
#include "osmesa_context.h"

#include "wayland-xdg-shell-client-protocol.h"
#include "wayland-viewporter-client-protocol.h"
#include "wayland-xdg-decoration-unstable-v1-client-protocol.h"
#include "wayland-relative-pointer-unstable-v1-client-protocol.h"
#include "wayland-pointer-constraints-unstable-v1-client-protocol.h"
#include "wayland-idle-inhibit-unstable-v1-client-protocol.h"
#include "wayland-primary-selection-unstable-v1-client-protocol.h"

#define _glfw_dlopen(name) dlopen(name, RTLD_LAZY | RTLD_LOCAL)
#define _glfw_dlclose(handle) dlclose(handle)
#define _glfw_dlsym(handle, name) dlsym(handle, name)

#define _GLFW_EGL_NATIVE_WINDOW         ((EGLNativeWindowType) window->wl.native)
#define _GLFW_EGL_NATIVE_DISPLAY        ((EGLNativeDisplayType) _glfw.wl.display)

#define _GLFW_PLATFORM_WINDOW_STATE         _GLFWwindowWayland  wl
#define _GLFW_PLATFORM_LIBRARY_WINDOW_STATE _GLFWlibraryWayland wl
#define _GLFW_PLATFORM_MONITOR_STATE        _GLFWmonitorWayland wl
#define _GLFW_PLATFORM_CURSOR_STATE         _GLFWcursorWayland  wl

#define _GLFW_PLATFORM_CONTEXT_STATE
#define _GLFW_PLATFORM_LIBRARY_CONTEXT_STATE

struct wl_cursor_image {
    uint32_t width;
    uint32_t height;
    uint32_t hotspot_x;
    uint32_t hotspot_y;
    uint32_t delay;
};
struct wl_cursor {
    unsigned int image_count;
    struct wl_cursor_image** images;
    char* name;
};
typedef struct wl_cursor_theme* (* PFN_wl_cursor_theme_load)(const char*, int, struct wl_shm*);
typedef void (* PFN_wl_cursor_theme_destroy)(struct wl_cursor_theme*);
typedef struct wl_cursor* (* PFN_wl_cursor_theme_get_cursor)(struct wl_cursor_theme*, const char*);
typedef struct wl_buffer* (* PFN_wl_cursor_image_get_buffer)(struct wl_cursor_image*);
#define wl_cursor_theme_load _glfw.wl.cursor.theme_load
#define wl_cursor_theme_destroy _glfw.wl.cursor.theme_destroy
#define wl_cursor_theme_get_cursor _glfw.wl.cursor.theme_get_cursor
#define wl_cursor_image_get_buffer _glfw.wl.cursor.image_get_buffer

typedef struct wl_egl_window* (* PFN_wl_egl_window_create)(struct wl_surface*, int, int);
typedef void (* PFN_wl_egl_window_destroy)(struct wl_egl_window*);
typedef void (* PFN_wl_egl_window_resize)(struct wl_egl_window*, int, int, int, int);
#define wl_egl_window_create _glfw.wl.egl.window_create
#define wl_egl_window_destroy _glfw.wl.egl.window_destroy
#define wl_egl_window_resize _glfw.wl.egl.window_resize

#define _GLFW_DECORATION_WIDTH 4
#define _GLFW_DECORATION_TOP 24
#define _GLFW_DECORATION_VERTICAL (_GLFW_DECORATION_TOP + _GLFW_DECORATION_WIDTH)
#define _GLFW_DECORATION_HORIZONTAL (2 * _GLFW_DECORATION_WIDTH)

typedef enum _GLFWdecorationSideWayland
{
    mainWindow,
    topDecoration,
    leftDecoration,
    rightDecoration,
    bottomDecoration,

} _GLFWdecorationSideWayland;

typedef struct _GLFWdecorationWayland
{
    struct wl_surface*          surface;
    struct wl_subsurface*       subsurface;
    struct wp_viewport*         viewport;

} _GLFWdecorationWayland;

// Wayland-specific per-window data
//
typedef struct _GLFWwindowWayland
{
    int                         width, height;
    GLFWbool                    visible;
    GLFWbool                    maximized;
    GLFWbool                    hovered;
    GLFWbool                    transparent;
    struct wl_surface*          surface;
    struct wl_egl_window*       native;
    struct wl_shell_surface*    shellSurface;
    struct wl_callback*         callback;

    struct {
        struct xdg_surface*     surface;
        struct xdg_toplevel*    toplevel;
        struct zxdg_toplevel_decoration_v1* decoration;
    } xdg;

    _GLFWcursor*                currentCursor;
    double                      cursorPosX, cursorPosY;

    char*                       title;
    char                        appId[256];

    // We need to track the monitors the window spans on to calculate the
    // optimal scaling factor.
    int                         scale;
    _GLFWmonitor**              monitors;
    int                         monitorsCount;
    int                         monitorsSize;

    struct {
        struct zwp_relative_pointer_v1*    relativePointer;
        struct zwp_locked_pointer_v1*      lockedPointer;
    } pointerLock;

    struct zwp_idle_inhibitor_v1*          idleInhibitor;

    // This is a hack to prevent auto-iconification on creation.
    GLFWbool                    wasFullScreen;

    struct {
        GLFWbool                           serverSide;
        struct wl_buffer*                  buffer;
        _GLFWdecorationWayland             top, left, right, bottom;
        int                                focus;
    } decorations;

    struct {
        unsigned long long id;
        void(*callback)(unsigned long long id);
        struct wl_callback *current_wl_callback;
    } frameCallbackData;


} _GLFWwindowWayland;

typedef enum _GLFWWaylandOfferType
{
    EXPIRED,
    CLIPBOARD,
    DRAG_AND_DROP,
    PRIMARY_SELECTION
}_GLFWWaylandOfferType ;

typedef struct _GLFWWaylandDataOffer
{
    struct wl_data_offer *id;
    const char *mime;
    _GLFWWaylandOfferType offer_type;
    size_t idx;
    int is_self_offer;
    int has_uri_list;
    uint32_t source_actions;
    uint32_t dnd_action;
    struct wl_surface *surface;
} _GLFWWaylandDataOffer;

typedef struct _GLFWWaylandPrimaryOffer
{
    struct zwp_primary_selection_offer_v1 *id;
    const char *mime;
    _GLFWWaylandOfferType offer_type;
    size_t idx;
    int is_self_offer;
    int has_uri_list;
    struct wl_surface *surface;
} _GLFWWaylandPrimaryOffer;

// Wayland-specific global data
//
typedef struct _GLFWlibraryWayland
{
    struct wl_display*          display;
    struct wl_registry*         registry;
    struct wl_compositor*       compositor;
    struct wl_subcompositor*    subcompositor;
    struct wl_shell*            shell;
    struct wl_shm*              shm;
    struct wl_seat*             seat;
    struct wl_pointer*          pointer;
    struct wl_keyboard*         keyboard;
    struct xdg_wm_base*         wmBase;
    struct zxdg_decoration_manager_v1*      decorationManager;
    struct wp_viewporter*       viewporter;
    struct zwp_relative_pointer_manager_v1* relativePointerManager;
    struct zwp_pointer_constraints_v1*      pointerConstraints;
    struct zwp_idle_inhibit_manager_v1*     idleInhibitManager;
    struct wl_data_device_manager*          dataDeviceManager;
    struct wl_data_device*                  dataDevice;
    struct wl_data_source*                  dataSourceForClipboard;
    struct zwp_primary_selection_device_manager_v1* primarySelectionDeviceManager;
    struct zwp_primary_selection_device_v1*    primarySelectionDevice;
    struct zwp_primary_selection_source_v1*    dataSourceForPrimarySelection;

    int                         compositorVersion;
    int                         seatVersion;

    struct wl_cursor_theme*     cursorTheme;
    struct wl_surface*          cursorSurface;
    uint32_t                    pointerSerial;

    int32_t                     keyboardRepeatRate;
    int32_t                     keyboardRepeatDelay;
    struct {
        uint32_t                key;
        id_type                 keyRepeatTimer;
        _GLFWwindow*            keyboardFocus;
    } keyRepeatInfo;
    id_type                     cursorAnimationTimer;
    _GLFWXKBData                xkb;
    _GLFWDBUSData               dbus;

    _GLFWwindow*                pointerFocus;
    _GLFWwindow*                keyboardFocus;

    struct {
        void*                   handle;

        PFN_wl_cursor_theme_load theme_load;
        PFN_wl_cursor_theme_destroy theme_destroy;
        PFN_wl_cursor_theme_get_cursor theme_get_cursor;
        PFN_wl_cursor_image_get_buffer image_get_buffer;
    } cursor;

    struct {
        void*                   handle;

        PFN_wl_egl_window_create window_create;
        PFN_wl_egl_window_destroy window_destroy;
        PFN_wl_egl_window_resize window_resize;
    } egl;

    EventLoopData eventLoopData;
    char* pasteString;
    char* clipboardString;
    size_t dataOffersCounter;
    _GLFWWaylandDataOffer dataOffers[8];
    char* primarySelectionString;
    size_t primarySelectionOffersCounter;
    _GLFWWaylandPrimaryOffer primarySelectionOffers[8];
} _GLFWlibraryWayland;

// Wayland-specific per-monitor data
//
typedef struct _GLFWmonitorWayland
{
    struct wl_output*           output;
    int                         name;
    int                         currentMode;

    int                         x;
    int                         y;
    int                         scale;

} _GLFWmonitorWayland;

// Wayland-specific per-cursor data
//
typedef struct _GLFWcursorWayland
{
    struct wl_cursor*           cursor;
    struct wl_buffer*           buffer;
    int                         width, height;
    int                         xhot, yhot;
    int                         currentImage;
} _GLFWcursorWayland;


void _glfwAddOutputWayland(uint32_t name, uint32_t version);
void _glfwSetupWaylandDataDevice();
void _glfwSetupWaylandPrimarySelectionDevice();
void animateCursorImage(id_type timer_id, void *data);
struct wl_cursor* _glfwLoadCursor(GLFWCursorShape);
