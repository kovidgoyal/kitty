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
#include "wayland-primary-selection-unstable-v1-client-protocol.h"
#include "wayland-primary-selection-unstable-v1-client-protocol.h"
#include "wayland-xdg-activation-v1-client-protocol.h"
#include "wayland-cursor-shape-v1-client-protocol.h"
#include "wayland-fractional-scale-v1-client-protocol.h"
#include "wayland-viewporter-client-protocol.h"
#include "wayland-kwin-blur-v1-client-protocol.h"
#include "wayland-wlr-layer-shell-unstable-v1-client-protocol.h"
#include "wayland-single-pixel-buffer-v1-client-protocol.h"
#include "wayland-idle-inhibit-unstable-v1-client-protocol.h"
#include "wayland-keyboard-shortcuts-inhibit-unstable-v1-client-protocol.h"
#include "wayland-xdg-toplevel-icon-v1-client-protocol.h"
#include "wayland-xdg-system-bell-v1-client-protocol.h"
#include "wayland-xdg-toplevel-tag-v1-client-protocol.h"

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

typedef enum _GLFWCSDSurface
{
    CENTRAL_WINDOW, CSD_titlebar, CSD_shadow_top, CSD_shadow_left, CSD_shadow_bottom, CSD_shadow_right,
    CSD_shadow_upper_left, CSD_shadow_upper_right, CSD_shadow_lower_left, CSD_shadow_lower_right,
} _GLFWCSDSurface;

typedef struct _GLFWWaylandBufferPair {
    struct wl_buffer *a, *b, *front, *back;
    struct { uint8_t *a, *b, *front, *back; } data;
    bool has_pending_update;
    size_t size_in_bytes, width, height, viewport_width, viewport_height, stride;
    bool a_needs_to_be_destroyed, b_needs_to_be_destroyed;
} _GLFWWaylandBufferPair;

typedef struct _GLFWWaylandCSDSurface {
    struct wl_surface *surface;
    struct wl_subsurface *subsurface;
    struct wp_viewport *wp_viewport;
    _GLFWWaylandBufferPair buffer;
    int x, y;
} _GLFWWaylandCSDSurface;

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
    TOPLEVEL_STATE_SUSPENDED = 256,
    TOPLEVEL_STATE_CONSTRAINED_LEFT = 512,
    TOPLEVEL_STATE_CONSTRAINED_RIGHT = 1024,
    TOPLEVEL_STATE_CONSTRAINED_TOP = 2048,
    TOPLEVEL_STATE_CONSTRAINED_BOTTOM = 4096,
} WaylandWindowState;

typedef struct glfw_wl_xdg_activation_request {
    GLFWid window_id;
    GLFWactivationcallback callback;
    void *callback_data;
    uintptr_t request_id;
    void *token;
} glfw_wl_xdg_activation_request;


static const WaylandWindowState TOPLEVEL_STATE_DOCKED = TOPLEVEL_STATE_MAXIMIZED | TOPLEVEL_STATE_FULLSCREEN | TOPLEVEL_STATE_TILED_TOP | TOPLEVEL_STATE_TILED_LEFT | TOPLEVEL_STATE_TILED_RIGHT | TOPLEVEL_STATE_TILED_BOTTOM;

enum WaylandWindowPendingState {
    PENDING_STATE_TOPLEVEL = 1,
    PENDING_STATE_DECORATION = 2
};

enum _GLFWWaylandAxisEvent {
    AXIS_EVENT_UNKNOWN = 0,
    AXIS_EVENT_CONTINUOUS = 1,
    AXIS_EVENT_DISCRETE = 2,
    AXIS_EVENT_VALUE120 = 3
};

// Wayland-specific per-window data
//
typedef struct _GLFWwindowWayland
{
    int                         width, height;
    bool                        visible, created;
    bool                        hovered;
    bool                        transparent;
    struct wl_surface*          surface;
    bool                        waiting_for_swap_to_commit;
    struct wl_egl_window*       native;
    struct wl_callback*         callback;

    struct {
        struct xdg_surface*     surface;
        struct xdg_toplevel*    toplevel;
        struct zxdg_toplevel_decoration_v1* decoration;
        struct { int width, height; } top_level_bounds;
    } xdg;
    struct wp_fractional_scale_v1 *wp_fractional_scale_v1;
    struct wp_viewport *wp_viewport;
    struct org_kde_kwin_blur *org_kde_kwin_blur;
    bool has_blur, expect_scale_from_compositor, window_fully_created;
    struct {
        bool surface_configured, preferred_scale_received, fractional_scale_received;
    } once;
    struct wl_buffer *temp_buffer_used_during_window_creation;
    struct {
        GLFWLayerShellConfig config;
        struct zwlr_layer_surface_v1* zwlr_layer_surface_v1;
    } layer_shell;

    /* information about axis events on current frame */
    struct
    {
        struct {
            enum _GLFWWaylandAxisEvent x_axis_type;
            float x;
            enum _GLFWWaylandAxisEvent y_axis_type;
            float y;
        } discrete, continuous;

        /* Event timestamp in nanoseconds */
        monotonic_t timestamp_ns;
    } pointer_curr_axis_info;

    _GLFWcursor*                currentCursor;
    double                      cursorPosX, cursorPosY, allCursorPosX, allCursorPosY;

    char*                       title;
    char                        appId[256], windowTag[256];

    // We need to track the monitors the window spans on to calculate the
    // optimal scaling factor.
    struct { uint32_t deduced, preferred; } integer_scale;
    uint32_t                    fractional_scale;
    bool                        initial_scale_notified;
    _GLFWmonitor**              monitors;
    int                         monitorsCount;
    int                         monitorsSize;

    struct {
        struct zwp_relative_pointer_v1*    relativePointer;
        struct zwp_locked_pointer_v1*      lockedPointer;
    } pointerLock;

    struct {
        bool serverSide, buffer_destroyed, titlebar_needs_update, dragging;
        _GLFWCSDSurface focus;

        _GLFWWaylandCSDSurface titlebar, shadow_left, shadow_right, shadow_top, shadow_bottom, shadow_upper_left, shadow_upper_right, shadow_lower_left, shadow_lower_right;

        struct {
            uint8_t *data;
            size_t size;
        } mapping;

        struct {
            int width, height;
            bool focused;
            double fscale;
            WaylandWindowState toplevel_states;
        } for_window_state;

        struct {
            unsigned int width, top, horizontal, vertical, visible_titlebar_height;
        } metrics;

        struct {
            int32_t x, y, width, height;
        } geometry;

        struct {
            bool hovered;
            int width, left;
        } minimize, maximize, close;

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

    struct {
        bool minimize, maximize, fullscreen, window_menu;
    } wm_capabilities;


    bool maximize_on_first_show;
    uint32_t pending_state;
    struct {
        int width, height;
        WaylandWindowState toplevel_states;
        uint32_t decoration_mode;
    } current, pending;
    struct zwp_keyboard_shortcuts_inhibitor_v1 *keyboard_shortcuts_inhibitor;
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
    const char *mime_for_drop;
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
    int xdg_wm_base_version;
    struct zxdg_decoration_manager_v1*      decorationManager;
    struct zwp_relative_pointer_manager_v1* relativePointerManager;
    struct zwp_pointer_constraints_v1*      pointerConstraints;
    struct wl_data_source*                  dataSourceForClipboard;
    struct zwp_primary_selection_device_manager_v1* primarySelectionDeviceManager;
    struct zwp_primary_selection_device_v1*    primarySelectionDevice;
    struct zwp_primary_selection_source_v1*    dataSourceForPrimarySelection;
    struct xdg_activation_v1* xdg_activation_v1;
    struct xdg_toplevel_icon_manager_v1* xdg_toplevel_icon_manager_v1;
    struct xdg_system_bell_v1* xdg_system_bell_v1;
    struct xdg_toplevel_tag_manager_v1* xdg_toplevel_tag_manager_v1;
    struct wp_cursor_shape_manager_v1* wp_cursor_shape_manager_v1;
    struct wp_cursor_shape_device_v1* wp_cursor_shape_device_v1;
    struct wp_fractional_scale_manager_v1 *wp_fractional_scale_manager_v1;
    struct wp_viewporter *wp_viewporter;
    struct org_kde_kwin_blur_manager *org_kde_kwin_blur_manager;
    struct zwlr_layer_shell_v1* zwlr_layer_shell_v1; uint32_t zwlr_layer_shell_v1_version;
    struct wp_single_pixel_buffer_manager_v1 *wp_single_pixel_buffer_manager_v1;
    struct zwp_idle_inhibit_manager_v1* idle_inhibit_manager;
    struct zwp_keyboard_shortcuts_inhibit_manager_v1 *keyboard_shortcuts_inhibit_manager;

    int                         compositorVersion;
    int                         seatVersion;

    struct wl_surface*          cursorSurface;
    GLFWCursorShape             cursorPreviousShape;
    uint32_t                    serial, input_serial, pointer_serial, pointer_enter_serial, keyboard_enter_serial;

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

    struct {
        glfw_wl_xdg_activation_request *array;
        size_t capacity, sz;
    } activation_requests;

    EventLoopData eventLoopData;
    size_t dataOffersCounter;
    _GLFWWaylandDataOffer dataOffers[8];
    bool has_preferred_buffer_scale;
    char *compositor_name;
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
void _glfwWaylandBeforeBufferSwap(_GLFWwindow *window);
void _glfwWaylandAfterBufferSwap(_GLFWwindow *window);
void _glfwSetupWaylandDataDevice(void);
void _glfwSetupWaylandPrimarySelectionDevice(void);
double _glfwWaylandWindowScale(_GLFWwindow*);
int _glfwWaylandIntegerWindowScale(_GLFWwindow*);
void animateCursorImage(id_type timer_id, void *data);
struct wl_cursor* _glfwLoadCursor(GLFWCursorShape, struct wl_cursor_theme*);
void destroy_data_offer(_GLFWWaylandDataOffer*);
const char* _glfwWaylandCompositorName(void);

typedef struct wayland_cursor_shape {
    int which; const char *name;
} wayland_cursor_shape;

wayland_cursor_shape
glfw_cursor_shape_to_wayland_cursor_shape(GLFWCursorShape g);
