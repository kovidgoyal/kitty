/*
 * Copyright (C) 2026, distributed under the GPL3 license.
 * GTK draws into Kitty's existing shared-memory titlebar. GTK never maps a
 * toplevel: input, window management and the terminal stay on Kitty's display.
 */
#include "wl_native_titlebar.h"
#include "wl_client_side_decorations.h"
#include <stdlib.h>
#include <string.h>

#ifdef KITTY_GNOME_TITLEBAR
#include <adwaita.h>
// CairoRenderer is deliberately used: no second GPU context or GL state changes.
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"

typedef struct {
    GtkWidget *window, *header, *title;
    GskRenderer *renderer;
    GtkCssProvider *colors;
    uint32_t color;
    bool custom_color;
    uint8_t *shadow_pixels[2];
    int shadow_width, shadow_height, shadow_margin;
    int shadow_window_width, shadow_window_height;
    double shadow_scale;
    unsigned shadow_generation;
    bool shadow_docked, shadow_round_top;
} NativeTitlebar;
static bool initialized, available, dirty;
static unsigned style_generation;
static unsigned long long settings_timer;
static gulong gtk_settings_signal, adw_settings_signal;
GLFWAPI void glfwWaylandRedrawCSDWindowTitle(GLFWwindow *window);

static void
settings_changed(GObject *object UNUSED, GParamSpec *property UNUSED, void *data UNUSED) {
    dirty = true;
    style_generation++;
}

static void
poll_settings(unsigned long long timer UNUSED, void *data UNUSED) {
    // Service GTK's separate connection without entering its main loop.
    for (unsigned i = 0; i < 16 && g_main_context_pending(NULL); i++) g_main_context_iteration(NULL, false);
    if (!dirty) return;
    dirty = false;
    for (_GLFWwindow *w = _glfw.windowListHead; w; w = w->next) {
        if (w->wl.decorations.native_titlebar) {
            w->wl.decorations.native_shadow_dirty = true;
            glfwWaylandRedrawCSDWindowTitle((GLFWwindow *)w);
        }
    }
}

static bool
initialize(void) {
    if (initialized) return available;
    initialized = true;
    const char *mode = getenv("KITTY_WAYLAND_TITLEBAR");
    if (!mode || strcmp(mode, "system")) return false;
    // Do not permit GTK to silently fall back to X11.
    gdk_set_allowed_backends("wayland");
    if (!gtk_init_check()) return false;
    adw_init();
    // Unmapped widgets have no ticking frame clock; use their final hover/press
    // style immediately instead of starting transitions that cannot advance.
    g_object_set(gtk_settings_get_default(), "gtk-enable-animations", false, NULL);
    gtk_settings_signal = g_signal_connect(gtk_settings_get_default(), "notify", G_CALLBACK(settings_changed), NULL);
    adw_settings_signal = g_signal_connect(adw_style_manager_get_default(), "notify", G_CALLBACK(settings_changed), NULL);
    settings_timer = _glfwPlatformAddTimer(ms_to_monotonic_t(250), true, poll_settings, NULL, NULL);
    available = true;
    return true;
}

static NativeTitlebar *
get_titlebar(_GLFWwindow *window) {
    if (window->wl.decorations.native_titlebar) return window->wl.decorations.native_titlebar;
    if (!initialize()) return NULL;
    NativeTitlebar *n = calloc(1, sizeof(*n));
    if (!n) return NULL;
    n->window = gtk_window_new();
    gtk_widget_add_css_class(n->window, "csd");
    n->header = adw_header_bar_new();
    // Use GTK's compact window-title style, rather than a toolbar-height header.
    // Its metrics still come from the system theme.
    gtk_widget_add_css_class(n->header, "default-decoration");
    n->title = gtk_label_new(NULL);
    gtk_widget_add_css_class(n->title, "title");
    gtk_label_set_ellipsize(GTK_LABEL(n->title), PANGO_ELLIPSIZE_END);
    adw_header_bar_set_title_widget(ADW_HEADER_BAR(n->header), n->title);
    adw_header_bar_set_show_back_button(ADW_HEADER_BAR(n->header), false);
    gtk_window_set_child(GTK_WINDOW(n->window), n->header);
    gtk_widget_realize(n->window);
    n->renderer = gsk_cairo_renderer_new();
    GError *error = NULL;
    if (!gsk_renderer_realize(n->renderer, gtk_native_get_surface(GTK_NATIVE(n->window)), &error)) {
        _glfwInputError(GLFW_PLATFORM_ERROR, "Cannot create GTK titlebar renderer: %s", error ? error->message : "unknown error");
        g_clear_error(&error);
        g_object_unref(n->renderer);
        gtk_window_destroy(GTK_WINDOW(n->window));
        free(n);
        return NULL;
    }
    n->colors = gtk_css_provider_new();
    gtk_style_context_add_provider(gtk_widget_get_style_context(n->header), GTK_STYLE_PROVIDER(n->colors), GTK_STYLE_PROVIDER_PRIORITY_APPLICATION);
    window->wl.decorations.native_titlebar = n;
    return n;
}

static GskRenderNode *
window_background(NativeTitlebar *n, int width, int height, bool focused) {
    if (focused) gtk_widget_unset_state_flags(n->window, GTK_STATE_FLAG_BACKDROP);
    else gtk_widget_set_state_flags(n->window, GTK_STATE_FLAG_BACKDROP, false);
    GtkSnapshot *snapshot = gtk_snapshot_new();
    gtk_snapshot_render_background(snapshot, gtk_widget_get_style_context(n->window), 0, 0, width, height);
    return gtk_snapshot_free_to_node(snapshot);
}

// Reuse only GTK's shadows, without the opaque window background. Match the
// square terminal bottom; the titlebar at the top has GTK's native corner shape.
static void
append_shadows(GtkSnapshot *snapshot, GskRenderNode *node, bool round_top) {
    if (gsk_render_node_get_node_type(node) == GSK_OUTSET_SHADOW_NODE) {
        GskRoundedRect outline = *gsk_outset_shadow_node_get_outline(node);
        outline.corner[2] = outline.corner[3] = GRAPHENE_SIZE_INIT(0, 0);
        if (!round_top) outline.corner[0] = outline.corner[1] = GRAPHENE_SIZE_INIT(0, 0);
        GskRenderNode *shadow = gsk_outset_shadow_node_new(
            &outline,
            gsk_outset_shadow_node_get_color(node),
            gsk_outset_shadow_node_get_dx(node),
            gsk_outset_shadow_node_get_dy(node),
            gsk_outset_shadow_node_get_spread(node),
            gsk_outset_shadow_node_get_blur_radius(node));
        gtk_snapshot_append_node(snapshot, shadow);
        gsk_render_node_unref(shadow);
    } else if (gsk_render_node_get_node_type(node) == GSK_CONTAINER_NODE) {
        for (unsigned i = 0; i < gsk_container_node_get_n_children(node); i++) append_shadows(snapshot, gsk_container_node_get_child(node, i), round_top);
    }
}

int
csd_native_titlebar_margin(_GLFWwindow *window) {
    NativeTitlebar *n = get_titlebar(window);
    if (!n) return 0;
    // Include the full native blur extent; cropping at Kitty's old 12px margin
    // leaves a visible rectangular edge in the translucent shadow.
    float margin = 1;
    for (unsigned i = 0; i < 2; i++) {
        GskRenderNode *node = window_background(n, 200, 200, i == 0);
        if (node) {
            graphene_rect_t bounds;
            gsk_render_node_get_bounds(node, &bounds);
            margin = MAX(margin, MAX(-bounds.origin.x, -bounds.origin.y));
            margin = MAX(margin, MAX(bounds.origin.x + bounds.size.width - 200, bounds.origin.y + bounds.size.height - 200));
            gsk_render_node_unref(node);
        }
    }
    return (int)ceilf(margin);
}

static const GskRoundedRect *background_clip(GskRenderNode *node);

static bool
ensure_shadow_atlas(_GLFWwindow *window) {
    NativeTitlebar *n = window->wl.decorations.native_titlebar;
    const int width = window->wl.width;
    const bool round_top = !window->wl.decorations.titlebar_hidden;
    const int height = window->wl.height + (round_top ? window->wl.decorations.metrics.visible_titlebar_height : 0);
    const double scale = window->wl.decorations.for_window_state.fscale;
    const int margin = (int)round(window->wl.decorations.metrics.width * scale);
    const bool docked = window->wl.current.toplevel_states & TOPLEVEL_STATE_DOCKED;
    if (n->shadow_pixels[0] && n->shadow_pixels[1] && n->shadow_window_width == width && n->shadow_window_height == height && n->shadow_scale == scale &&
        n->shadow_margin == margin && n->shadow_generation == style_generation && n->shadow_docked == docked && n->shadow_round_top == round_top)
        return true;
    for (unsigned i = 0; i < 2; i++) {
        free(n->shadow_pixels[i]);
        n->shadow_pixels[i] = NULL;
    }
    n->shadow_window_width = width;
    n->shadow_window_height = height;
    n->shadow_scale = scale;
    n->shadow_margin = margin;
    n->shadow_generation = style_generation;
    n->shadow_docked = docked;
    n->shadow_round_top = round_top;
    n->shadow_width = (int)round(width * scale) + 2 * margin;
    n->shadow_height = (int)round(height * scale) + 2 * margin;
    if (n->shadow_width <= 0 || n->shadow_height <= 0) return false;
    for (unsigned i = 0; i < 2; i++) {
        const size_t stride = (size_t)n->shadow_width * 4;
        n->shadow_pixels[i] = calloc(stride, n->shadow_height);
        if (!n->shadow_pixels[i]) return false;
        if (docked) continue;
        GskRenderNode *background = window_background(n, width, height, i == 0);
        if (!background) continue;
        GtkSnapshot *snapshot = gtk_snapshot_new();
        gtk_snapshot_scale(snapshot, (float)scale, (float)scale);
        const GskRoundedRect *clip = background_clip(background);
        if (clip) {
            // Round the outer shadow envelope as well as its inner outline.
            // This removes the faint square support of a focused blur, without
            // changing GTK's shadow color, spread or intensity.
            GskRoundedRect outer = *clip;
            const float padding = (float)(margin / scale);
            outer.bounds = GRAPHENE_RECT_INIT(-padding, -padding, width + 2 * padding, height + 2 * padding);
            for (unsigned c = 0; c < 4; c++) {
                const bool rounded_corner = c < 2 && round_top;
                outer.corner[c].width = (rounded_corner ? clip->corner[c].width : 0) + padding;
                outer.corner[c].height = (rounded_corner ? clip->corner[c].height : 0) + padding;
            }
            gtk_snapshot_push_rounded_clip(snapshot, &outer);
        }
        append_shadows(snapshot, background, round_top);
        if (clip) gtk_snapshot_pop(snapshot);
        GskRenderNode *node = gtk_snapshot_free_to_node(snapshot);
        gsk_render_node_unref(background);
        if (!node) continue;
        // Render the entire shadow once, then slice it. Independent blur renders
        // for the eight subsurfaces can expose their rectangular clip boundaries.
        graphene_rect_t viewport = GRAPHENE_RECT_INIT(-margin, -margin, n->shadow_width, n->shadow_height);
        GdkTexture *texture = gsk_renderer_render_texture(n->renderer, node, &viewport);
        gsk_render_node_unref(node);
        if (texture) {
            gdk_texture_download(texture, n->shadow_pixels[i], stride);
            g_object_unref(texture);
        }
    }
    return true;
}

static void
copy_shadow_part(NativeTitlebar *n, _GLFWWaylandBufferPair *buffer, int x, int y) {
    if (x < 0 || y < 0 || x + (int)buffer->width > n->shadow_width || y + (int)buffer->height > n->shadow_height) return;
    for (unsigned i = 0; i < 2; i++) {
        uint8_t *output = i == 0 ? buffer->data.front : buffer->data.back;
        if (!output || !n->shadow_pixels[i]) continue;
        for (size_t row = 0; row < buffer->height; row++)
            memcpy(output + row * buffer->stride, n->shadow_pixels[i] + ((y + row) * n->shadow_width + x) * 4, buffer->width * 4);
    }
}

bool
csd_native_titlebar_shadows(_GLFWwindow *window) {
    NativeTitlebar *n = window->wl.decorations.native_titlebar;
    if (!n || !ensure_shadow_atlas(window)) return false;
    const int margin = n->shadow_margin;
    const int width = n->shadow_width - 2 * margin, height = n->shadow_height - 2 * margin;
#define PART(which, x, y) copy_shadow_part(n, &window->wl.decorations.which.buffer, x, y)
    PART(shadow_top, margin, 0);
    PART(shadow_bottom, margin, margin + height);
    PART(shadow_left, 0, margin);
    PART(shadow_right, margin + width, margin);
    PART(shadow_upper_left, 0, 0);
    PART(shadow_upper_right, margin + width, 0);
    PART(shadow_lower_left, 0, margin + height);
    PART(shadow_lower_right, margin + width, margin + height);
#undef PART
    return true;
}

int
csd_native_titlebar_height(_GLFWwindow *window) {
    NativeTitlebar *n = get_titlebar(window);
    if (!n) return 0;
    int minimum, natural;
    gtk_widget_measure(n->header, GTK_ORIENTATION_VERTICAL, -1, &minimum, &natural, NULL, NULL);
    return MAX(minimum, natural);
}

static void
prepare_widgets(_GLFWwindow *window, GtkWidget *widget, NativeTitlebar *n, bool focused) {
    const bool maximized = window->wl.current.toplevel_states & TOPLEVEL_STATE_MAXIMIZED;
    if (focused) gtk_widget_unset_state_flags(widget, GTK_STATE_FLAG_BACKDROP);
    else gtk_widget_set_state_flags(widget, GTK_STATE_FLAG_BACKDROP, false);
    bool button = false, hovered = false, pressed = false, enabled = true;
#define BUTTON(which, capability)                                              \
    if (gtk_widget_has_css_class(widget, #which)) {                            \
        button = true;                                                         \
        hovered = window->wl.decorations.which.hovered;                        \
        pressed = window->wl.decorations.pressed_button == CSD_BUTTON_##which; \
        enabled = (capability);                                                \
    }
    BUTTON(minimize, window->wl.wm_capabilities.minimize)
    BUTTON(maximize, window->wl.wm_capabilities.maximize && window->resizable)
    BUTTON(close, true)
#undef BUTTON
    if (button) {
        gtk_widget_set_visible(widget, enabled);
        gtk_widget_set_sensitive(widget, true);
        gtk_widget_unset_state_flags(widget, GTK_STATE_FLAG_PRELIGHT | GTK_STATE_FLAG_ACTIVE);
        if (hovered) gtk_widget_set_state_flags(widget, GTK_STATE_FLAG_PRELIGHT | (pressed ? GTK_STATE_FLAG_ACTIVE : 0), false);
        if (gtk_widget_has_css_class(widget, "maximize")) {
            GtkWidget *image = gtk_button_get_child(GTK_BUTTON(widget));
            if (GTK_IS_IMAGE(image)) gtk_image_set_from_icon_name(GTK_IMAGE(image), maximized ? "window-restore-symbolic" : "window-maximize-symbolic");
        }
    }
    for (GtkWidget *child = gtk_widget_get_first_child(widget); child; child = gtk_widget_get_next_sibling(child)) {
        prepare_widgets(window, child, n, focused);
    }
    gtk_widget_queue_draw(widget);
}

static void
button_bounds(_GLFWwindow *window, GtkWidget *widget, NativeTitlebar *n, double scale) {
    graphene_rect_t bounds;
    if (!gtk_widget_get_visible(widget) || !gtk_widget_get_child_visible(widget)) return;
#define BUTTON(which)                                                                                                                               \
    if (gtk_widget_has_css_class(widget, #which) && gtk_widget_compute_bounds(widget, n->header, &bounds)) {                                        \
        window->wl.decorations.which.left = (int)floor(bounds.origin.x * scale);                                                                    \
        window->wl.decorations.which.top = (int)floor(bounds.origin.y * scale);                                                                     \
        window->wl.decorations.which.width = MAX(0, (int)ceil((bounds.origin.x + bounds.size.width) * scale) - window->wl.decorations.which.left);  \
        window->wl.decorations.which.height = MAX(0, (int)ceil((bounds.origin.y + bounds.size.height) * scale) - window->wl.decorations.which.top); \
    }
    BUTTON(minimize)
    BUTTON(maximize)
    BUTTON(close)
#undef BUTTON
    for (GtkWidget *child = gtk_widget_get_first_child(widget); child; child = gtk_widget_get_next_sibling(child)) button_bounds(window, child, n, scale);
}

// GTK's background snapshot includes both the CSS shadow and the rounded
// background. Reuse its clip, excluding the shadow, for the titlebar content.
static const GskRoundedRect *
background_clip(GskRenderNode *node) {
    if (gsk_render_node_get_node_type(node) == GSK_ROUNDED_CLIP_NODE) return gsk_rounded_clip_node_get_clip(node);
    if (gsk_render_node_get_node_type(node) == GSK_CONTAINER_NODE) {
        for (unsigned i = 0; i < gsk_container_node_get_n_children(node); i++) {
            const GskRoundedRect *clip = background_clip(gsk_container_node_get_child(node, i));
            if (clip) return clip;
        }
    }
    return NULL;
}

bool
csd_native_titlebar_render(_GLFWwindow *window, uint8_t *output) {
    NativeTitlebar *n = window->wl.decorations.native_titlebar;
    if (!n) return false;
    const bool focused = window->id == _glfw.focusedWindowId;
    gtk_label_set_text(GTK_LABEL(n->title), window->wl.title ? window->wl.title : "");
    gtk_window_set_resizable(GTK_WINDOW(n->window), window->resizable);
    if (n->custom_color != window->wl.decorations.use_custom_titlebar_color || n->color != window->wl.decorations.titlebar_color) {
        n->custom_color = window->wl.decorations.use_custom_titlebar_color;
        n->color = window->wl.decorations.titlebar_color;
        char css[256] = {0};
        if (n->custom_color) {
            const unsigned r = (n->color >> 16) & 255, g = (n->color >> 8) & 255, b = n->color & 255;
            snprintf(
                css,
                sizeof(css),
                "headerbar { background: #%06x; color: %s; }",
                n->color & 0xffffff,
                .2126 * r + .7152 * g + .0722 * b < 128 ? "white" : "black");
        }
        gtk_css_provider_load_from_string(n->colors, css);
    }
    prepare_widgets(window, n->header, n, focused);
    gtk_widget_queue_resize(n->header);
    gtk_widget_allocate(n->header, window->wl.width, window->wl.decorations.metrics.visible_titlebar_height, -1, NULL);
    if (!gtk_widget_get_mapped(n->header)) gtk_widget_map(n->header);
    // Buttons may be recreated by GTK when decoration-layout changes.
    prepare_widgets(window, n->header, n, focused);
    gtk_widget_queue_draw(n->header);
    GtkSnapshot *snapshot = gtk_snapshot_new();
    const double scale = window->wl.decorations.for_window_state.fscale;
    gtk_snapshot_scale(snapshot, (float)scale, (float)scale);
    bool rounded = false;
    if (!(window->wl.current.toplevel_states & TOPLEVEL_STATE_DOCKED)) {
        // The actual system CSS determines the radius, including --window-radius.
        // Only clip the upper corners; the terminal is a separate Wayland surface.
        const int total_height = MAX(
            window->wl.height + (int)window->wl.decorations.metrics.visible_titlebar_height, (int)window->wl.decorations.metrics.visible_titlebar_height * 2);
        GskRenderNode *background_node = window_background(n, window->wl.width, total_height, focused);

        const GskRoundedRect *native_clip = background_node ? background_clip(background_node) : NULL;
        if (native_clip) {
            GskRoundedRect clip = *native_clip;
            clip.bounds.size.height = window->wl.decorations.metrics.visible_titlebar_height;
            clip.corner[2] = clip.corner[3] = GRAPHENE_SIZE_INIT(0, 0);
            gtk_snapshot_push_rounded_clip(snapshot, &clip);
            rounded = true;
        }
        if (background_node) gsk_render_node_unref(background_node);
    }
    gtk_widget_snapshot_child(n->window, n->header, snapshot);
    if (rounded) gtk_snapshot_pop(snapshot);
    GskRenderNode *node = gtk_snapshot_free_to_node(snapshot);
    if (!node) return false;
    const int width = window->wl.decorations.titlebar.buffer.width, height = window->wl.decorations.titlebar.buffer.height;
    graphene_rect_t viewport = GRAPHENE_RECT_INIT(0, 0, width, height);
    GdkTexture *texture = gsk_renderer_render_texture(n->renderer, node, &viewport);
    gsk_render_node_unref(node);
    if (!texture) return false;
    gdk_texture_download(texture, output, (size_t)width * 4);
    g_object_unref(texture);
    if (ensure_shadow_atlas(window)) {
        const uint8_t *shadow = n->shadow_pixels[focused ? 0 : 1];
        const int margin = n->shadow_margin;
        for (int y = 0; y < height; y++) {
            for (int x = 0; x < width; x++) {
                uint8_t *pixel = output + ((size_t)y * width + x) * 4;
                if (pixel[3] == 255) continue;
                const uint8_t *under = shadow + (((size_t)y + margin) * n->shadow_width + x + margin) * 4;
                const unsigned inverse_alpha = 255 - pixel[3];
                for (unsigned c = 0; c < 4; c++) pixel[c] += (uint8_t)((under[c] * inverse_alpha + 127) / 255);
            }
        }
    }
    window->wl.decorations.minimize.width = window->wl.decorations.maximize.width = window->wl.decorations.close.width = 0;
    button_bounds(window, n->header, n, scale);
#define CLEAR_HIDDEN(which) \
    if (!window->wl.decorations.which.width) window->wl.decorations.which.hovered = false;
    CLEAR_HIDDEN(minimize)
    CLEAR_HIDDEN(maximize)
    CLEAR_HIDDEN(close)
#undef CLEAR_HIDDEN
    return true;
}

void
csd_native_titlebar_free(_GLFWwindow *window) {
    NativeTitlebar *n = window->wl.decorations.native_titlebar;
    if (!n) return;
    gtk_widget_unmap(n->header);
    gsk_renderer_unrealize(n->renderer);
    g_object_unref(n->renderer);
    g_object_unref(n->colors);
    free(n->shadow_pixels[0]);
    free(n->shadow_pixels[1]);
    gtk_window_destroy(GTK_WINDOW(n->window));
    free(n);
    window->wl.decorations.native_titlebar = NULL;
}

GLFWAPI bool
glfwWaylandUsesSystemTitlebar(void) {
    return available;
}

void
csd_native_titlebar_terminate(void) {
    if (settings_timer) _glfwPlatformRemoveTimer(settings_timer);
    settings_timer = 0;
    if (available) {
        g_signal_handler_disconnect(gtk_settings_get_default(), gtk_settings_signal);
        g_signal_handler_disconnect(adw_style_manager_get_default(), adw_settings_signal);
    }
    initialized = available = dirty = false;
}
#else
int
csd_native_titlebar_margin(_GLFWwindow *window UNUSED) {
    return 0;
}
bool
csd_native_titlebar_shadows(_GLFWwindow *window UNUSED) {
    return false;
}
int
csd_native_titlebar_height(_GLFWwindow *window UNUSED) {
    return 0;
}
bool
csd_native_titlebar_render(_GLFWwindow *window UNUSED, uint8_t *output UNUSED) {
    return false;
}
void
csd_native_titlebar_free(_GLFWwindow *window UNUSED) {}
void
csd_native_titlebar_terminate(void) {}
GLFWAPI bool
glfwWaylandUsesSystemTitlebar(void) {
    return false;
}
#endif
