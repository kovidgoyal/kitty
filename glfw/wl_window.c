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

#define _GNU_SOURCE

#include "internal.h"
#include "backend_utils.h"
#include "memfd.h"
#include "linux_notify.h"

#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include <string.h>
#include <fcntl.h>
#include <sys/mman.h>


#define URI_LIST_MIME "text/uri-list"


static GLFWbool checkScaleChange(_GLFWwindow* window)
{
    int scale = 1;
    int i;
    int monitorScale;

    // Check if we will be able to set the buffer scale or not.
    if (_glfw.wl.compositorVersion < 3)
        return GLFW_FALSE;

    // Get the scale factor from the highest scale monitor.
    for (i = 0; i < window->wl.monitorsCount; ++i)
    {
        monitorScale = window->wl.monitors[i]->wl.scale;
        if (scale < monitorScale)
            scale = monitorScale;
    }

    // Only change the framebuffer size if the scale changed.
    if (scale != window->wl.scale)
    {
        window->wl.scale = scale;
        wl_surface_set_buffer_scale(window->wl.surface, scale);
        return GLFW_TRUE;
    }
    return GLFW_FALSE;
}

// Makes the surface considered as XRGB instead of ARGB.
static void setOpaqueRegion(_GLFWwindow* window)
{
    struct wl_region* region;

    region = wl_compositor_create_region(_glfw.wl.compositor);
    if (!region)
        return;

    wl_region_add(region, 0, 0, window->wl.width, window->wl.height);
    wl_surface_set_opaque_region(window->wl.surface, region);
    wl_surface_commit(window->wl.surface);
    wl_region_destroy(region);
}


static void resizeFramebuffer(_GLFWwindow* window)
{
    int scale = window->wl.scale;
    int scaledWidth = window->wl.width * scale;
    int scaledHeight = window->wl.height * scale;
    wl_egl_window_resize(window->wl.native, scaledWidth, scaledHeight, 0, 0);
    if (!window->wl.transparent)
        setOpaqueRegion(window);
    _glfwInputFramebufferSize(window, scaledWidth, scaledHeight);

    if (!window->wl.decorations.top.surface)
        return;

    // Top decoration.
    wp_viewport_set_destination(window->wl.decorations.top.viewport,
                                window->wl.width, _GLFW_DECORATION_TOP);
    wl_surface_commit(window->wl.decorations.top.surface);

    // Left decoration.
    wp_viewport_set_destination(window->wl.decorations.left.viewport,
                                _GLFW_DECORATION_WIDTH, window->wl.height + _GLFW_DECORATION_TOP);
    wl_surface_commit(window->wl.decorations.left.surface);

    // Right decoration.
    wl_subsurface_set_position(window->wl.decorations.right.subsurface,
                               window->wl.width, -_GLFW_DECORATION_TOP);
    wp_viewport_set_destination(window->wl.decorations.right.viewport,
                                _GLFW_DECORATION_WIDTH, window->wl.height + _GLFW_DECORATION_TOP);
    wl_surface_commit(window->wl.decorations.right.surface);

    // Bottom decoration.
    wl_subsurface_set_position(window->wl.decorations.bottom.subsurface,
                               -_GLFW_DECORATION_WIDTH, window->wl.height);
    wp_viewport_set_destination(window->wl.decorations.bottom.viewport,
                                window->wl.width + _GLFW_DECORATION_HORIZONTAL, _GLFW_DECORATION_WIDTH);
    wl_surface_commit(window->wl.decorations.bottom.surface);
}


static const char*
clipboard_mime() {
    static char buf[128] = {0};
    if (buf[0] == 0) {
        snprintf(buf, sizeof(buf), "application/glfw+clipboard-%d", getpid());
    }
    return buf;
}

static void handlePing(void* data,
                       struct wl_shell_surface* shellSurface,
                       uint32_t serial)
{
    wl_shell_surface_pong(shellSurface, serial);
}


static void dispatchChangesAfterConfigure(_GLFWwindow *window, int32_t width, int32_t height) {
    if (width <= 0) width = window->wl.width;
    if (height <= 0) height = window->wl.height;
    GLFWbool size_changed = width != window->wl.width || height != window->wl.height;
    GLFWbool scale_changed = checkScaleChange(window);

    if (size_changed) {
        _glfwInputWindowSize(window, width, height);
        _glfwPlatformSetWindowSize(window, width, height);
    }

    if (scale_changed) {
        if (!size_changed)
            resizeFramebuffer(window);
        _glfwInputWindowContentScale(window, window->wl.scale, window->wl.scale);
    }

    _glfwInputWindowDamage(window);
}


static void handleConfigure(void* data,
                            struct wl_shell_surface* shellSurface,
                            uint32_t edges,
                            int32_t width,
                            int32_t height)
{
    _GLFWwindow* window = data;
    float aspectRatio;
    float targetRatio;

    if (!window->monitor)
    {
        if (_glfw.wl.viewporter && window->decorated)
        {
            width -= _GLFW_DECORATION_HORIZONTAL;
            height -= _GLFW_DECORATION_VERTICAL;
        }
        if (width < 1)
            width = 1;
        if (height < 1)
            height = 1;

        if (window->numer != GLFW_DONT_CARE && window->denom != GLFW_DONT_CARE)
        {
            aspectRatio = (float)width / (float)height;
            targetRatio = (float)window->numer / (float)window->denom;
            if (aspectRatio < targetRatio)
                height = width / targetRatio;
            else if (aspectRatio > targetRatio)
                width = height * targetRatio;
        }

        if (window->minwidth != GLFW_DONT_CARE && width < window->minwidth)
            width = window->minwidth;
        else if (window->maxwidth != GLFW_DONT_CARE && width > window->maxwidth)
            width = window->maxwidth;

        if (window->minheight != GLFW_DONT_CARE && height < window->minheight)
            height = window->minheight;
        else if (window->maxheight != GLFW_DONT_CARE && height > window->maxheight)
            height = window->maxheight;
    }

    dispatchChangesAfterConfigure(window, width, height);
}

static void handlePopupDone(void* data,
                            struct wl_shell_surface* shellSurface)
{
}

static const struct wl_shell_surface_listener shellSurfaceListener = {
    handlePing,
    handleConfigure,
    handlePopupDone
};

/*
 * Create a new, unique, anonymous file of the given size, and
 * return the file descriptor for it. The file descriptor is set
 * CLOEXEC. The file is immediately suitable for mmap()'ing
 * the given size at offset zero.
 *
 * The file should not have a permanent backing store like a disk,
 * but may have if XDG_RUNTIME_DIR is not properly implemented in OS.
 *
 * The file name is deleted from the file system.
 *
 * The file is suitable for buffer sharing between processes by
 * transmitting the file descriptor over Unix sockets using the
 * SCM_RIGHTS methods.
 *
 * posix_fallocate() is used to guarantee that disk space is available
 * for the file at the given size. If disk space is insufficent, errno
 * is set to ENOSPC. If posix_fallocate() is not supported, program may
 * receive SIGBUS on accessing mmap()'ed file contents instead.
 */
static int
createAnonymousFile(off_t size)
{
    int ret, fd = -1, shm_anon = 0;
#ifdef HAS_MEMFD_CREATE
    fd = memfd_create("glfw-shared", MFD_CLOEXEC | MFD_ALLOW_SEALING);
    if (fd < 0) return -1;
    // We can add this seal before calling posix_fallocate(), as the file
    // is currently zero-sized anyway.
    //
    // There is also no need to check for the return value, we couldn’t do
    // anything with it anyway.
    fcntl(fd, F_ADD_SEALS, F_SEAL_SHRINK | F_SEAL_SEAL);
#elif defined(SHM_ANON)
    fd = shm_open(SHM_ANON, O_RDWR | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    shm_anon = 1;
#else
    static const char template[] = "/glfw-shared-XXXXXX";
    const char* path;
    char* name;

    path = getenv("XDG_RUNTIME_DIR");
    if (!path)
    {
        errno = ENOENT;
        return -1;
    }

    name = calloc(strlen(path) + sizeof(template), 1);
    strcpy(name, path);
    strcat(name, template);

    fd = createTmpfileCloexec(name);

    free(name);

    if (fd < 0)
        return -1;
#endif
    // posix_fallocate does not work on SHM descriptors
    ret = shm_anon ? ftruncate(fd, size) : posix_fallocate(fd, 0, size);
    if (ret != 0)
    {
        close(fd);
        errno = ret;
        return -1;
    }
    return fd;
}

static struct wl_buffer* createShmBuffer(const GLFWimage* image)
{
    struct wl_shm_pool* pool;
    struct wl_buffer* buffer;
    int stride = image->width * 4;
    int length = image->width * image->height * 4;
    void* data;
    int fd, i;

    fd = createAnonymousFile(length);
    if (fd < 0)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Creating a buffer file for %d B failed: %m",
                        length);
        return NULL;
    }

    data = mmap(NULL, length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (data == MAP_FAILED)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: mmap failed: %m");
        close(fd);
        return NULL;
    }

    pool = wl_shm_create_pool(_glfw.wl.shm, fd, length);

    close(fd);
    unsigned char* source = (unsigned char*) image->pixels;
    unsigned char* target = data;
    for (i = 0;  i < image->width * image->height;  i++, source += 4)
    {
        unsigned int alpha = source[3];

        *target++ = (unsigned char) ((source[2] * alpha) / 255);
        *target++ = (unsigned char) ((source[1] * alpha) / 255);
        *target++ = (unsigned char) ((source[0] * alpha) / 255);
        *target++ = (unsigned char) alpha;
    }

    buffer =
        wl_shm_pool_create_buffer(pool, 0,
                                  image->width,
                                  image->height,
                                  stride, WL_SHM_FORMAT_ARGB8888);
    munmap(data, length);
    wl_shm_pool_destroy(pool);

    return buffer;
}

static void createDecoration(_GLFWdecorationWayland* decoration,
                             struct wl_surface* parent,
                             struct wl_buffer* buffer, GLFWbool opaque,
                             int x, int y,
                             int width, int height)
{
    struct wl_region* region;

    decoration->surface = wl_compositor_create_surface(_glfw.wl.compositor);
    decoration->subsurface =
        wl_subcompositor_get_subsurface(_glfw.wl.subcompositor,
                                        decoration->surface, parent);
    wl_subsurface_set_position(decoration->subsurface, x, y);
    decoration->viewport = wp_viewporter_get_viewport(_glfw.wl.viewporter,
                                                      decoration->surface);
    wp_viewport_set_destination(decoration->viewport, width, height);
    wl_surface_attach(decoration->surface, buffer, 0, 0);

    if (opaque)
    {
        region = wl_compositor_create_region(_glfw.wl.compositor);
        wl_region_add(region, 0, 0, width, height);
        wl_surface_set_opaque_region(decoration->surface, region);
        wl_surface_commit(decoration->surface);
        wl_region_destroy(region);
    }
    else
        wl_surface_commit(decoration->surface);
}

static void createDecorations(_GLFWwindow* window)
{
    unsigned char data[] = { 224, 224, 224, 255 };
    const GLFWimage image = { 1, 1, data };
    GLFWbool opaque = (data[3] == 255);

    if (!_glfw.wl.viewporter || !window->decorated || window->wl.decorations.serverSide)
        return;

    if (!window->wl.decorations.buffer)
        window->wl.decorations.buffer = createShmBuffer(&image);
    if (!window->wl.decorations.buffer)
        return;

    createDecoration(&window->wl.decorations.top, window->wl.surface,
                     window->wl.decorations.buffer, opaque,
                     0, -_GLFW_DECORATION_TOP,
                     window->wl.width, _GLFW_DECORATION_TOP);
    createDecoration(&window->wl.decorations.left, window->wl.surface,
                     window->wl.decorations.buffer, opaque,
                     -_GLFW_DECORATION_WIDTH, -_GLFW_DECORATION_TOP,
                     _GLFW_DECORATION_WIDTH, window->wl.height + _GLFW_DECORATION_TOP);
    createDecoration(&window->wl.decorations.right, window->wl.surface,
                     window->wl.decorations.buffer, opaque,
                     window->wl.width, -_GLFW_DECORATION_TOP,
                     _GLFW_DECORATION_WIDTH, window->wl.height + _GLFW_DECORATION_TOP);
    createDecoration(&window->wl.decorations.bottom, window->wl.surface,
                     window->wl.decorations.buffer, opaque,
                     -_GLFW_DECORATION_WIDTH, window->wl.height,
                     window->wl.width + _GLFW_DECORATION_HORIZONTAL, _GLFW_DECORATION_WIDTH);
}

static void destroyDecoration(_GLFWdecorationWayland* decoration)
{
    if (decoration->surface)
        wl_surface_destroy(decoration->surface);
    if (decoration->subsurface)
        wl_subsurface_destroy(decoration->subsurface);
    if (decoration->viewport)
        wp_viewport_destroy(decoration->viewport);
    decoration->surface = NULL;
    decoration->subsurface = NULL;
    decoration->viewport = NULL;
}

static void destroyDecorations(_GLFWwindow* window)
{
    destroyDecoration(&window->wl.decorations.top);
    destroyDecoration(&window->wl.decorations.left);
    destroyDecoration(&window->wl.decorations.right);
    destroyDecoration(&window->wl.decorations.bottom);
}

static void xdgDecorationHandleConfigure(void* data,
                                         struct zxdg_toplevel_decoration_v1* decoration,
                                         uint32_t mode)
{
    _GLFWwindow* window = data;
     window->wl.decorations.serverSide = (mode == ZXDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
     if (!window->wl.decorations.serverSide)
        createDecorations(window);
}

static const struct zxdg_toplevel_decoration_v1_listener xdgDecorationListener = {
    xdgDecorationHandleConfigure,
};

static void handleEnter(void *data,
                        struct wl_surface *surface,
                        struct wl_output *output)
{
    _GLFWwindow* window = data;
    _GLFWmonitor* monitor = wl_output_get_user_data(output);

    if (window->wl.monitorsCount + 1 > window->wl.monitorsSize)
    {
        ++window->wl.monitorsSize;
        window->wl.monitors =
            realloc(window->wl.monitors,
                    window->wl.monitorsSize * sizeof(_GLFWmonitor*));
    }

    window->wl.monitors[window->wl.monitorsCount++] = monitor;

    if (checkScaleChange(window)) {
        resizeFramebuffer(window);
        _glfwInputWindowContentScale(window, window->wl.scale, window->wl.scale);
    }
}

static void handleLeave(void *data,
                        struct wl_surface *surface,
                        struct wl_output *output)
{
    _GLFWwindow* window = data;
    _GLFWmonitor* monitor = wl_output_get_user_data(output);
    GLFWbool found;
    int i;

    for (i = 0, found = GLFW_FALSE; i < window->wl.monitorsCount - 1; ++i)
    {
        if (monitor == window->wl.monitors[i])
            found = GLFW_TRUE;
        if (found)
            window->wl.monitors[i] = window->wl.monitors[i + 1];
    }
    window->wl.monitors[--window->wl.monitorsCount] = NULL;

    if (checkScaleChange(window)) {
        resizeFramebuffer(window);
        _glfwInputWindowContentScale(window, window->wl.scale, window->wl.scale);
    }
}

static const struct wl_surface_listener surfaceListener = {
    handleEnter,
    handleLeave
};

static void setIdleInhibitor(_GLFWwindow* window, GLFWbool enable)
{
    if (enable && !window->wl.idleInhibitor && _glfw.wl.idleInhibitManager)
    {
        window->wl.idleInhibitor =
            zwp_idle_inhibit_manager_v1_create_inhibitor(
                _glfw.wl.idleInhibitManager, window->wl.surface);
        if (!window->wl.idleInhibitor)
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland: Idle inhibitor creation failed");
    }
    else if (!enable && window->wl.idleInhibitor)
    {
        zwp_idle_inhibitor_v1_destroy(window->wl.idleInhibitor);
        window->wl.idleInhibitor = NULL;
    }
}

static GLFWbool createSurface(_GLFWwindow* window,
                              const _GLFWwndconfig* wndconfig)
{
    window->wl.surface = wl_compositor_create_surface(_glfw.wl.compositor);
    if (!window->wl.surface)
        return GLFW_FALSE;

    wl_surface_add_listener(window->wl.surface,
                            &surfaceListener,
                            window);

    wl_surface_set_user_data(window->wl.surface, window);

    window->wl.native = wl_egl_window_create(window->wl.surface,
                                             wndconfig->width,
                                             wndconfig->height);
    if (!window->wl.native)
        return GLFW_FALSE;

    window->wl.width = wndconfig->width;
    window->wl.height = wndconfig->height;
    window->wl.scale = 1;

    if (!window->wl.transparent)
        setOpaqueRegion(window);

    return GLFW_TRUE;
}

static void setFullscreen(_GLFWwindow* window, _GLFWmonitor* monitor, int refreshRate)
{
    if (window->wl.xdg.toplevel)
    {
        xdg_toplevel_set_fullscreen(
            window->wl.xdg.toplevel,
            monitor->wl.output);
    }
    else if (window->wl.shellSurface)
    {
        wl_shell_surface_set_fullscreen(
            window->wl.shellSurface,
            WL_SHELL_SURFACE_FULLSCREEN_METHOD_DEFAULT,
            refreshRate * 1000, // Convert Hz to mHz.
            monitor->wl.output);
    }
    setIdleInhibitor(window, GLFW_TRUE);
    if (!window->wl.decorations.serverSide)
        destroyDecorations(window);
}

static GLFWbool createShellSurface(_GLFWwindow* window)
{
    if (!_glfw.wl.shell)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: wl_shell protocol not available");
        return GLFW_FALSE;
    }

    window->wl.shellSurface = wl_shell_get_shell_surface(_glfw.wl.shell,
                                                         window->wl.surface);
    if (!window->wl.shellSurface)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Shell surface creation failed");
        return GLFW_FALSE;
    }

    wl_shell_surface_add_listener(window->wl.shellSurface,
                                  &shellSurfaceListener,
                                  window);

    if (window->wl.title)
        wl_shell_surface_set_title(window->wl.shellSurface, window->wl.title);

    if (window->monitor)
    {
        setFullscreen(window, window->monitor, 0);
    }
    else if (window->wl.maximized)
    {
        wl_shell_surface_set_maximized(window->wl.shellSurface, NULL);
        setIdleInhibitor(window, GLFW_FALSE);
        createDecorations(window);
    }
    else
    {
        wl_shell_surface_set_toplevel(window->wl.shellSurface);
        setIdleInhibitor(window, GLFW_FALSE);
        createDecorations(window);
    }

    wl_surface_commit(window->wl.surface);

    return GLFW_TRUE;
}

static void xdgToplevelHandleConfigure(void* data,
                                       struct xdg_toplevel* toplevel,
                                       int32_t width,
                                       int32_t height,
                                       struct wl_array* states)
{
    _GLFWwindow* window = data;
    float aspectRatio;
    float targetRatio;
    uint32_t* state;
    GLFWbool maximized = GLFW_FALSE;
    GLFWbool fullscreen = GLFW_FALSE;
    GLFWbool activated = GLFW_FALSE;

    wl_array_for_each(state, states)
    {
        switch (*state)
        {
            case XDG_TOPLEVEL_STATE_MAXIMIZED:
                maximized = GLFW_TRUE;
                break;
            case XDG_TOPLEVEL_STATE_FULLSCREEN:
                fullscreen = GLFW_TRUE;
                break;
            case XDG_TOPLEVEL_STATE_RESIZING:
                break;
            case XDG_TOPLEVEL_STATE_ACTIVATED:
                activated = GLFW_TRUE;
                break;
        }
    }

    if (width != 0 && height != 0)
    {
        if (!maximized && !fullscreen)
        {
            if (window->numer != GLFW_DONT_CARE && window->denom != GLFW_DONT_CARE)
            {
                aspectRatio = (float)width / (float)height;
                targetRatio = (float)window->numer / (float)window->denom;
                if (aspectRatio < targetRatio)
                    height = width / targetRatio;
                else if (aspectRatio > targetRatio)
                    width = height * targetRatio;
            }
        }
    }
    dispatchChangesAfterConfigure(window, width, height);

    if (window->wl.wasFullScreen && window->autoIconify)
    {
        if (!activated || !fullscreen)
        {
            _glfwPlatformIconifyWindow(window);
            window->wl.wasFullScreen = GLFW_FALSE;
        }
    }
    if (fullscreen && activated)
        window->wl.wasFullScreen = GLFW_TRUE;
    _glfwInputWindowFocus(window, activated);
}

static void xdgToplevelHandleClose(void* data,
                                   struct xdg_toplevel* toplevel)
{
    _GLFWwindow* window = data;
    _glfwInputWindowCloseRequest(window);
}

static const struct xdg_toplevel_listener xdgToplevelListener = {
    xdgToplevelHandleConfigure,
    xdgToplevelHandleClose
};

static void xdgSurfaceHandleConfigure(void* data,
                                      struct xdg_surface* surface,
                                      uint32_t serial)
{
    xdg_surface_ack_configure(surface, serial);
}

static const struct xdg_surface_listener xdgSurfaceListener = {
    xdgSurfaceHandleConfigure
};

static void setXdgDecorations(_GLFWwindow* window)
{
    if (_glfw.wl.decorationManager)
    {
        window->wl.xdg.decoration =
            zxdg_decoration_manager_v1_get_toplevel_decoration(
                _glfw.wl.decorationManager, window->wl.xdg.toplevel);
        zxdg_toplevel_decoration_v1_add_listener(window->wl.xdg.decoration,
                                                 &xdgDecorationListener,
                                                 window);
        zxdg_toplevel_decoration_v1_set_mode(
            window->wl.xdg.decoration,
            ZXDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
    }
    else
    {
        window->wl.decorations.serverSide = GLFW_FALSE;
        createDecorations(window);
    }
}

static GLFWbool createXdgSurface(_GLFWwindow* window)
{
    window->wl.xdg.surface = xdg_wm_base_get_xdg_surface(_glfw.wl.wmBase,
                                                         window->wl.surface);
    if (!window->wl.xdg.surface)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: xdg-surface creation failed");
        return GLFW_FALSE;
    }

    xdg_surface_add_listener(window->wl.xdg.surface,
                             &xdgSurfaceListener,
                             window);

    window->wl.xdg.toplevel = xdg_surface_get_toplevel(window->wl.xdg.surface);
    if (!window->wl.xdg.toplevel)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: xdg-toplevel creation failed");
        return GLFW_FALSE;
    }

    xdg_toplevel_add_listener(window->wl.xdg.toplevel,
                              &xdgToplevelListener,
                              window);

    if (window->wl.title)
        xdg_toplevel_set_title(window->wl.xdg.toplevel, window->wl.title);

    if (window->minwidth != GLFW_DONT_CARE && window->minheight != GLFW_DONT_CARE)
        xdg_toplevel_set_min_size(window->wl.xdg.toplevel,
                                  window->minwidth, window->minheight);
    if (window->maxwidth != GLFW_DONT_CARE && window->maxheight != GLFW_DONT_CARE)
        xdg_toplevel_set_max_size(window->wl.xdg.toplevel,
                                  window->maxwidth, window->maxheight);

    if (window->monitor)
    {
        xdg_toplevel_set_fullscreen(window->wl.xdg.toplevel,
                                    window->monitor->wl.output);
        setIdleInhibitor(window, GLFW_TRUE);
    }
    else if (window->wl.maximized)
    {
        xdg_toplevel_set_maximized(window->wl.xdg.toplevel);
        setIdleInhibitor(window, GLFW_FALSE);
        setXdgDecorations(window);
    }
    else
    {
        setIdleInhibitor(window, GLFW_FALSE);
        setXdgDecorations(window);
    }
    if (strlen(window->wl.appId))
        xdg_toplevel_set_app_id(window->wl.xdg.toplevel, window->wl.appId);

    wl_surface_commit(window->wl.surface);
    wl_display_roundtrip(_glfw.wl.display);

    return GLFW_TRUE;
}

static void
setCursorImage(_GLFWcursorWayland* cursorWayland)
{
    struct wl_cursor_image* image;
    struct wl_buffer* buffer;
    struct wl_surface* surface = _glfw.wl.cursorSurface;

    if (!cursorWayland->cursor) {
        buffer = cursorWayland->buffer;
        toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, 0);
    } else
    {
        image = cursorWayland->cursor->images[cursorWayland->currentImage];
        buffer = wl_cursor_image_get_buffer(image);
        if (image->delay) {
            changeTimerInterval(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, ((double)image->delay) / 1000.0);
            toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, 1);
        } else {
            toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, 0);
        }

        if (!buffer)
            return;

        cursorWayland->width = image->width;
        cursorWayland->height = image->height;
        cursorWayland->xhot = image->hotspot_x;
        cursorWayland->yhot = image->hotspot_y;
    }

    wl_pointer_set_cursor(_glfw.wl.pointer, _glfw.wl.pointerSerial,
                          surface,
                          cursorWayland->xhot,
                          cursorWayland->yhot);
    wl_surface_attach(surface, buffer, 0, 0);
    wl_surface_damage(surface, 0, 0,
                      cursorWayland->width, cursorWayland->height);
    wl_surface_commit(surface);
}

static void
incrementCursorImage(_GLFWwindow* window)
{
    if (window && window->wl.decorations.focus == mainWindow) {
        _GLFWcursor* cursor = window->wl.currentCursor;
        if (cursor && cursor->wl.cursor)
        {
            cursor->wl.currentImage += 1;
            cursor->wl.currentImage %= cursor->wl.cursor->image_count;
            setCursorImage(&cursor->wl);
            toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, cursor->wl.cursor->image_count > 1);
            return;
        }
    }
    toggleTimer(&_glfw.wl.eventLoopData, _glfw.wl.cursorAnimationTimer, 1);
}

void
animateCursorImage(id_type timer_id, void *data) {
    incrementCursorImage(_glfw.wl.pointerFocus);
}

static void
abortOnFatalError(int last_error) {
    _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: fatal display error: %s", strerror(last_error));
    _GLFWwindow* window = _glfw.windowListHead;
    while (window)
    {
        _glfwInputWindowCloseRequest(window);
        window = window->next;
    }
}

static void
handleEvents(double timeout)
{
    struct wl_display* display = _glfw.wl.display;
    errno = 0;

    while (wl_display_prepare_read(display) != 0) {
        while(1) {
            errno = 0;
            int num_dispatched = wl_display_dispatch_pending(display);
            if (num_dispatched == 0) return;
            if (num_dispatched < 0) {
                if (errno == EAGAIN) continue;
                int last_error = wl_display_get_error(display);
                if (last_error) abortOnFatalError(last_error);
                return;
            }
            break;
        }
    }

    // If an error different from EAGAIN happens, we have likely been
    // disconnected from the Wayland session, try to handle that the best we
    // can.
    errno = 0;
    if (wl_display_flush(display) < 0 && errno != EAGAIN)
    {
        abortOnFatalError(errno);
        wl_display_cancel_read(display);
        return;
    }

    GLFWbool display_read_ok = pollForEvents(&_glfw.wl.eventLoopData, timeout);
    if (display_read_ok) {
        wl_display_read_events(display);
        wl_display_dispatch_pending(display);
    }
    else
    {
        wl_display_cancel_read(display);
    }
    glfw_ibus_dispatch(&_glfw.wl.xkb.ibus);
    glfw_dbus_session_bus_dispatch();
}

static struct wl_cursor*
try_cursor_names(int arg_count, ...) {
    struct wl_cursor* ans = NULL;
    va_list ap;
    va_start(ap, arg_count);
    for (int i = 0; i < arg_count && !ans; i++) {
        const char *name = va_arg(ap, const char *);
        ans = wl_cursor_theme_get_cursor(_glfw.wl.cursorTheme, name);
    }
    va_end(ap);
    return ans;
}

struct wl_cursor* _glfwLoadCursor(GLFWCursorShape shape)
{
    static GLFWbool warnings[GLFW_INVALID_CURSOR] = {0};
#define NUMARGS(...)  (sizeof((const char*[]){__VA_ARGS__})/sizeof(const char*))
#define C(name, ...) case name: { \
    ans = try_cursor_names(NUMARGS(__VA_ARGS__), __VA_ARGS__); \
    if (!ans && !warnings[name]) {\
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: Could not find standard cursor: %s", #name); \
        warnings[name] = GLFW_TRUE; \
    } \
    break; }

    struct wl_cursor* ans = NULL;
    switch (shape)
    {
        C(GLFW_ARROW_CURSOR, "arrow", "left_ptr", "default")
        C(GLFW_IBEAM_CURSOR, "xterm", "ibeam", "text")
        C(GLFW_CROSSHAIR_CURSOR, "crosshair", "cross")
        C(GLFW_HAND_CURSOR, "hand2", "grab", "grabbing", "closedhand")
        C(GLFW_HRESIZE_CURSOR, "sb_h_double_arrow", "h_double_arrow", "col-resize")
        C(GLFW_VRESIZE_CURSOR, "sb_v_double_arrow", "v_double_arrow", "row-resize")
        C(GLFW_NW_RESIZE_CURSOR, "top_left_corner", "nw-resize")
        C(GLFW_NE_RESIZE_CURSOR, "top_right_corner", "ne-resize")
        C(GLFW_SW_RESIZE_CURSOR, "bottom_left_corner", "sw-resize")
        C(GLFW_SE_RESIZE_CURSOR, "bottom_right_corner", "se-resize")
        case GLFW_INVALID_CURSOR:
            break;
    }
    return ans;
#undef NUMARGS
#undef C
}

//////////////////////////////////////////////////////////////////////////
//////                       GLFW platform API                      //////
//////////////////////////////////////////////////////////////////////////

int _glfwPlatformCreateWindow(_GLFWwindow* window,
                              const _GLFWwndconfig* wndconfig,
                              const _GLFWctxconfig* ctxconfig,
                              const _GLFWfbconfig* fbconfig)
{
    window->wl.transparent = fbconfig->transparent;
    strncpy(window->wl.appId, wndconfig->wl.appId, sizeof(window->wl.appId));

    if (!createSurface(window, wndconfig))
        return GLFW_FALSE;

    if (ctxconfig->client != GLFW_NO_API)
    {
        if (ctxconfig->source == GLFW_EGL_CONTEXT_API ||
            ctxconfig->source == GLFW_NATIVE_CONTEXT_API)
        {
            if (!_glfwInitEGL())
                return GLFW_FALSE;
            if (!_glfwCreateContextEGL(window, ctxconfig, fbconfig))
                return GLFW_FALSE;
        }
        else if (ctxconfig->source == GLFW_OSMESA_CONTEXT_API)
        {
            if (!_glfwInitOSMesa())
                return GLFW_FALSE;
            if (!_glfwCreateContextOSMesa(window, ctxconfig, fbconfig))
                return GLFW_FALSE;
        }
    }

    if (wndconfig->title)
        window->wl.title = _glfw_strdup(wndconfig->title);

    if (wndconfig->visible)
    {
        if (_glfw.wl.wmBase)
        {
            if (!createXdgSurface(window))
                return GLFW_FALSE;
        }
        else
        {
            if (!createShellSurface(window))
                return GLFW_FALSE;
        }

        window->wl.visible = GLFW_TRUE;
    }
    else
    {
        window->wl.xdg.surface = NULL;
        window->wl.xdg.toplevel = NULL;
        window->wl.shellSurface = NULL;
        window->wl.visible = GLFW_FALSE;
    }

    window->wl.currentCursor = NULL;

    window->wl.monitors = calloc(1, sizeof(_GLFWmonitor*));
    window->wl.monitorsCount = 0;
    window->wl.monitorsSize = 1;

    return GLFW_TRUE;
}

void _glfwPlatformDestroyWindow(_GLFWwindow* window)
{
    if (window == _glfw.wl.pointerFocus)
    {
        _glfw.wl.pointerFocus = NULL;
        _glfwInputCursorEnter(window, GLFW_FALSE);
    }
    if (window == _glfw.wl.keyboardFocus)
    {
        _glfw.wl.keyboardFocus = NULL;
        _glfwInputWindowFocus(window, GLFW_FALSE);
    }

    if (window->wl.idleInhibitor)
        zwp_idle_inhibitor_v1_destroy(window->wl.idleInhibitor);

    if (window->context.destroy)
        window->context.destroy(window);

    destroyDecorations(window);
    if (window->wl.xdg.decoration)
        zxdg_toplevel_decoration_v1_destroy(window->wl.xdg.decoration);
    if (window->wl.decorations.buffer)
        wl_buffer_destroy(window->wl.decorations.buffer);

    if (window->wl.native)
        wl_egl_window_destroy(window->wl.native);

    if (window->wl.shellSurface)
        wl_shell_surface_destroy(window->wl.shellSurface);

    if (window->wl.xdg.toplevel)
        xdg_toplevel_destroy(window->wl.xdg.toplevel);

    if (window->wl.xdg.surface)
        xdg_surface_destroy(window->wl.xdg.surface);

    if (window->wl.surface)
        wl_surface_destroy(window->wl.surface);

    free(window->wl.title);
    free(window->wl.monitors);
    if (window->wl.frameCallbackData.current_wl_callback)
        wl_callback_destroy(window->wl.frameCallbackData.current_wl_callback);
}

void _glfwPlatformSetWindowTitle(_GLFWwindow* window, const char* title)
{
    if (window->wl.title)
        free(window->wl.title);
    window->wl.title = _glfw_strdup(title);
    if (window->wl.xdg.toplevel)
        xdg_toplevel_set_title(window->wl.xdg.toplevel, title);
    else if (window->wl.shellSurface)
        wl_shell_surface_set_title(window->wl.shellSurface, title);
}

void _glfwPlatformSetWindowIcon(_GLFWwindow* window,
                                int count, const GLFWimage* images)
{
    _glfwInputError(GLFW_PLATFORM_ERROR,
                    "Wayland: Setting window icon not supported");
}

void _glfwPlatformGetWindowPos(_GLFWwindow* window, int* xpos, int* ypos)
{
    // A Wayland client is not aware of its position, so just warn and leave it
    // as (0, 0)

    _glfwInputError(GLFW_PLATFORM_ERROR,
                    "Wayland: Window position retrieval not supported");
}

void _glfwPlatformSetWindowPos(_GLFWwindow* window, int xpos, int ypos)
{
    // A Wayland client can not set its position, so just warn

    _glfwInputError(GLFW_PLATFORM_ERROR,
                    "Wayland: Window position setting not supported");
}

void _glfwPlatformGetWindowSize(_GLFWwindow* window, int* width, int* height)
{
    if (width)
        *width = window->wl.width;
    if (height)
        *height = window->wl.height;
}

void _glfwPlatformSetWindowSize(_GLFWwindow* window, int width, int height)
{
    if (width != window->wl.width || height != window->wl.height) {
        window->wl.width = width;
        window->wl.height = height;
        resizeFramebuffer(window);
    }
}

void _glfwPlatformSetWindowSizeLimits(_GLFWwindow* window,
                                      int minwidth, int minheight,
                                      int maxwidth, int maxheight)
{
    if (_glfw.wl.wmBase)
    {
        if (window->wl.xdg.toplevel)
        {
            if (minwidth == GLFW_DONT_CARE || minheight == GLFW_DONT_CARE)
                minwidth = minheight = 0;
            if (maxwidth == GLFW_DONT_CARE || maxheight == GLFW_DONT_CARE)
                maxwidth = maxheight = 0;
            xdg_toplevel_set_min_size(window->wl.xdg.toplevel, minwidth, minheight);
            xdg_toplevel_set_max_size(window->wl.xdg.toplevel, maxwidth, maxheight);
            wl_surface_commit(window->wl.surface);
        }
    }
    else
    {
        // TODO: find out how to trigger a resize.
        // The actual limits are checked in the wl_shell_surface::configure handler.
    }
}

void _glfwPlatformSetWindowAspectRatio(_GLFWwindow* window, int numer, int denom)
{
    // TODO: find out how to trigger a resize.
    // The actual limits are checked in the wl_shell_surface::configure handler.
}

void _glfwPlatformGetFramebufferSize(_GLFWwindow* window, int* width, int* height)
{
    _glfwPlatformGetWindowSize(window, width, height);
    *width *= window->wl.scale;
    *height *= window->wl.scale;
}

void _glfwPlatformGetWindowFrameSize(_GLFWwindow* window,
                                     int* left, int* top,
                                     int* right, int* bottom)
{
    if (window->decorated && !window->monitor && !window->wl.decorations.serverSide)
    {
        if (top)
            *top = _GLFW_DECORATION_TOP;
        if (left)
            *left = _GLFW_DECORATION_WIDTH;
        if (right)
            *right = _GLFW_DECORATION_WIDTH;
        if (bottom)
            *bottom = _GLFW_DECORATION_WIDTH;
    }
}

void _glfwPlatformGetWindowContentScale(_GLFWwindow* window,
                                        float* xscale, float* yscale)
{
    if (xscale)
        *xscale = (float) window->wl.scale;
    if (yscale)
        *yscale = (float) window->wl.scale;
}

double _glfwPlatformGetDoubleClickInterval(_GLFWwindow* window)
{
    return 0.5;
}

void _glfwPlatformIconifyWindow(_GLFWwindow* window)
{
    if (_glfw.wl.wmBase)
    {
        if (window->wl.xdg.toplevel)
            xdg_toplevel_set_minimized(window->wl.xdg.toplevel);
    }
    else
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Iconify window not supported on wl_shell");
    }
}

void _glfwPlatformRestoreWindow(_GLFWwindow* window)
{
    if (window->wl.xdg.toplevel)
    {
        if (window->monitor)
            xdg_toplevel_unset_fullscreen(window->wl.xdg.toplevel);
        if (window->wl.maximized)
            xdg_toplevel_unset_maximized(window->wl.xdg.toplevel);
        // There is no way to unset minimized, or even to know if we are
        // minimized, so there is nothing to do here.
    }
    else if (window->wl.shellSurface)
    {
        if (window->monitor || window->wl.maximized)
            wl_shell_surface_set_toplevel(window->wl.shellSurface);
    }
    _glfwInputWindowMonitor(window, NULL);
    window->wl.maximized = GLFW_FALSE;
}

void _glfwPlatformMaximizeWindow(_GLFWwindow* window)
{
    if (window->wl.xdg.toplevel)
    {
        xdg_toplevel_set_maximized(window->wl.xdg.toplevel);
    }
    else if (window->wl.shellSurface)
    {
        // Let the compositor select the best output.
        wl_shell_surface_set_maximized(window->wl.shellSurface, NULL);
    }
    window->wl.maximized = GLFW_TRUE;
}

void _glfwPlatformShowWindow(_GLFWwindow* window)
{
    if (!window->wl.visible)
    {
        if (_glfw.wl.wmBase)
            createXdgSurface(window);
        else if (!window->wl.shellSurface)
            createShellSurface(window);
        window->wl.visible = GLFW_TRUE;
    }
}

void _glfwPlatformHideWindow(_GLFWwindow* window)
{
    if (window->wl.xdg.toplevel)
    {
        xdg_toplevel_destroy(window->wl.xdg.toplevel);
        xdg_surface_destroy(window->wl.xdg.surface);
        window->wl.xdg.toplevel = NULL;
        window->wl.xdg.surface = NULL;
    }
    else if (window->wl.shellSurface)
    {
        wl_shell_surface_destroy(window->wl.shellSurface);
        window->wl.shellSurface = NULL;
    }
    window->wl.visible = GLFW_FALSE;
}

void _glfwPlatformRequestWindowAttention(_GLFWwindow* window)
{
    // TODO
    _glfwInputError(GLFW_PLATFORM_ERROR,
                    "Wayland: Window attention request not implemented yet");
}

int _glfwPlatformWindowBell(_GLFWwindow* window)
{
    // TODO: Use an actual Wayland API to implement this when one becomes available
    static char tty[L_ctermid + 1];
    int fd = open(ctermid(tty), O_WRONLY | O_CLOEXEC);
    if (fd > -1) {
        int ret = write(fd, "\x07", 1) == 1 ? GLFW_TRUE : GLFW_FALSE;
        close(fd);
        return ret;
    }
    return GLFW_FALSE;
}

void _glfwPlatformFocusWindow(_GLFWwindow* window)
{
    _glfwInputError(GLFW_PLATFORM_ERROR,
                    "Wayland: Focusing a window requires user interaction");
}

void _glfwPlatformSetWindowMonitor(_GLFWwindow* window,
                                   _GLFWmonitor* monitor,
                                   int xpos, int ypos,
                                   int width, int height,
                                   int refreshRate)
{
    if (monitor)
    {
        setFullscreen(window, monitor, refreshRate);
    }
    else
    {
        if (window->wl.xdg.toplevel)
            xdg_toplevel_unset_fullscreen(window->wl.xdg.toplevel);
        else if (window->wl.shellSurface)
            wl_shell_surface_set_toplevel(window->wl.shellSurface);
        setIdleInhibitor(window, GLFW_FALSE);
        if (!_glfw.wl.decorationManager)
            createDecorations(window);
    }
    _glfwInputWindowMonitor(window, monitor);
}

int _glfwPlatformWindowFocused(_GLFWwindow* window)
{
    return _glfw.wl.keyboardFocus == window;
}

int _glfwPlatformWindowOccluded(_GLFWwindow* window)
{
    return GLFW_FALSE;
}

int _glfwPlatformWindowIconified(_GLFWwindow* window)
{
    // wl_shell doesn't have any iconified concept, and xdg-shell doesn’t give
    // any way to request whether a surface is iconified.
    return GLFW_FALSE;
}

int _glfwPlatformWindowVisible(_GLFWwindow* window)
{
    return window->wl.visible;
}

int _glfwPlatformWindowMaximized(_GLFWwindow* window)
{
    return window->wl.maximized;
}

int _glfwPlatformWindowHovered(_GLFWwindow* window)
{
    return window->wl.hovered;
}

int _glfwPlatformFramebufferTransparent(_GLFWwindow* window)
{
    return window->wl.transparent;
}

void _glfwPlatformSetWindowResizable(_GLFWwindow* window, GLFWbool enabled)
{
    // TODO
    _glfwInputError(GLFW_PLATFORM_ERROR,
                    "Wayland: Window attribute setting not implemented yet");
}

void _glfwPlatformSetWindowDecorated(_GLFWwindow* window, GLFWbool enabled)
{
    if (!window->monitor)
    {
        if (enabled)
            createDecorations(window);
        else
            destroyDecorations(window);
    }
}

void _glfwPlatformSetWindowFloating(_GLFWwindow* window, GLFWbool enabled)
{
    // TODO
    _glfwInputError(GLFW_PLATFORM_ERROR,
                    "Wayland: Window attribute setting not implemented yet");
}

float _glfwPlatformGetWindowOpacity(_GLFWwindow* window)
{
    return 1.f;
}

void _glfwPlatformSetWindowOpacity(_GLFWwindow* window, float opacity)
{
}

void _glfwPlatformPollEvents(void)
{
    wl_display_dispatch_pending(_glfw.wl.display);
    handleEvents(0);
}

void _glfwPlatformWaitEvents(void)
{
    double timeout = wl_display_dispatch_pending(_glfw.wl.display) > 0 ? 0 : -1;
    handleEvents(timeout);
}

void _glfwPlatformWaitEventsTimeout(double timeout)
{
    if (wl_display_dispatch_pending(_glfw.wl.display) > 0) timeout = 0;
    handleEvents(timeout);
}

void _glfwPlatformPostEmptyEvent(void)
{
    wl_display_sync(_glfw.wl.display);
    while (write(_glfw.wl.eventLoopData.wakeupFds[1], "w", 1) < 0 && errno == EINTR);
}

void _glfwPlatformGetCursorPos(_GLFWwindow* window, double* xpos, double* ypos)
{
    if (xpos)
        *xpos = window->wl.cursorPosX;
    if (ypos)
        *ypos = window->wl.cursorPosY;
}

static GLFWbool isPointerLocked(_GLFWwindow* window);

void _glfwPlatformSetCursorPos(_GLFWwindow* window, double x, double y)
{
    if (isPointerLocked(window))
    {
        zwp_locked_pointer_v1_set_cursor_position_hint(
            window->wl.pointerLock.lockedPointer,
            wl_fixed_from_double(x), wl_fixed_from_double(y));
        wl_surface_commit(window->wl.surface);
    }
}

void _glfwPlatformSetCursorMode(_GLFWwindow* window, int mode)
{
    _glfwPlatformSetCursor(window, window->wl.currentCursor);
}

const char* _glfwPlatformGetScancodeName(int scancode)
{
    return glfw_xkb_keysym_name(scancode);
}

int _glfwPlatformGetKeyScancode(int key)
{
    return glfw_xkb_sym_for_key(key);
}

int _glfwPlatformCreateCursor(_GLFWcursor* cursor,
                              const GLFWimage* image,
                              int xhot, int yhot, int count)
{
    cursor->wl.buffer = createShmBuffer(image);
    if (!cursor->wl.buffer)
        return GLFW_FALSE;
    cursor->wl.width = image->width;
    cursor->wl.height = image->height;
    cursor->wl.xhot = xhot;
    cursor->wl.yhot = yhot;
    return GLFW_TRUE;
}

int _glfwPlatformCreateStandardCursor(_GLFWcursor* cursor, GLFWCursorShape shape)
{
    struct wl_cursor* standardCursor;

    standardCursor = _glfwLoadCursor(shape);
    if (!standardCursor) return GLFW_FALSE;
    cursor->wl.cursor = standardCursor;
    cursor->wl.currentImage = 0;
    return GLFW_TRUE;
}

void _glfwPlatformDestroyCursor(_GLFWcursor* cursor)
{
    // If it's a standard cursor we don't need to do anything here
    if (cursor->wl.cursor)
        return;

    if (cursor->wl.buffer)
        wl_buffer_destroy(cursor->wl.buffer);
}

static void handleRelativeMotion(void* data,
                                 struct zwp_relative_pointer_v1* pointer,
                                 uint32_t timeHi,
                                 uint32_t timeLo,
                                 wl_fixed_t dx,
                                 wl_fixed_t dy,
                                 wl_fixed_t dxUnaccel,
                                 wl_fixed_t dyUnaccel)
{
    _GLFWwindow* window = data;

    if (window->cursorMode != GLFW_CURSOR_DISABLED)
        return;

    _glfwInputCursorPos(window,
                        window->virtualCursorPosX + wl_fixed_to_double(dxUnaccel),
                        window->virtualCursorPosY + wl_fixed_to_double(dyUnaccel));
}

static const struct zwp_relative_pointer_v1_listener relativePointerListener = {
    handleRelativeMotion
};

static void handleLocked(void* data,
                         struct zwp_locked_pointer_v1* lockedPointer)
{
}

static void unlockPointer(_GLFWwindow* window)
{
    struct zwp_relative_pointer_v1* relativePointer =
        window->wl.pointerLock.relativePointer;
    struct zwp_locked_pointer_v1* lockedPointer =
        window->wl.pointerLock.lockedPointer;

    zwp_relative_pointer_v1_destroy(relativePointer);
    zwp_locked_pointer_v1_destroy(lockedPointer);

    window->wl.pointerLock.relativePointer = NULL;
    window->wl.pointerLock.lockedPointer = NULL;
}

static void lockPointer(_GLFWwindow* window);

static void handleUnlocked(void* data,
                           struct zwp_locked_pointer_v1* lockedPointer)
{
}

static const struct zwp_locked_pointer_v1_listener lockedPointerListener = {
    handleLocked,
    handleUnlocked
};

static void lockPointer(_GLFWwindow* window)
{
    struct zwp_relative_pointer_v1* relativePointer;
    struct zwp_locked_pointer_v1* lockedPointer;

    if (!_glfw.wl.relativePointerManager)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: no relative pointer manager");
        return;
    }

    relativePointer =
        zwp_relative_pointer_manager_v1_get_relative_pointer(
            _glfw.wl.relativePointerManager,
            _glfw.wl.pointer);
    zwp_relative_pointer_v1_add_listener(relativePointer,
                                         &relativePointerListener,
                                         window);

    lockedPointer =
        zwp_pointer_constraints_v1_lock_pointer(
            _glfw.wl.pointerConstraints,
            window->wl.surface,
            _glfw.wl.pointer,
            NULL,
            ZWP_POINTER_CONSTRAINTS_V1_LIFETIME_PERSISTENT);
    zwp_locked_pointer_v1_add_listener(lockedPointer,
                                       &lockedPointerListener,
                                       window);

    window->wl.pointerLock.relativePointer = relativePointer;
    window->wl.pointerLock.lockedPointer = lockedPointer;

    wl_pointer_set_cursor(_glfw.wl.pointer, _glfw.wl.pointerSerial,
                          NULL, 0, 0);
}

static GLFWbool isPointerLocked(_GLFWwindow* window)
{
    return window->wl.pointerLock.lockedPointer != NULL;
}

void _glfwPlatformSetCursor(_GLFWwindow* window, _GLFWcursor* cursor)
{
    struct wl_cursor* defaultCursor;

    if (!_glfw.wl.pointer)
        return;

    window->wl.currentCursor = cursor;

    // If we're not in the correct window just save the cursor
    // the next time the pointer enters the window the cursor will change
    if (window != _glfw.wl.pointerFocus || window->wl.decorations.focus != mainWindow)
        return;

    // Unlock possible pointer lock if no longer disabled.
    if (window->cursorMode != GLFW_CURSOR_DISABLED && isPointerLocked(window))
        unlockPointer(window);

    if (window->cursorMode == GLFW_CURSOR_NORMAL)
    {
        if (cursor)
            setCursorImage(&cursor->wl);
        else
        {
            defaultCursor = _glfwLoadCursor(GLFW_ARROW_CURSOR);
            if (!defaultCursor) return;
            _GLFWcursorWayland cursorWayland = {
                defaultCursor,
                NULL,
                0, 0,
                0, 0,
                0
            };
            setCursorImage(&cursorWayland);
        }
    }
    else if (window->cursorMode == GLFW_CURSOR_DISABLED)
    {
        if (!isPointerLocked(window))
            lockPointer(window);
    }
    else if (window->cursorMode == GLFW_CURSOR_HIDDEN)
    {
        wl_pointer_set_cursor(_glfw.wl.pointer, _glfw.wl.pointerSerial,
                              NULL, 0, 0);
    }
}

static void send_text(char *text, int fd)
{
    if (text) {
        size_t len = strlen(text), pos = 0;
        double start = glfwGetTime();
        while (pos < len && glfwGetTime() - start < 2.0) {
            ssize_t ret = write(fd, text + pos, len - pos);
            if (ret < 0) {
                if (errno == EAGAIN || errno == EINTR) continue;
                _glfwInputError(GLFW_PLATFORM_ERROR,
                    "Wayland: Could not copy writing to destination fd failed with error: %s", strerror(errno));
                break;
            }
            if (ret > 0) {
                start = glfwGetTime();
                pos += ret;
            }
        }
    }
    close(fd);
}

static void _glfwSendClipboardText(void *data, struct wl_data_source *data_source, const char *mime_type, int fd) {
    send_text(_glfw.wl.clipboardString, fd);
}

static void _glfwSendPrimarySelectionText(void *data, struct zwp_primary_selection_source_v1 *primary_selection_source,
        const char *mime_type, int fd) {
    send_text(_glfw.wl.primarySelectionString, fd);
}

static char* read_offer_string(int data_pipe) {
    wl_display_flush(_glfw.wl.display);
    size_t sz = 0, capacity = 0;
    char *buf = NULL;
    struct pollfd fds;
    fds.fd = data_pipe;
    fds.events = POLLIN;
    double start = glfwGetTime();
#define bail(...) { \
    _glfwInputError(GLFW_PLATFORM_ERROR, __VA_ARGS__); \
    free(buf); buf = NULL; \
    close(data_pipe); \
    return NULL; \
}

    while (glfwGetTime() - start < 2) {
        int ret = poll(&fds, 1, 2000);
        if (ret == -1) {
            if (errno == EINTR) continue;
            bail("Wayland: Failed to poll clipboard data from pipe with error: %s", strerror(errno));
        }
        if (!ret) {
            bail("Wayland: Failed to read clipboard data from pipe (timed out)");
        }
        if (capacity <= sz || capacity - sz <= 64) {
            capacity += 4096;
            buf = realloc(buf, capacity);
            if (!buf) {
                bail("Wayland: Failed to allocate memory to read clipboard data");
            }
        }
        ret = read(data_pipe, buf + sz, capacity - sz - 1);
        if (ret == -1) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) continue;
            bail("Wayland: Failed to read clipboard data from pipe with error: %s", strerror(errno));
        }
        if (ret == 0) { close(data_pipe); buf[sz] = 0; return buf; }
        sz += ret;
        start = glfwGetTime();
    }
    bail("Wayland: Failed to read clipboard data from pipe (timed out)");
#undef bail

}

static char* read_primary_selection_offer(struct zwp_primary_selection_offer_v1 *primary_selection_offer, const char *mime) {
    int pipefd[2];
    if (pipe2(pipefd, O_CLOEXEC) != 0) return NULL;
    zwp_primary_selection_offer_v1_receive(primary_selection_offer, mime, pipefd[1]);
    close(pipefd[1]);
    return read_offer_string(pipefd[0]);
}

static char* read_data_offer(struct wl_data_offer *data_offer, const char *mime) {
    int pipefd[2];
    if (pipe2(pipefd, O_CLOEXEC) != 0) return NULL;
    wl_data_offer_receive(data_offer, mime, pipefd[1]);
    close(pipefd[1]);
    return read_offer_string(pipefd[0]);
}

static void data_source_canceled(void *data, struct wl_data_source *wl_data_source) {
    if (_glfw.wl.dataSourceForClipboard == wl_data_source)
        _glfw.wl.dataSourceForClipboard = NULL;
    wl_data_source_destroy(wl_data_source);
}

static void primary_selection_source_canceled(void *data, struct zwp_primary_selection_source_v1 *primary_selection_source) {
    if (_glfw.wl.dataSourceForPrimarySelection == primary_selection_source)
        _glfw.wl.dataSourceForPrimarySelection = NULL;
    zwp_primary_selection_source_v1_destroy(primary_selection_source);
}

static void data_source_target(void *data, struct wl_data_source *wl_data_source, const char* mime) {
}

const static struct wl_data_source_listener data_source_listener = {
    .send = _glfwSendClipboardText,
    .cancelled = data_source_canceled,
    .target = data_source_target,
};

const static struct zwp_primary_selection_source_v1_listener primary_selection_source_listener = {
    .send = _glfwSendPrimarySelectionText,
    .cancelled = primary_selection_source_canceled,
};

static void prune_unclaimed_data_offers() {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id && !_glfw.wl.dataOffers[i].offer_type) {
            wl_data_offer_destroy(_glfw.wl.dataOffers[i].id);
            memset(_glfw.wl.dataOffers + i, 0, sizeof(_glfw.wl.dataOffers[0]));
        }
    }
}

static void prune_unclaimed_primary_selection_offers() {
    for (size_t i = 0; i < arraysz(_glfw.wl.primarySelectionOffers); i++) {
        if (_glfw.wl.primarySelectionOffers[i].id && !_glfw.wl.dataOffers[i].offer_type) {
            zwp_primary_selection_offer_v1_destroy(_glfw.wl.primarySelectionOffers[i].id);
            memset(_glfw.wl.primarySelectionOffers + i, 0, sizeof(_glfw.wl.primarySelectionOffers[0]));
        }
    }
}

static void mark_selection_offer(void *data, struct wl_data_device *data_device, struct wl_data_offer *data_offer)
{
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == data_offer) {
            _glfw.wl.dataOffers[i].offer_type = CLIPBOARD;
        } else if (_glfw.wl.dataOffers[i].offer_type == CLIPBOARD) {
            _glfw.wl.dataOffers[i].offer_type = EXPIRED;  // previous selection offer
        }
    }
    prune_unclaimed_data_offers();
}

static void mark_primary_selection_offer(void *data, struct zwp_primary_selection_device_v1* primary_selection_device,
        struct zwp_primary_selection_offer_v1 *primary_selection_offer) {
    for (size_t i = 0; i < arraysz(_glfw.wl.primarySelectionOffers); i++) {
        if (_glfw.wl.primarySelectionOffers[i].id == primary_selection_offer) {
            _glfw.wl.primarySelectionOffers[i].offer_type = PRIMARY_SELECTION;
        } else if (_glfw.wl.primarySelectionOffers[i].offer_type == PRIMARY_SELECTION) {
            _glfw.wl.primarySelectionOffers[i].offer_type = EXPIRED;  // previous selection offer
        }
    }
    prune_unclaimed_primary_selection_offers();
}

static void set_offer_mimetype(struct _GLFWWaylandDataOffer* offer, const char* mime) {
    if (strcmp(mime, "text/plain;charset=utf-8") == 0)
        offer->mime = "text/plain;charset=utf-8";
    else if (!offer->mime && strcmp(mime, "text/plain") == 0)
        offer->mime = "text/plain";
    else if (strcmp(mime, clipboard_mime()) == 0)
        offer->is_self_offer = 1;
    else if (strcmp(mime, URI_LIST_MIME) == 0)
        offer->has_uri_list = 1;
}

static void handle_offer_mimetype(void *data, struct wl_data_offer* id, const char *mime) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == id) {
            set_offer_mimetype(&_glfw.wl.dataOffers[i], mime);
            break;
        }
    }
}

static void handle_primary_selection_offer_mimetype(void *data, struct zwp_primary_selection_offer_v1* id, const char *mime) {
    for (size_t i = 0; i < arraysz(_glfw.wl.primarySelectionOffers); i++) {
        if (_glfw.wl.primarySelectionOffers[i].id == id) {
            set_offer_mimetype((struct _GLFWWaylandDataOffer*)&_glfw.wl.primarySelectionOffers[i], mime);
            break;
        }
    }
}

static void data_offer_source_actions(void *data, struct wl_data_offer* id, uint32_t actions) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == id) {
            _glfw.wl.dataOffers[i].source_actions = actions;
            break;
        }
    }
}

static void data_offer_action(void *data, struct wl_data_offer* id, uint32_t action) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == id) {
            _glfw.wl.dataOffers[i].dnd_action = action;
            break;
        }
    }
}


static const struct wl_data_offer_listener data_offer_listener = {
    .offer = handle_offer_mimetype,
    .source_actions = data_offer_source_actions,
    .action = data_offer_action,
};

static const struct zwp_primary_selection_offer_v1_listener primary_selection_offer_listener = {
    .offer = handle_primary_selection_offer_mimetype,
};

static void handle_data_offer(void *data, struct wl_data_device *wl_data_device, struct wl_data_offer *id) {
    size_t smallest_idx = SIZE_MAX, pos = 0;
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].idx && _glfw.wl.dataOffers[i].idx < smallest_idx) {
            smallest_idx = _glfw.wl.dataOffers[i].idx;
            pos = i;
        }
        if (_glfw.wl.dataOffers[i].id == NULL) {
            _glfw.wl.dataOffers[i].id = id;
            _glfw.wl.dataOffers[i].idx = ++_glfw.wl.dataOffersCounter;
            goto end;
        }
    }
    if (_glfw.wl.dataOffers[pos].id) wl_data_offer_destroy(_glfw.wl.dataOffers[pos].id);
    memset(_glfw.wl.dataOffers + pos, 0, sizeof(_glfw.wl.dataOffers[0]));
    _glfw.wl.dataOffers[pos].id = id;
    _glfw.wl.dataOffers[pos].idx = ++_glfw.wl.dataOffersCounter;
end:
    wl_data_offer_add_listener(id, &data_offer_listener, NULL);
}

static void handle_primary_selection_offer(void *data, struct zwp_primary_selection_device_v1 *zwp_primary_selection_device_v1, struct zwp_primary_selection_offer_v1 *id) {
    size_t smallest_idx = SIZE_MAX, pos = 0;
    for (size_t i = 0; i < arraysz(_glfw.wl.primarySelectionOffers); i++) {
        if (_glfw.wl.primarySelectionOffers[i].idx && _glfw.wl.primarySelectionOffers[i].idx < smallest_idx) {
            smallest_idx = _glfw.wl.primarySelectionOffers[i].idx;
            pos = i;
        }
        if (_glfw.wl.primarySelectionOffers[i].id == NULL) {
            _glfw.wl.primarySelectionOffers[i].id = id;
            _glfw.wl.primarySelectionOffers[i].idx = ++_glfw.wl.primarySelectionOffersCounter;
            goto end;
        }
    }
    if (_glfw.wl.primarySelectionOffers[pos].id) zwp_primary_selection_offer_v1_destroy(_glfw.wl.primarySelectionOffers[pos].id);
    memset(_glfw.wl.primarySelectionOffers + pos, 0, sizeof(_glfw.wl.primarySelectionOffers[0]));
    _glfw.wl.primarySelectionOffers[pos].id = id;
    _glfw.wl.primarySelectionOffers[pos].idx = ++_glfw.wl.primarySelectionOffersCounter;
end:
    zwp_primary_selection_offer_v1_add_listener(id, &primary_selection_offer_listener, NULL);
}

static void drag_enter(void *data, struct wl_data_device *wl_data_device, uint32_t serial, struct wl_surface *surface, wl_fixed_t x, wl_fixed_t y, struct wl_data_offer *id) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id == id) {
            _glfw.wl.dataOffers[i].offer_type = DRAG_AND_DROP;
            _glfw.wl.dataOffers[i].surface = surface;
            const char *mime = _glfw.wl.dataOffers[i].has_uri_list ? URI_LIST_MIME : NULL;
            wl_data_offer_accept(id, serial, mime);
        } else if (_glfw.wl.dataOffers[i].offer_type == DRAG_AND_DROP) {
            _glfw.wl.dataOffers[i].offer_type = EXPIRED;  // previous drag offer
        }
    }
    prune_unclaimed_data_offers();
}

static void drag_leave(void *data, struct wl_data_device *wl_data_device) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].offer_type == DRAG_AND_DROP) {
            wl_data_offer_destroy(_glfw.wl.dataOffers[i].id);
            memset(_glfw.wl.dataOffers + i, 0, sizeof(_glfw.wl.dataOffers[0]));
        }
    }
}

static void drop(void *data, struct wl_data_device *wl_data_device) {
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].offer_type == DRAG_AND_DROP) {
            char *uri_list = read_data_offer(_glfw.wl.dataOffers[i].id, URI_LIST_MIME);
            if (uri_list) {
                wl_data_offer_finish(_glfw.wl.dataOffers[i].id);
                int count;
                char** paths = parseUriList(data, &count);

                _GLFWwindow* window = _glfw.windowListHead;
                while (window)
                {
                    if (window->wl.surface == _glfw.wl.dataOffers[i].surface) {
                        _glfwInputDrop(window, count, (const char**) paths);
                        break;
                    }
                    window = window->next;
                }


                for (int k = 0;  k < count;  k++)
                    free(paths[k]);
                free(paths);
                free(uri_list);
            }
            wl_data_offer_destroy(_glfw.wl.dataOffers[i].id);
            memset(_glfw.wl.dataOffers + i, 0, sizeof(_glfw.wl.dataOffers[0]));
            break;
        }
    }
}

static void motion(void *data, struct wl_data_device *wl_data_device, uint32_t time, wl_fixed_t x, wl_fixed_t y) {
}

const static struct wl_data_device_listener data_device_listener = {
    .data_offer = handle_data_offer,
    .selection = mark_selection_offer,
    .enter = drag_enter,
    .motion = motion,
    .drop = drop,
    .leave = drag_leave,
};

const static struct zwp_primary_selection_device_v1_listener primary_selection_device_listener = {
    .data_offer = handle_primary_selection_offer,
    .selection = mark_primary_selection_offer,
};


static void
clipboard_copy_callback_done(void *data, struct wl_callback *callback, uint32_t serial) {
    if (_glfw.wl.dataDevice && data == (void*)_glfw.wl.dataSourceForClipboard) {
        wl_data_device_set_selection(_glfw.wl.dataDevice, data, serial);
    }
    wl_callback_destroy(callback);
}

static void
primary_selection_copy_callback_done(void *data, struct wl_callback *callback, uint32_t serial) {
    if (_glfw.wl.primarySelectionDevice && data == (void*)_glfw.wl.dataSourceForPrimarySelection) {
        zwp_primary_selection_device_v1_set_selection(_glfw.wl.primarySelectionDevice, data, serial);
    }
    wl_callback_destroy(callback);
}

void _glfwSetupWaylandDataDevice() {
    _glfw.wl.dataDevice = wl_data_device_manager_get_data_device(_glfw.wl.dataDeviceManager, _glfw.wl.seat);
    if (_glfw.wl.dataDevice) wl_data_device_add_listener(_glfw.wl.dataDevice, &data_device_listener, NULL);
}

void _glfwSetupWaylandPrimarySelectionDevice() {
    _glfw.wl.primarySelectionDevice = zwp_primary_selection_device_manager_v1_get_device(_glfw.wl.primarySelectionDeviceManager, _glfw.wl.seat);
    if (_glfw.wl.primarySelectionDevice) zwp_primary_selection_device_v1_add_listener(_glfw.wl.primarySelectionDevice, &primary_selection_device_listener, NULL);
}

static inline GLFWbool _glfwEnsureDataDevice() {
    if (!_glfw.wl.dataDeviceManager)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Cannot use clipboard, data device manager is not ready");
        return GLFW_FALSE;
    }

    if (!_glfw.wl.dataDevice)
    {
        if (!_glfw.wl.seat)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland: Cannot use clipboard, seat is not ready");
            return GLFW_FALSE;
        }
        if (!_glfw.wl.dataDevice)
        {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                    "Wayland: Cannot use clipboard, failed to create data device");
            return GLFW_FALSE;
        }
    }
    return GLFW_TRUE;
}

void _glfwPlatformSetClipboardString(const char* string)
{
    if (!_glfwEnsureDataDevice()) return;
    free(_glfw.wl.clipboardString);
    _glfw.wl.clipboardString = _glfw_strdup(string);
    if (_glfw.wl.dataSourceForClipboard)
        wl_data_source_destroy(_glfw.wl.dataSourceForClipboard);
    _glfw.wl.dataSourceForClipboard = wl_data_device_manager_create_data_source(_glfw.wl.dataDeviceManager);
    if (!_glfw.wl.dataSourceForClipboard)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Cannot copy failed to create data source");
        return;
    }
    wl_data_source_add_listener(_glfw.wl.dataSourceForClipboard, &data_source_listener, NULL);
    wl_data_source_offer(_glfw.wl.dataSourceForClipboard, clipboard_mime());
    wl_data_source_offer(_glfw.wl.dataSourceForClipboard, "text/plain");
    wl_data_source_offer(_glfw.wl.dataSourceForClipboard, "text/plain;charset=utf-8");
    wl_data_source_offer(_glfw.wl.dataSourceForClipboard, "TEXT");
    wl_data_source_offer(_glfw.wl.dataSourceForClipboard, "STRING");
    wl_data_source_offer(_glfw.wl.dataSourceForClipboard, "UTF8_STRING");
    struct wl_callback *callback = wl_display_sync(_glfw.wl.display);
    const static struct wl_callback_listener clipboard_copy_callback_listener = {.done = clipboard_copy_callback_done};
    wl_callback_add_listener(callback, &clipboard_copy_callback_listener, _glfw.wl.dataSourceForClipboard);
}

const char* _glfwPlatformGetClipboardString(void)
{
    for (size_t i = 0; i < arraysz(_glfw.wl.dataOffers); i++) {
        if (_glfw.wl.dataOffers[i].id && _glfw.wl.dataOffers[i].mime && _glfw.wl.dataOffers[i].offer_type == CLIPBOARD) {
            if (_glfw.wl.dataOffers[i].is_self_offer) return _glfw.wl.clipboardString;
            free(_glfw.wl.pasteString);
            _glfw.wl.pasteString = read_data_offer(_glfw.wl.dataOffers[i].id, _glfw.wl.dataOffers[i].mime);
            return _glfw.wl.pasteString;
        }
    }
    return NULL;
}

void _glfwPlatformSetPrimarySelectionString(const char* string)
{
    if (!_glfw.wl.primarySelectionDevice) {
        static GLFWbool warned_about_primary_selection_device = GLFW_FALSE;
        if (!warned_about_primary_selection_device) {
            _glfwInputError(GLFW_PLATFORM_ERROR,
                            "Wayland: Cannot copy no primary selection device available");
            warned_about_primary_selection_device = GLFW_TRUE;
        }
        return;
    }
    if (_glfw.wl.primarySelectionString == string) return;
    free(_glfw.wl.primarySelectionString);
    _glfw.wl.primarySelectionString = _glfw_strdup(string);

    if (_glfw.wl.dataSourceForPrimarySelection)
        zwp_primary_selection_source_v1_destroy(_glfw.wl.dataSourceForPrimarySelection);
    _glfw.wl.dataSourceForPrimarySelection = zwp_primary_selection_device_manager_v1_create_source(_glfw.wl.primarySelectionDeviceManager);
    if (!_glfw.wl.dataSourceForPrimarySelection)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Cannot copy failed to create primary selection source");
        return;
    }
    zwp_primary_selection_source_v1_add_listener(_glfw.wl.dataSourceForPrimarySelection, &primary_selection_source_listener, NULL);
    zwp_primary_selection_source_v1_offer(_glfw.wl.dataSourceForPrimarySelection, clipboard_mime());
    zwp_primary_selection_source_v1_offer(_glfw.wl.dataSourceForPrimarySelection, "text/plain");
    zwp_primary_selection_source_v1_offer(_glfw.wl.dataSourceForPrimarySelection, "text/plain;charset=utf-8");
    zwp_primary_selection_source_v1_offer(_glfw.wl.dataSourceForPrimarySelection, "TEXT");
    zwp_primary_selection_source_v1_offer(_glfw.wl.dataSourceForPrimarySelection, "STRING");
    zwp_primary_selection_source_v1_offer(_glfw.wl.dataSourceForPrimarySelection, "UTF8_STRING");
    struct wl_callback *callback = wl_display_sync(_glfw.wl.display);
    const static struct wl_callback_listener primary_selection_copy_callback_listener = {.done = primary_selection_copy_callback_done};
    wl_callback_add_listener(callback, &primary_selection_copy_callback_listener, _glfw.wl.dataSourceForPrimarySelection);
}

const char* _glfwPlatformGetPrimarySelectionString(void)
{
    if (_glfw.wl.dataSourceForPrimarySelection != NULL) return _glfw.wl.primarySelectionString;

    for (size_t i = 0; i < arraysz(_glfw.wl.primarySelectionOffers); i++) {
        if (_glfw.wl.primarySelectionOffers[i].id && _glfw.wl.primarySelectionOffers[i].mime && _glfw.wl.primarySelectionOffers[i].offer_type == PRIMARY_SELECTION) {
            if (_glfw.wl.primarySelectionOffers[i].is_self_offer) {
                return _glfw.wl.primarySelectionString;
            }
            free(_glfw.wl.pasteString);
            _glfw.wl.pasteString = read_primary_selection_offer(_glfw.wl.primarySelectionOffers[i].id, _glfw.wl.primarySelectionOffers[i].mime);
            return _glfw.wl.pasteString;
        }
    }
    return NULL;
}

void _glfwPlatformGetRequiredInstanceExtensions(char** extensions)
{
    if (!_glfw.vk.KHR_surface || !_glfw.vk.KHR_wayland_surface)
        return;

    extensions[0] = "VK_KHR_surface";
    extensions[1] = "VK_KHR_wayland_surface";
}

int _glfwPlatformGetPhysicalDevicePresentationSupport(VkInstance instance,
                                                      VkPhysicalDevice device,
                                                      uint32_t queuefamily)
{
    PFN_vkGetPhysicalDeviceWaylandPresentationSupportKHR
        vkGetPhysicalDeviceWaylandPresentationSupportKHR =
        (PFN_vkGetPhysicalDeviceWaylandPresentationSupportKHR)
        vkGetInstanceProcAddr(instance, "vkGetPhysicalDeviceWaylandPresentationSupportKHR");
    if (!vkGetPhysicalDeviceWaylandPresentationSupportKHR)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE,
                        "Wayland: Vulkan instance missing VK_KHR_wayland_surface extension");
        return VK_NULL_HANDLE;
    }

    return vkGetPhysicalDeviceWaylandPresentationSupportKHR(device,
                                                            queuefamily,
                                                            _glfw.wl.display);
}

VkResult _glfwPlatformCreateWindowSurface(VkInstance instance,
                                          _GLFWwindow* window,
                                          const VkAllocationCallbacks* allocator,
                                          VkSurfaceKHR* surface)
{
    VkResult err;
    VkWaylandSurfaceCreateInfoKHR sci;
    PFN_vkCreateWaylandSurfaceKHR vkCreateWaylandSurfaceKHR;

    vkCreateWaylandSurfaceKHR = (PFN_vkCreateWaylandSurfaceKHR)
        vkGetInstanceProcAddr(instance, "vkCreateWaylandSurfaceKHR");
    if (!vkCreateWaylandSurfaceKHR)
    {
        _glfwInputError(GLFW_API_UNAVAILABLE,
                        "Wayland: Vulkan instance missing VK_KHR_wayland_surface extension");
        return VK_ERROR_EXTENSION_NOT_PRESENT;
    }

    memset(&sci, 0, sizeof(sci));
    sci.sType = VK_STRUCTURE_TYPE_WAYLAND_SURFACE_CREATE_INFO_KHR;
    sci.display = _glfw.wl.display;
    sci.surface = window->wl.surface;

    err = vkCreateWaylandSurfaceKHR(instance, &sci, allocator, surface);
    if (err)
    {
        _glfwInputError(GLFW_PLATFORM_ERROR,
                        "Wayland: Failed to create Vulkan surface: %s",
                        _glfwGetVulkanResultString(err));
    }

    return err;
}

void
_glfwPlatformUpdateIMEState(_GLFWwindow *w, int which, int a, int b, int c, int d) {
    glfw_xkb_update_ime_state(w, &_glfw.wl.xkb, which, a, b, c, d);
}

static void
frame_handle_redraw(void *data, struct wl_callback *callback, uint32_t time) {
    _GLFWwindow* window = (_GLFWwindow*) data;
    if (callback == window->wl.frameCallbackData.current_wl_callback) {
        window->wl.frameCallbackData.callback(window->wl.frameCallbackData.id);
        window->wl.frameCallbackData.current_wl_callback = NULL;
    }
    wl_callback_destroy(callback);
}

//////////////////////////////////////////////////////////////////////////
//////                        GLFW native API                       //////
//////////////////////////////////////////////////////////////////////////

GLFWAPI struct wl_display* glfwGetWaylandDisplay(void)
{
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    return _glfw.wl.display;
}

GLFWAPI struct wl_surface* glfwGetWaylandWindow(GLFWwindow* handle)
{
    _GLFWwindow* window = (_GLFWwindow*) handle;
    _GLFW_REQUIRE_INIT_OR_RETURN(NULL);
    return window->wl.surface;
}

GLFWAPI int glfwGetXKBScancode(const char* keyName, GLFWbool caseSensitive) {
    return glfw_xkb_keysym_from_name(keyName, caseSensitive);
}

GLFWAPI void glfwRequestWaylandFrameEvent(GLFWwindow *handle, unsigned long long id, void(*callback)(unsigned long long id)) {
    _GLFWwindow* window = (_GLFWwindow*) handle;
    static const struct wl_callback_listener frame_listener = { .done = frame_handle_redraw };
    if (window->wl.frameCallbackData.current_wl_callback) wl_callback_destroy(window->wl.frameCallbackData.current_wl_callback);
    window->wl.frameCallbackData.id = id;
    window->wl.frameCallbackData.callback = callback;
    window->wl.frameCallbackData.current_wl_callback = wl_surface_frame(window->wl.surface);
    if (window->wl.frameCallbackData.current_wl_callback) {
        wl_callback_add_listener(window->wl.frameCallbackData.current_wl_callback, &frame_listener, window);
        wl_surface_commit(window->wl.surface);
    }
}

GLFWAPI unsigned long long glfwDBusUserNotify(const char *app_name, const char* icon, const char *summary, const char *body, const char *action_name, int32_t timeout, GLFWDBusnotificationcreatedfun callback, void *data) {
    return glfw_dbus_send_user_notification(app_name, icon, summary, body, action_name, timeout, callback, data);
}

GLFWAPI void glfwDBusSetUserNotificationHandler(GLFWDBusnotificationactivatedfun handler) {
    glfw_dbus_set_user_notification_activated_handler(handler);
}
