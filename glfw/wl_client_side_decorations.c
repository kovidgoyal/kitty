/*
 * wl_client_side_decorations.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "wl_client_side_decorations.h"

#include "backend_utils.h"
#include <sys/mman.h>
#include <errno.h>
#include <string.h>

#define decs window->wl.decorations

#define ARGB(a, r, g, b) (((a) << 24) | ((r) << 16) | ((g) << 8) | (b))
#define SWAP(x, y) do { __typeof__(x) SWAP = x; x = y; y = SWAP; } while (0)

static const uint32_t passive_bg_color = 0xffeeeeee;
static const uint32_t active_bg_color = 0xffdddad6;

static void
swap_buffers(_GLFWWaylandBufferPair *pair) {
    SWAP(pair->front, pair->back);
    SWAP(pair->data.front, pair->data.back);
}

static size_t
init_buffer_pair(_GLFWWaylandBufferPair *pair, size_t width, size_t height, unsigned scale) {
    memset(pair, 0, sizeof(_GLFWWaylandBufferPair));
    pair->width = width * scale;
    pair->height = height * scale;
    pair->stride = 4 * pair->width;
    pair->size_in_bytes = pair->stride * pair->height;
    return 2 * pair->size_in_bytes;
}

static void
alloc_buffer_pair(_GLFWWaylandBufferPair *pair, struct wl_shm_pool *pool, uint8_t *data, size_t *offset) {
    pair->data.a = data + *offset;
    pair->a = wl_shm_pool_create_buffer(pool, *offset, pair->width, pair->height, pair->stride, WL_SHM_FORMAT_ARGB8888);
    *offset += pair->size_in_bytes;
    pair->data.b = data + *offset;
    pair->b = wl_shm_pool_create_buffer(pool, *offset, pair->width, pair->height, pair->stride, WL_SHM_FORMAT_ARGB8888);
    *offset += pair->size_in_bytes;
    pair->front = pair->a; pair->back = pair->b;
    pair->data.front = pair->data.a; pair->data.back = pair->data.b;
}

static void
render_title_bar(_GLFWwindow *window, bool to_front_buffer) {
    const bool is_focused = window->id == _glfw.focusedWindowId;
    uint32_t bg_color = is_focused ? active_bg_color : passive_bg_color;
    uint8_t *output = to_front_buffer ? decs.top.buffer.data.front : decs.top.buffer.data.back;
    if (window->wl.title && window->wl.title[0] && _glfw.callbacks.draw_text) {
        uint32_t fg_color = is_focused ? 0xff444444 : 0xff888888;
        if (_glfw.callbacks.draw_text((GLFWwindow*)window, window->wl.title, fg_color, bg_color, output, decs.top.buffer.width, decs.top.buffer.height, 10, 0)) return;
    }
    for (uint32_t *px = (uint32_t*)output, *end = (uint32_t*)(output + decs.top.buffer.size_in_bytes); px < end; px++) {
        *px = bg_color;
    }
}

static void
update_title_bar(_GLFWwindow *window) {
    render_title_bar(window, false);
    swap_buffers(&decs.top.buffer);
}

static void
render_edge(_GLFWWaylandBufferPair *pair) {
    for (uint32_t *px = (uint32_t*)pair->data.front, *end = (uint32_t*)(pair->data.front + pair->size_in_bytes); px < end; px++) {
        *px = active_bg_color;
    }
    for (uint32_t *px = (uint32_t*)pair->data.back, *end = (uint32_t*)(pair->data.back + pair->size_in_bytes); px < end; px++) {
        *px = passive_bg_color;
    }
}

static bool
create_shm_buffers(_GLFWwindow* window) {
    int scale = window->wl.scale;
    if (scale < 1) scale = 1;

    const size_t vertical_width = decs.metrics.width, vertical_height = window->wl.height + decs.metrics.top;
    const size_t horizontal_height = decs.metrics.width, horizontal_width = window->wl.width + 2 * decs.metrics.width;

    decs.mapping.size = 0;
    decs.mapping.size += init_buffer_pair(&decs.top.buffer, window->wl.width, decs.metrics.top, scale);
    decs.mapping.size += init_buffer_pair(&decs.left.buffer, vertical_width, vertical_height, scale);
    decs.mapping.size += init_buffer_pair(&decs.bottom.buffer, horizontal_width, horizontal_height, scale);
    decs.mapping.size += init_buffer_pair(&decs.right.buffer, vertical_width, vertical_height, scale);

    int fd = createAnonymousFile(decs.mapping.size);
    if (fd < 0) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: Creating a buffer file for %zu B failed: %s",
                        decs.mapping.size, strerror(errno));
        return false;
    }
    decs.mapping.data = mmap(NULL, decs.mapping.size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (decs.mapping.data == MAP_FAILED) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland: mmap failed: %s", strerror(errno));
        close(fd);
        return false;
    }
    struct wl_shm_pool* pool = wl_shm_create_pool(_glfw.wl.shm, fd, decs.mapping.size);
    close(fd);
    size_t offset = 0;
#define a(which) alloc_buffer_pair(&decs.which.buffer, pool, decs.mapping.data, &offset)
    a(top); a(left); a(bottom); a(right);
#undef a
    wl_shm_pool_destroy(pool);
    render_title_bar(window, true);
    render_edge(&decs.left.buffer); render_edge(&decs.bottom.buffer); render_edge(&decs.right.buffer);
    return true;
}

void
free_csd_surfaces(_GLFWwindow *window) {
#define d(which) {\
    if (decs.which.subsurface) wl_subsurface_destroy(decs.which.subsurface); decs.which.subsurface = NULL; \
    if (decs.which.surface) wl_surface_destroy(decs.which.surface); decs.which.surface = NULL; \
}
    d(left); d(top); d(right); d(bottom);
#undef d
}

static void
free_csd_buffers(_GLFWwindow *window) {
#define d(which) { \
    if (decs.which.buffer.a) wl_buffer_destroy(decs.which.buffer.a); \
    if (decs.which.buffer.b) wl_buffer_destroy(decs.which.buffer.b); \
    memset(&decs.which.buffer, 0, sizeof(_GLFWWaylandBufferPair)); \
}
    d(left); d(top); d(right); d(bottom);
#undef d
    if (decs.mapping.data) munmap(decs.mapping.data, decs.mapping.size);
    decs.mapping.data = NULL; decs.mapping.size = 0;
}

static void
position_csd_surface(_GLFWWaylandCSDEdge *s, int x, int y, int scale) {
    wl_surface_set_buffer_scale(s->surface, scale);
    s->x = x; s->y = y;
    wl_subsurface_set_position(s->subsurface, s->x, s->y);
}

static void
create_csd_surfaces(_GLFWwindow *window, _GLFWWaylandCSDEdge *s) {
    s->surface = wl_compositor_create_surface(_glfw.wl.compositor);
    s->subsurface = wl_subcompositor_get_subsurface(_glfw.wl.subcompositor, s->surface, window->wl.surface);
}

#define damage_csd(which, xbuffer) \
    wl_surface_attach(decs.which.surface, xbuffer, 0, 0); \
    wl_surface_damage(decs.which.surface, 0, 0, decs.which.buffer.width, decs.which.buffer.height); \
    wl_surface_commit(decs.which.surface)

bool
ensure_csd_resources(_GLFWwindow *window) {
    const bool is_focused = window->id == _glfw.focusedWindowId;
    const bool focus_changed = is_focused != decs.for_window_state.focused;
    const bool size_changed = (
        decs.for_window_state.width != window->wl.width ||
        decs.for_window_state.height != window->wl.height ||
        decs.for_window_state.scale != window->wl.scale ||
        !decs.mapping.data
    );
    const bool needs_update = focus_changed || size_changed || !decs.left.surface;
    if (!needs_update) return false;
    if (size_changed) {
        free_csd_buffers(window);
        if (!create_shm_buffers(window)) return false;
    }

    int x, y, scale = window->wl.scale < 1 ? 1 : window->wl.scale;
    x = 0; y = -decs.metrics.top;
    if (!decs.top.surface) create_csd_surfaces(window, &decs.top);
    position_csd_surface(&decs.top, x, y, scale);

    x = -decs.metrics.width; y = -decs.metrics.top;
    if (!decs.left.surface) create_csd_surfaces(window, &decs.left);
    position_csd_surface(&decs.left, x, y, scale);

    x = -decs.metrics.width; y = window->wl.height;
    if (!decs.bottom.surface) create_csd_surfaces(window, &decs.bottom);
    position_csd_surface(&decs.bottom, x, y, scale);

    x = window->wl.width; y = -decs.metrics.top;
    if (!decs.right.surface) create_csd_surfaces(window, &decs.right);
    position_csd_surface(&decs.right, x, y, scale);

    if (focus_changed) update_title_bar(window);
    damage_csd(top, decs.top.buffer.front);
    damage_csd(left, is_focused ? decs.left.buffer.front : decs.left.buffer.back);
    damage_csd(bottom, is_focused ? decs.bottom.buffer.front : decs.bottom.buffer.back);
    damage_csd(right, is_focused ? decs.right.buffer.front : decs.right.buffer.back);

    decs.for_window_state.width = window->wl.width;
    decs.for_window_state.height = window->wl.height;
    decs.for_window_state.scale = window->wl.scale;
    decs.for_window_state.focused = is_focused;
    return true;
}

void
free_all_csd_resources(_GLFWwindow *window) {
    free_csd_surfaces(window);
    free_csd_buffers(window);
}

void
resize_csd(_GLFWwindow *window) {
    ensure_csd_resources(window);
}

void
change_csd_title(_GLFWwindow *window) {
    if (ensure_csd_resources(window)) return;  // CSD were re-rendered for other reasons
    if (decs.top.surface) {
        update_title_bar(window);
        damage_csd(top, decs.top.buffer.front);
    }
}
