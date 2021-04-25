//========================================================================
// GLFW 3.4 Wayland - www.glfw.org
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
#ifdef __linux__
#include "linux_joystick.h"
#else
#include "null_joystick.h"
#endif
#include "backend_utils.h"
#include "xkb_glfw.h"
#include "wl_cursors.h"

#include "wayland-xdg-shell-client-protocol.h"
#include "wayland-xdg-decoration-unstable-v1-client-protocol.h"
#include "wayland-relative-pointer-unstable-v1-client-protocol.h"
#include "wayland-pointer-constraints-unstable-v1-client-protocol.h"
#include "wayland-idle-inhibit-unstable-v1-client-protocol.h"
#include "wayland-primary-selection-unstable-v1-client-protocol.h"
#include "wl_text_input.h"

#define _glfw_dlopen(name) dlopen(name, RTLD_LAZY | RTLD_LOCAL)
#define _glfw_dlclose(handle) dlclose(handle)
#define _glfw_dlsym(handle, name) dlsym(handle, name)

#define _GLFW_PLATFORM_WINDOW_STATE         _GLFWwindowWayland  wl
#define _GLFW_PLATFORM_LIBRARY_WINDOW_STATE _GLFWlibraryWayland wl
#define _GLFW_PLATFORM_MONITOR_STATE        _GLFWmonitorWayland wl
#define _GLFW_PLATFORM_CURSOR_STATE         _GLFWcursorWayland  wl

#define _GLFW_PLATFORM_CONTEXT_STATE
#define _GLFW_PLATFORM_LIBRARY_CONTEXT_STATE

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

typedef enum _GLFWdecorationSideWayland
{
    CENTRAL_WINDOW,
    TOP_DECORATION,
    LEFT_DECORATION,
    RIGHT_DECORATION,
    BOTTOM_DECORATION,
} _GLFWdecorationSideWayland;

typedef struct _GLFWWaylandBufferPair {
    struct wl_buffer *a, *b, *front, *back;
    struct { uint8_t *a, *b, *front, *back; } data;
    bool has_pending_update;
    size_t size_in_bytes, width, height, stride;
} _GLFWWaylandBufferPair;

typedef struct _GLFWWaylandCSDEdge {
    struct wl_surface *surface;
    struct wl_subsurface *subsurface;
    _GLFWWaylandBufferPair buffer;
    int x, y;
} _GLFWWaylandCSDEdge;

typedef enum WaylandWindowState {

    TOPLEVEL_STATE_NONE = 0,
    TOPLEVEL_STATE_MAXIMIZED = 1,
    TOPLEVEL_STATE_FULLSCREEN = 2,
	TOPLEVEL_STATE_RESIZING = 4,
	TOPLEVEL_STATE_ACTIVATED = 8,
	TOPLEVEL_STATE_TILED_LEFT = 16,
	TOPLEVEL_STATE_TILED_RIGHT = 32,
	TOPLEVEL_STATE_TILED_TOP = 64,
	TOPLEVEL_STATE_TILED_BOTTOM = 128,
} WaylandWindowState;


static const WaylandWindowState TOPLEVEL_STATE_DOCKED = TOPLEVEL_STATE_MAXIMIZED | TOPLEVEL_STATE_FULLSCREEN | TOPLEVEL_STATE_TILED_TOP | TOPLEVEL_STATE_TILED_LEFT | TOPLEVEL_STATE_TILED_RIGHT | TOPLEVEL_STATE_TILED_BOTTOM;


// Wayland-specific per-window data
//
typedef struct _GLFWwindowWayland
{
    int                         width, height;
    bool                        visible;
    bool                        hovered;
    bool                        transparent;
    struct wl_surface*          surface;
    struct wl_egl_window*       native;
    struct wl_callback*         callback;

    struct {
        struct xdg_surface*     surface;
        struct xdg_toplevel*    toplevel;
        struct zxdg_toplevel_decoration_v1* decoration;
    } xdg;

    _GLFWcursor*                currentCursor;
    double                      cursorPosX, cursorPosY, allCursorPosX, allCursorPosY;

    char*                       title;
    char                        appId[256];

    // We need to track the monitors the window spans on to calculate the
    // optimal scaling factor.
    int                         scale;
    bool                        initial_scale_notified;
    _GLFWmonitor**              monitors;
    int                         monitorsCount;
    int                         monitorsSize;

    struct {
        struct zwp_relative_pointer_v1*    relativePointer;
        struct zwp_locked_pointer_v1*      lockedPointer;
    } pointerLock;

    struct zwp_idle_inhibitor_v1*          idleInhibitor;

    struct {
        bool serverSide;
        _GLFWdecorationSideWayland focus;
        _GLFWWaylandCSDEdge top, left, right, bottom;

        struct {
            uint8_t *data;
            size_t size;
        } mapping;

        struct {
            int width, height, scale;
            bool focused;
        } for_window_state;

        struct {
            unsigned int width, top, horizontal, vertical, visible_titlebar_height;
        } metrics;

        struct {
            int32_t x, y, width, height;
        } geometry;

        struct {
            uint32_t *data;
            size_t for_decoration_size, stride, segments, corner_size;
        } shadow_tile;
        monotonic_t last_click_on_top_decoration_at;

        uint32_t titlebar_color;
        bool use_custom_titlebar_color;
    } decorations;

    struct {
        unsigned long long id;
        void(*callback)(unsigned long long id);
        struct wl_callback *current_wl_callback;
    } frameCallbackData;

    struct {
        int32_t width, height;
    } user_requested_content_size;

    uint32_t toplevel_states;
    bool maximize_on_first_show;

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
    void *id;
    _GLFWWaylandOfferType offer_type;
    size_t idx;
    bool is_self_offer;
    bool is_primary;
    const char *plain_text_mime, *mime_for_drop;
    uint32_t source_actions;
    uint32_t dnd_action;
    struct wl_surface *surface;
    const char **mimes;
    size_t mimes_capacity, mimes_count;
} _GLFWWaylandDataOffer;

// Wayland-specific global data
//
typedef struct _GLFWlibraryWayland
{
    struct wl_display*          display;
    struct wl_registry*         registry;
    struct wl_compositor*       compositor;
    struct wl_subcompositor*    subcompositor;
    struct wl_shm*              shm;
    struct wl_seat*             seat;
    struct wl_pointer*          pointer;
    struct wl_keyboard*         keyboard;
    struct wl_data_device_manager*          dataDeviceManager;
    struct wl_data_device*      dataDevice;
    struct xdg_wm_base*         wmBase;
    struct zxdg_decoration_manager_v1*      decorationManager;
    struct zwp_relative_pointer_manager_v1* relativePointerManager;
    struct zwp_pointer_constraints_v1*      pointerConstraints;
    struct zwp_idle_inhibit_manager_v1*     idleInhibitManager;
    struct wl_data_source*                  dataSourceForClipboard;
    struct zwp_primary_selection_device_manager_v1* primarySelectionDeviceManager;
    struct zwp_primary_selection_device_v1*    primarySelectionDevice;
    struct zwp_primary_selection_source_v1*    dataSourceForPrimarySelection;

    int                         compositorVersion;
    int                         seatVersion;

    struct wl_surface*          cursorSurface;
    GLFWCursorShape             cursorPreviousShape;
    uint32_t                    serial;

    int32_t                     keyboardRepeatRate;
    monotonic_t                 keyboardRepeatDelay;

    struct {
        uint32_t                key;
        id_type                 keyRepeatTimer;
        GLFWid                  keyboardFocusId;
    } keyRepeatInfo;
    id_type                     cursorAnimationTimer;
    _GLFWXKBData                xkb;
    _GLFWDBUSData               dbus;

    _GLFWwindow*                pointerFocus;
    GLFWid                      keyboardFocusId;

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
} _GLFWlibraryWayland;

// Wayland-specific per-monitor data
//
typedef struct _GLFWmonitorWayland
{
    struct wl_output*           output;
    uint32_t                    name;
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
    unsigned int                currentImage;
    /** The scale of the cursor, or 0 if the cursor should be loaded late, or -1 if the cursor variable itself is unused. */
    int                         scale;
    /** Cursor shape stored to allow late cursor loading in setCursorImage. */
    GLFWCursorShape             shape;
} _GLFWcursorWayland;


void _glfwAddOutputWayland(uint32_t name, uint32_t version);
void _glfwSetupWaylandDataDevice(void);
void _glfwSetupWaylandPrimarySelectionDevice(void);
void animateCursorImage(id_type timer_id, void *data);
struct wl_cursor* _glfwLoadCursor(GLFWCursorShape, struct wl_cursor_theme*);
void destroy_data_offer(_GLFWWaylandDataOffer*);
