#define _POSIX_C_SOURCE 200809L
/* Standalone renderer checks; see docs/wayland-gnome-csd.md. */
#include "../wl_client_side_decorations.c"
#include <assert.h>

_GLFWlibrary _glfw;
_GLFWwindow *
_glfwWindowForId(GLFWid id) {
    (void)id;
    abort();
}
static GLFWTitlebarButtonLayout layout = {.right = {3, 2, 1}, .right_count = 3};
static double text_scale = 1.;
const GLFWTitlebarButtonLayout *glfw_current_titlebar_button_layout(void) { return &layout; }
double glfw_current_titlebar_text_scale(void) { return text_scale; }
unsigned glfw_current_titlebar_height(void) { return (unsigned)ceil(38 * fmax(1, text_scale)); }
static bool theme_available = true;
bool glfw_has_system_color_theme(void) { return theme_available; }
static GLFWColorScheme scheme = GLFW_COLOR_SCHEME_DARK;
GLFWAPI GLFWColorScheme
glfwGetCurrentSystemColorTheme(bool query) {
    (void)query;
    return scheme;
}

int
main(void) {
    _GLFWwindow w = {0};
    w.id = _glfw.focusedWindowId = 1;
    w.wl.wm_capabilities.maximize = w.wl.wm_capabilities.minimize = true;
    csd_initialize_metrics(&w);
    assert(w.wl.decorations.metrics.visible_titlebar_height == 38);
    const double scales[] = {1, 1.25, 1.5, 2};
    const int widths[] = {1, 12, 40, 72, 128, 800};
    for (unsigned si = 0; si < sizeof(scales) / sizeof(*scales); si++)
    for (unsigned wi = 0; wi < sizeof(widths) / sizeof(*widths); wi++)
    for (int state = 0; state < 4; state++) {
        double scale = scales[si];
        w.wl.decorations.for_window_state.fscale = scale;
        int width = (int)round(widths[wi] * scale), height = (int)round(38 * scale);
        w.wl.decorations.titlebar.buffer.width = width;
        w.wl.decorations.titlebar.buffer.height = height;
        w.wl.current.toplevel_states = state == 1 ? TOPLEVEL_STATE_MAXIMIZED : 0;
        _glfw.focusedWindowId = state == 2 ? 0 : 1;
        scheme = state == 3 ? GLFW_COLOR_SCHEME_LIGHT : GLFW_COLOR_SCHEME_DARK;
        size_t bytes = (size_t)width * height * 4;
        uint8_t *data = malloc(bytes + 32);
        assert(data);
        memset(data, 0xab, bytes + 32);
        render_titlebar_pixels(&w, data);
        for (int i = 0; i < 32; i++) assert(data[bytes + i] == 0xab);
        if (widths[wi] >= 128) {
            assert(((uint32_t *)data)[(height / 2) * width] == (state == 3 ? 0xffebebeb : 0xff303030));
            unsigned corner_alpha = A(((uint32_t *)data)[0]);
            if (state == 1) assert(corner_alpha == 255);
            else {
                assert(corner_alpha > 0 && corner_alpha < 128);
                size_t margin = (size_t)round(12 * scale);
                assert(w.wl.decorations.shadow_tile.data[0] == 0);
                unsigned expected = A(w.wl.decorations.shadow_tile.data[margin * w.wl.decorations.shadow_tile.stride + margin]);
                if (state == 2) expected /= 2;
                assert(corner_alpha == expected);
                size_t stride = w.wl.decorations.shadow_tile.stride;
                unsigned right = A(w.wl.decorations.shadow_tile.data[margin * stride + stride - margin - 1]);
                if (state == 2) right /= 2;
                assert(A(((uint32_t *)data)[width - 1]) == right);
            }
            assert(w.wl.decorations.close.width > 0);
            assert(w.wl.decorations.close.left >= 0);
            assert(w.wl.decorations.close.width == (int)round(36 * scale));
            assert(w.wl.decorations.close.left - w.wl.decorations.maximize.left == (int)round(36 * scale));
        }
        if (wi == 5 && si == 0 && state == 0) {
            FILE *f = fopen("/tmp/kitty-gnome-csd-preview.ppm", "wb");
            assert(f);
            fprintf(f, "P6\n%d %d\n255\n", width, height);
            for (int i = 0; i < width * height; i++) {
                uint32_t px = ((uint32_t *)data)[i];
                unsigned char rgb[] = {R(px), G(px), B(px)};
                fwrite(rgb, 1, 3, f);
            }
            fclose(f);
        }
        free(data);
    }
    w.wl.decorations.for_window_state.fscale = 1;
    w.wl.decorations.titlebar.buffer.width = 128;
    w.wl.decorations.titlebar.buffer.height = 38;
    uint32_t custom_pixels[128 * 38];
    theme_available = false;
    scheme = GLFW_COLOR_SCHEME_NO_PREFERENCE;
    render_titlebar_pixels(&w, (uint8_t *)custom_pixels);
    assert(custom_pixels[19 * 128] == 0xff303030);
    theme_available = true;
    render_titlebar_pixels(&w, (uint8_t *)custom_pixels);
    assert(custom_pixels[19 * 128] == 0xffebebeb);
    const GLFWColorScheme transitions[] = {GLFW_COLOR_SCHEME_DARK, GLFW_COLOR_SCHEME_NO_PREFERENCE,
        GLFW_COLOR_SCHEME_DARK, GLFW_COLOR_SCHEME_LIGHT, GLFW_COLOR_SCHEME_NO_PREFERENCE};
    for (unsigned i = 0; i < sizeof(transitions) / sizeof(*transitions); i++) {
        scheme = transitions[i];
        render_titlebar_pixels(&w, (uint8_t *)custom_pixels);
        assert(custom_pixels[19 * 128] == (scheme == GLFW_COLOR_SCHEME_DARK ? 0xff303030 : 0xffebebeb));
    }
    w.wl.decorations.use_custom_titlebar_color = true;
    const uint32_t custom_colors[] = {0x123456, 0xfafafa};
    for (unsigned i = 0; i < sizeof(custom_colors) / sizeof(*custom_colors); i++) {
        w.wl.decorations.titlebar_color = custom_colors[i];
        for (int dark = 0; dark < 2; dark++) {
            scheme = dark ? GLFW_COLOR_SCHEME_DARK : GLFW_COLOR_SCHEME_LIGHT;
            render_titlebar_pixels(&w, (uint8_t *)custom_pixels);
            assert(custom_pixels[19 * 128] == (0xff000000 | custom_colors[i]));
        }
    }
    w.wl.decorations.use_custom_titlebar_color = false;
    w.wl.decorations.titlebar.buffer.width = 128;
    w.wl.decorations.titlebar.buffer.height = 38;
    layout = (GLFWTitlebarButtonLayout){.left = {1}, .right = {3, 2}, .left_count = 1, .right_count = 2};
    render_titlebar_pixels(&w, (uint8_t *)custom_pixels);
    assert(w.wl.decorations.close.left == 6);
    assert(w.wl.decorations.minimize.left == 50 && w.wl.decorations.maximize.left == 86);
    layout = (GLFWTitlebarButtonLayout){0};
    render_titlebar_pixels(&w, (uint8_t *)custom_pixels);
    assert(!w.wl.decorations.close.width && !w.wl.decorations.maximize.width && !w.wl.decorations.minimize.width);
    layout = (GLFWTitlebarButtonLayout){.left = {1, 2, 3}, .left_count = 3};
    w.wl.decorations.titlebar.buffer.width = 40;
    render_titlebar_pixels(&w, (uint8_t *)custom_pixels);
    assert(w.wl.decorations.close.width == 36);
    assert(!w.wl.decorations.maximize.width && !w.wl.decorations.minimize.width);
    text_scale = 2.;
    csd_initialize_metrics(&w);
    assert(w.wl.decorations.metrics.visible_titlebar_height == 76);
    text_scale = .75;
    csd_initialize_metrics(&w);
    assert(w.wl.decorations.metrics.visible_titlebar_height == 38);
    kernel_type *square = create_shadow_mask(84, 84, 12, 25, .7f, 384, 0);
    kernel_type *rounded = create_shadow_mask(84, 84, 12, 25, .7f, 384, 12);
    assert(square && rounded);
    assert(rounded[12 * 84 + 12] < square[12 * 84 + 12]);
    assert(rounded[70 * 84 + 12] == square[70 * 84 + 12]);
    free(square);
    free(rounded);
    free(w.wl.decorations.shadow_tile.data);
    w.wl.decorations.shadow_tile.data = NULL;
    puts("GNOME CSD renderer: 96 scale/size/state combinations and corner-shadow continuity passed");
    return 0;
}
