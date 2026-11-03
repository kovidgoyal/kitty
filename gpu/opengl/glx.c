/*
 * glx.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 * Based on glx_context.c from GLFW, Copyright (c) 2002-2006 Marcus Geelnard
 * and (c) 2006-2019 Camilla Löwy
 *
 * Distributed under terms of the GPL3 license.
 */

// OpenGL contexts for X11 windows, created using GLX. All libraries are
// loaded at runtime, so that the driver has no link time dependencies.

#include "platform.h"
#include "version.h"
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/extensions/Xrender.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define GLX_VENDOR 1
#define GLX_RGBA_TYPE 0x8014
#define GLX_DOUBLEBUFFER 5
#define GLX_RED_SIZE 8
#define GLX_GREEN_SIZE 9
#define GLX_BLUE_SIZE 10
#define GLX_ALPHA_SIZE 11
#define GLX_DEPTH_SIZE 12
#define GLX_STENCIL_SIZE 13
#define GLX_DRAWABLE_TYPE 0x8010
#define GLX_VISUAL_ID 0x800b
#define GLX_FRAMEBUFFER_SRGB_CAPABLE_ARB 0x20b2
#define GLX_CONTEXT_FORWARD_COMPATIBLE_BIT_ARB 0x00000002
#define GLX_CONTEXT_MAJOR_VERSION_ARB 0x2091
#define GLX_CONTEXT_MINOR_VERSION_ARB 0x2092
#define GLX_CONTEXT_FLAGS_ARB 0x2094

typedef XID GLXWindow;
typedef XID GLXDrawable;
typedef struct __GLXFBConfig *GLXFBConfig;
typedef struct __GLXcontext *GLXContext;

static struct {
    void *handle, *x11_handle, *xrender_handle;
    Display *display;
    int screen;
    int major, minor, event_base, error_base;
    bool initialized, xrender_available;
    bool SGI_swap_control, EXT_swap_control, MESA_swap_control, ARB_framebuffer_sRGB, EXT_framebuffer_sRGB, ARB_create_context;
    // The cached result of choose_fb_config()
    struct {
        bool valid, transparent, srgb;
        GLXFBConfig config;
    } chosen;

    GLXFBConfig *(*GetFBConfigs)(Display *, int, int *);
    int (*GetFBConfigAttrib)(Display *, GLXFBConfig, int, int *);
    GLXFBConfig *(*ChooseFBConfig)(Display *, int, const int *, int *);
    const char *(*GetClientString)(Display *, int);
    Bool (*QueryExtension)(Display *, int *, int *);
    Bool (*QueryVersion)(Display *, int *, int *);
    void (*DestroyContext)(Display *, GLXContext);
    Bool (*MakeCurrent)(Display *, GLXDrawable, GLXContext);
    void (*SwapBuffers)(Display *, GLXDrawable);
    const char *(*QueryExtensionsString)(Display *, int);
    GLXContext (*CreateNewContext)(Display *, GLXFBConfig, int, GLXContext, Bool);
    XVisualInfo *(*GetVisualFromFBConfig)(Display *, GLXFBConfig);
    GLXWindow (*CreateWindow)(Display *, GLXFBConfig, Window, const int *);
    void (*DestroyWindow)(Display *, GLXWindow);
    gl_proc (*GetProcAddress)(const unsigned char *);
    gl_proc (*GetProcAddressARB)(const unsigned char *);
    int (*SwapIntervalSGI)(int);
    void (*SwapIntervalEXT)(Display *, GLXDrawable, int);
    int (*SwapIntervalMESA)(int);
    GLXContext (*CreateContextAttribsARB)(Display *, GLXFBConfig, GLXContext, Bool, const int *);

    int (*XFree)(void *);
    int (*XGetErrorText)(Display *, int, char *, int);
    int (*XDefaultScreen)(Display *);
    Bool (*XRenderQueryExtension)(Display *, int *, int *);
    XRenderPictFormat *(*XRenderFindVisualFormat)(Display *, const Visual *);
} glx = {0};

struct GLSurface {
    GLXContext context;
    GLXWindow window;
    GLSurface *next;
};

static const GLPlatformHost *host = NULL;
static GLSurface *all_surfaces = NULL;

#define LOAD(lib, dest, name)                                                      \
    do {                                                                           \
        *(void **)&(dest) = dlsym(lib, name);                                      \
        if (!(dest)) {                                                             \
            host->set_error("GLX: Failed to load required entry point: %s", name); \
            return false;                                                          \
        }                                                                          \
    } while (0)

static void *
open_first(const char *const *sonames) {
    for (size_t i = 0; sonames[i]; i++) {
        void *ans = dlopen(sonames[i], RTLD_LAZY | RTLD_LOCAL);
        if (ans) return ans;
    }
    return NULL;
}

static bool
load_libraries(void) {
    if (glx.handle) return true;
    static const char *const gl_sonames[] = {
#if defined(_GLFW_GLX_LIBRARY)
        _GLFW_GLX_LIBRARY,
#endif
        "libGL.so.1",
        "libGL.so",
        NULL};
    static const char *const x11_sonames[] = {"libX11.so.6", "libX11.so", NULL};
    static const char *const xrender_sonames[] = {"libXrender.so.1", "libXrender.so", NULL};
    glx.x11_handle = open_first(x11_sonames);
    if (!glx.x11_handle) {
        host->set_error("GLX: Failed to load libX11");
        return false;
    }
    LOAD(glx.x11_handle, glx.XFree, "XFree");
    LOAD(glx.x11_handle, glx.XGetErrorText, "XGetErrorText");
    LOAD(glx.x11_handle, glx.XDefaultScreen, "XDefaultScreen");
    glx.xrender_handle = open_first(xrender_sonames);
    if (glx.xrender_handle) {
        LOAD(glx.xrender_handle, glx.XRenderQueryExtension, "XRenderQueryExtension");
        LOAD(glx.xrender_handle, glx.XRenderFindVisualFormat, "XRenderFindVisualFormat");
    }
    glx.handle = open_first(gl_sonames);
    if (!glx.handle) {
        host->set_error("GLX: Failed to load GLX");
        return false;
    }
    LOAD(glx.handle, glx.GetFBConfigs, "glXGetFBConfigs");
    LOAD(glx.handle, glx.GetFBConfigAttrib, "glXGetFBConfigAttrib");
    LOAD(glx.handle, glx.ChooseFBConfig, "glXChooseFBConfig");
    LOAD(glx.handle, glx.GetClientString, "glXGetClientString");
    LOAD(glx.handle, glx.QueryExtension, "glXQueryExtension");
    LOAD(glx.handle, glx.QueryVersion, "glXQueryVersion");
    LOAD(glx.handle, glx.DestroyContext, "glXDestroyContext");
    LOAD(glx.handle, glx.MakeCurrent, "glXMakeCurrent");
    LOAD(glx.handle, glx.SwapBuffers, "glXSwapBuffers");
    LOAD(glx.handle, glx.QueryExtensionsString, "glXQueryExtensionsString");
    LOAD(glx.handle, glx.CreateNewContext, "glXCreateNewContext");
    LOAD(glx.handle, glx.CreateWindow, "glXCreateWindow");
    LOAD(glx.handle, glx.DestroyWindow, "glXDestroyWindow");
    LOAD(glx.handle, glx.GetProcAddress, "glXGetProcAddress");
    LOAD(glx.handle, glx.GetProcAddressARB, "glXGetProcAddressARB");
    LOAD(glx.handle, glx.GetVisualFromFBConfig, "glXGetVisualFromFBConfig");
    return true;
}
#undef LOAD

static bool
extension_supported(const char *name) {
    const char *extensions = glx.QueryExtensionsString(glx.display, glx.screen);
    return extensions && gl_extension_in_string(name, extensions);
}

static gl_proc
get_proc_address(const char *name) {
    if (glx.GetProcAddress) return glx.GetProcAddress((const unsigned char *)name);
    if (glx.GetProcAddressARB) return glx.GetProcAddressARB((const unsigned char *)name);
    gl_proc ans = NULL;
    *(void **)&ans = dlsym(glx.handle, name);
    return ans;
}

#define LOAD_EXT(dest, name)                 \
    do {                                     \
        gl_proc p_ = get_proc_address(name); \
        memcpy(&(dest), &p_, sizeof(p_));    \
    } while (0)

static bool
initialize(Display *display, int screen) {
    if (glx.initialized) {
        if (display != glx.display) {
            host->set_error("GLX: All windows must be on the same X11 display");
            return false;
        }
        return true;
    }
    if (!load_libraries()) return false;
    glx.display = display;
    glx.screen = screen < 0 ? glx.XDefaultScreen(display) : screen;
    int ev, err;
    glx.xrender_available = glx.xrender_handle && glx.XRenderQueryExtension(display, &ev, &err);
    if (!glx.QueryExtension(display, &glx.error_base, &glx.event_base)) {
        host->set_error("GLX: GLX extension not found");
        return false;
    }
    if (!glx.QueryVersion(display, &glx.major, &glx.minor)) {
        host->set_error("GLX: Failed to query GLX version");
        return false;
    }
    if (glx.major == 1 && glx.minor < 3) {
        host->set_error("GLX: GLX version 1.3 is required");
        return false;
    }
    if (extension_supported("GLX_EXT_swap_control")) {
        LOAD_EXT(glx.SwapIntervalEXT, "glXSwapIntervalEXT");
        glx.EXT_swap_control = glx.SwapIntervalEXT != NULL;
    }
    if (extension_supported("GLX_SGI_swap_control")) {
        LOAD_EXT(glx.SwapIntervalSGI, "glXSwapIntervalSGI");
        glx.SGI_swap_control = glx.SwapIntervalSGI != NULL;
    }
    if (extension_supported("GLX_MESA_swap_control")) {
        LOAD_EXT(glx.SwapIntervalMESA, "glXSwapIntervalMESA");
        glx.MESA_swap_control = glx.SwapIntervalMESA != NULL;
    }
    glx.ARB_framebuffer_sRGB = extension_supported("GLX_ARB_framebuffer_sRGB");
    glx.EXT_framebuffer_sRGB = extension_supported("GLX_EXT_framebuffer_sRGB");
    if (extension_supported("GLX_ARB_create_context")) {
        LOAD_EXT(glx.CreateContextAttribsARB, "glXCreateContextAttribsARB");
        glx.ARB_create_context = glx.CreateContextAttribsARB != NULL;
    }
    glx.initialized = true;
    return true;
}
#undef LOAD_EXT

static int
fb_config_attrib(GLXFBConfig config, int attrib) {
    int value = 0;
    glx.GetFBConfigAttrib(glx.display, config, attrib, &value);
    return value;
}

static bool
is_visual_transparent(Visual *visual) {
    if (!glx.xrender_available) return false;
    XRenderPictFormat *pf = glx.XRenderFindVisualFormat(glx.display, visual);
    return pf && pf->direct.alphaMask;
}

static GLXFBConfig *
query_fb_configs(bool trust_window_bit, int *count, bool use_best_color_depth) {
    int attribs[32];
    int pos = 0;
#define ATTR(x, y)          \
    {                       \
        attribs[pos++] = x; \
        attribs[pos++] = y; \
    }
    ATTR(GLX_DOUBLEBUFFER, True);
    // kitty uses neither depth nor stencil buffers
    ATTR(GLX_DEPTH_SIZE, 0);
    ATTR(GLX_STENCIL_SIZE, 0);
    if (use_best_color_depth) {
        // Ask for the highest available R+G+B+A color depth. This hopefully
        // works with 10bit (r=10, g=10, b=10, a=2) visuals
        ATTR(GLX_RED_SIZE, 1);
        ATTR(GLX_GREEN_SIZE, 1);
        ATTR(GLX_BLUE_SIZE, 1);
        ATTR(GLX_ALPHA_SIZE, 1);
    } else {
        ATTR(GLX_RED_SIZE, 8);
        ATTR(GLX_GREEN_SIZE, 8);
        ATTR(GLX_BLUE_SIZE, 8);
        ATTR(GLX_ALPHA_SIZE, 8);
    }
    if (!trust_window_bit) ATTR(GLX_DRAWABLE_TYPE, 0);
    ATTR(None, None);
#undef ATTR
    return glx.ChooseFBConfig(glx.display, glx.screen, attribs, count);
}

// Return the GLXFBConfig most closely matching the specified config
static bool
choose_fb_config(const GPUSurfaceConfig *desired, GLXFBConfig *result) {
    if (glx.chosen.valid && glx.chosen.transparent == desired->transparent && glx.chosen.srgb == desired->srgb) {
        *result = glx.chosen.config;
        return true;
    }
    // HACK: This is a workaround for Chromium (VirtualBox GL) not setting the
    // window bit on any GLXFBConfigs
    const char *vendor = glx.GetClientString(glx.display, GLX_VENDOR);
    const bool trust_window_bit = !(vendor && strcmp(vendor, "Chromium") == 0);
    int count = 0;
    GLXFBConfig *configs = query_fb_configs(trust_window_bit, &count, false);
    if (!configs || !count) {
        configs = query_fb_configs(trust_window_bit, &count, true);
        if (!configs || !count) {
            host->set_error("GLX: No GLXFBConfigs returned");
            return false;
        }
    }
    int ans_idx = 0;
    for (int i = 0; i < count; i++) {
        const GLXFBConfig n = configs[i];
        bool transparency_matches = true, srgb_matches = true;
        if (desired->transparent) {
            transparency_matches = false;
            XVisualInfo *vi = glx.GetVisualFromFBConfig(glx.display, n);
            if (vi) {
                if (is_visual_transparent(vi->visual)) transparency_matches = true;
                glx.XFree(vi);
            }
        }
        if (desired->srgb && (glx.ARB_framebuffer_sRGB || glx.EXT_framebuffer_sRGB)) {
            srgb_matches = fb_config_attrib(n, GLX_FRAMEBUFFER_SRGB_CAPABLE_ARB) ? true : false;
        }
        if (transparency_matches && srgb_matches) {
            ans_idx = i;
            break;
        }
    }
    *result = configs[ans_idx];
    glx.chosen.valid = true;
    glx.chosen.transparent = desired->transparent;
    glx.chosen.srgb = desired->srgb;
    glx.chosen.config = configs[ans_idx];
    glx.XFree(configs);
    return true;
}

static bool
choose_native_visual(const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint64_t *visual_id) {
    *visual_id = 0;
    if (native->platform != GPU_PLATFORM_X11 || !native->display) {
        host->set_error("GLX: Only X11 displays are supported");
        return false;
    }
    if (!initialize(native->display, native->screen)) return false;
    GLXFBConfig fbconfig;
    if (!choose_fb_config(config, &fbconfig)) return false;
    XVisualInfo *vi = glx.GetVisualFromFBConfig(glx.display, fbconfig);
    if (!vi) {
        host->set_error("GLX: Failed to retrieve Visual for GLXFBConfig");
        return false;
    }
    *visual_id = vi->visualid;
    glx.XFree(vi);
    return true;
}

static bool
make_current(GLSurface *s) {
    if (!glx.initialized) return true;
    if (s) {
        if (!glx.MakeCurrent(glx.display, s->window, s->context)) {
            host->set_error("GLX: Failed to make context current");
            return false;
        }
    } else {
        if (!glx.MakeCurrent(glx.display, None, NULL)) {
            host->set_error("GLX: Failed to clear current context");
            return false;
        }
    }
    return true;
}

static void
surface_destroy(GLSurface *s) {
    if (!s) return;
    if (s->window) glx.DestroyWindow(glx.display, s->window);
    if (s->context) glx.DestroyContext(glx.display, s->context);
    for (GLSurface **p = &all_surfaces; *p; p = &(*p)->next) {
        if (*p == s) {
            *p = s->next;
            break;
        }
    }
    free(s);
}

static GLSurface *
surface_create(const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint32_t width, uint32_t height) {
    (void)width;
    (void)height;
    if (native->platform != GPU_PLATFORM_X11 || !native->display || !native->x11_window) {
        host->set_error("GLX: Only X11 windows are supported");
        return NULL;
    }
    if (!initialize(native->display, native->screen)) return NULL;
    GLXFBConfig fbconfig;
    if (!choose_fb_config(config, &fbconfig)) return NULL;
    GLSurface *s = calloc(1, sizeof(GLSurface));
    if (!s) {
        host->set_error("GLX: Out of memory");
        return NULL;
    }
    s->next = all_surfaces;
    all_surfaces = s;
    // Share objects with any existing context
    GLXContext share = s->next ? s->next->context : NULL;
    // X errors are captured by the windowing system's error handler
    host->x11_push_error_trap();
    if (glx.ARB_create_context) {
        const int attribs[] = {
            GLX_CONTEXT_MAJOR_VERSION_ARB,
            OPENGL_REQUIRED_VERSION_MAJOR,
            GLX_CONTEXT_MINOR_VERSION_ARB,
            OPENGL_REQUIRED_VERSION_MINOR,
            GLX_CONTEXT_FLAGS_ARB,
            GLX_CONTEXT_FORWARD_COMPATIBLE_BIT_ARB,
            None,
            None,
        };
        s->context = glx.CreateContextAttribsARB(glx.display, fbconfig, share, True, attribs);
    } else {
        s->context = glx.CreateNewContext(glx.display, fbconfig, GLX_RGBA_TYPE, share, True);
    }
    // Waits for the server to process the requests, if needed
    const int x11_error_code = host->x11_pop_error_trap();
    if (!s->context) {
        char buf[512];
        glx.XGetErrorText(glx.display, x11_error_code, buf, sizeof(buf));
        host->set_error(
            "GLX: Failed to create context: %s. kitty requires working OpenGL %d.%d drivers.",
            buf,
            OPENGL_REQUIRED_VERSION_MAJOR,
            OPENGL_REQUIRED_VERSION_MINOR);
        surface_destroy(s);
        return NULL;
    }
    s->window = glx.CreateWindow(glx.display, fbconfig, (Window)native->x11_window, NULL);
    if (!s->window) {
        host->set_error("GLX: Failed to create window");
        surface_destroy(s);
        return NULL;
    }
    return s;
}

static void
surface_resize(GLSurface *s, uint32_t width, uint32_t height) {
    // GLX drawables are resized along with their X11 window
    (void)s;
    (void)width;
    (void)height;
}

static bool
present(GLSurface *s) {
    glx.SwapBuffers(glx.display, s->window);
    return true;
}

static void
set_swap_interval(GLSurface *s, int interval) {
    if (glx.EXT_swap_control) glx.SwapIntervalEXT(glx.display, s->window, interval);
    else if (glx.MESA_swap_control) glx.SwapIntervalMESA(interval);
    else if (glx.SGI_swap_control) {
        if (interval > 0) glx.SwapIntervalSGI(interval);
    }
}

static void
native_changed(GLSurface *s) {
    (void)s;
}

static bool
recreate(GLSurface *s) {
    (void)s;
    host->set_error("GLX: Recreating surfaces is not supported");
    return false;
}

static void
terminate(void) {
    while (all_surfaces) surface_destroy(all_surfaces);
    // libGL is never unloaded as doing so while the X11 display is still open
    // makes XCloseDisplay crash
    glx.initialized = false;
    glx.chosen.valid = false;
    glx.display = NULL;
}

const GLPlatform *
glx_platform(const GLPlatformHost *h) {
    static const GLPlatform ans = {
        .name = "GLX",
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
