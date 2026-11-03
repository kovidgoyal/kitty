/*
 * nsgl.m
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 * Based on nsgl_context.m from GLFW, Copyright (c) 2009-2019 Camilla Löwy
 *
 * Distributed under terms of the GPL3 license.
 */

// OpenGL contexts for Cocoa windows, created using NSOpenGLContext

#include "platform.h"
#include "version.h"
#import <Cocoa/Cocoa.h>
#include <OpenGL/OpenGL.h>
#include <stdlib.h>

struct GLSurface {
    NSOpenGLPixelFormat *pixel_format;
    NSOpenGLContext *context;
    NSView *view;
    bool high_resolution;
};

static const GLPlatformHost *host = NULL;
static CFBundleRef framework = NULL;
// We use a globally shared context across all OS Windows so that if all OS
// Windows are closed the context does not have to be recreated with all
// associated data lost. On Apple kitty can remain running with no OS Windows.
static NSOpenGLContext *globally_shared_context = nil;

static bool
choose_native_visual(const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint64_t *visual_id) {
    (void)native;
    (void)config;
    *visual_id = 0;
    return true;
}

static bool
make_current(GLSurface *s) {
    if (s) [s->context makeCurrentContext];
    else [NSOpenGLContext clearCurrentContext];
    return true;
}

static void
surface_destroy(GLSurface *s) {
    if (!s) return;
    @autoreleasepool {
        if (s->context != nil) {
            if ([NSOpenGLContext currentContext] == s->context) [NSOpenGLContext clearCurrentContext];
            [s->context release];
        }
        [s->pixel_format release];
        [s->view release];
    }
    free(s);
}

static void
attach_to_view(GLSurface *s, NSOpenGLContext *context) {
    [s->view setWantsBestResolutionOpenGLSurface:(s->high_resolution ? YES : NO)];
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    [context setView:s->view];
#pragma clang diagnostic pop
}

static GLSurface *
surface_create(const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint32_t width, uint32_t height) {
    (void)width;
    (void)height;
    if (native->platform != GPU_PLATFORM_COCOA || !native->handle) {
        host->set_error("NSGL: Only Cocoa windows are supported");
        return NULL;
    }
    if (!framework) {
        framework = CFBundleGetBundleWithIdentifier(CFSTR("com.apple.opengl"));
        if (framework == NULL) {
            host->set_error("NSGL: Failed to locate OpenGL framework");
            return NULL;
        }
    }
    GLSurface *s = calloc(1, sizeof(GLSurface));
    if (!s) {
        host->set_error("NSGL: Out of memory");
        return NULL;
    }
    s->view = [(NSView *)native->handle retain];
    s->high_resolution = config->high_resolution;

    NSOpenGLPixelFormatAttribute attribs[40];
    int index = 0;
#define add_attrib(a) attribs[index++] = a
#define set_attrib(a, v) \
    {                    \
        add_attrib(a);   \
        add_attrib(v);   \
    }
    add_attrib(NSOpenGLPFAAccelerated);
    add_attrib(NSOpenGLPFAClosestPolicy);
    if (config->allow_offline_renderers) {
        add_attrib(NSOpenGLPFAAllowOfflineRenderers);
        // NOTE: This replaces the NSSupportsAutomaticGraphicsSwitching key in
        //       Info.plist for unbundled applications
        // HACK: This assumes that NSOpenGLPixelFormat will remain
        //       a straightforward wrapper of its CGL counterpart
        add_attrib(kCGLPFASupportsAutomaticGraphicsSwitching);
    }
#if OPENGL_REQUIRED_VERSION_MAJOR >= 4
    set_attrib(NSOpenGLPFAOpenGLProfile, NSOpenGLProfileVersion4_1Core);
#else
    set_attrib(NSOpenGLPFAOpenGLProfile, NSOpenGLProfileVersion3_2Core);
#endif
    set_attrib(NSOpenGLPFAColorSize, 24);
    set_attrib(NSOpenGLPFAAlphaSize, 8);
    // kitty uses neither depth nor stencil buffers
    set_attrib(NSOpenGLPFADepthSize, 0);
    set_attrib(NSOpenGLPFAStencilSize, 0);
    add_attrib(NSOpenGLPFADoubleBuffer);
    set_attrib(NSOpenGLPFASampleBuffers, 0);
    // NOTE: All NSOpenGLPixelFormats on the relevant cards support sRGB
    //       framebuffer, so there's no need (and no way) to request it
    add_attrib(0);
#undef add_attrib
#undef set_attrib

    s->pixel_format = [[NSOpenGLPixelFormat alloc] initWithAttributes:attribs];
    if (s->pixel_format == nil) {
        host->set_error("NSGL: Failed to find a suitable pixel format");
        surface_destroy(s);
        return NULL;
    }
    s->context = [[NSOpenGLContext alloc] initWithFormat:s->pixel_format shareContext:globally_shared_context];
    if (s->context == nil) {
        host->set_error(
            "NSGL: Failed to create OpenGL context. kitty requires working OpenGL %d.%d drivers.",
            OPENGL_REQUIRED_VERSION_MAJOR,
            OPENGL_REQUIRED_VERSION_MINOR);
        surface_destroy(s);
        return NULL;
    }
    if (globally_shared_context == nil) globally_shared_context = [s->context retain];
    if (config->transparent) {
        GLint opaque = 0;
        [s->context setValues:&opaque forParameter:NSOpenGLContextParameterSurfaceOpacity];
    }
    // Swap intervals do not work as of Mojave, kitty uses CVDisplayLink instead
    GLint interval = 0;
    [s->context setValues:&interval forParameter:NSOpenGLContextParameterSwapInterval];
    attach_to_view(s, s->context);
    return s;
}

static void
surface_resize(GLSurface *s, uint32_t width, uint32_t height) {
    (void)width;
    (void)height;
    // The drawable is updated by native_changed()
    (void)s;
}

static bool
present(GLSurface *s) {
    [s->context flushBuffer];
    return true;
}

static void
set_swap_interval(GLSurface *s, int interval) {
    // As of Mojave this does not work so kitty uses CVDisplayLink instead
    (void)s;
    (void)interval;
}

static void
native_changed(GLSurface *s) {
    @try {
        [s->context update];
    } @catch (NSException *e) { host->log_error("Failed to update NSGL Context object with error: %s (%s)", [[e name] UTF8String], [[e reason] UTF8String]); }
}

static bool
recreate(GLSurface *s) {
    @try {
        NSOpenGLContext *old_context = s->context;
        // Create a new context sharing resources with the old one
        NSOpenGLContext *new_context = [[NSOpenGLContext alloc] initWithFormat:s->pixel_format shareContext:old_context];
        if (new_context == nil) {
            host->set_error("NSGL: Failed to create OpenGL context");
            return false;
        }
        // Copy settings from old context
        GLint opacity = 0;
        [old_context getValues:&opacity forParameter:NSOpenGLContextParameterSurfaceOpacity];
        [new_context setValues:&opacity forParameter:NSOpenGLContextParameterSurfaceOpacity];
        GLint interval = 0;
        [new_context setValues:&interval forParameter:NSOpenGLContextParameterSwapInterval];
        // Detach old context
        [NSOpenGLContext clearCurrentContext];
        [old_context clearDrawable];
        // Attach new context to the view
        attach_to_view(s, new_context);
        [new_context makeCurrentContext];
        [new_context update];
        // Replace context
        s->context = new_context;
        [old_context release];
    } @catch (NSException *e) {
        host->set_error("Failed to recreate NSGL context: %s (%s)", [[e name] UTF8String], [[e reason] UTF8String]);
        return false;
    }
    return true;
}

static gl_proc
get_proc_address(const char *name) {
    CFStringRef symbol_name = CFStringCreateWithCString(kCFAllocatorDefault, name, kCFStringEncodingASCII);
    gl_proc symbol = NULL;
    *(void **)&symbol = CFBundleGetFunctionPointerForName(framework, symbol_name);
    CFRelease(symbol_name);
    return symbol;
}

static void
terminate(void) {
    if (globally_shared_context != nil) {
        [globally_shared_context release];
        globally_shared_context = nil;
    }
}

const GLPlatform *
nsgl_platform(const GLPlatformHost *h) {
    static const GLPlatform ans = {
        .name = "NSGL",
        .choose_native_visual = choose_native_visual,
        .surface_create = surface_create,
        .surface_destroy = surface_destroy,
        .make_current = make_current,
        .surface_resize = surface_resize,
        .present = present,
        .set_swap_interval = set_swap_interval,
        .native_changed = native_changed,
        .recreate = recreate,
        .get_proc_address = get_proc_address,
        .terminate = terminate,
    };
    host = h;
    return &ans;
}
