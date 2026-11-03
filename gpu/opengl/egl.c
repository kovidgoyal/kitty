/*
 * egl.c
 * Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
 * Based on egl_context.c from GLFW, Copyright (c) 2002-2006 Marcus Geelnard
 * and (c) 2006-2019 Camilla Löwy
 *
 * Distributed under terms of the GPL3 license.
 */

// OpenGL contexts for Wayland windows, created using EGL. All libraries are
// loaded at runtime, so that the driver has no link time dependencies.

#include "platform.h"
#include "version.h"
#include <dlfcn.h>
#include <stdlib.h>
#include <string.h>

#define EGL_SUCCESS 0x3000
#define EGL_NOT_INITIALIZED 0x3001
#define EGL_BAD_ACCESS 0x3002
#define EGL_BAD_ALLOC 0x3003
#define EGL_BAD_ATTRIBUTE 0x3004
#define EGL_BAD_CONFIG 0x3005
#define EGL_BAD_CONTEXT 0x3006
#define EGL_BAD_CURRENT_SURFACE 0x3007
#define EGL_BAD_DISPLAY 0x3008
#define EGL_BAD_MATCH 0x3009
#define EGL_BAD_NATIVE_PIXMAP 0x300a
#define EGL_BAD_NATIVE_WINDOW 0x300b
#define EGL_BAD_PARAMETER 0x300c
#define EGL_BAD_SURFACE 0x300d
#define EGL_CONTEXT_LOST 0x300e
#define EGL_COLOR_BUFFER_TYPE 0x303f
#define EGL_RGB_BUFFER 0x308e
#define EGL_SURFACE_TYPE 0x3033
#define EGL_WINDOW_BIT 0x0004
#define EGL_RENDERABLE_TYPE 0x3040
#define EGL_OPENGL_BIT 0x0008
#define EGL_ALPHA_SIZE 0x3021
#define EGL_BLUE_SIZE 0x3022
#define EGL_GREEN_SIZE 0x3023
#define EGL_RED_SIZE 0x3024
#define EGL_OPENGL_API 0x30a2
#define EGL_NONE 0x3038
#define EGL_EXTENSIONS 0x3055
#define EGL_MIN_SWAP_INTERVAL 0x303B
#define EGL_NO_SURFACE ((EGLSurface)0)
#define EGL_NO_DISPLAY ((EGLDisplay)0)
#define EGL_NO_CONTEXT ((EGLContext)0)
#define EGL_CONTEXT_OPENGL_FORWARD_COMPATIBLE_BIT_KHR 0x00000002
#define EGL_CONTEXT_MAJOR_VERSION_KHR 0x3098
#define EGL_CONTEXT_MINOR_VERSION_KHR 0x30fb
#define EGL_CONTEXT_FLAGS_KHR 0x30fc
#define EGL_GL_COLORSPACE_KHR 0x309d
#define EGL_GL_COLORSPACE_SRGB_KHR 0x3089
#define EGL_PLATFORM_WAYLAND_EXT 0x31d8

typedef int EGLint;
typedef unsigned int EGLBoolean;
typedef unsigned int EGLenum;
typedef void *EGLConfig;
typedef void *EGLContext;
typedef void *EGLDisplay;
typedef void *EGLSurface;
typedef void *EGLNativeDisplayType;
typedef void *EGLNativeWindowType;

struct wl_surface;
struct wl_egl_window;

static struct {
    void *handle, *wl_egl_handle, *client;
    EGLenum platform;
    EGLDisplay display;
    EGLint major, minor;
    bool initialized, KHR_create_context, KHR_gl_colorspace, KHR_get_all_proc_addresses, EXT_platform_base, EXT_platform_wayland;

    EGLBoolean (*GetConfigAttrib)(EGLDisplay, EGLConfig, EGLint, EGLint *);
    EGLBoolean (*ChooseConfig)(EGLDisplay, EGLint const *, EGLConfig *, EGLint, EGLint *);
    EGLDisplay (*GetDisplay)(EGLNativeDisplayType);
    EGLint (*GetError)(void);
    EGLBoolean (*Initialize)(EGLDisplay, EGLint *, EGLint *);
    EGLBoolean (*Terminate)(EGLDisplay);
    EGLBoolean (*BindAPI)(EGLenum);
    EGLContext (*CreateContext)(EGLDisplay, EGLConfig, EGLContext, const EGLint *);
    EGLBoolean (*DestroySurface)(EGLDisplay, EGLSurface);
    EGLBoolean (*DestroyContext)(EGLDisplay, EGLContext);
    EGLSurface (*CreateWindowSurface)(EGLDisplay, EGLConfig, EGLNativeWindowType, const EGLint *);
    EGLBoolean (*MakeCurrent)(EGLDisplay, EGLSurface, EGLSurface, EGLContext);
    EGLBoolean (*SwapBuffers)(EGLDisplay, EGLSurface);
    EGLBoolean (*SwapInterval)(EGLDisplay, EGLint);
    const char *(*QueryString)(EGLDisplay, EGLint);
    gl_proc (*GetProcAddress)(const char *);
    EGLDisplay (*GetPlatformDisplayEXT)(EGLenum, void *, const EGLint *);
    EGLSurface (*CreatePlatformWindowSurfaceEXT)(EGLDisplay, EGLConfig, void *, const EGLint *);

    struct wl_egl_window *(*wl_egl_window_create)(struct wl_surface *, int, int);
    void (*wl_egl_window_destroy)(struct wl_egl_window *);
    void (*wl_egl_window_resize)(struct wl_egl_window *, int, int, int, int);
} egl = {0};

struct GLSurface {
    EGLConfig config;
    EGLContext context;
    EGLSurface surface;
    struct wl_egl_window *native;
    GLSurface *next;
};

static const GLPlatformHost *host = NULL;
static GLSurface *all_surfaces = NULL;

static const char *
egl_error_string(EGLint error) {
    switch (error) {
        case EGL_SUCCESS: return "Success";
        case EGL_NOT_INITIALIZED: return "EGL is not or could not be initialized";
        case EGL_BAD_ACCESS: return "EGL cannot access a requested resource";
        case EGL_BAD_ALLOC: return "EGL failed to allocate resources for the requested operation";
        case EGL_BAD_ATTRIBUTE: return "An unrecognized attribute or attribute value was passed in the attribute list";
        case EGL_BAD_CONTEXT: return "An EGLContext argument does not name a valid EGL rendering context";
        case EGL_BAD_CONFIG: return "An EGLConfig argument does not name a valid EGL frame buffer configuration";
        case EGL_BAD_CURRENT_SURFACE: return "The current surface of the calling thread is a window, pixel buffer or pixmap that is no longer valid";
        case EGL_BAD_DISPLAY: return "An EGLDisplay argument does not name a valid EGL display connection";
        case EGL_BAD_SURFACE: return "An EGLSurface argument does not name a valid surface configured for GL rendering";
        case EGL_BAD_MATCH: return "Arguments are inconsistent";
        case EGL_BAD_PARAMETER: return "One or more argument values are invalid";
        case EGL_BAD_NATIVE_PIXMAP: return "A NativePixmapType argument does not refer to a valid native pixmap";
        case EGL_BAD_NATIVE_WINDOW: return "A NativeWindowType argument does not refer to a valid native window";
        case EGL_CONTEXT_LOST: return "The application must destroy all contexts and reinitialise";
        default: return "ERROR: UNKNOWN EGL ERROR";
    }
}

#define LOAD(lib, dest, name)                                                      \
    do {                                                                           \
        *(void **)&(dest) = dlsym(lib, name);                                      \
        if (!(dest)) {                                                             \
            host->set_error("EGL: Failed to load required entry point: %s", name); \
            return false;                                                          \
        }                                                                          \
    } while (0)

static bool
load_libraries(void) {
    if (egl.handle) return true;
#ifdef _GLFW_EGL_LIBRARY
    const char *soname = _GLFW_EGL_LIBRARY;
#else
    const char *soname = "libEGL.so.1";
#endif
    egl.handle = dlopen(soname, RTLD_LAZY | RTLD_LOCAL);
    if (!egl.handle) {
        host->set_error("EGL: Library not found: %s", soname);
        return false;
    }
    egl.wl_egl_handle = dlopen("libwayland-egl.so.1", RTLD_LAZY | RTLD_LOCAL);
    if (!egl.wl_egl_handle) {
        host->set_error("Wayland: Failed to open libwayland-egl");
        return false;
    }
    LOAD(egl.wl_egl_handle, egl.wl_egl_window_create, "wl_egl_window_create");
    LOAD(egl.wl_egl_handle, egl.wl_egl_window_destroy, "wl_egl_window_destroy");
    LOAD(egl.wl_egl_handle, egl.wl_egl_window_resize, "wl_egl_window_resize");
    LOAD(egl.handle, egl.GetConfigAttrib, "eglGetConfigAttrib");
    LOAD(egl.handle, egl.ChooseConfig, "eglChooseConfig");
    LOAD(egl.handle, egl.GetDisplay, "eglGetDisplay");
    LOAD(egl.handle, egl.GetError, "eglGetError");
    LOAD(egl.handle, egl.Initialize, "eglInitialize");
    LOAD(egl.handle, egl.Terminate, "eglTerminate");
    LOAD(egl.handle, egl.BindAPI, "eglBindAPI");
    LOAD(egl.handle, egl.CreateContext, "eglCreateContext");
    LOAD(egl.handle, egl.DestroySurface, "eglDestroySurface");
    LOAD(egl.handle, egl.DestroyContext, "eglDestroyContext");
    LOAD(egl.handle, egl.CreateWindowSurface, "eglCreateWindowSurface");
    LOAD(egl.handle, egl.MakeCurrent, "eglMakeCurrent");
    LOAD(egl.handle, egl.SwapBuffers, "eglSwapBuffers");
    LOAD(egl.handle, egl.SwapInterval, "eglSwapInterval");
    LOAD(egl.handle, egl.QueryString, "eglQueryString");
    LOAD(egl.handle, egl.GetProcAddress, "eglGetProcAddress");
    return true;
}
#undef LOAD

static bool
extension_supported(const char *name) {
    const char *extensions = egl.QueryString(egl.display, EGL_EXTENSIONS);
    return extensions && gl_extension_in_string(name, extensions);
}

static bool
initialize(void *wl_display) {
    if (egl.initialized) return true;
    if (!load_libraries()) return false;
    const char *extensions = egl.QueryString(EGL_NO_DISPLAY, EGL_EXTENSIONS);
    if (extensions && egl.GetError() == EGL_SUCCESS) {
        egl.EXT_platform_base = gl_extension_in_string("EGL_EXT_platform_base", extensions);
        egl.EXT_platform_wayland = gl_extension_in_string("EGL_EXT_platform_wayland", extensions);
    }
    if (egl.EXT_platform_base) {
        // Converting between function pointer types is allowed, unlike
        // between function and object pointers
        gl_proc p = egl.GetProcAddress("eglGetPlatformDisplayEXT");
        memcpy(&egl.GetPlatformDisplayEXT, &p, sizeof(p));
        p = egl.GetProcAddress("eglCreatePlatformWindowSurfaceEXT");
        memcpy(&egl.CreatePlatformWindowSurfaceEXT, &p, sizeof(p));
    }
    egl.platform =
        egl.EXT_platform_base && egl.EXT_platform_wayland && egl.GetPlatformDisplayEXT && egl.CreatePlatformWindowSurfaceEXT ? EGL_PLATFORM_WAYLAND_EXT : 0;
    egl.display = EGL_NO_DISPLAY;
    if (egl.platform) egl.display = egl.GetPlatformDisplayEXT(egl.platform, wl_display, NULL);
    if (egl.display == EGL_NO_DISPLAY) egl.display = egl.GetDisplay(wl_display);
    EGLint egl_err;
    if (egl.display == EGL_NO_DISPLAY && (egl_err = egl.GetError()) != EGL_SUCCESS) {
        host->set_error("EGL: Failed to get EGL display: %s", egl_error_string(egl_err));
        return false;
    }
    if (!egl.Initialize(egl.display, &egl.major, &egl.minor)) {
        host->set_error(
            "EGL: Failed to initialize EGL: %s display_present: %d egl_platform_present: %d",
            egl_error_string(egl.GetError()),
            egl.display != EGL_NO_DISPLAY,
            egl.platform != 0);
        egl.display = EGL_NO_DISPLAY;
        return false;
    }
    egl.KHR_create_context = extension_supported("EGL_KHR_create_context");
    egl.KHR_gl_colorspace = extension_supported("EGL_KHR_gl_colorspace");
    egl.KHR_get_all_proc_addresses = extension_supported("EGL_KHR_get_all_proc_addresses");
    if (!egl.KHR_get_all_proc_addresses) {
        // eglGetProcAddress() may not return core functions, so they must be
        // looked up in the client library instead
        egl.client = dlopen("libGL.so.1", RTLD_LAZY | RTLD_LOCAL);
        if (!egl.client) {
            host->set_error("EGL: Failed to load client library");
            return false;
        }
    }
    egl.initialized = true;
    return true;
}

static bool
choose_config(const GPUSurfaceConfig *config, EGLConfig *result) {
    (void)config; // Wayland composites using the alpha channel of every buffer, so no special config is needed for transparency
    EGLConfig configs[512];
    EGLint native_count = 0;
    const EGLint attributes[] = {
        EGL_COLOR_BUFFER_TYPE,
        EGL_RGB_BUFFER,
        EGL_SURFACE_TYPE,
        EGL_WINDOW_BIT,
        EGL_RENDERABLE_TYPE,
        EGL_OPENGL_BIT,
        EGL_RED_SIZE,
        8,
        EGL_GREEN_SIZE,
        8,
        EGL_BLUE_SIZE,
        8,
        EGL_ALPHA_SIZE,
        8,
        EGL_NONE,
        EGL_NONE,
    };
    if (!egl.ChooseConfig(egl.display, attributes, configs, sizeof(configs) / sizeof(configs[0]), &native_count)) {
        host->set_error("EGL: eglChooseConfig failed");
        return false;
    }
    if (!native_count) {
        host->set_error("EGL: No EGLConfigs returned");
        return false;
    }
    *result = configs[0];
    return true;
}

static bool
choose_native_visual(const GPUNativeWindow *native, const GPUSurfaceConfig *config, uint64_t *visual_id) {
    (void)native;
    (void)config;
    *visual_id = 0;
    return true;
}

static bool
make_current(GLSurface *s) {
    if (!egl.initialized) return true;
    if (s) {
        if (!egl.MakeCurrent(egl.display, s->surface, s->surface, s->context)) {
            host->set_error("EGL: Failed to make context current: %s", egl_error_string(egl.GetError()));
            return false;
        }
    } else {
        if (!egl.MakeCurrent(egl.display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT)) {
            host->set_error("EGL: Failed to clear current context: %s", egl_error_string(egl.GetError()));
            return false;
        }
    }
    return true;
}

static void
surface_destroy(GLSurface *s) {
    if (!s) return;
    if (s->surface) egl.DestroySurface(egl.display, s->surface);
    if (s->context) egl.DestroyContext(egl.display, s->context);
    if (s->native) egl.wl_egl_window_destroy(s->native);
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
    if (native->platform != GPU_PLATFORM_WAYLAND || !native->handle) {
        host->set_error("EGL: Only Wayland windows are supported");
        return NULL;
    }
    if (!initialize(native->display)) return NULL;
    GLSurface *s = calloc(1, sizeof(GLSurface));
    if (!s) {
        host->set_error("EGL: Out of memory");
        return NULL;
    }
    s->next = all_surfaces;
    all_surfaces = s;
    if (!choose_config(config, &s->config)) {
        surface_destroy(s);
        return NULL;
    }
    if (!egl.BindAPI(EGL_OPENGL_API)) {
        host->set_error("EGL: Failed to bind OpenGL: %s", egl_error_string(egl.GetError()));
        surface_destroy(s);
        return NULL;
    }
    EGLint attribs[16];
    int index = 0;
#define set_attrib(a, v)      \
    {                         \
        attribs[index++] = a; \
        attribs[index++] = v; \
    }
    if (egl.KHR_create_context) {
        set_attrib(EGL_CONTEXT_MAJOR_VERSION_KHR, OPENGL_REQUIRED_VERSION_MAJOR);
        set_attrib(EGL_CONTEXT_MINOR_VERSION_KHR, OPENGL_REQUIRED_VERSION_MINOR);
        set_attrib(EGL_CONTEXT_FLAGS_KHR, EGL_CONTEXT_OPENGL_FORWARD_COMPATIBLE_BIT_KHR);
    }
    set_attrib(EGL_NONE, EGL_NONE);
    // Share objects with any existing context
    EGLContext share = s->next ? s->next->context : EGL_NO_CONTEXT;
    s->context = egl.CreateContext(egl.display, s->config, share, attribs);
    if (s->context == EGL_NO_CONTEXT) {
        host->set_error(
            "EGL: Failed to create context: %s. kitty requires working OpenGL %d.%d drivers.",
            egl_error_string(egl.GetError()),
            OPENGL_REQUIRED_VERSION_MAJOR,
            OPENGL_REQUIRED_VERSION_MINOR);
        surface_destroy(s);
        return NULL;
    }
    index = 0;
    if (config->srgb && egl.KHR_gl_colorspace) set_attrib(EGL_GL_COLORSPACE_KHR, EGL_GL_COLORSPACE_SRGB_KHR);
    // EGL_PRESENT_OPAQUE_EXT is not used because it prevents transparency from
    // working on NVIDIA drivers under Wayland https://github.com/kovidgoyal/kitty/issues/5479
    set_attrib(EGL_NONE, EGL_NONE);
#undef set_attrib
    s->native = egl.wl_egl_window_create((struct wl_surface *)native->handle, (int)width, (int)height);
    if (!s->native) {
        host->set_error("Wayland: Failed to create EGL window");
        surface_destroy(s);
        return NULL;
    }
    if (egl.platform) s->surface = egl.CreatePlatformWindowSurfaceEXT(egl.display, s->config, s->native, attribs);
    else s->surface = egl.CreateWindowSurface(egl.display, s->config, (EGLNativeWindowType)s->native, attribs);
    if (s->surface == EGL_NO_SURFACE) {
        host->set_error("EGL: Failed to create window surface: %s", egl_error_string(egl.GetError()));
        surface_destroy(s);
        return NULL;
    }
    EGLint min_interval = 0;
    if (!egl.GetConfigAttrib(egl.display, s->config, EGL_MIN_SWAP_INTERVAL, &min_interval)) {
        host->log_error("EGL: could not check for non-blocking buffer swap with error: %s", egl_error_string(egl.GetError()));
    } else if (min_interval > 0) {
        host->log_error("EGL: non-blocking swap buffers not available, minimum swap interval is: %d", min_interval);
    }
    return s;
}

static void
surface_resize(GLSurface *s, uint32_t width, uint32_t height) {
    // Does not actually resize the buffer until the next draw call or buffer state query
    egl.wl_egl_window_resize(s->native, (int)width, (int)height, 0, 0);
}

static bool
present(GLSurface *s) {
    if (!egl.SwapBuffers(egl.display, s->surface)) {
        host->set_error("EGL: Failed to swap buffers: %s", egl_error_string(egl.GetError()));
        return false;
    }
    return true;
}

static void
set_swap_interval(GLSurface *s, int interval) {
    (void)s;
    egl.SwapInterval(egl.display, interval);
}

static void
native_changed(GLSurface *s) {
    (void)s;
}

static bool
recreate(GLSurface *s) {
    (void)s;
    host->set_error("EGL: Recreating surfaces is not supported");
    return false;
}

static gl_proc
get_proc_address(const char *name) {
    if (egl.client) {
        gl_proc ans = NULL;
        *(void **)&ans = dlsym(egl.client, name);
        if (ans) return ans;
    }
    return egl.GetProcAddress(name);
}

static void
terminate(void) {
    while (all_surfaces) surface_destroy(all_surfaces);
    // Must be called before disconnecting from the Wayland display since
    // eglTerminate sends Wayland protocol requests. The libraries are never
    // unloaded as the Wayland message format tables they contain must remain
    // mapped while the Wayland event queue is drained during disconnection.
    if (egl.display) {
        egl.Terminate(egl.display);
        egl.display = EGL_NO_DISPLAY;
    }
    egl.initialized = false;
}

const GLPlatform *
egl_platform(const GLPlatformHost *h) {
    static const GLPlatform ans = {
        .name = "EGL",
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
