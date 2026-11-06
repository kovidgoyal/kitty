/*
 * surfaces.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Surfaces and swapchains for X11 and Wayland windows

#include "internal.h"
#include <X11/Xutil.h>
#include <dlfcn.h>

#define AS_SURFACE(handle) ((Surface *)(uintptr_t)(handle))

// libX11 {{{
// libX11 is already loaded by the X11 backend of glfw, it is used here only
// to find visuals.
static struct {
    bool loaded;
    int (*default_screen)(Display *);
    Visual *(*default_visual)(Display *, int);
    VisualID (*visual_id_from_visual)(Visual *);
    Status (*match_visual_info)(Display *, int, int, int, XVisualInfo *);
} x11;

static bool
load_x11(Driver *d) {
    if (x11.loaded) return true;
    void *lib = dlopen("libX11.so.6", RTLD_LAZY | RTLD_LOCAL);
    if (!lib) lib = dlopen("libX11.so", RTLD_LAZY | RTLD_LOCAL);
    if (!lib) {
        set_error(d, "Could not load libX11: %s", dlerror());
        return false;
    }
    *(void **)&x11.default_screen = dlsym(lib, "XDefaultScreen");
    *(void **)&x11.default_visual = dlsym(lib, "XDefaultVisual");
    *(void **)&x11.visual_id_from_visual = dlsym(lib, "XVisualIDFromVisual");
    *(void **)&x11.match_visual_info = dlsym(lib, "XMatchVisualInfo");
    if (!x11.default_screen || !x11.default_visual || !x11.visual_id_from_visual || !x11.match_visual_info) {
        set_error(d, "libX11 is missing required functions");
        return false;
    }
    x11.loaded = true;
    return true;
}
// }}}

bool
presentation_supported(Driver *d, VkPhysicalDevice device, uint32_t queue_family) {
    if (d->platform == GPU_PLATFORM_WAYLAND) return vkGetPhysicalDeviceWaylandPresentationSupportKHR(device, queue_family, d->native_display);
    if (!load_x11(d)) return false;
    Display *dpy = d->native_display;
    const VisualID visual = x11.visual_id_from_visual(x11.default_visual(dpy, x11.default_screen(dpy)));
    return vkGetPhysicalDeviceXlibPresentationSupportKHR(device, queue_family, dpy, visual);
}

bool
choose_native_visual(void *driver, const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint64_t *visual_id) {
    Driver *d = driver;
    *visual_id = 0;
    if (native->platform != GPU_PLATFORM_X11 || !config->transparent) return true;
    // Semi-transparent windows need a visual with an alpha channel
    if (!load_x11(d)) return false;
    Display *dpy = native->display;
    const int screen = native->screen < 0 ? x11.default_screen(dpy) : native->screen;
    XVisualInfo vi;
    if (x11.match_visual_info(dpy, screen, 32, TrueColor, &vi) &&
        vkGetPhysicalDeviceXlibPresentationSupportKHR(d->physical_device, d->queue_family, dpy, vi.visualid)) {
        *visual_id = vi.visualid;
    }
    return true;
}

// Swapchains {{{
static void
destroy_swapchain_objects(Driver *d, Swapchain *sc) {
    for (uint32_t i = 0; i < sc->num_images; i++) {
        destroy_image_views(d, sc->images + i);
        if (sc->present_semaphores[i]) vkDestroySemaphore(d->device, sc->present_semaphores[i], NULL);
    }
    free(sc->images);
    free(sc->present_semaphores);
    sc->images = NULL;
    sc->present_semaphores = NULL;
    sc->num_images = 0;
}

// Wait until the GPU no longer uses the swapchain of the surface
static void
finish_using_swapchain(Driver *d, Surface *s) {
    if (d->rendering.active && d->current_surface == s && !d->render_target) end_rendering(d);
    // Commands recorded for an acquired image must be submitted, as they wait on the acquire semaphore
    if (s->image_acquired) submit_commands(d, NULL, 0, false);
    s->image_acquired = false;
    vkQueueWaitIdle(d->queue);
    wait_for_serial(d, d->next_serial - 1);
}

static VkPresentModeKHR
choose_present_mode(Driver *d, Surface *s) {
    if (s->swap_interval > 0) return VK_PRESENT_MODE_FIFO_KHR; // always supported
    uint32_t n = 0;
    vkGetPhysicalDeviceSurfacePresentModesKHR(d->physical_device, s->surface, &n, NULL);
    VkPresentModeKHR modes[16];
    n = MIN(n, (uint32_t)arraysz(modes));
    vkGetPhysicalDeviceSurfacePresentModesKHR(d->physical_device, s->surface, &n, modes);
    // Mailbox never tears and, unlike FIFO, does not block when the window is hidden
    static const VkPresentModeKHR preferred[] = {VK_PRESENT_MODE_MAILBOX_KHR, VK_PRESENT_MODE_IMMEDIATE_KHR};
    for (size_t p = 0; p < arraysz(preferred); p++) {
        for (uint32_t i = 0; i < n; i++) {
            if (modes[i] == preferred[p]) return modes[i];
        }
    }
    return VK_PRESENT_MODE_FIFO_KHR;
}

static bool
choose_surface_format(Driver *d, Surface *s, VkFormat *format, VkFormat *srgb_format, VkColorSpaceKHR *color_space) {
    uint32_t n = 0;
    vkGetPhysicalDeviceSurfaceFormatsKHR(d->physical_device, s->surface, &n, NULL);
    VkSurfaceFormatKHR *formats = calloc(MAX(1u, n), sizeof(VkSurfaceFormatKHR));
    if (!formats) {
        set_error(d, "Out of memory");
        return false;
    }
    vkGetPhysicalDeviceSurfaceFormatsKHR(d->physical_device, s->surface, &n, formats);
    static const VkFormat preferred[][2] = {
        {VK_FORMAT_B8G8R8A8_UNORM, VK_FORMAT_B8G8R8A8_SRGB},
        {VK_FORMAT_R8G8B8A8_UNORM, VK_FORMAT_R8G8B8A8_SRGB},
    };
    bool found = false;
    for (size_t p = 0; p < arraysz(preferred) && !found; p++) {
        for (uint32_t i = 0; i < n && !found; i++) {
            if (formats[i].format == preferred[p][0] && formats[i].colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR) {
                *format = preferred[p][0];
                *srgb_format = preferred[p][1];
                *color_space = formats[i].colorSpace;
                found = true;
            }
        }
    }
    free(formats);
    if (!found) set_error(d, "The window surface supports no suitable format");
    return found;
}

static VkCompositeAlphaFlagBitsKHR
choose_composite_alpha(const Surface *s, VkCompositeAlphaFlagsKHR supported) {
    static const VkCompositeAlphaFlagBitsKHR transparent[] = {VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR, VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR};
    static const VkCompositeAlphaFlagBitsKHR opaque[] = {VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR, VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR};
    const VkCompositeAlphaFlagBitsKHR *order = s->config.transparent ? transparent : opaque;
    for (size_t i = 0; i < 2; i++) {
        if (supported & order[i]) return order[i];
    }
    for (uint32_t bit = 1; bit; bit <<= 1) {
        if (supported & bit) return (VkCompositeAlphaFlagBitsKHR)bit;
    }
    return VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
}

typedef enum {
    SWAPCHAIN_CREATED,
    SWAPCHAIN_EMPTY, // there is nothing to render to, such as when the window is minimized
    SWAPCHAIN_FAILED,
} SwapchainResult;

// (Re-)create the swapchain of the surface
static SwapchainResult
create_swapchain(Driver *d, Surface *s) {
    VkSurfaceCapabilitiesKHR caps;
    VkResult r = vkGetPhysicalDeviceSurfaceCapabilitiesKHR(d->physical_device, s->surface, &caps);
    if (r != VK_SUCCESS) {
        set_error(d, "Failed to query the window surface with error: %s", vk_result_string(r));
        return SWAPCHAIN_FAILED;
    }
    VkExtent2D extent = caps.currentExtent;
    if (extent.width == UINT32_MAX) {
        // The size is decided by the swapchain, as on Wayland
        extent.width = MAX(caps.minImageExtent.width, MIN(caps.maxImageExtent.width, s->width));
        extent.height = MAX(caps.minImageExtent.height, MIN(caps.maxImageExtent.height, s->height));
    }
    if (!extent.width || !extent.height) return SWAPCHAIN_EMPTY;
    VkFormat format, srgb_format;
    VkColorSpaceKHR color_space;
    if (!choose_surface_format(d, s, &format, &srgb_format, &color_space)) return SWAPCHAIN_FAILED;
    uint32_t num_images = MAX(caps.minImageCount + 1, 3u);
    if (caps.maxImageCount) num_images = MIN(num_images, caps.maxImageCount);
    const VkPresentModeKHR present_mode = choose_present_mode(d, s);
    const bool mutable_format = d->has_swapchain_mutable_format;
    const VkFormat view_formats[2] = {format, srgb_format};
    const VkImageFormatListCreateInfo format_list = {
        .sType = VK_STRUCTURE_TYPE_IMAGE_FORMAT_LIST_CREATE_INFO, .viewFormatCount = 2, .pViewFormats = view_formats};
    Swapchain old = s->swapchain;
    const VkSwapchainCreateInfoKHR info = {
        .sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR,
        .pNext = mutable_format ? &format_list : NULL,
        .flags = mutable_format ? VK_SWAPCHAIN_CREATE_MUTABLE_FORMAT_BIT_KHR : 0,
        .surface = s->surface,
        .minImageCount = num_images,
        .imageFormat = format,
        .imageColorSpace = color_space,
        .imageExtent = extent,
        .imageArrayLayers = 1,
        // Transfers are used to read back the contents of the window
        .imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT | (caps.supportedUsageFlags & VK_IMAGE_USAGE_TRANSFER_SRC_BIT),
        .imageSharingMode = VK_SHARING_MODE_EXCLUSIVE,
        .preTransform = (caps.supportedTransforms & VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR) ? VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR : caps.currentTransform,
        .compositeAlpha = choose_composite_alpha(s, caps.supportedCompositeAlpha),
        .presentMode = present_mode,
        .clipped = VK_TRUE,
        .oldSwapchain = old.swapchain,
    };
    VkSwapchainKHR swapchain;
    r = vkCreateSwapchainKHR(d->device, &info, NULL, &swapchain);
    if (old.swapchain) {
        destroy_swapchain_objects(d, &old);
        vkDestroySwapchainKHR(d->device, old.swapchain, NULL);
    }
    s->swapchain = (Swapchain){0};
    if (r != VK_SUCCESS) {
        set_error(d, "Failed to create the swapchain for the window with error: %s", vk_result_string(r));
        return SWAPCHAIN_FAILED;
    }
    Swapchain *sc = &s->swapchain;
    sc->swapchain = swapchain;
    sc->extent = extent;
    sc->format = format;
    sc->present_mode = present_mode;
    uint32_t n = 0;
    vkGetSwapchainImagesKHR(d->device, swapchain, &n, NULL);
    VkImage *images = calloc(MAX(1u, n), sizeof(VkImage));
    sc->images = calloc(MAX(1u, n), sizeof(Image));
    sc->present_semaphores = calloc(MAX(1u, n), sizeof(VkSemaphore));
    if (!images || !sc->images || !sc->present_semaphores) {
        free(images);
        set_error(d, "Out of memory");
        return SWAPCHAIN_FAILED;
    }
    vkGetSwapchainImagesKHR(d->device, swapchain, &n, images);
    sc->num_images = n;
    for (uint32_t i = 0; i < n; i++) {
        Image *img = sc->images + i;
        img->image = images[i];
        img->format = format;
        img->unorm_format = format;
        img->srgb_format = mutable_format ? srgb_format : VK_FORMAT_UNDEFINED;
        img->width = extent.width;
        img->height = extent.height;
        img->layers = 1;
        const VkSemaphoreCreateInfo si = {.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};
        if (!create_image_views(d, img, VK_IMAGE_VIEW_TYPE_MAX_ENUM) || vkCreateSemaphore(d->device, &si, NULL, sc->present_semaphores + i) != VK_SUCCESS) {
            free(images);
            set_error(d, "Failed to create the views of swapchain images: %s", d->last_error);
            return SWAPCHAIN_FAILED;
        }
    }
    free(images);
    s->needs_recreate = false;
    debug_print(d, "Created a Vulkan swapchain of %u images of size %ux%u with present mode: %d", n, extent.width, extent.height, (int)present_mode);
    return SWAPCHAIN_CREATED;
}

static void
destroy_swapchain(Driver *d, Surface *s) {
    if (!s->swapchain.swapchain) return;
    finish_using_swapchain(d, s);
    destroy_swapchain_objects(d, &s->swapchain);
    vkDestroySwapchainKHR(d->device, s->swapchain.swapchain, NULL);
    s->swapchain = (Swapchain){0};
}

static bool
recreate_swapchain(Driver *d, Surface *s) {
    if (s->swapchain.swapchain) finish_using_swapchain(d, s);
    switch (create_swapchain(d, s)) {
        case SWAPCHAIN_CREATED: return true;
        case SWAPCHAIN_EMPTY: return false;
        case SWAPCHAIN_FAILED: log_error(d, "Vulkan: %s", d->last_error); return false;
    }
    return false;
}

Image *
current_surface_image(Driver *d) {
    Surface *s = d->current_surface;
    if (!s) return NULL;
    if (s->image_acquired) return s->swapchain.images + s->image_index;
    for (int attempt = 0; attempt < 2; attempt++) {
        if ((s->needs_recreate || !s->swapchain.swapchain) && !recreate_swapchain(d, s)) return NULL;
        VkSemaphore sem = get_semaphore(d);
        uint32_t idx;
        // Do not block forever if the compositor never releases an image
        VkResult r = vkAcquireNextImageKHR(d->device, s->swapchain.swapchain, 1000000000ull, sem, VK_NULL_HANDLE, &idx);
        switch (r) {
            case VK_SUCCESS:
            case VK_SUBOPTIMAL_KHR: {
                if (r == VK_SUBOPTIMAL_KHR) s->needs_recreate = true; // at the next frame
                add_wait_semaphore(d, sem);
                s->image_acquired = true;
                s->image_index = idx;
                Image *img = s->swapchain.images + idx;
                // The previous contents are not needed, and the first access must
                // wait on the acquire semaphore, which submissions wait on at all stages
                img->state = (ImageState){.layout = VK_IMAGE_LAYOUT_UNDEFINED, .stage = VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT};
                return img;
            }
            case VK_ERROR_OUT_OF_DATE_KHR: s->needs_recreate = true; break;
            case VK_TIMEOUT:
            case VK_NOT_READY: debug_print(d, "Vulkan: Timed out acquiring a swapchain image"); return NULL;
            default: log_error(d, "Vulkan: Failed to acquire a swapchain image with error: %s", vk_result_string(r)); return NULL;
        }
    }
    return NULL;
}
// }}}

// Surfaces {{{
gpu_surface_t
surface_create(void *driver, const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint32_t width, uint32_t height) {
    Driver *d = driver;
    Surface *s = calloc(1, sizeof(Surface));
    if (!s) {
        set_error(d, "Out of memory");
        return GPU_NULL_HANDLE;
    }
    s->platform = native->platform;
    s->config = *config;
    s->width = width;
    s->height = height;
    s->swap_interval = config->swap_interval;
    VkResult r;
    if (native->platform == GPU_PLATFORM_WAYLAND) {
        const VkWaylandSurfaceCreateInfoKHR info = {
            .sType = VK_STRUCTURE_TYPE_WAYLAND_SURFACE_CREATE_INFO_KHR, .display = native->display, .surface = native->handle};
        r = vkCreateWaylandSurfaceKHR(d->instance, &info, NULL, &s->surface);
    } else if (native->platform == GPU_PLATFORM_X11) {
        const VkXlibSurfaceCreateInfoKHR info = {
            .sType = VK_STRUCTURE_TYPE_XLIB_SURFACE_CREATE_INFO_KHR, .dpy = native->display, .window = (Window)native->x11_window};
        r = vkCreateXlibSurfaceKHR(d->instance, &info, NULL, &s->surface);
    } else {
        set_error(d, "The Vulkan driver supports only X11 and Wayland windows");
        free(s);
        return GPU_NULL_HANDLE;
    }
    if (r != VK_SUCCESS) {
        set_error(d, "Failed to create a Vulkan surface for the window with error: %s", vk_result_string(r));
        free(s);
        return GPU_NULL_HANDLE;
    }
    VkBool32 supported = VK_FALSE;
    vkGetPhysicalDeviceSurfaceSupportKHR(d->physical_device, d->queue_family, s->surface, &supported);
    if (!supported) {
        set_error(d, "The GPU cannot present to the window");
        vkDestroySurfaceKHR(d->instance, s->surface, NULL);
        free(s);
        return GPU_NULL_HANDLE;
    }
    // Create the swapchain now, so that failures happen while kitty can still
    // fall back to another GPU driver. Windows of size zero get a swapchain later.
    if (create_swapchain(d, s) == SWAPCHAIN_FAILED) {
        vkDestroySurfaceKHR(d->instance, s->surface, NULL);
        free(s);
        return GPU_NULL_HANDLE;
    }
    LIST_ADD(d->surfaces, s);
    debug_print(d, "Created Vulkan surface for window of size: %ux%u", width, height);
    return AS_HANDLE(s);
}

void
surface_destroy(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    Surface *s = AS_SURFACE(surface);
    if (!s) return;
    destroy_swapchain(d, s);
    if (d->current_surface == s) d->current_surface = NULL;
    vkDestroySurfaceKHR(d->instance, s->surface, NULL);
    LIST_REMOVE(d->surfaces, s);
    free(s);
}

bool
make_surface_current(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    Surface *s = AS_SURFACE(surface);
    if (s != d->current_surface && !d->render_target) end_rendering(d);
    d->current_surface = s;
    return true;
}

gpu_surface_t
get_current_surface(void *driver) {
    return AS_HANDLE(((Driver *)driver)->current_surface);
}

void
surface_resize(void *driver UNUSED, gpu_surface_t surface, uint32_t width, uint32_t height) {
    Surface *s = AS_SURFACE(surface);
    if (!s) return;
    s->width = width;
    s->height = height;
    if (width != s->swapchain.extent.width || height != s->swapchain.extent.height) s->needs_recreate = true;
}

bool
surface_present(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    Surface *s = AS_SURFACE(surface);
    if (!s) return false;
    if (!s->image_acquired) return true; // nothing was rendered
    if (d->rendering.active && d->rendering.image == s->swapchain.images + s->image_index) end_rendering(d);
    Image *img = s->swapchain.images + s->image_index;
    transition_image(d, img, VK_IMAGE_LAYOUT_PRESENT_SRC_KHR, VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT, 0);
    VkSemaphore done = s->swapchain.present_semaphores[s->image_index];
    submit_commands(d, &done, 1, false);
    s->image_acquired = false;
    const VkPresentInfoKHR info = {
        .sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR,
        .waitSemaphoreCount = 1,
        .pWaitSemaphores = &done,
        .swapchainCount = 1,
        .pSwapchains = &s->swapchain.swapchain,
        .pImageIndices = &s->image_index,
    };
    VkResult r = vkQueuePresentKHR(d->queue, &info);
    switch (r) {
        case VK_SUCCESS: return true;
        case VK_SUBOPTIMAL_KHR:
        case VK_ERROR_OUT_OF_DATE_KHR: s->needs_recreate = true; return true;
        case VK_ERROR_DEVICE_LOST: fatal(d, "Vulkan: The GPU device was lost");
        default: set_error(d, "Failed to present the window with error: %s", vk_result_string(r)); return false;
    }
}

void
surface_set_swap_interval(void *driver, gpu_surface_t surface, int interval) {
    Driver *d = driver;
    Surface *s = AS_SURFACE(surface);
    if (!s || s->swap_interval == interval) return;
    s->swap_interval = interval;
    if (s->swapchain.swapchain && choose_present_mode(d, s) != s->swapchain.present_mode) s->needs_recreate = true;
}

void
surface_native_changed(void *driver UNUSED, gpu_surface_t surface UNUSED) {
    // Only needed on macOS
}

bool
surface_recreate(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    Surface *s = AS_SURFACE(surface);
    if (!s) return false;
    s->needs_recreate = true;
    return make_surface_current(d, surface);
}

void
release_native_resources(void *driver) {
    Driver *d = driver;
    while (d->surfaces) surface_destroy(d, AS_HANDLE(d->surfaces));
}
// }}}
