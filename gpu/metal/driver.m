/*
 * driver.m
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// The Metal implementation of the kitty GPU driver API, see ../api.h and
// internal.h for an overview.

#include "internal.h"
#include "version.h"
#import <CoreGraphics/CGDirectDisplayMetal.h>

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
error_description(NSError *err) {
    if (err == nil) return "unknown error";
    const char *ans = [[err localizedDescription] UTF8String];
    return ans ? ans : "unknown error";
}
// }}}

// Device {{{
static id<MTLDevice>
choose_device(Driver *d) {
    // Use the GPU driving the main display, which avoids copying rendered
    // frames between GPUs and, on machines with automatic graphics switching,
    // does not force a switch to the discrete GPU.
    id<MTLDevice> ans = CGDirectDisplayCopyCurrentMetalDevice(CGMainDisplayID());
    if (ans == nil) {
        debug_print(d, "Metal: Could not get the GPU driving the main display, using the system default GPU");
        ans = MTLCreateSystemDefaultDevice();
    }
    return ans;
}

static bool
create_shared_objects(Driver *d) {
    // The indices of the two triangles covering a quad, see draw_quad() in ../api.h
    static const uint16_t indices[6] = {0, 1, 2, 0, 2, 3};
    d->quad_indices = [d->device newBufferWithBytes:indices length:sizeof(indices) options:MTLResourceStorageModeShared];
    if (d->quad_indices == nil) {
        set_error(d, "Failed to create a Metal buffer");
        return false;
    }
    d->in_flight = dispatch_semaphore_create(NUM_IN_FLIGHT);
    if (!d->in_flight) {
        set_error(d, "Failed to create a semaphore");
        return false;
    }
    d->next_serial = 1;
    return create_samplers(d) && create_utility_pipelines(d);
}
// }}}

// Lifecycle {{{
static const char *
shader_target(void *driver UNUSED) {
#define S(x) #x
#define TARGET(v) "msl-" S(v)
    return TARGET(MSL_VERSION);
#undef TARGET
#undef S
}

static bool
connect_to_display(void *driver, const GPUNativeWindow *display) {
    Driver *d = driver;
    if (display->platform != GPU_PLATFORM_COCOA) {
        set_error(d, "The Metal driver supports only Cocoa");
        return false;
    }
    if (d->params.renderer == GPU_RENDERER_SOFTWARE) {
        set_error(d, "Metal has no software renderer");
        return false;
    }
    @autoreleasepool {
        d->device = choose_device(d);
        if (d->device == nil) {
            set_error(d, "No Metal capable GPU found");
            return false;
        }
        // MSL 2.4 needs macOS 12, every Mac that can run it supports the Mac2 or Apple7 GPU families.
        // Mac2 is deprecated from macOS 27, which no longer supports the Intel Macs that need it.
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        const bool supported = [d->device supportsFamily:MTLGPUFamilyApple7] || [d->device supportsFamily:MTLGPUFamilyMac2];
#pragma clang diagnostic pop
        if (!supported) {
            set_error(d, "The GPU %s does not support the Metal features needed by kitty", [[d->device name] UTF8String]);
            return false;
        }
        d->queue = [d->device newCommandQueueWithMaxCommandBufferCount:NUM_IN_FLIGHT + 1];
        if (d->queue == nil) {
            set_error(d, "Failed to create a Metal command queue");
            return false;
        }
        [d->queue setLabel:@"kitty"];
        if (!create_shared_objects(d)) return false;
        snprintf(d->version_string, sizeof(d->version_string), "Metal (MSL %d.%d) on %s", MSL_VERSION / 10, MSL_VERSION % 10, [[d->device name] UTF8String]);
    }
    debug_print(d, "Using %s", d->version_string);
    return true;
}

static bool
initialize(void *driver) {
    Driver *d = driver;
    if (d->device == nil) {
        set_error(d, "The Metal driver was not connected to a display");
        return false;
    }
    d->initialized = true;
    return true;
}

static void
destroy(void *driver) {
    Driver *d = driver;
    @autoreleasepool {
        if (d->device != nil) {
            release_native_resources(d);
            if (d->cmd != nil) submit_commands(d, false);
            // Acquiring every slot ensures the completed handlers of all
            // command buffers have run, as they access the driver
            if (d->in_flight) wait_for_idle(d);
            release_staging(d);
            destroy_all_pipelines(d);
            destroy_all_textures(d);
            destroy_all_buffers(d);
            while (d->vertex_layouts) vertex_layout_destroy(d, AS_HANDLE(d->vertex_layouts));
            destroy_utility_pipelines(d);
            destroy_samplers(d);
            [d->quad_indices release];
            [d->queue release];
            [d->device release];
        }
        if (d->in_flight) dispatch_release(d->in_flight);
    }
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
    ans->max_texture_size = MAX_TEXTURE_SIZE;
    ans->max_array_texture_layers = MAX_TEXTURE_LAYERS;
    // Any texture can be viewed with the sRGB variant of its pixel format, including drawables
    ans->supports_srgb_output = d->device != nil;
    ans->vertex_input_alignment = VERTEX_INPUT_ALIGNMENT;
    ans->is_software = false; // Metal always renders on a GPU
}
// }}}

__attribute__((visibility("default"))) bool
kitty_gpu_driver_load(uint32_t api_version, const GPUDriverInitParams *params, GPUDriverAPI *api, void **driver, char *errbuf, size_t errbuf_size) {
    if (api_version != KITTY_GPU_API_VERSION) {
        snprintf(errbuf, errbuf_size, "The Metal driver supports GPU API version %u but version %u was requested", KITTY_GPU_API_VERSION, api_version);
        return false;
    }
    if (!params->log_error || !params->fatal || !params->debug_print) {
        snprintf(errbuf, errbuf_size, "The Metal driver was not passed all required callbacks");
        return false;
    }
    if (the_driver) {
        snprintf(errbuf, errbuf_size, "The Metal driver has already been loaded");
        return false;
    }
    Driver *d = calloc(1, sizeof(Driver));
    if (!d) {
        snprintf(errbuf, errbuf_size, "Out of memory allocating the Metal driver");
        return false;
    }
    d->params = *params;
    the_driver = d;
    *api = (GPUDriverAPI){
        .api_version = KITTY_GPU_API_VERSION,
        .name = "Metal",
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
