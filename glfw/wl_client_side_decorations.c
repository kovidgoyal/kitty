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
#include <stdlib.h>

#define decs window->wl.decorations

#define ARGB(a, r, g, b) (((a) << 24) | ((r) << 16) | ((g) << 8) | (b))
#define A(x) (((x) >> 24) & 0xff)
#define R(x) (((x) >> 16) & 0xff)
#define G(x) (((x) >> 8) & 0xff)
#define B(x) ((x) & 0xff)
#define SWAP(x, y) do { __typeof__(x) SWAP = x; x = y; y = SWAP; } while (0)

typedef float kernel_type;

static void
build_blur_kernel(kernel_type *blur_kernel, const size_t size, kernel_type sigma) {
    // 1D Normalized Gaussian
    const kernel_type half = size / (kernel_type)2;
    kernel_type sum = 0;
    for (size_t i = 0; i < size; i++) {
        kernel_type f = (i - half);
        blur_kernel[i] = (kernel_type)exp(- f * f / sigma);
        sum += blur_kernel[i];
    }
    for (size_t i = 0; i < size; i++) blur_kernel[i] /= sum;
}

static void
blur_mask(kernel_type *image_data, ssize_t width, ssize_t height, ssize_t kernel_size, kernel_type sigma, kernel_type *scratch, kernel_type *blur_kernel, ssize_t margin) {
    (void)margin;
    build_blur_kernel(blur_kernel, kernel_size, sigma);
    const size_t half = kernel_size / 2;

    for (ssize_t y = 0; y < height; y++) {
        kernel_type *s = image_data + y * width, *d = scratch + y * width;
        for (ssize_t x = 0; x < width; x++) {
            kernel_type a = 0;
            for (ssize_t k = 0; k < kernel_size; k++) {
                const ssize_t px = x + k - half;
                if (0 <= px && px < width) a += s[px] * blur_kernel[k];
            }
            d[x] = a;
        }
    }

    for (ssize_t y = 0; y < height; y++) {
        kernel_type *d = image_data + y * width;
        for (ssize_t x = 0; x < width; x++) {
            kernel_type a = 0;
            for (ssize_t k = 0; k < kernel_size; k++) {
                const ssize_t py = y + k - half;
                if (0 <= py && py < height) {
                    kernel_type *s = scratch + py * width;
                    a += s[x] * blur_kernel[k];
                }
            }
            d[x] = a;
        }
    }
}

static kernel_type*
create_shadow_mask(size_t width, size_t height, size_t margin, size_t kernel_size, kernel_type base_alpha, kernel_type sigma) {
    kernel_type *mask = calloc(2 * width * height + kernel_size, sizeof(kernel_type));
    if (!mask) return NULL;
    for (size_t y = margin; y < height - margin; y++) {
        kernel_type *row = mask + y * width;
        for (size_t x = margin; x < width - margin; x++) row[x] = base_alpha;
    }
    blur_mask(mask, width, height, kernel_size, sigma, mask + width * height, (kernel_type*)(mask + 2 * width * height), margin);
    return mask;
}

static void
swap_buffers(_GLFWWaylandBufferPair *pair) {
    SWAP(pair->front, pair->back);
    SWAP(pair->data.front, pair->data.back);
}

static size_t
init_buffer_pair(_GLFWWaylandBufferPair *pair, size_t width, size_t height, float scale) {
    memset(pair, 0, sizeof(_GLFWWaylandBufferPair));
    pair->width = (int)roundf(width * scale);
    pair->height = (int)roundf(height * scale);
    pair->viewport_width = width; pair->viewport_height = height;
    pair->stride = 4 * pair->width;
    pair->size_in_bytes = pair->stride * pair->height;
    return 2 * pair->size_in_bytes;
}

static bool
window_has_buffer(_GLFWwindow *window, struct wl_buffer *q) {
#define Q(which) if (decs.which.buffer.a == q) { decs.which.buffer.a_needs_to_be_destroyed = false; return true; } if (decs.which.buffer.b == q) { decs.which.buffer.b_needs_to_be_destroyed = false; return true; }
    Q(left); Q(top); Q(right); Q(bottom);
#undef Q
    return false;
}

static void
buffer_release_event(void *data, struct wl_buffer *buffer) {
    wl_buffer_destroy(buffer);
    _GLFWwindow *window = _glfwWindowForId((uintptr_t)data);
    if (window && window_has_buffer(window, buffer)) decs.buffer_destroyed = true;
}

static struct wl_buffer_listener handle_buffer_events = {.release = buffer_release_event};

static void
alloc_buffer_pair(uintptr_t window_id, _GLFWWaylandBufferPair *pair, struct wl_shm_pool *pool, uint8_t *data, size_t *offset) {
    pair->data.a = data + *offset;
    pair->a = wl_shm_pool_create_buffer(pool, *offset, pair->width, pair->height, pair->stride, WL_SHM_FORMAT_ARGB8888);
    pair->a_needs_to_be_destroyed = true;
    wl_buffer_add_listener(pair->a, &handle_buffer_events, (void*)window_id);
    *offset += pair->size_in_bytes;
    pair->data.b = data + *offset;
    pair->b = wl_shm_pool_create_buffer(pool, *offset, pair->width, pair->height, pair->stride, WL_SHM_FORMAT_ARGB8888);
    pair->b_needs_to_be_destroyed = true;
    wl_buffer_add_listener(pair->b, &handle_buffer_events, (void*)window_id);
    *offset += pair->size_in_bytes;
    pair->front = pair->a; pair->back = pair->b;
    pair->data.front = pair->data.a; pair->data.back = pair->data.b;
}

#define st decs.shadow_tile

void
csd_initialize_metrics(_GLFWwindow *window) {
    decs.metrics.width = 12;
    decs.metrics.top = 36;
    decs.metrics.visible_titlebar_height = decs.metrics.top - decs.metrics.width;
    decs.metrics.horizontal = 2 * decs.metrics.width;
    decs.metrics.vertical = decs.metrics.width + decs.metrics.top;
}

static size_t
create_shadow_tile(_GLFWwindow *window) {
    const size_t margin = decs.bottom.buffer.height;
    if (st.data && st.for_decoration_size == margin) return margin;
    st.for_decoration_size = margin;
    free(st.data);
    st.segments = 7;
    st.stride = st.segments * margin;
    st.corner_size = margin * (st.segments - 1) / 2;
    kernel_type* mask = create_shadow_mask(st.stride, st.stride, margin, 2 * margin + 1, (kernel_type)0.7, 32 * margin);
    st.data = malloc(sizeof(uint32_t) * st.stride * st.stride);
    if (st.data) for (size_t i = 0; i < st.stride * st.stride; i++) st.data[i] = ((uint8_t)(mask[i] * 255)) << 24;
    free(mask);
    return margin;
}


static void
render_title_bar(_GLFWwindow *window, bool to_front_buffer) {
    const bool is_focused = window->id == _glfw.focusedWindowId;
    const uint32_t light_fg = is_focused ? 0xff444444 : 0xff888888, light_bg = is_focused ? 0xffdddad6 : 0xffeeeeee;
    const uint32_t dark_fg = is_focused ? 0xffffffff : 0xffcccccc, dark_bg = is_focused ? 0xff303030 : 0xff242424;
    static const uint32_t hover_dark_bg = 0xff444444, hover_light_bg = 0xffbbbbbb;
    uint32_t bg_color = light_bg, fg_color = light_fg, hover_bg = hover_light_bg;
    GLFWColorScheme appearance = glfwGetCurrentSystemColorTheme();
    bool is_dark = false;
    if (decs.use_custom_titlebar_color || appearance == GLFW_COLOR_SCHEME_NO_PREFERENCE) {
        bg_color = 0xff000000 | (decs.titlebar_color & 0xffffff);
        double red = ((bg_color >> 16) & 0xFF) / 255.0;
        double green = ((bg_color >> 8) & 0xFF) / 255.0;
        double blue = (bg_color & 0xFF) / 255.0;
        double luma = 0.2126 * red + 0.7152 * green + 0.0722 * blue;
        if (luma < 0.5) { fg_color = dark_fg; hover_bg = hover_dark_bg; is_dark = true; }
        if (!decs.use_custom_titlebar_color) bg_color = luma < 0.5 ? dark_bg : light_bg;
    } else if (appearance == GLFW_COLOR_SCHEME_DARK) { bg_color = dark_bg; fg_color = dark_fg; hover_bg = hover_dark_bg; is_dark = true; }
    uint8_t *output = to_front_buffer ? decs.top.buffer.data.front : decs.top.buffer.data.back;

    // render shadow part
    const size_t margin = create_shadow_tile(window);
    const size_t edge_segment_size = st.corner_size - margin;
    const uint8_t divisor = is_focused ? 1 : 2;
    for (size_t y = 0; y < margin; y++) {
        // left segment
        uint32_t *s = st.data + y * st.stride + margin;
        uint32_t *d = (uint32_t*)(output + y * decs.top.buffer.stride);
        for (size_t x = 0; x < edge_segment_size; x++) d[x] = (A(s[x]) / divisor) << 24;
        // middle segment
        s += edge_segment_size;
        size_t limit = decs.top.buffer.width > edge_segment_size ? decs.top.buffer.width - edge_segment_size : 0;
        for (size_t x = edge_segment_size, sx = 0; x < limit; x++, sx = (sx + 1) % margin) d[x] = (A(s[sx]) / divisor) << 24;
        // right segment
        s += margin;
        for (size_t x = limit; x < decs.top.buffer.width; x++, s++) d[x] = (A(*s) / divisor) << 24;
    }

    // render text part
    int button_size = (int)roundf(decs.metrics.visible_titlebar_height * decs.for_window_state.fscale);
    int num_buttons = 1;
    if (window->wl.wm_capabilities.maximize) num_buttons++;
    if (window->wl.wm_capabilities.minimize) num_buttons++;
    output += decs.top.buffer.stride * margin;
    if (window->wl.title && window->wl.title[0] && _glfw.callbacks.draw_text) {
        if (_glfw.callbacks.draw_text((GLFWwindow*)window, window->wl.title, fg_color, bg_color, output, decs.top.buffer.width, decs.top.buffer.height - margin, 0, 0, num_buttons * button_size, false)) goto render_buttons;
    }
    // rendering of text failed, blank the buffer
    for (uint32_t *px = (uint32_t*)output, *end = (uint32_t*)(output + decs.top.buffer.size_in_bytes); px < end; px++) *px = bg_color;

render_buttons:
    decs.maximize.width = 0; decs.minimize.width = 0; decs.close.width = 0;
    if (!button_size) return;
    int left = decs.top.buffer.width - num_buttons * button_size;
#define draw(which, text, hover_bg) { \
    _glfw.callbacks.draw_text((GLFWwindow*)window, text, fg_color, decs.which.hovered ? hover_bg : bg_color, output, decs.top.buffer.width, \
            decs.top.buffer.height - margin, /*x=*/left, /*y=*/0, /*right_margin=*/decs.top.buffer.width - left - button_size, true); \
    decs.which.left = left; decs.which.width = button_size; left += button_size; \
}
    if (window->wl.wm_capabilities.minimize) draw(minimize, "🗕", hover_bg);
    if (window->wl.wm_capabilities.maximize) draw(maximize, "🗖", hover_bg);
    draw(close, "🗙", is_dark ? 0xff880000: 0xffc80000);
#undef draw
}

static void
update_title_bar(_GLFWwindow *window) {
    render_title_bar(window, false);
    swap_buffers(&decs.top.buffer);
}

static void
render_edges(_GLFWwindow *window) {
    const size_t margin = create_shadow_tile(window);
    if (!st.data) return;  // out of memory

    // bottom edge
    uint32_t *src = st.data + (st.segments - 1) * margin * st.stride;
    for (size_t y = 0; y < margin; y++) {
        uint32_t *d = (uint32_t*)(decs.bottom.buffer.data.front + y * decs.bottom.buffer.stride);
        uint32_t *s = src + st.stride * y;
        // left corner
        for (size_t x = 0; x < st.corner_size && x < decs.bottom.buffer.width; x++) d[x] = s[x];
        // middle
        size_t pos = st.corner_size, limit = decs.bottom.buffer.width > st.corner_size ? decs.bottom.buffer.width - st.corner_size : 0;
        s += st.corner_size;
        while (pos < limit) {
            uint32_t *p = d + pos;
            for (size_t x = 0; x < margin && pos + x < limit; x++) p[x] = s[x];
            pos += margin;
        }
        // right corner
        s += margin;
        for (size_t x = 0; x < st.corner_size && limit + x < decs.bottom.buffer.width; x++) d[limit + x] = s[x];
    }

    // upper corners
    for (size_t y = 0; y < st.corner_size && y < decs.left.buffer.height; y++) {
        uint32_t *left_src = st.data + st.stride * y;
        uint32_t *left_dest = (uint32_t*)(decs.left.buffer.data.front + y * decs.left.buffer.stride);
        memcpy(left_dest, left_src, margin * sizeof(uint32_t));
        uint32_t *right_src = left_src + 2 * st.corner_size;
        uint32_t *right_dest = (uint32_t*)(decs.right.buffer.data.front + y * decs.right.buffer.stride);
        memcpy(right_dest, right_src, margin * sizeof(uint32_t));
    }

    // lower corners
    size_t src_height = st.corner_size - margin;
    size_t dest_top = decs.left.buffer.height > src_height ? decs.left.buffer.height - src_height : 0;
    size_t src_top = st.corner_size + margin;
    for (size_t src_y = src_top, dest_y = dest_top; src_y < src_top + src_height && dest_y < decs.left.buffer.height; src_y++, dest_y++) {
        uint32_t *s = st.data + st.stride * src_y;
        uint32_t *d = (uint32_t*)(decs.left.buffer.data.front + dest_y * decs.left.buffer.stride);
        memcpy(d, s, margin * sizeof(uint32_t));
        s += 2 * st.corner_size;
        d = (uint32_t*)(decs.right.buffer.data.front + dest_y * decs.left.buffer.stride);
        memcpy(d, s, margin * sizeof(uint32_t));
    }

    // sides
    size_t limit = decs.left.buffer.height > src_height ? decs.left.buffer.height - src_height : 0;
    for (size_t dest_y = st.corner_size, src_y = 0; dest_y < limit; dest_y++, src_y = (src_y + 1) % margin) {
        uint32_t *src = st.data + (st.corner_size + src_y) * st.stride;
        uint32_t *left_dest = (uint32_t*)(decs.left.buffer.data.front + dest_y * decs.left.buffer.stride);
        memcpy(left_dest, src, margin * sizeof(uint32_t));
        src += 2 * st.corner_size;
        uint32_t *right_dest = (uint32_t*)(decs.right.buffer.data.front + dest_y * decs.right.buffer.stride);
        memcpy(right_dest, src, margin * sizeof(uint32_t));
    }

#define copy(which) for (uint32_t *src = (uint32_t*)decs.which.buffer.data.front, *dest = (uint32_t*)decs.which.buffer.data.back; src < (uint32_t*)(decs.which.buffer.data.front + decs.which.buffer.size_in_bytes); src++, dest++) *dest = (A(*src) / 2 ) << 24;
    copy(left); copy(bottom); copy(right);
#undef copy

}
#undef st

static bool
create_shm_buffers(_GLFWwindow* window) {
    const float scale = _glfwWaylandWindowScale(window);

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
#define a(which) alloc_buffer_pair(window->id, &decs.which.buffer, pool, decs.mapping.data, &offset)
    a(top); a(left); a(bottom); a(right);
#undef a
    wl_shm_pool_destroy(pool);
    create_shadow_tile(window);
    render_title_bar(window, true);
    render_edges(window);
    debug("Created decoration buffers at scale: %f vertical_height: %zu horizontal_width: %zu\n", scale, vertical_height, horizontal_width);
    return true;
}

static void
free_csd_surfaces(_GLFWwindow *window) {
#define d(which) {\
    if (decs.which.subsurface) wl_subsurface_destroy(decs.which.subsurface); \
    decs.which.subsurface = NULL; \
    if (decs.which.surface) wl_surface_destroy(decs.which.surface); \
    decs.which.surface = NULL; \
    if (decs.which.wp_viewport) wp_viewport_destroy(decs.which.wp_viewport); \
    decs.which.wp_viewport = NULL; \
}
    d(left); d(top); d(right); d(bottom);
#undef d
}

static void
free_csd_buffers(_GLFWwindow *window) {
#define d(which) { \
    if (decs.which.buffer.a_needs_to_be_destroyed && decs.which.buffer.a) wl_buffer_destroy(decs.which.buffer.a); \
    if (decs.which.buffer.b_needs_to_be_destroyed && decs.which.buffer.b) wl_buffer_destroy(decs.which.buffer.b); \
    memset(&decs.which.buffer, 0, sizeof(_GLFWWaylandBufferPair)); \
}
    d(left); d(top); d(right); d(bottom);
#undef d
    if (decs.mapping.data) munmap(decs.mapping.data, decs.mapping.size);
    decs.mapping.data = NULL; decs.mapping.size = 0;
}

static void
position_csd_surface(_GLFWWaylandCSDEdge *s, int x, int y) {
    wl_surface_set_buffer_scale(s->surface, 1);
    s->x = x; s->y = y;
    wl_subsurface_set_position(s->subsurface, s->x, s->y);
}

static void
create_csd_surfaces(_GLFWwindow *window, _GLFWWaylandCSDEdge *s) {
    s->surface = wl_compositor_create_surface(_glfw.wl.compositor);
    s->subsurface = wl_subcompositor_get_subsurface(_glfw.wl.subcompositor, s->surface, window->wl.surface);
    if (_glfw.wl.wp_viewporter) s->wp_viewport = wp_viewporter_get_viewport(_glfw.wl.wp_viewporter, s->surface);
}

#define damage_csd(which, xbuffer) \
    wl_surface_attach(decs.which.surface, (xbuffer), 0, 0); \
    if (decs.which.wp_viewport) wp_viewport_set_destination(decs.which.wp_viewport, decs.which.buffer.viewport_width, decs.which.buffer.viewport_height); \
    wl_surface_damage(decs.which.surface, 0, 0, decs.which.buffer.width, decs.which.buffer.height); \
    wl_surface_commit(decs.which.surface); \
    if (decs.which.buffer.a == (xbuffer)) { decs.which.buffer.a_needs_to_be_destroyed = false; } else { decs.which.buffer.b_needs_to_be_destroyed = false; }

static bool
window_is_csd_capable(_GLFWwindow *window) {
    return window->decorated && !decs.serverSide && window->wl.xdg.toplevel;
}

static bool
ensure_csd_resources(_GLFWwindow *window) {
    if (!window_is_csd_capable(window)) return false;
    const bool is_focused = window->id == _glfw.focusedWindowId;
    const bool focus_changed = is_focused != decs.for_window_state.focused;
    const bool size_changed = (
        decs.for_window_state.width != window->wl.width ||
        decs.for_window_state.height != window->wl.height ||
        decs.for_window_state.fscale != _glfwWaylandWindowScale(window) ||
        !decs.mapping.data
    );
    const bool needs_update = focus_changed || size_changed || !decs.left.surface || decs.buffer_destroyed;
    debug("CSD: old.size: %dx%d new.size: %dx%d needs_update: %d size_changed: %d buffer_destroyed: %d\n",
            decs.for_window_state.width, decs.for_window_state.height, window->wl.width, window->wl.height, needs_update, size_changed, decs.buffer_destroyed);
    if (!needs_update) return false;
    if (size_changed || decs.buffer_destroyed) {
        free_csd_buffers(window);
        if (!create_shm_buffers(window)) return false;
        decs.buffer_destroyed = false;
    }

    int32_t x, y;
    x = 0; y = -decs.metrics.top;
    if (!decs.top.surface) create_csd_surfaces(window, &decs.top);
    position_csd_surface(&decs.top, x, y);

    x = -decs.metrics.width; y = -decs.metrics.top;
    if (!decs.left.surface) create_csd_surfaces(window, &decs.left);
    position_csd_surface(&decs.left, x, y);

    x = -decs.metrics.width; y = window->wl.height;
    if (!decs.bottom.surface) create_csd_surfaces(window, &decs.bottom);
    position_csd_surface(&decs.bottom, x, y);

    x = window->wl.width; y = -decs.metrics.top;
    if (!decs.right.surface) create_csd_surfaces(window, &decs.right);
    position_csd_surface(&decs.right, x, y);

    if (focus_changed) update_title_bar(window);
    damage_csd(top, decs.top.buffer.front);
    damage_csd(left, is_focused ? decs.left.buffer.front : decs.left.buffer.back);
    damage_csd(bottom, is_focused ? decs.bottom.buffer.front : decs.bottom.buffer.back);
    damage_csd(right, is_focused ? decs.right.buffer.front : decs.right.buffer.back);

    decs.for_window_state.width = window->wl.width;
    decs.for_window_state.height = window->wl.height;
    decs.for_window_state.fscale = _glfwWaylandWindowScale(window);
    decs.for_window_state.focused = is_focused;
    return true;
}

void
csd_set_visible(_GLFWwindow *window, bool visible) {
    // When setting to visible will only take effect if window currently has
    // CSD and will also ensure CSD is of correct size for current window size.
    // When hiding CSD simply destroys all CSD surfaces.
    if (visible) ensure_csd_resources(window); else free_csd_surfaces(window);
}

void
csd_free_all_resources(_GLFWwindow *window) {
    free_csd_surfaces(window);
    free_csd_buffers(window);
    if (decs.shadow_tile.data) free(decs.shadow_tile.data);
    decs.shadow_tile.data = NULL;
}

bool
csd_change_title(_GLFWwindow *window) {
    if (!window_is_csd_capable(window)) return false;
    if (ensure_csd_resources(window)) return true;  // CSD were re-rendered for other reasons
    if (decs.top.surface) {
        update_title_bar(window);
        damage_csd(top, decs.top.buffer.front);
        return true;
    }
    return false;
}

void
csd_set_window_geometry(_GLFWwindow *window, int32_t *width, int32_t *height) {
    bool has_csd = window_is_csd_capable(window) && decs.top.surface && !(window->wl.current.toplevel_states & TOPLEVEL_STATE_FULLSCREEN);
    bool size_specified_by_compositor = *width > 0 && *height > 0;
    if (!size_specified_by_compositor) {
        *width = window->wl.user_requested_content_size.width;
        *height = window->wl.user_requested_content_size.height;
        if (window->wl.xdg.top_level_bounds.width > 0) *width = MIN(*width, window->wl.xdg.top_level_bounds.width);
        if (window->wl.xdg.top_level_bounds.height > 0) *height = MIN(*height, window->wl.xdg.top_level_bounds.height);
        if (has_csd) *height += decs.metrics.visible_titlebar_height;
    }
    decs.geometry.x = 0; decs.geometry.y = 0;
    decs.geometry.width = *width; decs.geometry.height = *height;
    if (has_csd) {
        decs.geometry.y = -decs.metrics.visible_titlebar_height;
        *height -= decs.metrics.visible_titlebar_height;
    }
}

bool
csd_set_titlebar_color(_GLFWwindow *window, uint32_t color, bool use_system_color) {
    bool use_custom_color = !use_system_color;
    decs.use_custom_titlebar_color = use_custom_color;
    decs.titlebar_color = color;
    return csd_change_title(window);
}

#define x window->wl.allCursorPosX
#define y window->wl.allCursorPosY

static void
set_cursor(GLFWCursorShape shape, _GLFWwindow* window)
{
    if (_glfw.wl.wp_cursor_shape_device_v1) {
        wayland_cursor_shape s = glfw_cursor_shape_to_wayland_cursor_shape(shape);
        if (s.which > -1) {
            debug("Changing cursor shape to: %s with serial: %u\n", s.name, _glfw.wl.pointer_enter_serial);
            wp_cursor_shape_device_v1_set_shape(_glfw.wl.wp_cursor_shape_device_v1, _glfw.wl.pointer_enter_serial, (uint32_t)s.which);
            return;
        }
    }

    struct wl_buffer* buffer;
    struct wl_cursor* cursor;
    struct wl_cursor_image* image;
    struct wl_surface* surface = _glfw.wl.cursorSurface;
    const int scale = _glfwWaylandIntegerWindowScale(window);

    struct wl_cursor_theme *theme = glfw_wlc_theme_for_scale(scale);
    if (!theme) return;
    cursor = _glfwLoadCursor(shape, theme);
    if (!cursor) return;
    image = cursor->images[0];
    if (!image) return;
    if (image->width % scale || image->height % scale) {
        static uint32_t warned_width = 0, warned_height = 0;
        if (warned_width != image->width || warned_height != image->height) {
            _glfwInputError(GLFW_PLATFORM_ERROR, "WARNING: Cursor image size: %dx%d is not a multiple of window scale: %d. This will"
                    " cause some compositors such as GNOME to crash. See https://github.com/kovidgoyal/kitty/issues/4878", image->width, image->height, scale);
            warned_width = image->width; warned_height = image->height;
        }
    }

    buffer = wl_cursor_image_get_buffer(image);
    if (!buffer) return;
    debug("Calling wl_pointer_set_cursor in set_cursor with surface: %p\n", (void*)surface);
    wl_pointer_set_cursor(_glfw.wl.pointer, _glfw.wl.serial,
                          surface,
                          image->hotspot_x / scale,
                          image->hotspot_y / scale);
    wl_surface_set_buffer_scale(surface, scale);
    wl_surface_attach(surface, buffer, 0, 0);
    wl_surface_damage(surface, 0, 0,
                      image->width, image->height);
    wl_surface_commit(surface);
    _glfw.wl.cursorPreviousShape = shape;
}


static bool
update_hovered_button(_GLFWwindow *window) {
    bool has_hovered_button = false;
    if (y >= decs.metrics.width) {
        int scaled_x = (int)round(decs.for_window_state.fscale * x);
#define c(which) \
        if (decs.which.left <= scaled_x && scaled_x < decs.which.left + decs.which.width) { \
            has_hovered_button = true; \
            if (!decs.which.hovered) { decs.titlebar_needs_update = true; decs.which.hovered = true; } \
        } else if (decs.which.hovered) { decs.titlebar_needs_update = true; decs.which.hovered = false; }

        c(minimize); c(maximize); c(close);
#undef c
    }
    update_title_bar(window);
    return has_hovered_button;
}

static bool
has_hovered_button(_GLFWwindow *window) {
    return decs.minimize.hovered || decs.maximize.hovered || decs.close.hovered;
}

static void
handle_pointer_leave(_GLFWwindow *window) {
#define c(which) if (decs.which.hovered) { decs.titlebar_needs_update = true; decs.which.hovered = false; }
    if (decs.focus == TOP_DECORATION) {
        c(minimize); c(maximize); c(close);
    }
#undef c
    decs.focus = CENTRAL_WINDOW;
}


static void
handle_pointer_move(_GLFWwindow *window) {
    GLFWCursorShape cursorShape = GLFW_DEFAULT_CURSOR;
    switch (decs.focus)
    {
        case CENTRAL_WINDOW: break;
        case TOP_DECORATION:
            if (update_hovered_button(window)) {
                cursorShape = GLFW_POINTER_CURSOR;
            } else if (y < decs.metrics.width) cursorShape = GLFW_N_RESIZE_CURSOR;
            break;
        case LEFT_DECORATION:
            if (y < decs.metrics.width)
                cursorShape = GLFW_NW_RESIZE_CURSOR;
            else
                cursorShape = GLFW_W_RESIZE_CURSOR;
            break;
        case RIGHT_DECORATION:
            if (y < decs.metrics.width)
                cursorShape = GLFW_NE_RESIZE_CURSOR;
            else
                cursorShape = GLFW_E_RESIZE_CURSOR;
            break;
        case BOTTOM_DECORATION:
            if (x < decs.metrics.width)
                cursorShape = GLFW_SW_RESIZE_CURSOR;
            else if (x > window->wl.width + decs.metrics.width)
                cursorShape = GLFW_SE_RESIZE_CURSOR;
            else
                cursorShape = GLFW_S_RESIZE_CURSOR;
            break;
    }
    if (_glfw.wl.cursorPreviousShape != cursorShape) set_cursor(cursorShape, window);
}

static void
handle_pointer_enter(_GLFWwindow *window) {
    handle_pointer_move(window); // enter is also a move
}

static void
handle_pointer_button(_GLFWwindow *window, uint32_t button, uint32_t state) {
    uint32_t edges = XDG_TOPLEVEL_RESIZE_EDGE_NONE;
    if (button == BTN_LEFT) {
        switch (decs.focus) {
            case CENTRAL_WINDOW: break;
            case TOP_DECORATION:
                if (state == WL_POINTER_BUTTON_STATE_PRESSED) {
                    monotonic_t last_click_at = decs.last_click_on_top_decoration_at;
                    decs.last_click_on_top_decoration_at = monotonic();
                    if (decs.last_click_on_top_decoration_at - last_click_at <= _glfwPlatformGetDoubleClickInterval(window)) {
                        decs.last_click_on_top_decoration_at = 0;
                        if (window->wl.current.toplevel_states & TOPLEVEL_STATE_MAXIMIZED) _glfwPlatformRestoreWindow(window);
                        else _glfwPlatformMaximizeWindow(window);
                        return;
                    }
                } else {
                    if (decs.minimize.hovered) _glfwPlatformIconifyWindow(window);
                    else if (decs.maximize.hovered) {
                        if (window->wl.current.toplevel_states & TOPLEVEL_STATE_MAXIMIZED) _glfwPlatformRestoreWindow(window);
                        else _glfwPlatformMaximizeWindow(window);
                        // hack otherwise on GNOME maximize button remains hovered sometimes
                        decs.maximize.hovered = false; decs.titlebar_needs_update = true;
                    } else if (decs.close.hovered) _glfwInputWindowCloseRequest(window);
                }
                if (!has_hovered_button(window)) {
                    if (y < decs.metrics.width)
                        edges = XDG_TOPLEVEL_RESIZE_EDGE_TOP;
                    else {
                        if (window->wl.xdg.toplevel)
                            xdg_toplevel_move(window->wl.xdg.toplevel, _glfw.wl.seat, _glfw.wl.pointer_serial);
                    }
                }
                break;
            case LEFT_DECORATION:
                if (y < decs.metrics.width)
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_TOP_LEFT;
                else
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_LEFT;
                break;
            case RIGHT_DECORATION:
                if (y < decs.metrics.width)
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_TOP_RIGHT;
                else
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_RIGHT;
                break;
            case BOTTOM_DECORATION:
                if (x < decs.metrics.width)
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_BOTTOM_LEFT;
                else if (x > window->wl.width + decs.metrics.width)
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_BOTTOM_RIGHT;
                else
                    edges = XDG_TOPLEVEL_RESIZE_EDGE_BOTTOM;
                break;
        }
        if (edges != XDG_TOPLEVEL_RESIZE_EDGE_NONE) xdg_toplevel_resize(window->wl.xdg.toplevel, _glfw.wl.seat, _glfw.wl.pointer_serial, edges);
    }
    else if (button == BTN_RIGHT) {
        if (decs.focus != CENTRAL_WINDOW && window->wl.xdg.toplevel)
        {
            if (window->wl.wm_capabilities.window_menu) xdg_toplevel_show_window_menu(
                    window->wl.xdg.toplevel, _glfw.wl.seat, _glfw.wl.pointer_serial, (int32_t)x, (int32_t)y - decs.metrics.top);
            else
                _glfwInputError(GLFW_PLATFORM_ERROR, "Wayland compositor does not support showing wndow menu");
            return;
        }
    }
}


void
csd_handle_pointer_event(_GLFWwindow *window, int button, int state) {
    if (!window_is_csd_capable(window)) return;
    decs.titlebar_needs_update = false;
    switch (button) {
        case -1: handle_pointer_move(window); break;
        case -2: handle_pointer_enter(window); break;
        case -3: handle_pointer_leave(window); break;
        default: handle_pointer_button(window, button, state); break;
    }
    if (decs.titlebar_needs_update) {
        csd_change_title(window);
        if (!window->wl.waiting_for_swap_to_commit) wl_surface_commit(window->wl.surface);
    }
}
#undef x
#undef y
