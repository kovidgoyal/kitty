/* Integration test: real GTK widgets, real Wayland display, no mapped window.
 * gcc -D_GLFW_WAYLAND -DKITTY_GNOME_TITLEBAR -Iglfw glfw/tests/native_titlebar.c \
 *   glfw/wl_native_titlebar.c $(pkg-config --cflags --libs libadwaita-1 dbus-1) -lm -o /tmp/kitty-native-titlebar-test
 */
#include "wl_native_titlebar.h"
#include <adwaita.h>
#include <assert.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

_GLFWlibrary _glfw;
void
_glfwInputError(int code, const char *format, ...) {
    (void)code;
    va_list args;
    va_start(args, format);
    vfprintf(stderr, format, args);
    va_end(args);
    abort();
}
unsigned long long
_glfwPlatformAddTimer(monotonic_t interval, bool repeats, GLFWuserdatafun cb, void *data, GLFWuserdatafun cleanup) {
    (void)interval;
    (void)repeats;
    (void)cb;
    (void)data;
    (void)cleanup;
    return 1;
}
void
_glfwPlatformRemoveTimer(unsigned long long timer) {
    (void)timer;
}
GLFWAPI void
glfwWaylandRedrawCSDWindowTitle(GLFWwindow *window) {
    (void)window;
}

static uint8_t *
render(_GLFWwindow *w, double scale, const char *filename) {
    const int height = csd_native_titlebar_height(w);
    assert(height >= 32);
    w->wl.decorations.metrics.visible_titlebar_height = height;
    if (!w->wl.decorations.metrics.width) w->wl.decorations.metrics.width = csd_native_titlebar_margin(w);
    w->wl.decorations.for_window_state.fscale = scale;
    w->wl.decorations.titlebar.buffer.width = (int)ceil(w->wl.width * scale);
    w->wl.decorations.titlebar.buffer.height = (int)ceil(height * scale);
    size_t size = (size_t)w->wl.decorations.titlebar.buffer.width * w->wl.decorations.titlebar.buffer.height * 4;
    // Canaries detect out of bounds writes at fractional scales and tiny widths.
    uint8_t *output = malloc(size + 32);
    memset(output, 0xab, size + 32);
    assert(csd_native_titlebar_render(w, output));
    for (unsigned i = 0; i < 32; i++) assert(output[size + i] == 0xab);
    if (filename) {
        cairo_surface_t *surface = cairo_image_surface_create_for_data(
            output,
            CAIRO_FORMAT_ARGB32,
            w->wl.decorations.titlebar.buffer.width,
            w->wl.decorations.titlebar.buffer.height,
            w->wl.decorations.titlebar.buffer.width * 4);
        assert(cairo_surface_write_to_png(surface, filename) == CAIRO_STATUS_SUCCESS);
        cairo_surface_destroy(surface);
    }
    return output;
}

static void
test_native_shadows(_GLFWwindow *w, double scale, const char *filename) {
    const int margin = csd_native_titlebar_margin(w), width = w->wl.width;
    assert(margin > 0); // The theme supplies its own complete shadow extent.
    w->wl.decorations.metrics.width = margin;
    w->wl.height = 200;
    const int height = w->wl.height + w->wl.decorations.metrics.visible_titlebar_height;
    uint8_t *title = render(w, scale, NULL);
    struct {
        _GLFWWaylandBufferPair *buffer;
        int x, y, width, height;
    } parts[] = {
#define PART(which, x, y, width, height) {&w->wl.decorations.which.buffer, x, y, width, height}
        PART(shadow_top, 0, -margin, width, margin),
        PART(shadow_bottom, 0, height, width, margin),
        PART(shadow_left, -margin, 0, margin, height),
        PART(shadow_right, width, 0, margin, height),
        PART(shadow_upper_left, -margin, -margin, margin, margin),
        PART(shadow_upper_right, width, -margin, margin, margin),
        PART(shadow_lower_left, -margin, height, margin, margin),
        PART(shadow_lower_right, width, height, margin, margin),
#undef PART
    };
    for (unsigned i = 0; i < sizeof(parts) / sizeof(parts[0]); i++) {
        _GLFWWaylandBufferPair *b = parts[i].buffer;
        b->width = (int)round(parts[i].width * scale);
        b->height = (int)round(parts[i].height * scale);
        b->stride = b->width * 4;
        b->size_in_bytes = b->stride * b->height;
        b->data.front = malloc(b->size_in_bytes + 32);
        b->data.back = malloc(b->size_in_bytes + 32);
        memset(b->data.front, 0xab, b->size_in_bytes + 32);
        memset(b->data.back, 0xab, b->size_in_bytes + 32);
    }
    assert(csd_native_titlebar_shadows(w));
    _GLFWWaylandBufferPair *corner = &w->wl.decorations.shadow_upper_left.buffer;
    const size_t outside_curve = ((corner->height / 4) * corner->width + corner->width / 4) * 4 + 3;
    assert(corner->data.front[outside_curve] == 0); // Focused shadow's outer envelope is rounded.
    assert(corner->data.back[outside_curve] == 0);
    _GLFWWaylandBufferPair *top = &w->wl.decorations.shadow_top.buffer;
    // No visible straight cut at the outside boundary of the shadow.
    for (size_t x = 0; x < top->width; x++) assert(top->data.front[4 * x + 3] <= 1);
    cairo_surface_t *canvas =
        cairo_image_surface_create(CAIRO_FORMAT_ARGB32, (int)round((width + 2 * margin) * scale), (int)round((height + 2 * margin) * scale));
    cairo_t *cr = cairo_create(canvas);
    cairo_set_source_rgb(cr, .30, .06, .19);
    cairo_paint(cr);
    for (unsigned i = 0; i < sizeof(parts) / sizeof(parts[0]); i++) {
        _GLFWWaylandBufferPair *b = parts[i].buffer;
        for (unsigned j = 0; j < 32; j++) {
            assert(b->data.front[b->size_in_bytes + j] == 0xab);
            assert(b->data.back[b->size_in_bytes + j] == 0xab);
        }
        cairo_surface_t *part = cairo_image_surface_create_for_data(b->data.front, CAIRO_FORMAT_ARGB32, b->width, b->height, b->stride);
        cairo_set_source_surface(cr, part, round((parts[i].x + margin) * scale), round((parts[i].y + margin) * scale));
        cairo_paint(cr);
        cairo_surface_destroy(part);
        free(b->data.front);
        free(b->data.back);
        b->data.front = b->data.back = NULL;
    }
    cairo_set_source_rgb(cr, .12, .12, .13);
    cairo_rectangle(cr, margin * scale, (margin + w->wl.decorations.metrics.visible_titlebar_height) * scale, width * scale, w->wl.height * scale);
    cairo_fill(cr);
    cairo_surface_t *header = cairo_image_surface_create_for_data(
        title,
        CAIRO_FORMAT_ARGB32,
        w->wl.decorations.titlebar.buffer.width,
        w->wl.decorations.titlebar.buffer.height,
        w->wl.decorations.titlebar.buffer.width * 4);
    cairo_set_source_surface(cr, header, round(margin * scale), round(margin * scale));
    cairo_paint(cr);
    assert(cairo_surface_write_to_png(canvas, filename) == CAIRO_STATUS_SUCCESS);
    cairo_surface_destroy(header);
    cairo_destroy(cr);
    cairo_surface_destroy(canvas);
    free(title);
}

int
main(void) {
    g_setenv("KITTY_WAYLAND_TITLEBAR", "system", true);
    _GLFWwindow w = {0};
    w.id = _glfw.focusedWindowId = 1;
    w.resizable = true;
    w.wl.width = 800;
    w.wl.title = "Kitty — GTK 4 / libadwaita";
    w.wl.wm_capabilities.minimize = w.wl.wm_capabilities.maximize = true;
    assert(csd_native_titlebar_height(&w) > 0);
    g_object_set(gtk_settings_get_default(), "gtk-decoration-layout", ":minimize,maximize,close", "gtk-enable-animations", false, NULL);
    adw_style_manager_set_color_scheme(adw_style_manager_get_default(), ADW_COLOR_SCHEME_FORCE_DARK);
    uint8_t *dark = render(&w, 1, "/tmp/kitty-titlebar-dark.png");
    test_native_shadows(&w, 1, "/tmp/kitty-native-shadow-dark.png");
    test_native_shadows(&w, 1.5, "/tmp/kitty-native-shadow-150.png");
    free(render(&w, 1, NULL));
    assert(dark[3] < 128); // Only the native shadow remains outside the rounded body.
    assert(dark[((size_t)w.wl.decorations.titlebar.buffer.height - 1) * 800 * 4 + 3] == 255);
    assert(w.wl.decorations.minimize.width > 0 && w.wl.decorations.maximize.width > 0 && w.wl.decorations.close.width > 0);
    assert(w.wl.decorations.close.left > w.wl.decorations.maximize.left);
    // Directory/app titles and every spinner frame must redraw immediately,
    // without waiting for a GTK frame clock or another pointer/focus event.
    const char *dynamic_titles[] = {"~/repos", "nvim · main.py", "⠋ Cargando", "⠙ Cargando", "⠹ Cargando", "~/repos"};
    uint8_t *previous = dark;
    for (unsigned i = 0; i < sizeof(dynamic_titles) / sizeof(dynamic_titles[0]); i++) {
        w.wl.title = (char *)dynamic_titles[i];
        uint8_t *frame = render(&w, 1, NULL);
        assert(memcmp(previous, frame, (size_t)w.wl.width * w.wl.decorations.metrics.visible_titlebar_height * 4));
        if (previous != dark) free(previous);
        previous = frame;
    }
    free(previous);
    w.wl.title = "Kitty — GTK 4 / libadwaita";
    adw_style_manager_set_color_scheme(adw_style_manager_get_default(), ADW_COLOR_SCHEME_FORCE_LIGHT);
    uint8_t *light = render(&w, 1, "/tmp/kitty-titlebar-light.png");
    assert(memcmp(dark, light, (size_t)w.wl.width * w.wl.decorations.metrics.visible_titlebar_height * 4));
    w.wl.decorations.close.hovered = true;
    w.wl.decorations.pressed_button = CSD_BUTTON_close;
    uint8_t *pressed = render(&w, 1, NULL);
    assert(memcmp(light, pressed, (size_t)w.wl.width * w.wl.decorations.metrics.visible_titlebar_height * 4));
    free(pressed);
    w.wl.decorations.close.hovered = false;
    w.wl.decorations.pressed_button = CSD_BUTTON_none;
    w.wl.decorations.use_custom_titlebar_color = true;
    w.wl.decorations.titlebar_color = 0x123456;
    uint8_t *custom = render(&w, 1, NULL);
    assert(custom[400 * 4] == 0x56 && custom[400 * 4 + 1] == 0x34 && custom[400 * 4 + 2] == 0x12);
    free(custom);
    w.wl.decorations.use_custom_titlebar_color = false;
    free(dark);
    free(light);
    g_object_set(gtk_settings_get_default(), "gtk-decoration-layout", "close,minimize,maximize:", NULL);
    free(render(&w, 1.5, "/tmp/kitty-titlebar-left-150.png"));
    assert(w.wl.decorations.close.left < w.wl.decorations.minimize.left);
    assert(w.wl.decorations.maximize.left < 300);
    w.wl.current.toplevel_states = TOPLEVEL_STATE_MAXIMIZED;
    w.wl.decorations.maximize.hovered = true;
    w.wl.decorations.pressed_button = CSD_BUTTON_maximize;
    uint8_t *maximized = render(&w, 2, "/tmp/kitty-titlebar-maximized-200.png");
    assert(maximized[3] == 255); // Maximized windows must meet the screen edge.
    free(maximized);
    w.wl.wm_capabilities.minimize = w.wl.wm_capabilities.maximize = false;
    free(render(&w, 1, NULL));
    assert(!w.wl.decorations.minimize.width && !w.wl.decorations.maximize.width);
    g_object_set(gtk_settings_get_default(), "gtk-decoration-layout", ":", NULL);
    free(render(&w, 1, NULL));
    assert(!w.wl.decorations.close.width);
    w.wl.width = 20;
    free(render(&w, 1.25, NULL));
    csd_native_titlebar_free(&w);
    assert(!w.wl.decorations.native_titlebar);
    csd_native_titlebar_terminate();
    puts("Native GTK titlebar: theme, layout, capabilities, scaling and lifecycle passed");
    return 0;
}
