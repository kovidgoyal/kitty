/*
 * surfaces.m
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

// Surfaces, rendering into Cocoa windows with CAMetalLayer

#include "internal.h"

#define AS_SURFACE(handle) ((Surface *)(uintptr_t)(handle))

bool
choose_native_visual(void *driver UNUSED, const GPUNativeWindow *native UNUSED, const GPUSurfaceConfig *config UNUSED, uint64_t *visual_id) {
    *visual_id = 0;
    return true;
}

// Update the properties of the layer that depend on the window
static void
configure_layer(Surface *s) {
    @autoreleasepool {
        NSWindow *w = [s->view window];
        [s->layer setContentsScale:(s->config.high_resolution && w != nil) ? [w backingScaleFactor] : 1.0];
        // The contents are in the color space of the window, as with OpenGL,
        // see the macos_colorspace option
        [s->layer setColorspace:w != nil ? [[w colorSpace] CGColorSpace] : NULL];
        if (s->width && s->height) [s->layer setDrawableSize:CGSizeMake(s->width, s->height)];
    }
}

// Release the drawable of the surface, without presenting it
static void
release_drawable(Driver *d, Surface *s) {
    if (s->drawable == nil) return;
    if (d->rendering.texture == [s->drawable texture]) end_rendering(d);
    [s->drawable_srgb_view release];
    [s->drawable release];
    s->drawable_srgb_view = nil;
    s->drawable = nil;
}

bool
current_surface_image(Driver *d, RenderImage *ans) {
    Surface *s = d->current_surface;
    if (!s) return false;
    if (s->drawable == nil) {
        // There is nothing to render to, such as when the window is minimized
        if (!s->width || !s->height) return false;
        @autoreleasepool {
            // Waits for at most a second, see allowsNextDrawableTimeout
            s->drawable = [[s->layer nextDrawable] retain];
        }
        if (s->drawable == nil) {
            debug_print(d, "Metal: Timed out acquiring a drawable");
            return false;
        }
        // The view for encoding to sRGB, see set_srgb_output(). Views that
        // differ from the texture only in being sRGB need no special usage.
        s->drawable_srgb_view = [[s->drawable texture] newTextureViewWithPixelFormat:MTLPixelFormatBGRA8Unorm_sRGB];
    }
    id<MTLTexture> t = [s->drawable texture];
    *ans = (RenderImage){.texture = t, .unorm_view = t, .srgb_view = s->drawable_srgb_view, .width = (uint32_t)[t width], .height = (uint32_t)[t height]};
    return true;
}

gpu_surface_t
surface_create(void *driver, const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint32_t width, uint32_t height) {
    Driver *d = driver;
    if (native->platform != GPU_PLATFORM_COCOA || !native->handle) {
        set_error(d, "The Metal driver supports only Cocoa windows");
        return GPU_NULL_HANDLE;
    }
    Surface *s = calloc(1, sizeof(Surface));
    if (!s) {
        set_error(d, "Out of memory");
        return GPU_NULL_HANDLE;
    }
    s->config = *config;
    s->width = width;
    s->height = height;
    @autoreleasepool {
        s->layer = [[CAMetalLayer layer] retain];
        if (s->layer == nil) {
            set_error(d, "Failed to create a CAMetalLayer");
            free(s);
            return GPU_NULL_HANDLE;
        }
        s->view = [(NSView *)native->handle retain];
        [s->layer setDevice:d->device];
        [s->layer setPixelFormat:MTLPixelFormatBGRA8Unorm];
        // Drawables are read back and copied from, see read_pixels() and copy_to_texture()
        [s->layer setFramebufferOnly:NO];
        [s->layer setOpaque:config->transparent ? NO : YES];
        [s->layer setMaximumDrawableCount:3];
        [s->layer setAllowsNextDrawableTimeout:YES];
        // kitty paces rendering itself, using CVDisplayLink, as with OpenGL,
        // where the swap interval is zero, see surface_set_swap_interval()
        [s->layer setDisplaySyncEnabled:NO];
        configure_layer(s);
        // Make the view layer hosting, the layer must be set before wantsLayer
        [s->view setLayer:s->layer];
        [s->view setWantsLayer:YES];
    }
    LIST_ADD(d->surfaces, s);
    debug_print(d, "Created Metal surface for window of size: %ux%u", width, height);
    return AS_HANDLE(s);
}

void
surface_destroy(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    Surface *s = AS_SURFACE(surface);
    if (!s) return;
    release_drawable(d, s);
    if (d->current_surface == s) d->current_surface = NULL;
    @autoreleasepool {
        if ([s->view layer] == s->layer) {
            [s->view setWantsLayer:NO];
            [s->view setLayer:nil];
        }
        [s->layer release];
        [s->view release];
    }
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
    // A drawable that has already been acquired keeps its size until presented
    configure_layer(s);
}

bool
surface_present(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    Surface *s = AS_SURFACE(surface);
    if (!s) return false;
    if (s->drawable == nil) return true; // nothing was rendered
    @autoreleasepool {
        if (d->rendering.texture == [s->drawable texture]) end_rendering(d);
        // Presented once the command buffer has completed
        [command_buffer(d) presentDrawable:s->drawable];
        submit_commands(d, false);
        release_drawable(d, s);
    }
    return true;
}

void
surface_set_swap_interval(void *driver UNUSED, gpu_surface_t surface, int interval) {
    Surface *s = AS_SURFACE(surface);
    if (!s || s->swap_interval == interval) return;
    s->swap_interval = interval;
    [s->layer setDisplaySyncEnabled:interval > 0 ? YES : NO];
}

void
surface_native_changed(void *driver UNUSED, gpu_surface_t surface) {
    // The window changed screens or its backing properties changed
    Surface *s = AS_SURFACE(surface);
    if (s) configure_layer(s);
}

bool
surface_recreate(void *driver, gpu_surface_t surface) {
    Driver *d = driver;
    Surface *s = AS_SURFACE(surface);
    if (!s) return false;
    // A new drawable is acquired by the next rendering
    release_drawable(d, s);
    @autoreleasepool {
        if ([s->view layer] != s->layer) {
            [s->view setLayer:s->layer];
            [s->view setWantsLayer:YES];
        }
    }
    configure_layer(s);
    return make_surface_current(d, surface);
}

void
release_native_resources(void *driver) {
    Driver *d = driver;
    while (d->surfaces) surface_destroy(d, AS_HANDLE(d->surfaces));
}
