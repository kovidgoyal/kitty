/*
 * driver.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// The Vulkan implementation of the kitty GPU driver API, see ../api.h and
// internal.h for an overview.

#include "internal.h"
#include "version.h"
#include <dlfcn.h>

#define VK_DEFINE_FUNCTION(name) PFN_##name name = NULL;
VK_GLOBAL_FUNCTIONS(VK_DEFINE_FUNCTION)
VK_INSTANCE_FUNCTIONS(VK_DEFINE_FUNCTION)
VK_XLIB_FUNCTIONS(VK_DEFINE_FUNCTION)
VK_WAYLAND_FUNCTIONS(VK_DEFINE_FUNCTION)
VK_DEBUG_FUNCTIONS(VK_DEFINE_FUNCTION)
VK_DEVICE_FUNCTIONS(VK_DEFINE_FUNCTION)
#undef VK_DEFINE_FUNCTION
PFN_vkGetInstanceProcAddr vkGetInstanceProcAddr = NULL;

// There is only ever one driver per process
static Driver *the_driver = NULL;

// Errors {{{
void
set_error(Driver *d, const char *fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(d->last_error, sizeof(d->last_error), fmt, ap);
    va_end(ap);
}

void
log_error(Driver *d, const char *fmt, ...) {
    char buf[4096];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    d->params.log_error(buf);
}

void
debug_print(Driver *d, const char *fmt, ...) {
    if (!d->params.debug_rendering) return;
    char buf[4096];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    d->params.debug_print(buf);
}

void
fatal(Driver *d, const char *fmt, ...) {
    char buf[4096];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    d->params.fatal(buf);
    abort();
}

const char *
vk_result_string(VkResult r) {
    switch (r) {
#define C(x) \
    case x: return #x;
        C(VK_SUCCESS)
        C(VK_NOT_READY)
        C(VK_TIMEOUT)
        C(VK_INCOMPLETE)
        C(VK_SUBOPTIMAL_KHR)
        C(VK_ERROR_OUT_OF_HOST_MEMORY)
        C(VK_ERROR_OUT_OF_DEVICE_MEMORY)
        C(VK_ERROR_INITIALIZATION_FAILED)
        C(VK_ERROR_DEVICE_LOST)
        C(VK_ERROR_MEMORY_MAP_FAILED)
        C(VK_ERROR_LAYER_NOT_PRESENT)
        C(VK_ERROR_EXTENSION_NOT_PRESENT)
        C(VK_ERROR_FEATURE_NOT_PRESENT)
        C(VK_ERROR_INCOMPATIBLE_DRIVER)
        C(VK_ERROR_TOO_MANY_OBJECTS)
        C(VK_ERROR_FORMAT_NOT_SUPPORTED)
        C(VK_ERROR_SURFACE_LOST_KHR)
        C(VK_ERROR_NATIVE_WINDOW_IN_USE_KHR)
        C(VK_ERROR_OUT_OF_DATE_KHR)
        C(VK_ERROR_INCOMPATIBLE_DISPLAY_KHR)
        C(VK_ERROR_INVALID_SHADER_NV)
        C(VK_ERROR_OUT_OF_POOL_MEMORY)
        C(VK_ERROR_UNKNOWN)
#undef C
        default: return "unknown Vulkan error";
    }
}

void
check_vk(Driver *d, VkResult r, const char *what) {
    if (r != VK_SUCCESS) fatal(d, "Vulkan: %s failed with error: %s", what, vk_result_string(r));
}

static VKAPI_ATTR VkBool32 VKAPI_CALL
debug_messenger(
    VkDebugUtilsMessageSeverityFlagBitsEXT severity,
    VkDebugUtilsMessageTypeFlagsEXT type UNUSED,
    const VkDebugUtilsMessengerCallbackDataEXT *data,
    void *user_data) {
    Driver *d = user_data;
    if (severity >= VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT) log_error(d, "Vulkan: %s", data->pMessage);
    else debug_print(d, "Vulkan: %s", data->pMessage);
    return VK_FALSE;
}
// }}}

// Loading {{{
static bool
load_libvulkan(Driver *d) {
    static const char *names[] = {"libvulkan.so.1", "libvulkan.so"};
    for (size_t i = 0; i < arraysz(names) && !d->libvulkan; i++) d->libvulkan = dlopen(names[i], RTLD_LAZY | RTLD_LOCAL);
    if (!d->libvulkan) {
        set_error(d, "Could not load the Vulkan library: %s", dlerror());
        return false;
    }
    *(void **)&vkGetInstanceProcAddr = dlsym(d->libvulkan, "vkGetInstanceProcAddr");
    if (!vkGetInstanceProcAddr) {
        set_error(d, "The Vulkan library does not export vkGetInstanceProcAddr");
        return false;
    }
#define LOAD(name)                                                     \
    if (!(name = (PFN_##name)vkGetInstanceProcAddr(NULL, #name))) {    \
        set_error(d, "Could not load the Vulkan function: %s", #name); \
        return false;                                                  \
    }
    VK_GLOBAL_FUNCTIONS(LOAD)
#undef LOAD
    return true;
}

static bool
load_instance_functions(Driver *d) {
#define LOAD(name)                                                         \
    if (!(name = (PFN_##name)vkGetInstanceProcAddr(d->instance, #name))) { \
        set_error(d, "Could not load the Vulkan function: %s", #name);     \
        return false;                                                      \
    }
    VK_INSTANCE_FUNCTIONS(LOAD)
    if (d->platform == GPU_PLATFORM_WAYLAND) {
        VK_WAYLAND_FUNCTIONS(LOAD)
    } else {
        VK_XLIB_FUNCTIONS(LOAD)
    }
#undef LOAD
    if (d->has_debug_utils) {
#define LOAD(name) name = (PFN_##name)vkGetInstanceProcAddr(d->instance, #name);
        VK_DEBUG_FUNCTIONS(LOAD)
#undef LOAD
        if (!vkCreateDebugUtilsMessengerEXT || !vkDestroyDebugUtilsMessengerEXT) d->has_debug_utils = false;
    }
    return true;
}

static bool
load_device_functions(Driver *d) {
#define LOAD(name)                                                            \
    if (!(name = (PFN_##name)vkGetDeviceProcAddr(d->device, #name))) {        \
        set_error(d, "Could not load the Vulkan device function: %s", #name); \
        return false;                                                         \
    }
    VK_DEVICE_FUNCTIONS(LOAD)
#undef LOAD
    return true;
}
// }}}

// Instance and device {{{
static bool
has_extension(const VkExtensionProperties *exts, uint32_t count, const char *name) {
    for (uint32_t i = 0; i < count; i++) {
        if (strcmp(exts[i].extensionName, name) == 0) return true;
    }
    return false;
}

static bool
create_instance(Driver *d, GPUPlatform platform) {
    uint32_t version = 0;
    if (vkEnumerateInstanceVersion(&version) != VK_SUCCESS ||
        version < VK_MAKE_API_VERSION(0, VULKAN_REQUIRED_VERSION_MAJOR, VULKAN_REQUIRED_VERSION_MINOR, 0)) {
        set_error(
            d,
            "The Vulkan loader supports version %u.%u, at least %d.%d is needed",
            VK_API_VERSION_MAJOR(version),
            VK_API_VERSION_MINOR(version),
            VULKAN_REQUIRED_VERSION_MAJOR,
            VULKAN_REQUIRED_VERSION_MINOR);
        return false;
    }
    uint32_t num_exts = 0;
    vkEnumerateInstanceExtensionProperties(NULL, &num_exts, NULL);
    VkExtensionProperties *exts = calloc(MAX(1u, num_exts), sizeof(VkExtensionProperties));
    if (!exts) {
        set_error(d, "Out of memory");
        return false;
    }
    vkEnumerateInstanceExtensionProperties(NULL, &num_exts, exts);
    const char *platform_ext = platform == GPU_PLATFORM_WAYLAND ? VK_KHR_WAYLAND_SURFACE_EXTENSION_NAME : VK_KHR_XLIB_SURFACE_EXTENSION_NAME;
    const char *enabled[4];
    uint32_t num_enabled = 0;
    const char *required[] = {VK_KHR_SURFACE_EXTENSION_NAME, platform_ext};
    for (size_t i = 0; i < arraysz(required); i++) {
        if (!has_extension(exts, num_exts, required[i])) {
            set_error(d, "The Vulkan instance does not support the required extension: %s", required[i]);
            free(exts);
            return false;
        }
        enabled[num_enabled++] = required[i];
    }
    if (d->params.debug_rendering && has_extension(exts, num_exts, VK_EXT_DEBUG_UTILS_EXTENSION_NAME)) {
        enabled[num_enabled++] = VK_EXT_DEBUG_UTILS_EXTENSION_NAME;
        d->has_debug_utils = true;
    }
    free(exts);
    // Enable the validation layer when debugging rendering, if it is installed
    const char *layers[1];
    uint32_t num_layers = 0;
    if (d->params.debug_rendering) {
        uint32_t n = 0;
        vkEnumerateInstanceLayerProperties(&n, NULL);
        VkLayerProperties *props = calloc(MAX(1u, n), sizeof(VkLayerProperties));
        if (props) {
            vkEnumerateInstanceLayerProperties(&n, props);
            for (uint32_t i = 0; i < n; i++) {
                if (strcmp(props[i].layerName, "VK_LAYER_KHRONOS_validation") == 0) layers[num_layers++] = "VK_LAYER_KHRONOS_validation";
            }
            free(props);
        }
        debug_print(d, "Vulkan validation layer is %s", num_layers ? "enabled" : "not installed");
    }
    const VkApplicationInfo app = {
        .sType = VK_STRUCTURE_TYPE_APPLICATION_INFO,
        .pApplicationName = "kitty",
        .pEngineName = "kitty",
        .apiVersion = VK_MAKE_API_VERSION(0, VULKAN_REQUIRED_VERSION_MAJOR, VULKAN_REQUIRED_VERSION_MINOR, 0),
    };
    const VkDebugUtilsMessengerCreateInfoEXT messenger_info = {
        .sType = VK_STRUCTURE_TYPE_DEBUG_UTILS_MESSENGER_CREATE_INFO_EXT,
        .messageSeverity = VK_DEBUG_UTILS_MESSAGE_SEVERITY_WARNING_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_SEVERITY_ERROR_BIT_EXT,
        .messageType =
            VK_DEBUG_UTILS_MESSAGE_TYPE_GENERAL_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_VALIDATION_BIT_EXT | VK_DEBUG_UTILS_MESSAGE_TYPE_PERFORMANCE_BIT_EXT,
        .pfnUserCallback = debug_messenger,
        .pUserData = d,
    };
    const VkInstanceCreateInfo info = {
        .sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO,
        .pNext = d->has_debug_utils ? &messenger_info : NULL,
        .pApplicationInfo = &app,
        .enabledExtensionCount = num_enabled,
        .ppEnabledExtensionNames = enabled,
        .enabledLayerCount = num_layers,
        .ppEnabledLayerNames = layers,
    };
    VkResult r = vkCreateInstance(&info, NULL, &d->instance);
    if (r != VK_SUCCESS) {
        set_error(d, "Failed to create the Vulkan instance with error: %s", vk_result_string(r));
        return false;
    }
    if (!load_instance_functions(d)) return false;
    if (d->has_debug_utils) {
        if (vkCreateDebugUtilsMessengerEXT(d->instance, &messenger_info, NULL, &d->messenger) != VK_SUCCESS) d->messenger = VK_NULL_HANDLE;
    }
    return true;
}

static const char *required_device_extensions[] = {
    VK_KHR_SWAPCHAIN_EXTENSION_NAME,
    VK_KHR_PUSH_DESCRIPTOR_EXTENSION_NAME,
};

// Why the physical device cannot be used, NULL if it can. Sets queue_family
// to a queue family that supports graphics and presentation.
static const char *
unsuitable_device(Driver *d, VkPhysicalDevice dev, uint32_t *queue_family, bool *has_mutable_format) {
    static char reason[512];
    VkPhysicalDeviceProperties props;
    vkGetPhysicalDeviceProperties(dev, &props);
    if (props.apiVersion < VK_MAKE_API_VERSION(0, VULKAN_REQUIRED_VERSION_MAJOR, VULKAN_REQUIRED_VERSION_MINOR, 0)) {
        snprintf(reason, sizeof(reason), "it supports only Vulkan %u.%u", VK_API_VERSION_MAJOR(props.apiVersion), VK_API_VERSION_MINOR(props.apiVersion));
        return reason;
    }
    uint32_t num_exts = 0;
    vkEnumerateDeviceExtensionProperties(dev, NULL, &num_exts, NULL);
    VkExtensionProperties *exts = calloc(MAX(1u, num_exts), sizeof(VkExtensionProperties));
    if (!exts) return "out of memory";
    vkEnumerateDeviceExtensionProperties(dev, NULL, &num_exts, exts);
    for (size_t i = 0; i < arraysz(required_device_extensions); i++) {
        if (!has_extension(exts, num_exts, required_device_extensions[i])) {
            snprintf(reason, sizeof(reason), "it does not support the extension: %s", required_device_extensions[i]);
            free(exts);
            return reason;
        }
    }
    *has_mutable_format = has_extension(exts, num_exts, VK_KHR_SWAPCHAIN_MUTABLE_FORMAT_EXTENSION_NAME);
    free(exts);
    VkPhysicalDeviceVulkan13Features f13 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
    VkPhysicalDeviceVulkan11Features f11 = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES, .pNext = &f13};
    VkPhysicalDeviceFeatures2 features = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &f11};
    vkGetPhysicalDeviceFeatures2(dev, &features);
    if (!f13.dynamicRendering) return "it does not support dynamic rendering";
    if (!f13.synchronization2) return "it does not support synchronization2";
    if (!f11.shaderDrawParameters) return "it does not support shader draw parameters";
    uint32_t n = 0;
    vkGetPhysicalDeviceQueueFamilyProperties(dev, &n, NULL);
    VkQueueFamilyProperties *families = calloc(MAX(1u, n), sizeof(VkQueueFamilyProperties));
    if (!families) return "out of memory";
    vkGetPhysicalDeviceQueueFamilyProperties(dev, &n, families);
    bool found = false;
    for (uint32_t i = 0; i < n && !found; i++) {
        if ((families[i].queueFlags & VK_QUEUE_GRAPHICS_BIT) && presentation_supported(d, dev, i)) {
            *queue_family = i;
            found = true;
        }
    }
    free(families);
    if (!found) return "it has no queue that can render and present to windows on this display";
    return NULL;
}

static bool
create_device(Driver *d) {
    uint32_t n = 0;
    VkResult r = vkEnumeratePhysicalDevices(d->instance, &n, NULL);
    if (r != VK_SUCCESS || !n) {
        set_error(d, "No Vulkan devices found");
        return false;
    }
    VkPhysicalDevice *devices = calloc(n, sizeof(VkPhysicalDevice));
    if (!devices) {
        set_error(d, "Out of memory");
        return false;
    }
    vkEnumeratePhysicalDevices(d->instance, &n, devices);
    // Use the first suitable device, in the order of the Vulkan loader, which
    // puts the device driving the display first, honoring user preferences
    // such as DRI_PRIME and MESA_VK_DEVICE_SELECT.
    char reasons[2048] = {0};
    size_t pos = 0;
    for (uint32_t i = 0; i < n && !d->physical_device; i++) {
        uint32_t qf = 0;
        bool mutable_format = false;
        const char *reason = unsuitable_device(d, devices[i], &qf, &mutable_format);
        VkPhysicalDeviceProperties props;
        vkGetPhysicalDeviceProperties(devices[i], &props);
        if (reason) {
            debug_print(d, "Vulkan: Not using the device %s as %s", props.deviceName, reason);
            if (pos < sizeof(reasons)) pos += snprintf(reasons + pos, sizeof(reasons) - pos, "%s%s: %s", pos ? "; " : "", props.deviceName, reason);
            continue;
        }
        d->physical_device = devices[i];
        d->queue_family = qf;
        d->has_swapchain_mutable_format = mutable_format;
        d->properties = props;
    }
    free(devices);
    if (!d->physical_device) {
        set_error(d, "No suitable Vulkan device found: %s", reasons);
        return false;
    }
    vkGetPhysicalDeviceMemoryProperties(d->physical_device, &d->memory_properties);
    const float priority = 1.f;
    const VkDeviceQueueCreateInfo queue_info = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO,
        .queueFamilyIndex = d->queue_family,
        .queueCount = 1,
        .pQueuePriorities = &priority,
    };
    VkPhysicalDeviceVulkan13Features f13 = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES,
        .dynamicRendering = VK_TRUE,
        .synchronization2 = VK_TRUE,
    };
    VkPhysicalDeviceVulkan11Features f11 = {
        .sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES,
        .pNext = &f13,
        .shaderDrawParameters = VK_TRUE,
    };
    const VkPhysicalDeviceFeatures2 features = {.sType = VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2, .pNext = &f11};
    const char *exts[arraysz(required_device_extensions) + 1];
    uint32_t num_exts = 0;
    for (size_t i = 0; i < arraysz(required_device_extensions); i++) exts[num_exts++] = required_device_extensions[i];
    if (d->has_swapchain_mutable_format) exts[num_exts++] = VK_KHR_SWAPCHAIN_MUTABLE_FORMAT_EXTENSION_NAME;
    const VkDeviceCreateInfo info = {
        .sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO,
        .pNext = &features,
        .queueCreateInfoCount = 1,
        .pQueueCreateInfos = &queue_info,
        .enabledExtensionCount = num_exts,
        .ppEnabledExtensionNames = exts,
    };
    r = vkCreateDevice(d->physical_device, &info, NULL, &d->device);
    if (r != VK_SUCCESS) {
        set_error(d, "Failed to create the Vulkan device for %s with error: %s", d->properties.deviceName, vk_result_string(r));
        return false;
    }
    if (!load_device_functions(d)) return false;
    vkGetDeviceQueue(d->device, d->queue_family, 0, &d->queue);
    return true;
}

static bool
create_shared_objects(Driver *d) {
    // The indices of the two triangles covering a quad, see draw_quad() in ../api.h
    static const uint16_t indices[6] = {0, 1, 2, 0, 2, 3};
    if (!create_buffer_with_memory(d, sizeof(indices), VK_BUFFER_USAGE_INDEX_BUFFER_BIT, MEMORY_UPLOAD, &d->quad_indices, &d->quad_indices_alloc)) return false;
    memcpy(d->quad_indices_alloc.mapped, indices, sizeof(indices));
    for (size_t i = 0; i < NUM_CONTEXTS; i++) {
        Context *c = d->contexts + i;
        const VkCommandPoolCreateInfo pool_info = {
            .sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO,
            .flags = VK_COMMAND_POOL_CREATE_TRANSIENT_BIT,
            .queueFamilyIndex = d->queue_family,
        };
        if (vkCreateCommandPool(d->device, &pool_info, NULL, &c->pool) != VK_SUCCESS) {
            set_error(d, "Failed to create a Vulkan command pool");
            return false;
        }
        const VkCommandBufferAllocateInfo alloc_info = {
            .sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO,
            .commandPool = c->pool,
            .level = VK_COMMAND_BUFFER_LEVEL_PRIMARY,
            .commandBufferCount = 1,
        };
        if (vkAllocateCommandBuffers(d->device, &alloc_info, &c->cmd) != VK_SUCCESS) {
            set_error(d, "Failed to allocate a Vulkan command buffer");
            return false;
        }
        const VkFenceCreateInfo fence_info = {.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};
        if (vkCreateFence(d->device, &fence_info, NULL, &c->fence) != VK_SUCCESS) {
            set_error(d, "Failed to create a Vulkan fence");
            return false;
        }
    }
    d->next_serial = 1;
    return create_samplers(d);
}
// }}}

// Lifecycle {{{
static const char *
shader_target(void *driver UNUSED) {
#define S(x) #x
#define TARGET(v) "spirv-" S(v)
    return TARGET(SPIRV_VERSION);
#undef TARGET
#undef S
}

static bool
connect_to_display(void *driver, const GPUNativeWindow *display) {
    Driver *d = driver;
    if (display->platform != GPU_PLATFORM_X11 && display->platform != GPU_PLATFORM_WAYLAND) {
        set_error(d, "The Vulkan driver supports only X11 and Wayland");
        return false;
    }
    d->platform = display->platform;
    d->native_display = display->display;
    if (!load_libvulkan(d) || !create_instance(d, display->platform) || !create_device(d) || !create_shared_objects(d)) return false;
    snprintf(
        d->version_string,
        sizeof(d->version_string),
        "Vulkan %u.%u.%u on %s",
        VK_API_VERSION_MAJOR(d->properties.apiVersion),
        VK_API_VERSION_MINOR(d->properties.apiVersion),
        VK_API_VERSION_PATCH(d->properties.apiVersion),
        d->properties.deviceName);
    debug_print(d, "Using %s", d->version_string);
    return true;
}

static bool
initialize(void *driver) {
    Driver *d = driver;
    if (!d->device) {
        set_error(d, "The Vulkan driver was not connected to a display");
        return false;
    }
    d->initialized = true;
    return true;
}

static void
destroy(void *driver) {
    Driver *d = driver;
    if (d->device) {
        vkDeviceWaitIdle(d->device);
        release_native_resources(d);
        destroy_contexts(d);
        destroy_all_pipelines(d);
        destroy_all_textures(d);
        destroy_all_buffers(d);
        while (d->vertex_layouts) vertex_layout_destroy(d, AS_HANDLE(d->vertex_layouts));
        destroy_samplers(d);
        if (d->quad_indices) {
            vkDestroyBuffer(d->device, d->quad_indices, NULL);
            free_memory(d, &d->quad_indices_alloc);
        }
        for (size_t i = 0; i < d->num_free_semaphores; i++) vkDestroySemaphore(d->device, d->free_semaphores[i], NULL);
        free_all_memory(d);
        vkDestroyDevice(d->device, NULL);
    }
    if (d->instance) {
        if (d->messenger) vkDestroyDebugUtilsMessengerEXT(d->instance, d->messenger, NULL);
        vkDestroyInstance(d->instance, NULL);
    }
    // The library is not unloaded, as with the drivers themselves, see unload_gpu_driver()
    if (the_driver == d) the_driver = NULL;
    free(d);
}

static const char *
last_error(void *driver) {
    return ((Driver *)driver)->last_error;
}

static const char *
version_string(void *driver) {
    return ((Driver *)driver)->version_string;
}

static void
get_capabilities(void *driver, GPUCapabilities *ans) {
    Driver *d = driver;
    ans->max_texture_size = d->properties.limits.maxImageDimension2D;
    ans->max_array_texture_layers = d->properties.limits.maxImageArrayLayers;
    // Encoding to sRGB needs both UNORM and SRGB views of swapchain images
    ans->supports_srgb_output = d->has_swapchain_mutable_format;
    // Vulkan places no alignment requirements on vertex input offsets and strides
    ans->vertex_input_alignment = 1;
}
// }}}

__attribute__((visibility("default"))) bool
kitty_gpu_driver_load(uint32_t api_version, const GPUDriverInitParams *params, GPUDriverAPI *api, void **driver, char *errbuf, size_t errbuf_size) {
    if (api_version != KITTY_GPU_API_VERSION) {
        snprintf(errbuf, errbuf_size, "The Vulkan driver supports GPU API version %u but version %u was requested", KITTY_GPU_API_VERSION, api_version);
        return false;
    }
    if (!params->log_error || !params->fatal || !params->debug_print) {
        snprintf(errbuf, errbuf_size, "The Vulkan driver was not passed all required callbacks");
        return false;
    }
    if (the_driver) {
        snprintf(errbuf, errbuf_size, "The Vulkan driver has already been loaded");
        return false;
    }
    Driver *d = calloc(1, sizeof(Driver));
    if (!d) {
        snprintf(errbuf, errbuf_size, "Out of memory allocating the Vulkan driver");
        return false;
    }
    d->params = *params;
    the_driver = d;
    *api = (GPUDriverAPI){
        .api_version = KITTY_GPU_API_VERSION,
        .name = "Vulkan",
#define F(name) .name = name
        F(shader_target),
        .connect = connect_to_display,
        F(initialize),
        F(destroy),
        F(last_error),
        F(version_string),
        F(get_capabilities),

        F(texture_create),
        F(texture_reset),
        F(texture_destroy),
        F(texture_upload),
        F(texture_copy),
        F(texture_read),
        F(texture_get_desc),
        F(bind_texture),

        F(buffer_create),
        F(buffer_destroy),
        F(buffer_allocate),
        F(buffer_map),
        F(buffer_unmap),
        F(buffer_copy),
        F(bind_uniform_buffer),

        F(pipeline_create),
        F(pipeline_destroy),
        F(use_pipeline),
        F(pipeline_uniform_block),
        F(pipeline_attribute_location),
        F(set_params),

        F(vertex_layout_create),
        F(vertex_layout_destroy),
        F(bind_vertex_layout),
        F(vertex_layout_set_attribute),

        F(choose_native_visual),
        F(surface_create),
        F(surface_destroy),
        F(make_surface_current),
        F(get_current_surface),
        F(surface_resize),
        F(surface_present),
        F(surface_set_swap_interval),
        F(surface_native_changed),
        F(surface_recreate),
        F(release_native_resources),

        F(render_target_create),
        F(render_target_destroy),
        F(set_render_target),
        F(get_render_target),
        F(render_target_status),
        F(clear),
        F(set_viewport),
        F(get_viewport),
        F(set_scissor),
        F(set_srgb_output),
        F(read_pixels),
        F(copy_to_texture),

        F(draw_quad),
#undef F
    };
    *driver = d;
    return true;
}
