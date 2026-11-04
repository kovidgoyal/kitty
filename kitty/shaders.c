/*
 * shaders.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"
#include "gpu.h"
#include "cleanup.h"
#include "colors.h"
#include <stddef.h>
#include <string.h>
#include "animation.h"
#include "animation-parse.h"
#include "text-cache.h"
#include "tupleobject.h"
#include "window_logo.h"
#include "srgb_gamma.h"
#include "state.h"

enum {
    CELL_PROGRAM,
    CELL_FG_PROGRAM,
    CELL_BG_PROGRAM,
    CELL_PROGRAM_SENTINEL,
    BORDERS_PROGRAM,
    GRAPHICS_PROGRAM,
    GRAPHICS_PREMULT_PROGRAM,
    GRAPHICS_ALPHA_MASK_PROGRAM,
    GRAPHICS_INDEXED_PROGRAM,
    GRAPHICS_INDEXED_UNSCALED_PROGRAM,
    BGIMAGE_PROGRAM,
    TINT_PROGRAM,
    TRAIL_PROGRAM,
    BLIT_PROGRAM,
    SCREENSHOT_PROGRAM,
    ROUNDED_RECT_PROGRAM,
    PADDING_PROGRAM,

    CUSTOM_END_PROGRAM,

    NUM_PROGRAMS
};
static_assert(NUM_PROGRAMS <= MAX_GPU_PROGRAMS, "Too many GPU programs");
// The binding slots of textures and uniform blocks come from the program
// metadata, see SHADER_BINDING_SLOTS in shaders/slang.py

typedef struct UIRenderData {
    unsigned screen_width, screen_height, cell_width, cell_height, screen_left, screen_top, full_framebuffer_width, full_framebuffer_height;
    Window *window;
    Screen *screen;
    OSWindow *os_window;
    GraphicsRenderData grd;
    WindowLogoRenderData *window_logo;
    float bg_alpha, inactive_text_alpha;
    bool has_background_image;
    color_type background_color; // RGB only
    monotonic_t now;
} UIRenderData;

static inline float
row_offset_for_screen(const Screen *screen) {
    if (!pixel_scroll_enabled(screen) || !screen->cell_size.height) return 0.f;
    return -1.f + (float)(rendered_pixel_scroll_offset_y(screen) / (double)screen->cell_size.height);
}

static inline float
scroll_offset_lines_for_screen(const Screen *screen) {
    if (!pixel_scroll_enabled(screen) || !screen->cell_size.height) return 0.f;
    return (float)(rendered_pixel_scroll_offset_y(screen) / (double)screen->cell_size.height);
}

// Sprites {{{
typedef struct {
    int xnum, ynum, x, y, z, last_num_of_layers, last_ynum;
    gpu_texture_t texture_id;
    int32_t max_texture_size, max_array_texture_layers;
    struct decorations_map {
        gpu_texture_t texture_id;
        unsigned width, height;
        size_t count;
    } decorations_map;
} SpriteMap;

static const SpriteMap NEW_SPRITE_MAP = {.xnum = 1, .ynum = 1, .last_num_of_layers = 1, .last_ynum = -1};
static int32_t max_texture_size = 0, max_array_texture_layers = 0;
// The number of bytes per cell in the buffers holding the selection state of
// cells. The state is a single byte, padded to the vertex input alignment
// required by the GPU driver, set in initialize_gpu().
static size_t selection_stride = 1;

static float
srgb_color(uint8_t color) {
    return srgb_lut[color];
}

static void
color_vec3(int32_t location, color_type color) {
    param_3f(location, srgb_lut[(color >> 16) & 0xFF], srgb_lut[(color >> 8) & 0xFF], srgb_lut[color & 0xFF]);
}

static void
color_vec4_premult(int32_t location, color_type color, float alpha) {
    param_4f(location, srgb_lut[(color >> 16) & 0xFF] * alpha, srgb_lut[(color >> 8) & 0xFF] * alpha, srgb_lut[color & 0xFF] * alpha, alpha);
}

static void
color_vec4(int32_t location, color_type color, float alpha) {
    param_4f(location, srgb_lut[(color >> 16) & 0xFF], srgb_lut[(color >> 8) & 0xFF], srgb_lut[color & 0xFF], alpha);
}

// Write a color into a std140 float4 whose fourth component is unused. Uses
// the same table as the shaders so the result is identical to converting the
// color in the shader.
static void
linear_color_vec4(float *dest, color_type color) {
    dest[0] = srgb_lut[(color >> 16) & 0xFF];
    dest[1] = srgb_lut[(color >> 8) & 0xFF];
    dest[2] = srgb_lut[color & 0xFF];
    dest[3] = 0.f;
}


static void
clear_current_framebuffer(void) {
    gpu_clear(0, 0, 0, 0);
}

// Must be called as soon as there is an initialized GPU driver, see
// initialize_gpu(). Font groups are created before that happens and size their
// sprite layout using these limits, so the sooner they are known the better.
static void
query_gpu_texture_limits(void) {
    if (max_texture_size || !gpu_driver.initialized) return;
    GPUCapabilities caps;
    gpu_get_capabilities(&caps);
    max_texture_size = (int32_t)caps.max_texture_size;
    max_array_texture_layers = (int32_t)caps.max_array_texture_layers;
    sprite_tracker_set_limits(max_texture_size, max_array_texture_layers);
}

SPRITE_MAP_HANDLE
alloc_sprite_map(void) {
    query_gpu_texture_limits();
    SpriteMap *ans = calloc(1, sizeof(SpriteMap));
    if (!ans) fatal("Out of memory allocating a sprite map");
    *ans = NEW_SPRITE_MAP;
    ans->max_texture_size = max_texture_size;
    ans->max_array_texture_layers = max_array_texture_layers;
    return (SPRITE_MAP_HANDLE)ans;
}

void
free_sprite_data(FONTS_DATA_HANDLE fg) {
    SpriteMap *sprite_map = (SpriteMap *)fg->sprite_map;
    if (sprite_map) {
        if (sprite_map->texture_id) free_texture(&sprite_map->texture_id);
        if (sprite_map->decorations_map.texture_id) free_texture(&sprite_map->decorations_map.texture_id);
        free(sprite_map);
        fg->sprite_map = NULL;
    }
}

static gpu_texture_t
create_texture_or_die(const GPUTextureDesc *desc, const GPUPixelData *initial) {
    gpu_texture_t ans = gpu_texture_create(desc, initial);
    if (!ans) fatal("Failed to create a GPU texture with error: %s", gpu_last_error());
    return ans;
}

static bool
decorations_map_new_size(size_t count, size_t current_capacity, size_t max_size, int32_t *width, int32_t *height) {
    const size_t max_capacity = max_size * max_size;
    if (count >= max_capacity) return false;
    size_t capacity = MAX(MAX(count + 256, current_capacity * 2), (size_t)4096);
    capacity = MIN(capacity, max_capacity);
    if (capacity <= max_size) {
        *width = capacity;
        *height = 1;
    } else {
        *width = max_size;
        *height = (capacity + max_size - 1) / max_size;
    }
    return true;
}

static void
realloc_sprite_decorations_texture_if_needed(FONTS_DATA_HANDLE fg) {
#define dm (sm->decorations_map)
    SpriteMap *sm = (SpriteMap *)fg->sprite_map;
    size_t current_capacity = (size_t)dm.width * dm.height;
    if (dm.count < current_capacity && dm.texture_id) return;
    int32_t width, height;
    if (!decorations_map_new_size(dm.count, current_capacity, sm->max_texture_size, &width, &height))
        fatal("Max texture size too small for sprite decorations map, maybe switch to using a GPU_TEXTURE_2D_ARRAY");
    // We use nearest filtering otherwise glyphs that touch the edge of the cell
    // often show a border between cells
    const GPUTextureDesc desc = {
        .kind = GPU_TEXTURE_2D, .format = GPU_FORMAT_R32UI, .width = width, .height = height, .filter = GPU_FILTER_NEAREST, .wrap = GPU_WRAP_CLAMP_TO_EDGE};
    gpu_texture_t tex = create_texture_or_die(&desc, NULL);
    if (dm.texture_id) { // copy data from old texture
        gpu_texture_copy(dm.texture_id, tex);
        free_texture(&dm.texture_id);
    }
    dm.texture_id = tex;
    dm.width = width;
    dm.height = height;
#undef dm
}

static void
realloc_sprite_texture(FONTS_DATA_HANDLE fg) {
    unsigned int xnum, ynum, z, znum, width, height;
    sprite_tracker_current_layout(fg, &xnum, &ynum, &z);
    znum = z + 1;
    SpriteMap *sprite_map = (SpriteMap *)fg->sprite_map;
    width = xnum * fg->fcm.cell_width;
    height = ynum * (fg->fcm.cell_height + 1);
    // We use nearest filtering otherwise glyphs that touch the edge of the cell
    // often show a border between cells
    const GPUTextureDesc desc = {
        .kind = GPU_TEXTURE_2D_ARRAY,
        .format = GPU_FORMAT_SRGB8_ALPHA8,
        .width = width,
        .height = height,
        .layers = znum,
        .filter = GPU_FILTER_NEAREST,
        .wrap = GPU_WRAP_CLAMP_TO_EDGE};
    gpu_texture_t tex = create_texture_or_die(&desc, NULL);
    if (sprite_map->texture_id) { // copy old texture data into new texture
        gpu_texture_copy(sprite_map->texture_id, tex);
        free_texture(&sprite_map->texture_id);
    }
    sprite_map->last_num_of_layers = znum;
    sprite_map->last_ynum = ynum;
    sprite_map->texture_id = tex;
}

static void
bind_sprite_map(const SpriteMap *sprite_map) {
    // The sprite textures are bound once and used by all the cell programs,
    // which share the same layout. They have binding slots distinct from those
    // of every other program, so drawing images in between does not displace them.
    uint32_t slot;
    // The cell programs are compiled only once the first OS window is created
    if (try_program_texture_slot(CELL_PROGRAM, "sprite_decorations_map", &slot)) gpu_bind_texture(slot, sprite_map->decorations_map.texture_id);
    if (try_program_texture_slot(CELL_PROGRAM, "sprites", &slot)) gpu_bind_texture(slot, sprite_map->texture_id);
}

static void
ensure_sprite_map(FONTS_DATA_HANDLE fg) {
    SpriteMap *sprite_map = (SpriteMap *)fg->sprite_map;
    if (!sprite_map->texture_id) realloc_sprite_texture(fg);
    if (!sprite_map->decorations_map.texture_id) realloc_sprite_decorations_texture_if_needed(fg);
    // We have to rebind since we don't know if the texture was ever bound
    // in the context of the current OSWindow
    bind_sprite_map(sprite_map);
}

void
send_sprite_to_gpu(FONTS_DATA_HANDLE fg, sprite_index idx, pixel *buf, sprite_index decoration_idx) {
    SpriteMap *sprite_map = (SpriteMap *)fg->sprite_map;
    unsigned int xnum, ynum, znum, x, y, z;
#define dm (sprite_map->decorations_map)
    if (idx >= dm.count) dm.count = idx + 1;
    realloc_sprite_decorations_texture_if_needed(fg);
    div_t d = div(idx, dm.width);
    x = d.rem;
    y = d.quot;
    const GPUPixelData decoration_pixels = {.layout = GPU_PIXELS_R32UI, .row_alignment = 4, .data = &decoration_idx};
    gpu_texture_upload(dm.texture_id, x, y, 0, 1, 1, &decoration_pixels);
#undef dm
    sprite_tracker_current_layout(fg, &xnum, &ynum, &znum);
    if ((int)znum >= sprite_map->last_num_of_layers || (znum == 0 && (int)ynum > sprite_map->last_ynum)) {
        realloc_sprite_texture(fg);
        sprite_tracker_current_layout(fg, &xnum, &ynum, &znum);
    }
    sprite_index_to_pos(idx, xnum, ynum, &x, &y, &z);
    x *= fg->fcm.cell_width;
    y *= (fg->fcm.cell_height + 1);
    const GPUPixelData sprite_pixels = {.layout = GPU_PIXELS_RGBA8_PACKED, .row_alignment = 4, .data = buf};
    gpu_texture_upload(sprite_map->texture_id, x, y, z, fg->fcm.cell_width, fg->fcm.cell_height + 1, &sprite_pixels);
    // Sprites are sent while preparing to render, after ensure_sprite_map(),
    // and the sprite textures may have been re-allocated, so rebind them.
    bind_sprite_map(sprite_map);
}

static void
define_texture(gpu_texture_t *tex_id, const GPUTextureDesc *desc, const GPUPixelData *pixels) {
    if (*tex_id) {
        if (!gpu_texture_reset(*tex_id, desc, pixels)) fatal("Failed to re-allocate GPU texture with error: %s", gpu_last_error());
    } else *tex_id = create_texture_or_die(desc, pixels);
}

void
send_image_to_gpu(
    gpu_texture_t *tex_id, const void *data, int32_t width, int32_t height, bool is_opaque, bool is_4byte_aligned, bool linear, RepeatStrategy repeat) {
    GPUWrap wrap;
    switch (repeat) {
        case REPEAT_MIRROR: wrap = GPU_WRAP_MIRRORED_REPEAT; break;
        case REPEAT_CLAMP: wrap = GPU_WRAP_CLAMP_TO_BORDER; break;
        default: wrap = GPU_WRAP_REPEAT;
    }
    const GPUTextureDesc desc = {
        .kind = GPU_TEXTURE_2D,
        .format = GPU_FORMAT_SRGB8_ALPHA8,
        .width = width,
        .height = height,
        .filter = linear ? GPU_FILTER_LINEAR : GPU_FILTER_NEAREST,
        .wrap = wrap};
    const GPUPixelData pixels = {.layout = is_opaque ? GPU_PIXELS_RGB8 : GPU_PIXELS_RGBA8, .row_alignment = is_4byte_aligned ? 4 : 1, .data = data};
    define_texture(tex_id, &desc, &pixels);
}

// Indexed color images are stored as integer textures with the palette index
// in the red channel and, if bytes_per_pixel is 2, alpha in the green channel.
// Integer textures cannot be filtered, the shader does its own filtering after
// the palette lookup.
void
send_indexed_image_to_gpu(gpu_texture_t *tex_id, const void *data, int32_t width, int32_t height, unsigned bytes_per_pixel, bool is_4byte_aligned) {
    const bool has_alpha = bytes_per_pixel == 2;
    const GPUTextureDesc desc = {
        .kind = GPU_TEXTURE_2D,
        .format = has_alpha ? GPU_FORMAT_RG8UI : GPU_FORMAT_R8UI,
        .width = width,
        .height = height,
        .filter = GPU_FILTER_NEAREST,
        .wrap = GPU_WRAP_CLAMP_TO_EDGE};
    const GPUPixelData pixels = {.layout = has_alpha ? GPU_PIXELS_RG8 : GPU_PIXELS_R8, .row_alignment = is_4byte_aligned ? 4 : 1, .data = data};
    define_texture(tex_id, &desc, &pixels);
}

// }}}

// Rounded rect {{{
static double
thickness_as_float(const OSWindow *os_window, unsigned level) {
    level = MIN(level, arraysz(OPT(box_drawing_scale)));
    double pts = OPT(box_drawing_scale)[level];
    double dpi = (os_window->fonts_data->logical_dpi_x + os_window->fonts_data->logical_dpi_y) / 2.0;
    return line_thickness_scale_for_font_size(os_window->fonts_data) * pts * dpi / 72.0;
}


static void
draw_rounded_rect(
    Viewport rect,
    float thickness,
    unsigned corner_radius_px,
    color_type srgb_color,
    color_type srgb_background,
    float bg_alpha,
    color_type srgb_outer,
    float outer_alpha) {
    bind_program(ROUNDED_RECT_PROGRAM);
    color_vec4(program_param(ROUNDED_RECT_PROGRAM, "color"), srgb_color, 1.f);
    color_vec4(program_param(ROUNDED_RECT_PROGRAM, "background_color"), srgb_background, bg_alpha);
    color_vec4(program_param(ROUNDED_RECT_PROGRAM, "outer_color"), srgb_outer, outer_alpha);
    param_2f(program_param(ROUNDED_RECT_PROGRAM, "size"), rect.width, rect.height);
    param_2f(program_param(ROUNDED_RECT_PROGRAM, "params"), thickness, corner_radius_px);
    save_viewport(rect.left, rect.top, rect.width, rect.height);
    draw_quad(true, 0);
    restore_viewport();
}
// }}}

// Cell {{{

enum { BORDER_COLORS_GLOBAL_BUFFER };
// VAOs used only to hold buffers for UBOs that are shared amongst programs/windows,
// their vertex attribute/array facilities are unused.
static ssize_t shader_globals_vao_idx = -1;
static ssize_t custom_end_vao_idx = -1;

typedef enum { CUSTOM_SHADER_TEXTURE_DEFAULT, CUSTOM_SHADER_TEXTURE_A, CUSTOM_SHADER_TEXTURE_B, CUSTOM_SHADER_TEXTURE_PERSIST } NamedTexture;

typedef struct CustomShaderGroup {
    struct {
        float x, y;
    } viewport_pos;
    struct {
        float w, h;
    } viewport_size;
    NamedTexture output_texture;
    ShaderAnimEventMask animation_start_events;  // events that start the animation; 0 = none
    ShaderAnimEventMask animation_toggle_events; // events that start the animation when stopped and vice versa; 0 = none
    ShaderAnimEventMask animation_end_events;    // events that stop the animation; 0 = none
    monotonic_t animation_end_duration;          // nanoseconds; 0 = no time limit, < 0 = use cursor_stop_blinking_after
    monotonic_t animation_duration;              // nanoseconds for animation_progress to reach one; < 0 = same as the stop duration
    monotonic_t animation_reverse;               // nanoseconds to play the animation in reverse when stopped; 0 = no, < 0 = animation_duration
    unsigned animation_loops;                    // times to play the animation forwards and in reverse when reversing
    monotonic_t animation_step;                  // nanoseconds between animation samples
    Animation *animation_curve;                  // parsed easing curve; NULL = no animation
    bool animation_curve_is_shared;              // true if animation_curve is owned by an earlier group
    bool attached;                               // true = always active when the preceding group is active
} CustomShaderGroup;

typedef struct CustomShaderPipeline {
    unsigned textures; // bit mask of named textures from above enum
    CustomShaderGroup groups[MAX_CUSTOM_SHADER_GROUPS];
    size_t num_groups;
    bool active;
    bool bypass_builtin_trail;                      // true when any group subscribes to cursor-trail-move
    ShaderAnimEventMask all_animation_start_events; // union of the start and toggle events of all groups
    bool has_pointer_map;                           // true when a shader defines pointer_map() to move pointer events
    uint32_t pointer_map_groups;                    // bitmask of the groups with shaders whose pointer_map() is used
    // Names (without the user: prefix) of the user events the pipeline uses,
    // user event i is bit SHADER_ANIM_FIRST_USER_EVENT + i
    char user_events[MAX_SHADER_ANIM_USER_EVENTS][MAX_SHADER_ANIM_USER_EVENT_NAME_LEN + 1];
    size_t num_user_events;
} CustomShaderPipeline;

static struct {
    CustomShaderPipeline end;
    size_t count;
    unsigned generation; // incremented every time the end pipeline changes
} custom_shaders;

static struct {
    gpu_texture_t texture_id;
    gpu_render_target_t framebuffer_id;
} pointer_map_target;

static void
write_uint_array_to_ubo(void *dest, const uint32_t *src, size_t count, const ArrayInformation *ai) {
    int32_t stride = MAX((int32_t)sizeof(uint32_t), ai->stride);
    uint8_t *buf = (uint8_t *)dest + ai->offset;
    for (size_t i = 0; i < count; i++, buf += stride) memcpy(buf, src + i, sizeof(uint32_t));
}

// The gamma LUT is a compile time constant that lives in the default uniform
// block of every program that needs it, rather than in a UBO shared between
// them. Uniform values are part of program object state, which the GL
// implementation must maintain, while the data store of a buffer object is
// ours and some drivers silently discard it, notably macOS waking from sleep
// or reconfiguring its displays. Every color in every affected program then
// resolves to garbage with nothing to ever restore it. Uploading it costs a
// single GL call per program, so this can simply be called again whenever we
// have reason to believe GPU state was lost.
// See https://github.com/kovidgoyal/kitty/issues/10571
void
upload_gamma_lut(void) {
#define U(program)                                                       \
    {                                                                    \
        bind_program(program);                                           \
        int32_t loc = program_param(program, "gamma_lut");               \
        if (loc >= 0) param_floats(loc, 1, arraysz(srgb_lut), srgb_lut); \
    }
    for (int i = CELL_PROGRAM; i < CELL_PROGRAM_SENTINEL; i++) U(i);
    U(BORDERS_PROGRAM);
    U(PADDING_PROGRAM);
    U(GRAPHICS_INDEXED_PROGRAM);
    U(GRAPHICS_INDEXED_UNSCALED_PROGRAM);
#undef U
    unbind_program();
}

static void
init_cell_program(void) {
    // Sanity check to ensure the attribute location binding worked
#define C(p, name, expected)                                                                                                             \
    {                                                                                                                                    \
        int aloc = attrib_location(p, #name);                                                                                            \
        if (aloc != expected && aloc != -1) fatal("The attribute location for %s is %d != %d in program: %d", #name, aloc, expected, p); \
    }
    for (int p = CELL_PROGRAM; p < CELL_PROGRAM_SENTINEL; p++) {
        C(p, colors, 0);
        C(p, sprite_idx, 1);
        C(p, is_selected, 2);
        C(p, decorations_sprite_map, 3);
    }
#undef C
    UniformBlock border_colors = program_uniform_block(BORDERS_PROGRAM, "Colors");

#define C(name, expected)                                                                                                                     \
    {                                                                                                                                         \
        int aloc = attrib_location(PADDING_PROGRAM, #name);                                                                                   \
        if (aloc != expected && aloc != -1) fatal("The attribute location for %s is %d != %d in the padding program", #name, aloc, expected); \
    }
    C(colors, 0);
    C(sprite_idx, 1);
    C(is_selected, 2);
#undef C
    // The sprite textures are bound once for all cell programs, see bind_sprite_map()
    for (int i = CELL_PROGRAM + 1; i < CELL_PROGRAM_SENTINEL; i++) {
        uint32_t a, b;
        if (try_program_texture_slot(i, "sprites", &a) && (!try_program_texture_slot(CELL_PROGRAM, "sprites", &b) || a != b))
            fatal("The cell programs use different binding slots for the sprites texture");
    }

    if (shader_globals_vao_idx == -1) {
        shader_globals_vao_idx = create_vao();
        add_buffer_to_vao(shader_globals_vao_idx, GPU_BUFFER_UNIFORM);
        // The border colors change on every draw, but are shared amongst all border VAOs (only one is ever drawn at a time)
        alloc_vao_buffer(shader_globals_vao_idx, border_colors.size, BORDER_COLORS_GLOBAL_BUFFER, GPU_UPDATE_EVERY_USE);
    }
    upload_gamma_lut();
    bind_shader_globals_to_current_context();
}

// Whether the group has events of its own that turn it on, as opposed to
// running on every frame or only following its predecessor via attach
static inline bool
group_has_own_animation(const CustomShaderGroup *cg) {
    return (cg->animation_start_events | cg->animation_toggle_events) != 0;
}

// Whether the group runs only when the animation state machine says it is active
static inline bool
group_is_animated(const CustomShaderGroup *cg) {
    return cg->attached || group_has_own_animation(cg);
}

// How long after starting the group stops by itself, zero if it does not
static inline monotonic_t
group_stop_duration(const CustomShaderGroup *cg) {
    return cg->animation_end_duration < 0 ? OPT(cursor_stop_blinking_after) : cg->animation_end_duration;
}

// How long animation_progress takes to rise to one, zero if it stays at zero
static inline monotonic_t
group_ramp_duration(const CustomShaderGroup *cg) {
    return cg->animation_duration < 0 ? group_stop_duration(cg) : cg->animation_duration;
}

// How long animation_progress takes to fall from one to zero after the group
// is stopped, zero if the group turns off immediately instead
static inline monotonic_t
group_reverse_duration(const CustomShaderGroup *cg) {
    return cg->animation_reverse < 0 ? group_ramp_duration(cg) : cg->animation_reverse;
}

// The animation_progress of an active group before applying the easing curve
static double
group_linear_progress(const CustomShaderGroup *cg, const ShaderGroupAnimState *s, monotonic_t now) {
    double ans = 0;
    if (s->reverse_ends_at) {
        const monotonic_t d = group_reverse_duration(cg);
        if (d > 0) ans = (double)(s->reverse_ends_at - now) / (double)d;
    } else {
        const monotonic_t d = group_ramp_duration(cg);
        if (d > 0) ans = (double)(now - s->ramp_started_at) / (double)d;
    }
    return MAX(0., MIN(ans, 1.));
}

// The animation_progress of every group in the current pipeline. Attached
// groups without events of their own share the progress of the group they are
// attached to, so that multi-pass effects animate in sync.
static void
custom_shader_group_progress(const OSWindow *os_window, monotonic_t now, float *ans) {
    for (size_t g = 0; g < custom_shaders.end.num_groups; g++) {
        const CustomShaderGroup *cg = custom_shaders.end.groups + g;
        const ShaderGroupAnimState *s = os_window->shader_group_anim + g;
        ans[g] = 0.f;
        if (!group_is_animated(cg) || !s->active) continue;
        if (g > 0 && cg->attached && !group_has_own_animation(cg)) {
            ans[g] = ans[g - 1];
            continue;
        }
        const double t = group_linear_progress(cg, s, now);
        ans[g] = (float)(cg->animation_curve ? apply_easing_curve(cg->animation_curve, t, group_ramp_duration(cg)) : t);
    }
}

static void
start_group_animation(const CustomShaderGroup *cg, ShaderGroupAnimState *s, monotonic_t now) {
    // Restarting while playing in reverse or looping continues from the
    // current progress rather than jumping back to zero
    if (s->active && (s->reverse_ends_at || s->looping)) {
        s->ramp_started_at = now - (monotonic_t)(group_linear_progress(cg, s, now) * (double)group_ramp_duration(cg));
    } else s->ramp_started_at = now;
    s->active = true;
    s->started_at = now;
    s->reverse_ends_at = 0;
    s->loops_left = 0;
    s->looping = false;
}

static void
stop_group_animation(const CustomShaderGroup *cg, ShaderGroupAnimState *s, monotonic_t now) {
    // Playing in reverse takes as long as falling from the current progress
    // to zero, so a group stopped part way through rising does not jump to one
    const monotonic_t reverse_for = (monotonic_t)(group_linear_progress(cg, s, now) * (double)group_reverse_duration(cg));
    if (reverse_for > 0) {
        s->reverse_ends_at = now + reverse_for;
        s->loops_left = cg->animation_loops > 1 ? cg->animation_loops - 1 : 0;
    } else s->active = false;
}

// Moves a group that is playing in reverse or looping on to whichever phase it
// should be in at now, turning it off once it has finished. The phases are
// advanced from the time the previous one ended rather than from now, so that
// loops do not drift when the state machine runs late.
static void
advance_stopped_group_animation(const CustomShaderGroup *cg, ShaderGroupAnimState *s, monotonic_t now, size_t i) {
    while (true) {
        if (s->reverse_ends_at && now >= s->reverse_ends_at) {
            if (s->loops_left) {
                s->loops_left--;
                s->ramp_started_at = s->reverse_ends_at;
                s->reverse_ends_at = 0;
                s->looping = true;
            } else {
                s->active = false;
                s->reverse_ends_at = 0;
                debug_rendering("Custom shader group %zu finished playing in reverse\n", i);
                break;
            }
        } else if (s->looping && now >= s->ramp_started_at + group_ramp_duration(cg)) {
            // Loops only start after a reverse, which needs both durations to be non-zero, so this terminates
            s->looping = false;
            s->reverse_ends_at = s->ramp_started_at + group_ramp_duration(cg) + group_reverse_duration(cg);
        } else break;
    }
}

// Non-animated, non-attached groups are active from the moment the pipeline
// loads; animated groups start inactive and attached groups inherit the state
// of their predecessor.
static bool
group_is_initially_active(const CustomShaderGroup *cg, bool predecessor_is_active) {
    return cg->attached ? predecessor_is_active : !group_has_own_animation(cg);
}

static bool
pipeline_has_initially_active_group(void) {
    bool prev = false;
    for (size_t i = 0; i < custom_shaders.end.num_groups; i++) {
        prev = group_is_initially_active(custom_shaders.end.groups + i, prev);
        if (prev) return true;
    }
    return false;
}

static void
init_custom_programs(void) {
    custom_shaders.count = 0;
    for (int i = CUSTOM_END_PROGRAM; i < NUM_PROGRAMS; i++) {
        if (program_pipeline(i)) {
            custom_shaders.count++;
            if (i == CUSTOM_END_PROGRAM) {
                bind_program(i);
                int32_t group_loc = try_program_param(i, "group");
                if (group_loc >= 0) param_1i(group_loc, 0);
                else if (custom_shaders.end.num_groups > 1) {
                    // Every group is dispatched by setting this uniform, so without it
                    // all of them render as group zero, which for a multi pass pipeline
                    // means the intermediate passes are drawn to the screen.
                    log_error(
                        "The custom shader pipeline has %zu groups but its group uniform was optimized away by the"
                        " GPU driver. Every group will render as group zero.",
                        custom_shaders.end.num_groups);
                }
                UniformBlock ubd = program_uniform_block(i, "KittyCustomShaderData");
                if (custom_end_vao_idx == -1) {
                    custom_end_vao_idx = create_vao();
                    add_buffer_to_vao(custom_end_vao_idx, GPU_BUFFER_UNIFORM);
                    alloc_vao_buffer(custom_end_vao_idx, ubd.size, 0, GPU_UPDATE_EVERY_USE);
                }
            }
        }
    }
    // Free global named textures that are no longer declared in the pipeline
    const bool drop_a = !(custom_shaders.end.textures & (1u << CUSTOM_SHADER_TEXTURE_A));
    const bool drop_b = !(custom_shaders.end.textures & (1u << CUSTOM_SHADER_TEXTURE_B));
    if (drop_a) {
        if (global_state.layers_render_texture.texture_a_id) free_texture(&global_state.layers_render_texture.texture_a_id);
        if (global_state.layers_render_texture.texture_a_fbo_id) free_framebuffer(&global_state.layers_render_texture.texture_a_fbo_id);
    }
    if (drop_b) {
        if (global_state.layers_render_texture.texture_b_id) free_texture(&global_state.layers_render_texture.texture_b_id);
        if (global_state.layers_render_texture.texture_b_fbo_id) free_framebuffer(&global_state.layers_render_texture.texture_b_fbo_id);
    }
    // persist is per-window and freed lazily in start_os_window_rendering
    for (size_t w = 0; w < global_state.num_os_windows; w++) {
        OSWindow *osw = global_state.os_windows + w;
        // Per window framebuffers must be attached afresh to the textures that
        // replace the ones freed above, should a later pipeline declare them again
        if (drop_a) osw->indirect_output.fbo_a_generation = 0;
        if (drop_b) osw->indirect_output.fbo_b_generation = 0;
        init_shader_animation_state(osw);
        // Synthesize focus events for windows that already have focus so that
        // animations triggered by os-window-focus-in start on the first render
        // after shader compilation (the focus-in event fired before shaders were
        // compiled and was consumed without being processed).
        if (osw->is_focused) { osw->shader_anim_event_registry |= (1u << SHADER_ANIM_EVENT_OS_WINDOW_FOCUS_IN) | (1u << SHADER_ANIM_EVENT_WINDOW_FOCUS_IN); }
    }
    debug_rendering(
        "Custom shaders: %zu program(s), %zu group(s), textures_mask=0x%x, initially_active=%d\n",
        custom_shaders.count,
        custom_shaders.end.num_groups,
        custom_shaders.end.textures,
        custom_shaders.count > 0 && pipeline_has_initially_active_group());
}

// Reset the per-OS-window animation state to what it should be immediately
// after the current pipeline was loaded. Called both when the pipeline changes
// and when an OS window is created, so that the MONOTONIC_T_MAX sentinels in
// ShaderAnimState are never left at their zero initialized values -- a zero
// min_step/next_end_at reads as "an animation is running and its deadline has
// already passed", which would make the renderer redraw on every single tick.
void
init_shader_animation_state(OSWindow *osw) {
    zero_at_ptr_count(osw->shader_group_anim, custom_shaders.end.num_groups);
    bool prev_init = false, any_initially_active = false;
    for (size_t i = 0; i < custom_shaders.end.num_groups; i++) {
        const CustomShaderGroup *cg = &custom_shaders.end.groups[i];
        const bool this_init = group_is_initially_active(cg, prev_init);
        // Only attached groups are tracked by the state machine when initially
        // active; always-active non-attached groups never enter it at all.
        if (cg->attached && this_init) osw->shader_group_anim[i].active = true;
        if (this_init) any_initially_active = true;
        prev_init = this_init;
    }
    osw->shader_anim.has_active_shaders = custom_shaders.count > 0 && any_initially_active;
    osw->shader_anim.min_step = MONOTONIC_T_MAX;
    osw->shader_anim.next_end_at = MONOTONIC_T_MAX;
}

static const char *
shader_anim_event_mask_str(ShaderAnimEventMask mask) {
    static char buf[256];
    char *p = buf;
    char *const end = buf + sizeof(buf) - 1;
    static const struct {
        ShaderAnimEventMask bit;
        const char *name;
    } events[] = {
        {1u << SHADER_ANIM_EVENT_POINTER_LEFT_BUTTON_PRESS, "pointer-left-button-press"},
        {1u << SHADER_ANIM_EVENT_OS_WINDOW_FOCUS_IN, "os-window-focus-in"},
        {1u << SHADER_ANIM_EVENT_OS_WINDOW_FOCUS_OUT, "os-window-focus-out"},
        {1u << SHADER_ANIM_EVENT_WINDOW_FOCUS_IN, "window-focus-in"},
        {1u << SHADER_ANIM_EVENT_WINDOW_FOCUS_OUT, "window-focus-out"},
        {1u << SHADER_ANIM_EVENT_TAB_CHANGE, "tab-change"},
        {1u << SHADER_ANIM_EVENT_BELL_IN_WINDOW, "bell-in-window"},
        {1u << SHADER_ANIM_EVENT_USER_ACTIVITY, "user-activity"},
        {1u << SHADER_ANIM_EVENT_USER_IDLE, "user-idle"},
        {1u << SHADER_ANIM_EVENT_CURSOR_TRAIL_MOVE, "cursor-trail-move"},
        {1u << SHADER_ANIM_EVENT_CURSOR_TRAIL_STOP, "cursor-trail-stop"},
        {1u << SHADER_ANIM_EVENT_COMMAND_START, "command-start"},
        {1u << SHADER_ANIM_EVENT_COMMAND_FINISH, "command-finish"},
        {1u << SHADER_ANIM_EVENT_ALTERNATE_SCREEN_ENTER, "alternate-screen-enter"},
        {1u << SHADER_ANIM_EVENT_ALTERNATE_SCREEN_EXIT, "alternate-screen-exit"},
    };
    bool first = true;
    for (size_t i = 0; i < sizeof(events) / sizeof(events[0]); i++) {
        if (!(mask & events[i].bit)) continue;
        if (!first && p < end) *p++ = '|';
        size_t len = strlen(events[i].name);
        if (p + len >= end) break;
        memcpy(p, events[i].name, len);
        p += len;
        first = false;
    }
    for (size_t i = 0; i < custom_shaders.end.num_user_events; i++) {
        if (!(mask & (1ull << (SHADER_ANIM_FIRST_USER_EVENT + i)))) continue;
        if (!first && p < end) *p++ = '|';
        int n = snprintf(p, end - p + 1, "user:%s", custom_shaders.end.user_events[i]);
        if (n < 0 || p + n >= end) break;
        p += n;
        first = false;
    }
    if (first) {
        memcpy(buf, "(none)", 7);
    } else {
        *p = '\0';
    }
    return buf;
}

monotonic_t
update_custom_shader_animations(ShaderAnimEventMask event_mask, monotonic_t now, OSWindow *os_window) {
    if (!custom_shaders.count) {
        os_window->shader_anim = (ShaderAnimState){.min_step = MONOTONIC_T_MAX, .next_end_at = MONOTONIC_T_MAX};
        return MONOTONIC_T_MAX;
    }
    // Fast path: no events and no duration-bounded animation expiring this frame.
    // Cached state is still valid — skip group iteration entirely.
    if (!event_mask && now < os_window->shader_anim.next_end_at) return os_window->shader_anim.min_step;

    // Slow path: update per-group state and recompute cached values in one pass.
    CustomShaderPipeline *p = &custom_shaders.end;
    bool any_active = false;
    monotonic_t min_step = MONOTONIC_T_MAX;
    monotonic_t next_end = MONOTONIC_T_MAX;
    bool prev_active = false;
    for (size_t i = 0; i < p->num_groups; i++) {
        const CustomShaderGroup *cg = &p->groups[i];
        bool this_active;
        if (!group_is_animated(cg)) {
            // Always-active, non-attached group — never enters the state machine.
            any_active = true;
            this_active = true;
            min_step = MIN(min_step, cg->animation_step);
        } else {
            const monotonic_t eff_dur = group_stop_duration(cg);
            ShaderGroupAnimState *s = os_window->shader_group_anim + i;
            if (group_has_own_animation(cg)) {
                advance_stopped_group_animation(cg, s, now, i);
                // Whether the group is on, as opposed to off or playing in reverse or looping after being stopped
                const bool was_on = s->active && !s->reverse_ends_at && !s->looping;
                // Focus-out events are hard stops: if a focus-out stop condition is present in
                // the same tick as a start event (e.g. user-activity fired by the click that
                // moved focus away), the focus-out wins and the animation is not restarted.
                const ShaderAnimEventMask focus_out_mask = (1u << SHADER_ANIM_EVENT_OS_WINDOW_FOCUS_OUT) | (1u << SHADER_ANIM_EVENT_WINDOW_FOCUS_OUT);
                const bool hard_stop = (cg->animation_end_events & event_mask & focus_out_mask) != 0;
                // A simultaneous start and end lets start win, except for focus-out
                // events which act as hard stops.
                bool turn_on = false, turn_off = false;
                if (was_on) {
                    turn_off = (cg->animation_end_events && (event_mask & cg->animation_end_events)) || (eff_dur > 0 && now - s->started_at >= eff_dur);
                }
                if ((event_mask & cg->animation_start_events) && !hard_stop) turn_on = true;
                // A toggle flips the state the group had before this tick and so
                // takes precedence over simultaneous start and stop events.
                if (event_mask & cg->animation_toggle_events) {
                    turn_on = !was_on && !hard_stop;
                    turn_off = was_on;
                }
                if (turn_on) {
                    start_group_animation(cg, s, now);
                    debug_rendering("Custom shader group %zu animation started (events=%s)\n", i, shader_anim_event_mask_str(event_mask));
                } else if (turn_off) {
                    stop_group_animation(cg, s, now);
                    debug_rendering(
                        "Custom shader group %zu animation stopped%s (events=%s)\n",
                        i,
                        s->active ? ", playing in reverse" : "",
                        shader_anim_event_mask_str(event_mask));
                }
            }
            // Attach: follow the previous group's effective active state.
            if (cg->attached) {
                if (prev_active && !s->active) {
                    s->active = true;
                    // Sync animation timing with the previous group when possible.
                    monotonic_t prev_started = (i > 0) ? os_window->shader_group_anim[i - 1].started_at : 0;
                    s->started_at = prev_started ? prev_started : now;
                    s->ramp_started_at = s->started_at;
                    s->reverse_ends_at = 0;
                    s->loops_left = 0;
                    s->looping = false;
                    debug_rendering("Custom shader group %zu activated via attach\n", i);
                } else if (!prev_active && !group_has_own_animation(cg) && s->active) {
                    // No own events: mirror the previous group's deactivation.
                    s->active = false;
                }
            }
            this_active = s->active;
            if (this_active) {
                any_active = true;
                min_step = MIN(min_step, cg->animation_step);
                // Only track next_end for groups with own stop conditions; attached-only groups
                // deactivate when their predecessor does (already tracked by the predecessor).
                if (group_has_own_animation(cg)) {
                    if (s->reverse_ends_at) next_end = MIN(next_end, s->reverse_ends_at);
                    else if (s->looping) next_end = MIN(next_end, s->ramp_started_at + group_ramp_duration(cg));
                    else if (eff_dur > 0) next_end = MIN(next_end, s->started_at + eff_dur);
                }
            }
        }
        prev_active = this_active;
    }
    bool prev_has_active = os_window->shader_anim.has_active_shaders;
    if (prev_has_active != any_active) debug_rendering("has_active_shaders: %d -> %d\n", prev_has_active, any_active);
    os_window->shader_anim.has_active_shaders = any_active;
    os_window->shader_anim.min_step = min_step;
    os_window->shader_anim.next_end_at = next_end;
    return min_step;
}

// The bit for the user event with the specified name (without the user:
// prefix) in the current pipeline, zero if the pipeline does not use it
static ShaderAnimEventMask
user_event_bit(const char *name) {
    for (size_t i = 0; i < custom_shaders.end.num_user_events; i++) {
        if (strcmp(custom_shaders.end.user_events[i], name) == 0) return 1ull << (SHADER_ANIM_FIRST_USER_EVENT + i);
    }
    return 0;
}

// Queue the user event with the specified name for the OS window with the
// specified id, or for all OS windows when the id is zero. Returns false when
// the current pipeline does not use the event.
static bool
fire_custom_shader_user_event(const char *name, id_type os_window_id) {
    const ShaderAnimEventMask bit = user_event_bit(name);
    if (!bit) {
        debug_rendering("Ignoring the custom shader event user:%s as the current pipeline does not use it\n", name);
        return false;
    }
    bool queued = false;
    for (size_t i = 0; i < global_state.num_os_windows; i++) {
        OSWindow *osw = global_state.os_windows + i;
        if (os_window_id && osw->id != os_window_id) continue;
        osw->shader_anim_event_registry |= bit;
        queued = true;
    }
    if (queued) wakeup_main_loop();
    return true;
}

// Decide whether the custom shader layer needs a frame drawn this tick, given
// the cached state from the previous tick and the state just recomputed by
// update_custom_shader_animations(). Kept separate from the renderer so it can
// be unit tested -- see test_custom_shader_redraw_logic.
bool
custom_shader_needs_render(const ShaderAnimState *before, const ShaderAnimState *after, ShaderAnimEventMask event_mask, monotonic_t now) {
    // Groups turned on or off: draw once so the change becomes visible. This is
    // what produces the final frame that clears a finished effect.
    if (before->has_active_shaders != after->has_active_shaders) return true;
    // A duration bounded animation expires on this tick.
    if (now >= before->next_end_at) return true;
    // Something was animating last tick, so it either wants its next frame or
    // has just stopped and wants one last one.
    if (before->min_step < MONOTONIC_T_MAX) return true;
    if (!after->has_active_shaders) return false;
    // Animated groups need periodic frames. Static groups (animation_step 0)
    // only need one when an event may have changed what they draw; everything
    // else that changes the screen requests a redraw through other paths.
    return event_mask != 0 || after->min_step < MONOTONIC_T_MAX;
}

void
bind_shader_globals_to_current_context(void) {
    if (shader_globals_vao_idx == -1) return;
    bind_vao_uniform_buffer(shader_globals_vao_idx, BORDER_COLORS_GLOBAL_BUFFER, program_uniform_block(BORDERS_PROGRAM, "Colors").slot);
}

#define CELL_BUFFERS enum { cell_data_buffer, selection_buffer, uniform_buffer, color_table_buffer, padding_cell_data_buffer, padding_selection_buffer };

ssize_t
create_cell_vao(void) {
    ssize_t vao_idx = create_vao();
#define A(name, size, dtype, offset, stride) \
    add_attribute_to_vao(                    \
        vao_idx, program_attribute_location(CELL_PROGRAM, name), /*size=*/size, /*dtype=*/dtype, /*stride=*/stride, /*offset=*/offset, /*divisor=*/1);
#define A1(name, size, dtype, offset) A(name, size, dtype, offsetof(GPUCell, offset), sizeof(GPUCell))

    add_buffer_to_vao(vao_idx, GPU_BUFFER_VERTEX);
    A1("sprite_idx", 2, GPU_ATTRIB_U32, sprite_idx);
    A1("colors", 3, GPU_ATTRIB_U32, fg);

    add_buffer_to_vao(vao_idx, GPU_BUFFER_VERTEX);
    A("is_selected", 1, GPU_ATTRIB_U8, 0, (uint32_t)selection_stride);

    size_t bufnum = add_buffer_to_vao(vao_idx, GPU_BUFFER_UNIFORM);
    alloc_vao_buffer(vao_idx, program_uniform_block(CELL_PROGRAM, "CellRenderData").size, bufnum, GPU_UPDATE_EVERY_USE);

    size_t ctbufnum = add_buffer_to_vao(vao_idx, GPU_BUFFER_UNIFORM);
    alloc_vao_buffer(vao_idx, program_uniform_block(CELL_PROGRAM, "ColorTable").size, ctbufnum, GPU_UPDATE_RARELY);

    add_buffer_to_vao(vao_idx, GPU_BUFFER_VERTEX); // padding_cell_data_buffer (slot 4)
    add_buffer_to_vao(vao_idx, GPU_BUFFER_VERTEX); // padding_selection_buffer  (slot 5)

    return vao_idx;
#undef A
#undef A1
}

#define IS_SPECIAL_COLOR(name)                                          \
    (screen->color_profile->overridden.name.type == COLOR_IS_SPECIAL || \
     (screen->color_profile->overridden.name.type == COLOR_NOT_SET && screen->color_profile->configured.name.type == COLOR_IS_SPECIAL))

static float
cursor_color_luminance(color_type color) {
    // Match color_to_vec() and contrast_ratio() in background.slang.
    return 0.2126f * srgb_lut[(color >> 16) & 0xff] + 0.7152f * srgb_lut[(color >> 8) & 0xff] + 0.0722f * srgb_lut[color & 0xff];
}

static float
cursor_color_contrast(color_type a, color_type b) {
    const float la = cursor_color_luminance(a), lb = cursor_color_luminance(b);
    return (MAX(la, lb) + 0.05f) / (MIN(la, lb) + 0.05f);
}

static void
pick_cursor_color(color_type cell_fg, color_type cell_bg, color_type *cursor_fg, color_type *cursor_bg, color_type default_fg, color_type default_bg) {
    *cursor_fg = cell_bg;
    *cursor_bg = cell_fg;
    const float cell_contrast = cursor_color_contrast(cell_fg, cell_bg);
    if (cell_contrast < 2.5) {
        if (cursor_color_contrast(default_fg, default_bg) > cell_contrast) {
            *cursor_fg = default_bg;
            *cursor_bg = default_fg;
        }
    }
}

static uint8_t
dimmed_color_component(uint8_t fg, uint8_t bg, float opacity) {
    // DIM blends text with the cell background in linear color space.
    const float linear = (1.f - opacity) * srgb_lut[bg] + opacity * srgb_lut[fg];
    const float srgb = linear <= 0.0031308f ? 12.92f * linear : 1.055f * powf(linear, 1.f / 2.4f) - 0.055f;
    return (uint8_t)lroundf(255.f * srgb);
}

static color_type
dimmed_cursor_color(color_type fg, color_type bg, float opacity) {
    if (opacity >= 1.f) return fg;
    return ((color_type)dimmed_color_component((fg >> 16) & 0xff, (bg >> 16) & 0xff, opacity) << 16) |
           ((color_type)dimmed_color_component((fg >> 8) & 0xff, (bg >> 8) & 0xff, opacity) << 8) |
           (color_type)dimmed_color_component(fg & 0xff, bg & 0xff, opacity);
}

static bool
has_bgimage(OSWindow *w) {
    return background_image_for_os_window(w) != NULL;
}

// The value resolve_dynamic_color() in background.slang needs for the color
// types that are an actual color. The other two types resolve to colors that
// are only known per-cell, so the shader ignores this value for them.
static color_type
dynamic_color_for_gpu(const ColorProfile *cp, color_type val) {
    const DynamicColor dc = {.val = val}, zero = {0};
    if (dc.type != COLOR_IS_RGB && dc.type != COLOR_IS_INDEX) return 0;
    return colorprofile_to_color(cp, dc, zero).rgb;
}

static color_type
cell_update_uniform_block(
    ssize_t vao_idx,
    Screen *screen,
    int uniform_buffer,
    int color_table_buf,
    const CursorRenderInfo *cursor,
    OSWindow *os_window,
    float inactive_text_alpha,
    float bg_alpha) {
    struct GPUCellRenderData {
        // Colors that are constant for the whole draw, pre-converted to linear
        // space so the vertex shader does not do a gamma LUT lookup for them
        // once per vertex. These must come first and the fourth component of
        // each is unused padding, see CellRenderData in background.slang.
        float default_fg_lin[4], default_bg_lin[4], highlight_fg_lin[4], highlight_bg_lin[4];
        float main_cursor_fg_lin[4], main_cursor_bg_lin[4], url_color_lin[4];
        float extra_cursor_fg_lin[4], extra_cursor_bg_lin[4];

        float use_cell_bg_for_selection_fg, use_cell_fg_for_selection_color, use_cell_for_selection_bg;

        uint32_t default_fg, url_style, inverted, main_cursor_is_special, extra_cursor_fg, extra_cursor_bg;

        uint32_t columns, lines, sprites_xnum, sprites_ynum, cursor_shape, cell_width, cell_height;
        uint32_t cursor_x1, cursor_x2, cursor_y1, cursor_y2;
        float cursor_opacity, inactive_text_alpha, fg_override_threshold, row_offset, dim_opacity, blink_opacity;

        uint32_t bg_colors0, bg_colors1, bg_colors2, bg_colors3, bg_colors4, bg_colors5, bg_colors6, bg_colors7;
        float bg_opacities0, bg_opacities1, bg_opacities2, bg_opacities3, bg_opacities4, bg_opacities5, bg_opacities6, bg_opacities7;
    };
    // Send the uniform data
    ColorProfile *cp = screen->paused_rendering.expires_at ? &screen->paused_rendering.color_profile : screen->color_profile;
    if (cp->dirty || screen->reload_all_gpu_data) {
        const ArrayInformation ai = program_uniform_array(CELL_PROGRAM, "color_table");
        uint8_t *base = (uint8_t *)map_vao_buffer_for_write_only(vao_idx, color_table_buf, 0, program_uniform_block(CELL_PROGRAM, "ColorTable").size);
        uint32_t *ct_buf = (uint32_t *)(base + ai.offset);
        copy_color_table_to_buffer(cp, ct_buf, 0, ai.stride / sizeof(uint32_t));
        unmap_vao_buffer(vao_idx, color_table_buf);
    }
    // This struct is a hand written mirror of the std140 layout of
    // CellRenderData in background.slang, a mismatch silently corrupts every
    // color, so check it once.
    const UniformBlock crd_block = program_uniform_block(CELL_PROGRAM, "CellRenderData");
    static bool crd_block_size_checked = false;
    if (!crd_block_size_checked) {
        crd_block_size_checked = true;
        if ((size_t)crd_block.size < sizeof(struct GPUCellRenderData))
            fatal("The CellRenderData uniform block is %d bytes but the C struct mirroring it is %zu bytes", crd_block.size, sizeof(struct GPUCellRenderData));
    }
    struct GPUCellRenderData *rd = (struct GPUCellRenderData *)map_vao_buffer_for_write_only(vao_idx, uniform_buffer, 0, crd_block.size);
#define COLOR(name) colorprofile_to_color(cp, cp->overridden.name, cp->configured.name).rgb
    // The shaders need these only in linear space, they are converted and
    // written into rd just before the buffer is unmapped. The cursor colors
    // are left as is when there is no cursor to render.
    const color_type highlight_fg = COLOR(highlight_fg), highlight_bg = COLOR(highlight_bg);
    color_type main_cursor_fg = 0, main_cursor_bg = 0;
    rd->default_fg = COLOR(default_fg);
    rd->extra_cursor_fg = screen->extra_cursors.color.text.val;
    rd->extra_cursor_bg = screen->extra_cursors.color.cursor.val;
    rd->main_cursor_is_special = IS_SPECIAL_COLOR(cursor_color);
    rd->bg_colors0 = COLOR(default_bg);
    rd->bg_opacities0 = bg_alpha;
    rd->fg_override_threshold = OPT(text_fg_override_threshold);
    rd->row_offset = row_offset_for_screen(screen);
#define SETBG(which) \
    { colorprofile_to_transparent_color(cp, which - 1, &rd->bg_colors##which, &rd->bg_opacities##which); }
    SETBG(1);
    SETBG(2);
    SETBG(3);
    SETBG(4);
    SETBG(5);
    SETBG(6);
    SETBG(7);
#undef SETBG
    // selection
    if (IS_SPECIAL_COLOR(highlight_fg)) {
        if (IS_SPECIAL_COLOR(highlight_bg)) {
            rd->use_cell_bg_for_selection_fg = 1.f;
            rd->use_cell_fg_for_selection_color = 0.f;
        } else {
            rd->use_cell_bg_for_selection_fg = 0.f;
            rd->use_cell_fg_for_selection_color = 1.f;
        }
    } else {
        rd->use_cell_bg_for_selection_fg = 0.f;
        rd->use_cell_fg_for_selection_color = 0.f;
    }
    rd->use_cell_for_selection_bg = IS_SPECIAL_COLOR(highlight_bg) ? 1. : 0.;
    // Cursor position
    Line *line_for_cursor = NULL, overlay_line_for_cursor;
    rd->cursor_opacity = MAX(0, MIN(cursor->cursor_opacity, 1));
    rd->blink_opacity = MAX(0, MIN(cursor->text_blink_opacity, 1));
    // The extra cursors inherit the colors of the main cursor and, optionally,
    // its shape, so the main cursor render data must be computed even when the
    // main cursor itself is hidden by DECTCEM.
    if (rd->cursor_opacity != 0 && (cursor->is_visible || cursor->multicursor_count)) {
        rd->cursor_x1 = cursor->x, rd->cursor_y1 = cursor->y;
        rd->cursor_x2 = cursor->x, rd->cursor_y2 = cursor->y;
        if (pixel_scroll_enabled(screen)) {
            rd->cursor_y1 += 1;
            rd->cursor_y2 += 1;
        }
        CursorShape cs = (cursor->is_focused || OPT(cursor_shape_unfocused) == NO_CURSOR_SHAPE) ? cursor->shape : OPT(cursor_shape_unfocused);
        rd->cursor_shape = cs;
        color_type cell_fg = rd->default_fg, cell_bg = rd->bg_colors0;
        index_type cell_color_x = cursor->x;
        bool reversed = false;
        if (cursor->x < screen->columns && cursor->y < screen->lines) {
            if (screen->paused_rendering.expires_at) {
                linebuf_init_line(screen->paused_rendering.linebuf, cursor->y);
                line_for_cursor = screen->paused_rendering.linebuf->line;
            } else {
                linebuf_init_line(screen->linebuf, cursor->y);
                line_for_cursor = screen->linebuf->line;
                if (screen_is_overlay_active(screen) && cursor->y == screen->overlay_line.ynum) {
                    // The linebuf holds the original line, the pre-edit text is
                    // drawn over it only in the overlay cells, so use those to size
                    // and color the cursor, for example when it is over a wide character.
                    overlay_line_for_cursor = *line_for_cursor;
                    overlay_line_for_cursor.cpu_cells = screen->overlay_line.cpu_cells;
                    overlay_line_for_cursor.gpu_cells = screen->overlay_line.gpu_cells;
                    line_for_cursor = &overlay_line_for_cursor;
                }
            }
        }
        if (line_for_cursor) {
            colors_for_cell(line_for_cursor, cp, &cell_color_x, &cell_fg, &cell_bg, &reversed);
            const CPUCell *cursor_cell;
            const bool large_cursor = ((cursor_cell = &line_for_cursor->cpu_cells[cursor->x])->is_multicell) && cursor_cell->x == 0 && cursor_cell->y == 0;
            if (large_cursor) {
                switch (cs) {
                    case CURSOR_BEAM: rd->cursor_y2 += cursor_cell->scale - 1; break;
                    case CURSOR_UNDERLINE:
                        rd->cursor_y1 += cursor_cell->scale - 1;
                        rd->cursor_y2 = rd->cursor_y1;
                        rd->cursor_x2 += mcd_x_limit(cursor_cell) - 1;
                        break;
                    case CURSOR_BLOCK:
                        rd->cursor_y2 += cursor_cell->scale - 1;
                        rd->cursor_x2 += mcd_x_limit(cursor_cell) - 1;
                        break;
                    case CURSOR_HOLLOW:
                    case NUM_OF_CURSOR_SHAPES:
                    case NO_CURSOR_SHAPE: break;
                };
            }
        }
        // If you change the following algorithm remember to change it in the cell shader for extra cursors too
        if (rd->main_cursor_is_special) {
            if (line_for_cursor && line_for_cursor->gpu_cells[cell_color_x].attrs.dim) {
                cell_fg = dimmed_cursor_color(cell_fg, cell_bg, OPT(dim_opacity));
                pick_cursor_color(cell_fg, cell_bg, &main_cursor_fg, &main_cursor_bg, rd->default_fg, rd->bg_colors0);
            } else if (cell_bg == cell_fg) {
                main_cursor_fg = rd->bg_colors0;
                main_cursor_bg = rd->default_fg;
            } else {
                main_cursor_fg = cell_bg;
                main_cursor_bg = cell_fg;
            }
        } else {
            main_cursor_bg = COLOR(cursor_color);
            if (IS_SPECIAL_COLOR(cursor_text_color)) main_cursor_fg = cell_bg;
            else main_cursor_fg = COLOR(cursor_text_color);
        }
        // store last rendered cursor color for trail rendering
        screen->last_rendered.cursor_bg = main_cursor_bg;
        if (!cursor->is_visible) {
            // Move the main cursor off screen so that only it is hidden, the
            // extra cursors keep their shape and colors.
            rd->cursor_x1 = screen->columns + 1;
            rd->cursor_x2 = screen->columns;
            rd->cursor_y1 = screen->lines + 1;
            rd->cursor_y2 = screen->lines;
        }
    } else {
        rd->cursor_shape = 0;
        rd->cursor_x1 = screen->columns + 1;
        rd->cursor_x2 = screen->columns;
        rd->cursor_y1 = screen->lines + 1;
        rd->cursor_y2 = screen->lines;
    }

    rd->columns = screen->columns;
    rd->lines = screen->lines;

    unsigned int x, y, z;
    sprite_tracker_current_layout(os_window->fonts_data, &x, &y, &z);
    rd->sprites_xnum = x;
    rd->sprites_ynum = y;
    rd->inverted = screen_invert_colors(screen) ? 1 : 0;
    rd->cell_width = os_window->fonts_data->fcm.cell_width;
    rd->cell_height = os_window->fonts_data->fcm.cell_height;
    rd->inactive_text_alpha = inactive_text_alpha;
    rd->dim_opacity = OPT(dim_opacity);

#undef COLOR
    rd->url_style = OPT(url_style);
    linear_color_vec4(rd->default_fg_lin, rd->default_fg);
    linear_color_vec4(rd->default_bg_lin, rd->bg_colors0);
    linear_color_vec4(rd->highlight_fg_lin, highlight_fg);
    linear_color_vec4(rd->highlight_bg_lin, highlight_bg);
    linear_color_vec4(rd->main_cursor_fg_lin, main_cursor_fg);
    linear_color_vec4(rd->main_cursor_bg_lin, main_cursor_bg);
    linear_color_vec4(rd->url_color_lin, OPT(url_color));
    linear_color_vec4(rd->extra_cursor_fg_lin, dynamic_color_for_gpu(cp, rd->extra_cursor_fg));
    linear_color_vec4(rd->extra_cursor_bg_lin, dynamic_color_for_gpu(cp, rd->extra_cursor_bg));
    color_type default_bg = rd->bg_colors0;
    unmap_vao_buffer(vao_idx, uniform_buffer);
    rd = NULL;
    return default_bg;
}

static bool
cell_prepare_to_render(ssize_t vao_idx, Screen *screen, FONTS_DATA_HANDLE fonts_data) {
    size_t sz;
    CELL_BUFFERS;
    void *address;
    bool changed = false;

    ensure_sprite_map(fonts_data);
    const Cursor *cursor = screen->paused_rendering.expires_at ? &screen->paused_rendering.cursor : screen->cursor;

    bool cursor_pos_changed = cursor->x != screen->last_rendered.cursor.x || cursor->y != screen->last_rendered.cursor.y;
    bool disable_ligatures = screen->disable_ligatures == DISABLE_LIGATURES_CURSOR;
    bool screen_resized = screen->last_rendered.columns != screen->columns || screen->last_rendered.lines != screen->lines;

#define update_cell_data                                                                               \
    {                                                                                                  \
        const unsigned int render_lines = render_lines_for_screen(screen);                             \
        sz = sizeof(GPUCell) * render_lines * screen->columns;                                         \
        address = alloc_and_map_vao_buffer_for_full_rewrite(vao_idx, sz, cell_data_buffer);            \
        screen_update_cell_data(screen, address, fonts_data, disable_ligatures && cursor_pos_changed); \
        unmap_vao_buffer(vao_idx, cell_data_buffer);                                                   \
        address = NULL;                                                                                \
        changed = true;                                                                                \
    }

    if (screen->paused_rendering.expires_at) {
        if (!screen->paused_rendering.cell_data_updated) update_cell_data;
    } else if (screen->reload_all_gpu_data || screen->scroll_changed || screen->is_dirty || screen_resized || (disable_ligatures && cursor_pos_changed))
        update_cell_data;

#define update_selection_data                                                                                  \
    {                                                                                                          \
        const unsigned int render_lines = render_lines_for_screen(screen);                                     \
        sz = (size_t)render_lines * screen->columns;                                                           \
        address = alloc_and_map_vao_buffer_for_full_rewrite(vao_idx, sz * selection_stride, selection_buffer); \
        screen_apply_selection(screen, address, sz, selection_stride);                                         \
        unmap_vao_buffer(vao_idx, selection_buffer);                                                           \
        address = NULL;                                                                                        \
        changed = true;                                                                                        \
    }

#define update_graphics_data(grman)             \
    grman_update_layers(                        \
        grman,                                  \
        screen->scrolled_by,                    \
        scroll_offset_lines_for_screen(screen), \
        -1.f,                                   \
        -1.f,                                   \
        2.f / screen->columns,                  \
        2.f / screen->lines,                    \
        screen->columns,                        \
        screen->lines,                          \
        screen->cell_size)

    if (screen->paused_rendering.expires_at) {
        if (!screen->paused_rendering.cell_data_updated) {
            update_selection_data;
            update_graphics_data(screen->paused_rendering.grman);
        }
        screen->paused_rendering.cell_data_updated = true;
        screen->last_rendered.scrolled_by = screen->paused_rendering.scrolled_by;
    } else {
        if (screen->reload_all_gpu_data || screen_resized || screen_is_selection_dirty(screen)) update_selection_data;
        if (update_graphics_data(screen->grman)) changed = true;
        screen->last_rendered.scrolled_by = screen->scrolled_by;
    }
#undef update_selection_data
#undef update_cell_data
    screen->last_rendered.columns = screen->columns;
    screen->last_rendered.lines = screen->lines;
    screen->last_rendered.cursor = screen->cursor_render_info;

    return changed;
}

static void
draw_graphics(int program, ImageRenderData *data, uint32_t start, uint32_t count, float extra_alpha) {
    bind_program(program);
    if (program != GRAPHICS_ALPHA_MASK_PROGRAM) param_1f(program_param(program, "extra_alpha"), extra_alpha);
    int32_t src_rect_loc = program_param(program, "src_rect");
    int32_t dest_rect_loc = program_param(program, "dest_rect");
    const bool is_indexed = program == GRAPHICS_INDEXED_PROGRAM || program == GRAPHICS_INDEXED_UNSCALED_PROGRAM;
    const int32_t has_alpha_loc = is_indexed ? program_param(program, "has_alpha") : -1;
    const uint32_t image_slot = program_texture_slot(program, "image");
    for (uint32_t i = 0; i < count;) {
        ImageRenderData *group = data + start + i;
        gpu_bind_texture(image_slot, group->texture_id);
        if (has_alpha_loc > -1) param_1ui(has_alpha_loc, group->indexed_px_sz == 2);
        if (group->group_count == 0) {
            i++;
            continue;
        }
        for (uint32_t k = 0; k < group->group_count; k++, i++) {
            ImageRenderData *rd = data + start + i;
            param_4f(src_rect_loc, rd->src_rect.left, rd->src_rect.top, rd->src_rect.right, rd->src_rect.bottom);
            param_4f(dest_rect_loc, rd->dest_rect.left, rd->dest_rect.top, rd->dest_rect.right, rd->dest_rect.bottom);
            draw_quad(true, 0);
        }
    }
}

static ImageRenderData *
load_alpha_mask_texture(size_t width, size_t height, uint8_t *canvas) {
    static ImageRenderData data = {.group_count = 1};
    const GPUTextureDesc desc = {
        .kind = GPU_TEXTURE_2D, .format = GPU_FORMAT_R8, .width = width, .height = height, .filter = GPU_FILTER_NEAREST, .wrap = GPU_WRAP_CLAMP_TO_EDGE};
    const GPUPixelData pixels = {.layout = GPU_PIXELS_R8, .row_alignment = 1, .data = canvas};
    define_texture(&data.texture_id, &desc, &pixels);
    return &data;
}

static void
setup_texture_as_render_target(unsigned width, unsigned height, gpu_texture_t *texture_id, gpu_render_target_t *framebuffer_id) {
    // We use 16 bit color channels to avoid incorrect colors due to quantization loss when
    // blending, see https://github.com/kovidgoyal/kitty/issues/8953
    static struct {
        bool ok;
        GPUTextureFormat fmt;
    } status = {false, GPU_FORMAT_RGBA16};
    const GPUTextureDesc desc = {
        .kind = GPU_TEXTURE_2D, .format = status.fmt, .width = width, .height = height, .filter = GPU_FILTER_LINEAR, .wrap = GPU_WRAP_CLAMP_TO_EDGE};
    *texture_id = create_texture_or_die(&desc, NULL);
    *framebuffer_id = gpu_render_target_create(*texture_id);
    if (!*framebuffer_id) fatal("Failed to create a GPU render target with error: %s", gpu_last_error());
    if (!status.ok) {
        if (gpu_render_target_status(*framebuffer_id) == NULL) {
            status.ok = true;
        } else {
            if (status.fmt == GPU_FORMAT_RGBA16) {
                // Driver does not support 16 bit render targets so fall back
                // to 8 bit. Inaccurate colors are better than completely
                // broken rendering. See https://github.com/kovidgoyal/kitty/issues/9068
                status.fmt = GPU_FORMAT_RGBA8;
                free_framebuffer(framebuffer_id);
                free_texture(texture_id);
                setup_texture_as_render_target(width, height, texture_id, framebuffer_id);
                log_error("WARNING: Your GPU driver does not support 16bit textures as framebuffer targets, some colors may be slightly inaccurate.");
            } else {
                fatal("Your GPU driver does not support indirect rendering to a RGBA texture via a framebuffer");
            }
        }
    }
}

static void
set_cell_uniforms(bool force) {
    static bool constants_set = false;
    if (!constants_set || force) {
        float text_contrast = 1.0f + OPT(text_contrast) * 0.01f;
        float text_gamma_adjustment = OPT(text_gamma_adjustment) < 0.01f ? 1.0f : 1.0f / OPT(text_gamma_adjustment);
        // These are set for every cell program, but the background program draws no
        // text and so does not have them.
#define set_optional(setter, name, value)         \
    {                                             \
        int32_t loc = try_program_param(i, name); \
        if (loc >= 0) setter(loc, value);         \
    }
        for (int i = CELL_PROGRAM; i < CELL_PROGRAM_SENTINEL; i++) {
            bind_program(i);
            set_optional(param_1f, "text_contrast", text_contrast);
            set_optional(param_1f, "text_gamma_adjustment", text_gamma_adjustment);
        }
#undef set_optional
        constants_set = true;
    }
}


// UI Layer {{{
static Animation *default_visual_bell_animation = NULL;

static float
get_visual_bell_intensity(Screen *screen) {
    if (screen->start_visual_bell_at > 0) {
        if (!default_visual_bell_animation) {
            default_visual_bell_animation = alloc_animation();
            if (!default_visual_bell_animation) fatal("Out of memory");
            add_cubic_bezier_animation(default_visual_bell_animation, 0, 1, EASE_IN_OUT);
            add_cubic_bezier_animation(default_visual_bell_animation, 1, 0, EASE_IN_OUT);
        }
        const monotonic_t progress = monotonic() - screen->start_visual_bell_at;
        const monotonic_t duration = OPT(visual_bell_duration) / 2;
        if (progress <= duration) {
            Animation *a = animation_is_valid(OPT(animation.visual_bell)) ? OPT(animation.visual_bell) : default_visual_bell_animation;
            return (float)apply_easing_curve(a, progress / (double)duration, duration);
        }
        screen->start_visual_bell_at = 0;
    }
    return 0.0f;
}

static void
draw_visual_bell_flash(float intensity, const color_type flash) {
    bind_program(TINT_PROGRAM);
    float attenuation = 0.4f;
#define C(shift) srgb_color((flash >> shift) & 0xFF)
    const float r = C(16), g = C(8), b = C(0);
    const float max_channel = r > g ? (r > b ? r : b) : (g > b ? g : b);
#undef C
#define C(x) (x * intensity * attenuation)
    if (max_channel > 0.45) attenuation = 0.6f; // light color
    param_4f(program_param(TINT_PROGRAM, "tint_color"), C(r), C(g), C(b), C(1));
#undef C
    param_4f(program_param(TINT_PROGRAM, "edges"), -1, -1, 1, 1);
    draw_quad(true, 0);
}

static color_type
get_flash_color(const Screen *screen) {
#define COLOR(name, fallback)                       \
    colorprofile_to_color_with_fallback(            \
        screen->color_profile,                      \
        screen->color_profile->overridden.name,     \
        screen->color_profile->configured.name,     \
        screen->color_profile->overridden.fallback, \
        screen->color_profile->configured.fallback)
    return !IS_SPECIAL_COLOR(highlight_bg) ? COLOR(visual_bell_color, highlight_bg) : COLOR(visual_bell_color, default_fg);
#undef COLOR
}

static void
draw_visual_bell(const UIRenderData *ui) {
    if (!ui->screen->start_visual_bell_at) return;
    Screen *screen = ui->screen;
    float intensity = get_visual_bell_intensity(screen);
    if (intensity <= 0) return;
    draw_visual_bell_flash(intensity, get_flash_color(screen));
}

static void
draw_drag_preview_overlay(const UIRenderData *ui) {
    const Screen *screen = ui->screen;
    if (!screen->start_drag_overlay_at || !screen->drag_overlay_quadrant) return;
    const monotonic_t elapsed = monotonic() - screen->start_drag_overlay_at;
    const monotonic_t fade_ms = ms_to_monotonic_t(150ll);
    float intensity = elapsed >= fade_ms ? 1.0f : (float)elapsed / (float)fade_ms;
    float left = -1.f, top = -1.f, right = 1.f, bottom = 1.f;
    switch (screen->drag_overlay_quadrant) {
        case 1: right = 0.f; break;  // left half
        case 2: left = 0.f; break;   // right half
        case 3: bottom = 0.f; break; // top half
        case 4: top = 0.f; break;    // bottom half
        case 5: break;               // full window + title bar highlight (title bar hover)
        case 6: break;               // full window, no title bar highlight (body hover)
        default: return;
    }
    bind_program(TINT_PROGRAM);
    float a = intensity * 0.25f;
    color_type hint = get_flash_color(screen);
#define C(shift) (srgb_color((hint >> shift) & 0xFF) * a)
    param_4f(program_param(TINT_PROGRAM, "tint_color"), C(16), C(8), C(0), a);
#undef C
    param_4f(program_param(TINT_PROGRAM, "edges"), left, top, right, bottom);
    draw_quad(true, 0);
}

static bool
has_scrollbar(Window *w, Screen *screen) {
    if (screen->linebuf != screen->main_linebuf || !screen->historybuf->count) return false;
    switch (OPT(scrollbar)) {
        case SCROLLBAR_NEVER: return false;
        case SCROLLBAR_ALWAYS: return true;
        case SCROLLBAR_ON_SCROLLED: return screen->scrolled_by > 0;
        case SCROLLBAR_ON_HOVERED: return w->scrollbar.is_hovering;
        case SCROLLBAR_ON_SCROLL_AND_HOVER: return screen->scrolled_by > 0 && w->scrollbar.is_hovering;
        case SCROLLBAR_ON_SCROLL_OR_HOVER: return screen->scrolled_by > 0 || w->scrollbar.is_hovering;
    }
    return false;
}

static unsigned
bar_border_width(const UIRenderData *ui) {
    return MAX(1u, (unsigned)ceil(thickness_as_float(ui->os_window, 1)));
}

// The rect, including borders, of a full width bar along the top of the window
static Viewport
window_bar_rect(const UIRenderData *ui) {
    return (Viewport){.left = ui->screen_left, .top = ui->screen_top, .width = ui->screen_width, .height = ui->cell_height + 2 + 2 * bar_border_width(ui)};
}

static void
bar_colors(const UIRenderData *ui, color_type *fg, color_type *bg) {
#define RGBCOL(which, fallback)                                       \
    (0xff000000 | colorprofile_to_color_with_fallback(                \
                      ui->screen->color_profile,                      \
                      ui->screen->color_profile->overridden.which,    \
                      ui->screen->color_profile->configured.which,    \
                      ui->screen->color_profile->overridden.fallback, \
                      ui->screen->color_profile->configured.fallback))
    *fg = RGBCOL(default_fg, default_fg);
    *bg = RGBCOL(default_bg, default_bg);
#undef RGBCOL
}

// Render title into bar->buf, if needed. The rendered text is max_width x
// height pixels, unless fit_to_text is true, in which case its width is reduced
// to the width of the text. The actual width is stored in bar->width.
static bool
render_bar_text(
    const UIRenderData *ui, WindowBarData *bar, PyObject *title, unsigned max_width, unsigned height, bool fit_to_text, color_type fg, color_type bg) {
    if (!title) return false;
    if (!bar->buf || bar->requested_width != max_width || bar->height != height || bar->fit_to_text != fit_to_text) {
        free(bar->buf);
        bar->buf = malloc((size_t)4 * max_width * height);
        if (!bar->buf) return false;
        bar->requested_width = max_width;
        bar->width = max_width;
        bar->height = height;
        bar->fit_to_text = fit_to_text;
        bar->needs_render = true;
    }
    if (bar->last_drawn_title_object_id != title || bar->needs_render) {
        static char titlebuf[2048] = {0};
        snprintf(titlebuf, arraysz(titlebuf), fit_to_text ? " %s " : " %s", PyUnicode_AsUTF8(title));
        size_t actual_width = max_width;
        if (!draw_window_title(
                ui->os_window->fonts_data->font_sz_in_pts,
                ui->os_window->fonts_data->logical_dpi_y,
                titlebuf,
                fg,
                bg,
                bar->buf,
                max_width,
                height,
                fit_to_text ? &actual_width : NULL))
            return false;
        bar->width = MAX(1u, (unsigned)actual_width);
        Py_CLEAR(bar->last_drawn_title_object_id);
        bar->last_drawn_title_object_id = Py_NewRef(title);
    }
    return true;
}

// Draw the text previously rendered by render_bar_text() surrounded by a
// border. border_rect must be the size of the rendered text plus the borders.
static void
draw_bar(const UIRenderData *ui, const WindowBarData *bar, Viewport border_rect, color_type fg, color_type bg) {
    const double thickness = thickness_as_float(ui->os_window, 1);
    const unsigned border_width = bar_border_width(ui);
    // The rounded rect shader anti-aliases each edge over a band extending
    // one pixel on either side of it, so keep the drawn line at least half a
    // pixel inside the border_width pixels reserved for it, otherwise it would
    // bleed onto the rendered title.
    const float drawn_thickness = (float)MIN(thickness, border_width - 0.5);
    static ImageRenderData data = {.group_count = 1};
    gpu_data_for_image(&data, -1, -1, 1, 1);
    const GPUTextureDesc desc = {
        .kind = GPU_TEXTURE_2D,
        .format = GPU_FORMAT_SRGB8_ALPHA8,
        .width = bar->width,
        .height = bar->height,
        .filter = GPU_FILTER_NEAREST,
        .wrap = GPU_WRAP_CLAMP_TO_EDGE};
    const GPUPixelData pixels = {.layout = GPU_PIXELS_RGBA8, .row_alignment = 1, .data = bar->buf};
    data.texture_id = create_texture_or_die(&desc, &pixels);
    bind_program(GRAPHICS_PROGRAM);
    // first blank the area to be drawn to background
    enable_scissor(border_rect);
    blank_canvas(ui->bg_alpha, bg, false);
    disable_scissor();
    // then draw the rendered text
    save_viewport(border_rect.left + border_width, border_rect.top + border_width, bar->width, bar->height);
    draw_graphics(GRAPHICS_PROGRAM, &data, 0, 1, 1.f);
    restore_viewport();
    free_texture(&data.texture_id);
    // finally draw border with transparent bg
    draw_rounded_rect(border_rect, drawn_thickness, ui->cell_width, fg, bg, 0.f, 0, 0.f);
}

static unsigned
render_a_bar(const UIRenderData *ui, WindowBarData *bar, PyObject *title, Viewport border_rect) {
    const unsigned border_width = bar_border_width(ui);
    if (border_rect.width <= 2 * border_width || border_rect.height <= 2 * border_width) return 0;
    color_type fg, bg;
    bar_colors(ui, &fg, &bg);
    if (!render_bar_text(ui, bar, title, border_rect.width - 2 * border_width, border_rect.height - 2 * border_width, false, fg, bg)) return 0;
    draw_bar(ui, bar, border_rect, fg, bg);
    return border_rect.height;
}

static bool
show_hyperlink_targets_with_modifiers(int mods) {
    switch (OPT(show_hyperlink_targets)) {
        case SHOW_HYPERLINK_TARGETS_ALWAYS: return true;
        case SHOW_HYPERLINK_TARGETS_CTRL: return (mods & GLFW_MOD_CONTROL) != 0;
        case SHOW_HYPERLINK_TARGETS_SHIFT: return (mods & GLFW_MOD_SHIFT) != 0;
        case SHOW_HYPERLINK_TARGETS_SUPER: return (mods & GLFW_MOD_SUPER) != 0;
        case SHOW_HYPERLINK_TARGETS_ALT: return (mods & GLFW_MOD_ALT) != 0;
        default: return false;
    }
}

static bool
has_hyperlink_target(OSWindow *os_window, Window *w, Screen *screen) {
    return show_hyperlink_targets_with_modifiers(global_state.mods_at_last_key_or_button_event) && screen->current_hyperlink_under_mouse.id && w &&
           !is_mouse_hidden(os_window) && global_state.mouse_hover_in_window == w->id;
}

// Return the offset from the top of the screen at which to draw a bar of the
// specified height so that it does not obscure the hovered line
static unsigned
hyperlink_target_bar_top(const UIRenderData *ui, unsigned bar_height) {
    const double max_top = ui->screen_height - bar_height;
    const double row_top = (double)ui->screen->current_hyperlink_under_mouse.y * ui->cell_height + ui->screen->pixel_scroll_offset_y;
    const double row_bottom = row_top + ui->cell_height;
    double top = 0;
    switch (OPT(hyperlink_target_position)) {
        case HYPERLINK_TARGET_TOP: top = row_top < bar_height ? max_top : 0; break;
        case HYPERLINK_TARGET_BOTTOM: top = row_bottom > max_top ? 0 : max_top; break;
        case HYPERLINK_TARGET_BELOW:
        case HYPERLINK_TARGET_TOOLTIP: top = row_bottom > max_top ? row_top - bar_height : row_bottom; break;
    }
    return (unsigned)MAX(0., MIN(top, max_top));
}

// Draw the URL in a box sized to fit it, starting at the hovered cell, moved
// left as needed to fit in the window. rect is the full width bar it replaces.
static void
draw_hyperlink_target_tooltip(const UIRenderData *ui, Viewport rect, PyObject *url) {
    const unsigned border_width = bar_border_width(ui);
    if (rect.width <= 2 * border_width || rect.height <= 2 * border_width) return;
    WindowBarData *bar = &ui->window->title_bar_data;
    color_type fg, bg;
    bar_colors(ui, &fg, &bg);
    if (!render_bar_text(ui, bar, url, rect.width - 2 * border_width, rect.height - 2 * border_width, true, fg, bg)) return;
    const unsigned width = bar->width + 2 * border_width;
    const unsigned left = ui->screen->current_hyperlink_under_mouse.x * ui->cell_width;
    rect.left += MIN(left, rect.width - width);
    rect.width = width;
    draw_bar(ui, bar, rect, fg, bg);
}

static void
draw_hyperlink_target(const UIRenderData *ui) {
    if (!has_hyperlink_target(ui->os_window, ui->window, ui->screen)) return;
    Screen *screen = ui->screen;
    Window *window = ui->window;
    Viewport rect = window_bar_rect(ui);
    if (rect.height > ui->screen_height) return;
    WindowBarData *bd = &window->url_target_bar_data;
    hyperlink_id_type hid = screen->current_hyperlink_under_mouse.id;
    if (bd->hyperlink_id_for_title_object != hid) {
        bd->hyperlink_id_for_title_object = hid;
        Py_CLEAR(bd->last_drawn_title_object_id);
        const char *url = get_hyperlink_for_id(screen->hyperlink_pool, bd->hyperlink_id_for_title_object, true);
        if (url == NULL) url = "";
        bd->last_drawn_title_object_id = PyObject_CallMethod(global_state.boss, "sanitize_url_for_display_to_user", "s", url);
        if (bd->last_drawn_title_object_id == NULL) {
            PyErr_Print();
            return;
        }
        bd->needs_render = true;
    }
    if (bd->last_drawn_title_object_id == NULL) return;
    PyObject *ref = Py_NewRef(bd->last_drawn_title_object_id); // render_bar_text() clears bd->last_drawn_title_object_id
    rect.top += hyperlink_target_bar_top(ui, rect.height);
    if (OPT(hyperlink_target_position) == HYPERLINK_TARGET_TOOLTIP) draw_hyperlink_target_tooltip(ui, rect, bd->last_drawn_title_object_id);
    else render_a_bar(ui, &window->title_bar_data, bd->last_drawn_title_object_id, rect);
    Py_DECREF(ref);
}

static bool
has_window_number(Window *w, Screen *screen) {
    return w != NULL && screen->display_window_char != 0;
}

static void
draw_window_number(const UIRenderData *ui) {
    if (!has_window_number(ui->window, ui->screen)) return;
    unsigned title_bar_height = 0, requested_height = ui->screen_height;
    if (ui->window->title && PyUnicode_Check(ui->window->title) && (requested_height > (ui->cell_height + 1) * 2)) {
        title_bar_height = render_a_bar(ui, &ui->window->title_bar_data, ui->window->title, window_bar_rect(ui));
    }
    unsigned height_for_letter = ui->screen_height - title_bar_height - ui->cell_height;
    unsigned width_for_letter = ui->screen_width - ui->cell_width;
    requested_height = MIN(12 * ui->cell_height, MIN(height_for_letter, width_for_letter));
    if (requested_height < 4) return;
#define lr ui->screen->last_rendered_window_char
    if (!lr.canvas || lr.ch != ui->screen->display_window_char || lr.requested_height != requested_height) {
        free(lr.canvas);
        lr.canvas = NULL;
        lr.requested_height = requested_height;
        lr.height_px = requested_height;
        lr.ch = 0;
        lr.canvas = draw_single_ascii_char(ui->screen->display_window_char, &lr.width_px, &lr.height_px);
        if (lr.height_px < 4 || lr.width_px < 4 || !lr.canvas) return;
        lr.ch = ui->screen->display_window_char;
    }
    unsigned letter_x = 0, letter_y = title_bar_height;
    if (lr.width_px < ui->screen_width) letter_x = (ui->screen_width - lr.width_px) / 2;
    if (lr.height_px + title_bar_height < ui->screen_height) letter_y += (ui->screen_height - lr.height_px - title_bar_height) / 2;
    bind_program(GRAPHICS_ALPHA_MASK_PROGRAM);
    ImageRenderData *ird = load_alpha_mask_texture(lr.width_px, lr.height_px, lr.canvas);
    gpu_data_for_image(ird, -1, -1, 1, 1);
    color_type digit_color = colorprofile_to_color_with_fallback(
        ui->screen->color_profile,
        ui->screen->color_profile->overridden.highlight_bg,
        ui->screen->color_profile->configured.highlight_bg,
        ui->screen->color_profile->overridden.default_fg,
        ui->screen->color_profile->configured.default_fg);
    color_vec3(program_param(GRAPHICS_ALPHA_MASK_PROGRAM, "amask_fg"), digit_color);
    param_4f(program_param(GRAPHICS_ALPHA_MASK_PROGRAM, "amask_bg_premult"), 0.f, 0.f, 0.f, 0.f);
    save_viewport(ui->screen_left + letter_x, ui->screen_top + letter_y, lr.width_px, lr.height_px);
    draw_graphics(GRAPHICS_ALPHA_MASK_PROGRAM, ird, 0, 1, 1.f);
    restore_viewport();
#undef lr
}

// Helper function to extract and apply opacity to color components
static void
set_color_uniform_with_opacity(color_type color, float opacity) {
    float r = srgb_color((color >> 16) & 0xFF) * opacity;
    float g = srgb_color((color >> 8) & 0xFF) * opacity;
    float b = srgb_color(color & 0xFF) * opacity;
    param_4f(program_param(TINT_PROGRAM, "tint_color"), r, g, b, opacity);
}

static color_type
scrollbar_color(Screen *screen, unsigned val) {
    switch (val & 0xff) {
#define C(which) colorprofile_to_color(screen->color_profile, screen->color_profile->overridden.which, screen->color_profile->configured.which).rgb
        case 0: return C(default_fg);
        case 1: return C(highlight_bg);
#undef C
        default: return val >> 8;
    }
}

static void
draw_scrollbar(const UIRenderData *ui) {
    Screen *screen = ui->screen;
    Window *window = ui->window;
    if (!window || !screen || !has_scrollbar(window, screen)) return;

    color_type bar_color = scrollbar_color(screen, OPT(scrollbar_handle_color)), track_color = scrollbar_color(screen, OPT(scrollbar_track_color));
    double cell_frac = (double)screen->pixel_scroll_offset_y / screen->cell_size.height;
    if (!OPT(pixel_scroll)) cell_frac = 0;
    float bar_frac = (float)(screen->scrolled_by + cell_frac) / MAX(1u, (float)screen->historybuf->count);
    float opacity = OPT(scrollbar_handle_opacity);
    float track_opacity = window->scrollbar.is_hovering ? OPT(scrollbar_track_hover_opacity) : OPT(scrollbar_track_opacity);
    int32_t scrollbar_width_px = (int32_t)(OPT(scrollbar_width) * ui->cell_width);
    if (window->scrollbar.is_hovering) scrollbar_width_px = (int32_t)(OPT(scrollbar_hover_width) * ui->cell_width);
    int32_t scrollbar_gap_px = (int32_t)(OPT(scrollbar_gap) * ui->cell_width);
    unsigned scrollbar_radius = (unsigned)(OPT(scrollbar_radius) * ui->cell_width);

    // Calculate window boundaries including padding
    int32_t window_right_edge = ui->screen_left + ui->screen_width + window->render_data.geometry.spaces.right;
    int32_t window_top_edge = ui->screen_top - window->render_data.geometry.spaces.top;
    int32_t window_height = ui->screen_height + window->render_data.geometry.spaces.top + window->render_data.geometry.spaces.bottom;

    // Position scrollbar on right side with gap
    int32_t scrollbar_left = window_right_edge - scrollbar_width_px - scrollbar_gap_px;
    int32_t scrollbar_top = window_top_edge + scrollbar_gap_px;
    int32_t scrollbar_height = window_height - 2 * scrollbar_gap_px;

    // Calculate thumb size and position
    float visible_fraction = (float)screen->lines / (float)(screen->lines + screen->historybuf->count);
    float min_thumb_height_fraction = (OPT(scrollbar_min_handle_height) * ui->cell_height) / (float)window_height;
    float thumb_height_fraction = MAX(min_thumb_height_fraction, visible_fraction);

    // Convert to NDC (range -1.0 to 1.0, total span = 2.0, -1 is the top)
    const float GL_COORD_SPAN = 2.0f;
    float thumb_height_gl = thumb_height_fraction * GL_COORD_SPAN;
    float available_space = GL_COORD_SPAN - thumb_height_gl;
    float thumb_bottom_gl = 1.0f - available_space * bar_frac;
    float thumb_top_gl = thumb_bottom_gl - thumb_height_gl;

    // Store thumb position for mouse interaction (normalized window coordinates)
    float scrollbar_top_in_window = (float)(window_top_edge + scrollbar_gap_px) / (float)ui->full_framebuffer_height;
    float scrollbar_height_in_window = (float)(window_height - 2 * scrollbar_gap_px) / (float)ui->full_framebuffer_height;
    float thumb_top_fraction = (1.0f + thumb_top_gl) / 2.0f;
    float thumb_bottom_fraction = (1.0f + thumb_bottom_gl) / 2.0f;
    window->scrollbar.thumb_top = scrollbar_top_in_window + thumb_top_fraction * scrollbar_height_in_window;
    window->scrollbar.thumb_bottom = scrollbar_top_in_window + thumb_bottom_fraction * scrollbar_height_in_window;

    // Set viewport for scrollbar area
    save_viewport(scrollbar_left, scrollbar_top, scrollbar_width_px, scrollbar_height);

    // Draw scrollbar track (background)
    if (track_opacity > 0) {
        bind_program(TINT_PROGRAM);
        set_color_uniform_with_opacity(track_color, track_opacity);
        param_4f(program_param(TINT_PROGRAM, "edges"), -1.f, -1.f, 1.f, 1.f);
        draw_quad(true, 0);
    }

    // Draw scrollbar thumb (handle)
    if (scrollbar_radius > 0) {
        // Rounded thumb - use separate viewport and rounded rect program
        int32_t thumb_height_px = (int32_t)(thumb_height_fraction * scrollbar_height);
        int32_t thumb_top_px = scrollbar_top + (int32_t)(thumb_top_fraction * scrollbar_height);

        restore_viewport();

        bind_program(ROUNDED_RECT_PROGRAM);
        color_vec4(program_param(ROUNDED_RECT_PROGRAM, "color"), bar_color, opacity);
        color_vec4(program_param(ROUNDED_RECT_PROGRAM, "background_color"), 0, 0.0f);
        color_vec4(program_param(ROUNDED_RECT_PROGRAM, "outer_color"), 0, 0.0f);

        param_2f(program_param(ROUNDED_RECT_PROGRAM, "size"), (float)scrollbar_width_px, (float)thumb_height_px);

        float thickness = (float)MAX(scrollbar_width_px, thumb_height_px);
        param_2f(program_param(ROUNDED_RECT_PROGRAM, "params"), thickness, (float)scrollbar_radius);

        save_viewport(scrollbar_left, thumb_top_px, scrollbar_width_px, thumb_height_px);
        draw_quad(true, 0);
        restore_viewport();
    } else {
        set_color_uniform_with_opacity(bar_color, opacity);
        param_4f(program_param(TINT_PROGRAM, "edges"), -1.f, thumb_top_gl, 1.f, thumb_bottom_gl);
        draw_quad(true, 0);
        restore_viewport();
    }
}

static bool
has_progress_bar(Screen *screen) {
    if (OPT(progress_bar) == PROGRESS_BAR_HIDDEN) return false;
    return screen && screen->progress_state != PROGRESS_STATE_UNSET;
}

static void
draw_progress_handle(
    color_type bar_color,
    float opacity,
    unsigned bar_radius,
    int32_t track_left,
    int32_t track_top,
    int32_t track_width,
    int32_t track_height,
    float handle_start,
    float handle_size,
    bool is_horizontal) {
    // handle_start and handle_size are fractions of the track length (0..1)
    // For horizontal: handle moves left-to-right; For vertical: handle moves top-to-bottom
    // Use lroundf to avoid sub-pixel jitter at the leading edge
    int32_t handle_left, handle_top;
    int32_t handle_w, handle_h;
    if (is_horizontal) {
        int32_t handle_start_px = (int32_t)lroundf(handle_start * track_width);
        int32_t handle_end_px = (int32_t)lroundf((handle_start + handle_size) * track_width);
        int32_t handle_w_px = handle_end_px - handle_start_px;
        if (handle_w_px < 1) handle_w_px = 1;
        handle_left = track_left + handle_start_px;
        handle_top = track_top;
        handle_w = handle_w_px;
        handle_h = track_height;
    } else {
        int32_t handle_start_px = (int32_t)lroundf(handle_start * track_height);
        int32_t handle_end_px = (int32_t)lroundf((handle_start + handle_size) * track_height);
        int32_t handle_h_px = handle_end_px - handle_start_px;
        if (handle_h_px < 1) handle_h_px = 1;
        handle_left = track_left;
        handle_top = track_top + handle_start_px;
        handle_w = track_width;
        handle_h = handle_h_px;
    }

    if (bar_radius > 0) {
        bind_program(ROUNDED_RECT_PROGRAM);
        color_vec4(program_param(ROUNDED_RECT_PROGRAM, "color"), bar_color, opacity);
        color_vec4(program_param(ROUNDED_RECT_PROGRAM, "background_color"), 0, 0.0f);
        color_vec4(program_param(ROUNDED_RECT_PROGRAM, "outer_color"), 0, 0.0f);

        param_2f(program_param(ROUNDED_RECT_PROGRAM, "size"), (float)handle_w, (float)handle_h);

        float thickness = (float)(is_horizontal ? handle_h : handle_w);
        param_2f(program_param(ROUNDED_RECT_PROGRAM, "params"), thickness, (float)bar_radius);

        save_viewport(handle_left, handle_top, handle_w, handle_h);
        draw_quad(true, 0);
        restore_viewport();
    } else {
        // Use GL coordinates within the track viewport, snapped to pixel boundaries
        int32_t track_len = is_horizontal ? track_width : track_height;
        float start_snapped = (float)lroundf(handle_start * track_len) / (float)track_len;
        float end_snapped = (float)lroundf((handle_start + handle_size) * track_len) / (float)track_len;
        float start_gl = -1.0f + 2.0f * start_snapped;
        float end_gl = -1.0f + 2.0f * end_snapped;
        bind_program(TINT_PROGRAM);
        set_color_uniform_with_opacity(bar_color, opacity);
        if (is_horizontal) {
            // edges: left, top, right, bottom
            save_viewport(track_left, track_top, track_width, track_height);
            param_4f(program_param(TINT_PROGRAM, "edges"), start_gl, -1.f, end_gl, 1.f);
        } else {
            save_viewport(track_left, track_top, track_width, track_height);
            // For vertical: the handle moves top to bottom, as NDC y does
            param_4f(program_param(TINT_PROGRAM, "edges"), -1.f, start_gl, 1.f, end_gl);
        }
        draw_quad(true, 0);
        restore_viewport();
    }
}

static void
draw_progress_bar(const UIRenderData *ui) {
    Screen *screen = ui->screen;
    Window *window = ui->window;
    if (!window || !has_progress_bar(screen)) return;

    const ProgressBarPosition pos = OPT(progress_bar);
    const bool is_horizontal = (pos == PROGRESS_BAR_TOP || pos == PROGRESS_BAR_BOTTOM);
    color_type bar_color = scrollbar_color(screen, OPT(scrollbar_handle_color));
    color_type track_color = scrollbar_color(screen, OPT(scrollbar_track_color));
    float opacity = OPT(scrollbar_handle_opacity);
    float track_opacity = OPT(scrollbar_track_hover_opacity);
    int32_t bar_thickness_px = (int32_t)(OPT(scrollbar_width) * ui->cell_width);
    int32_t gap_px = (int32_t)(OPT(scrollbar_gap) * ui->cell_width);
    unsigned bar_radius = (unsigned)(OPT(scrollbar_radius) * ui->cell_width);
    if (bar_thickness_px < 1) return;

    // Calculate window boundaries including padding
    int32_t window_left_edge = ui->screen_left - (int32_t)window->render_data.geometry.spaces.left;
    int32_t window_top_edge = ui->screen_top - (int32_t)window->render_data.geometry.spaces.top;
    int32_t window_width = ui->screen_width + (int32_t)(window->render_data.geometry.spaces.left + window->render_data.geometry.spaces.right);
    int32_t window_height = ui->screen_height + (int32_t)(window->render_data.geometry.spaces.top + window->render_data.geometry.spaces.bottom);

    // Position the track depending on the chosen edge
    int32_t track_left, track_top, track_width, track_height;
    switch (pos) {
        case PROGRESS_BAR_BOTTOM:
            track_left = window_left_edge + gap_px;
            track_width = window_width - 2 * gap_px;
            track_height = bar_thickness_px;
            track_top = window_top_edge + window_height - bar_thickness_px - gap_px;
            break;
        case PROGRESS_BAR_TOP:
            track_left = window_left_edge + gap_px;
            track_width = window_width - 2 * gap_px;
            track_height = bar_thickness_px;
            track_top = window_top_edge + gap_px;
            break;
        case PROGRESS_BAR_LEFT:
            track_left = window_left_edge + gap_px;
            track_width = bar_thickness_px;
            track_top = window_top_edge + gap_px;
            track_height = window_height - 2 * gap_px;
            break;
        case PROGRESS_BAR_RIGHT:
            track_left = window_left_edge + window_width - bar_thickness_px - gap_px;
            track_width = bar_thickness_px;
            track_top = window_top_edge + gap_px;
            track_height = window_height - 2 * gap_px;
            break;
        default: return;
    }
    if (track_width <= 0 || track_height <= 0) return;

    // Calculate fill fraction and indeterminate animation
    float fill_fraction = 0.0f;
    bool is_indeterminate = false;
    switch (screen->progress_state) {
        case PROGRESS_STATE_SET:
        case PROGRESS_STATE_PAUSED: fill_fraction = screen->progress_percent / 100.0f; break;
        case PROGRESS_STATE_ERROR: fill_fraction = 1.0f; break;
        case PROGRESS_STATE_INDETERMINATE: is_indeterminate = true; break;
        default: return;
    }

    // Draw track (background)
    save_viewport(track_left, track_top, track_width, track_height);
    if (track_opacity > 0) {
        bind_program(TINT_PROGRAM);
        set_color_uniform_with_opacity(track_color, track_opacity);
        param_4f(program_param(TINT_PROGRAM, "edges"), -1.f, -1.f, 1.f, 1.f);
        draw_quad(true, 0);
    }
    restore_viewport();

    // Draw fill or indeterminate handle
    // For vertical bars, progress grows from bottom to top, so invert the fraction
    if (is_indeterminate) {
        // Animate a handle bouncing back and forth like a scrollbar thumb
        const float handle_size = 0.15f;                        // 15% of track length
        const monotonic_t cycle = s_double_to_monotonic_t(2.0); // 2 second full cycle (forth and back)
        monotonic_t elapsed = screen->progress_indeterminate_anim_at > 0 ? monotonic() - screen->progress_indeterminate_anim_at : 0;
        double t = (double)(elapsed % cycle) / (double)cycle; // 0..1 over one cycle
        // Triangle wave: goes 0→1→0 over one cycle
        float pos_frac = (float)(t < 0.5 ? t * 2.0 : 2.0 - t * 2.0);
        if (!is_horizontal) pos_frac = 1.0f - pos_frac; // vertical: bounce bottom-to-top first
        float handle_start = pos_frac * (1.0f - handle_size);
        if (opacity > 0.0f) {
            draw_progress_handle(bar_color, opacity, bar_radius, track_left, track_top, track_width, track_height, handle_start, handle_size, is_horizontal);
        }
    } else if (fill_fraction > 0.0f && opacity > 0.0f) {
        float handle_start = is_horizontal ? 0.0f : 1.0f - fill_fraction;
        draw_progress_handle(bar_color, opacity, bar_radius, track_left, track_top, track_width, track_height, handle_start, fill_fraction, is_horizontal);
    }
}


static void
draw_window_logo(const UIRenderData *ui) {
    struct {
        unsigned width, height;
        int left, top;
    } w;
    WindowLogoRenderData *wl = ui->window_logo;
    w.height = wl->instance->height;
    w.width = wl->instance->width;
    if (OPT(window_logo_scale.width) > 0 || OPT(window_logo_scale.height) > 0) {
        unsigned scaled_wl_width = ui->screen_width, scaled_wl_height = ui->screen_height;

        // [sx] Scales logo to sx % of the viewports shortest dimension, preserving aspect ratio
        if (OPT(window_logo_scale.height) < 0) {
            if (ui->screen_height < ui->screen_width) {
                scaled_wl_height = (int)(ui->screen_height * OPT(window_logo_scale.width) / 100);
                scaled_wl_width = wl->instance->width * scaled_wl_height / wl->instance->height;
            } else {
                scaled_wl_width = (int)(ui->screen_width * OPT(window_logo_scale.width) / 100);
                scaled_wl_height = wl->instance->height * scaled_wl_width / wl->instance->width;
            }
        }
        // [0 sy] Scales logo's y dimension to sy % of viewporty keeping original x dimension
        else if (OPT(window_logo_scale.width) == 0.0) {
            scaled_wl_height = (int)(scaled_wl_height * OPT(window_logo_scale.height) / 100);
            scaled_wl_width = wl->instance->width;
        }
        // [sx 0] Scales logo's x dimension to sx % of viewportx keeping original y dimension
        else if (OPT(window_logo_scale.height) == 0.0) {
            scaled_wl_width = (int)(scaled_wl_width * OPT(window_logo_scale.width) / 100);
            scaled_wl_height = wl->instance->height;
        }
        // [sx sy] Scales logo's x and y dimension to sx and sy % of viewportx and viewporty respectively
        else {
            scaled_wl_height = (int)(scaled_wl_height * OPT(window_logo_scale.height) / 100);
            scaled_wl_width = (int)(scaled_wl_width * OPT(window_logo_scale.width) / 100);
        }
        w.width = scaled_wl_width;
        w.height = scaled_wl_height;
    }
    w.left = (int)(ui->screen_width * wl->position.canvas_x - w.width * wl->position.image_x);
    w.top = (int)(ui->screen_height * wl->position.canvas_y - w.height * wl->position.image_y);
    float left = gl_pos_x(w.left, ui->screen_width), top = gl_pos_y(w.top, ui->screen_height);
    ImageRenderData d = {.texture_id = wl->instance->texture_id};
    gpu_data_for_image(&d, left, top, left + gl_size(w.width, ui->screen_width), top + gl_size(w.height, ui->screen_height));
    draw_graphics(GRAPHICS_PROGRAM, &d, 0, 1, ui->inactive_text_alpha * OPT(window_logo_alpha));
}

bool
screen_needs_rendering_in_layers(OSWindow *os_window, Window *w, Screen *screen) {
    const bool has_ui = w && ((screen->start_visual_bell_at | screen->start_drag_overlay_at) || has_scrollbar(w, screen) || has_progress_bar(screen) ||
                              has_hyperlink_target(os_window, w, screen) || has_window_number(w, screen) || w->window_logo.id);
    GraphicsManager *grman = screen->paused_rendering.expires_at && screen->paused_rendering.grman ? screen->paused_rendering.grman : screen->grman;
    return has_ui || grman_has_images(grman);
}

bool
current_framebuffer_is_ok(void) {
    return check_framebuffer_status() == NULL;
}

// }}}

enum { DRAW_NEITHER_BG = 0, DRAW_DEFAULT_BG = 1, DRAW_NON_DEFAULT_BG = 2, DRAW_BOTH_BG = 3 };

static void
call_cell_program(int program, const UIRenderData *ui, ssize_t vao_idx, bool for_final_output, unsigned draw_bg_bitfield) {
    bind_program(program);
    CELL_BUFFERS;
    bind_vao_uniform_buffer(vao_idx, uniform_buffer, program_uniform_block(program, "CellRenderData").slot);
    bind_vao_uniform_buffer(vao_idx, color_table_buffer, program_uniform_block(program, "ColorTable").slot);
    param_1ui(program_param(program, "draw_bg_bitfield"), draw_bg_bitfield);
    if (for_final_output) gpu_set_srgb_output(true);
    draw_quad(!for_final_output, render_lines_for_screen(ui->screen) * ui->screen->columns);
    if (for_final_output) gpu_set_srgb_output(false);
}

static void
draw_cells_without_layers(const UIRenderData *ui, ssize_t vao_idx) {
    call_cell_program(CELL_PROGRAM, ui, vao_idx, true, DRAW_BOTH_BG);
}

static void
configure_cell_vao_attributes(ssize_t vao_idx, unsigned int base_cell, unsigned int cell_step) {
    // (Re)point the instanced cell attributes so that instance i corresponds to
    // the cell at (base_cell + i*cell_step). Used to restore the canonical
    // layout after padding draws (base_cell=0, cell_step=1). The VAO must be
    // bound before calling this.
    CELL_BUFFERS;
    const uint32_t cell_stride = (uint32_t)(cell_step * sizeof(GPUCell));
    const size_t cell_base = (size_t)base_cell * sizeof(GPUCell);
    set_vao_attribute(
        vao_idx,
        cell_data_buffer,
        program_attribute_location(CELL_PROGRAM, "sprite_idx"),
        2,
        GPU_ATTRIB_U32,
        cell_stride,
        cell_base + offsetof(GPUCell, sprite_idx),
        1);
    set_vao_attribute(
        vao_idx, cell_data_buffer, program_attribute_location(CELL_PROGRAM, "colors"), 3, GPU_ATTRIB_U32, cell_stride, cell_base + offsetof(GPUCell, fg), 1);
    set_vao_attribute(
        vao_idx,
        selection_buffer,
        program_attribute_location(CELL_PROGRAM, "is_selected"),
        1,
        GPU_ATTRIB_U8,
        (uint32_t)(cell_step * selection_stride),
        (size_t)base_cell * selection_stride,
        1);
}

static void
configure_padding_vao_attributes(ssize_t vao_idx) {
    // Point the instanced cell attributes at the dedicated padding buffers
    // (base=0, stride=sizeof(GPUCell)), which are pre-packed before each
    // combined draw. The VAO must be bound before calling this.
    CELL_BUFFERS;
    set_vao_attribute(
        vao_idx,
        padding_cell_data_buffer,
        program_attribute_location(CELL_PROGRAM, "sprite_idx"),
        2,
        GPU_ATTRIB_U32,
        sizeof(GPUCell),
        offsetof(GPUCell, sprite_idx),
        1);
    set_vao_attribute(
        vao_idx, padding_cell_data_buffer, program_attribute_location(CELL_PROGRAM, "colors"), 3, GPU_ATTRIB_U32, sizeof(GPUCell), offsetof(GPUCell, fg), 1);
    set_vao_attribute(
        vao_idx, padding_selection_buffer, program_attribute_location(CELL_PROGRAM, "is_selected"), 1, GPU_ATTRIB_U8, (uint32_t)selection_stride, 0, 1);
}

static void
draw_window_padding(const UIRenderData *ui, unsigned int cl, unsigned int ct, unsigned int cr, unsigned int cb, ssize_t vao_idx, bool for_final_output) {
    // Color the compensatory padding strips (the innermost slice of the window
    // padding, arising from the window size not being an exact multiple of the
    // cell size) to match their neighboring cell. The strips lie outside the
    // per-window cell viewport, so this runs with the full framebuffer viewport.
    //
    // Two instanced draws are issued: one covers the horizontal pair (top+bottom)
    // and one the vertical pair (left+right). Each draw packs its strip cells into
    // a dedicated buffer so the VAO needs no per-strip reconfiguration. The shader
    // selects per-strip geometry and cell indices branch-free via lerp.
    if (OPT(padding_fill_strategy) != PADDING_FILL_NEIGHBORING_CELL || !(cl | ct | cr | cb)) return;
    Screen *screen = ui->screen;
    const unsigned int columns = screen->columns, lines = screen->lines;
    if (!columns || !lines) return;
    const unsigned int render_offset = pixel_scroll_enabled(screen) ? 1u : 0u;
    const unsigned int top_row = render_offset, bottom_row = render_offset + lines - 1u;

    const float fbw = (float)ui->full_framebuffer_width, fbh = (float)ui->full_framebuffer_height;
    const float cw = (float)ui->cell_width, ch = (float)ui->cell_height;
    const float fL = (float)ui->screen_left, T = (float)ui->screen_top;
    const float R = fL + (float)ui->screen_width, B = T + (float)ui->screen_height;
#define NX(px) (2.f * (px) / fbw - 1.f)
#define NY(px) (2.f * (px) / fbh - 1.f)
    const float dx = 2.f * cw / fbw, dy = 2.f * ch / fbh;

    bind_program(PADDING_PROGRAM);
    bind_vertex_array(vao_idx);
    CELL_BUFFERS;
    bind_vao_uniform_buffer(vao_idx, uniform_buffer, program_uniform_block(PADDING_PROGRAM, "CellRenderData").slot);
    bind_vao_uniform_buffer(vao_idx, color_table_buffer, program_uniform_block(PADDING_PROGRAM, "ColorTable").slot);
    if (for_final_output) gpu_set_srgb_output(true);

    // Point instanced attributes at the padding-specific buffers once for both draws.
    configure_padding_vao_attributes(vao_idx);

#define PL(x) program_param(PADDING_PROGRAM, #x)

    // Horizontal combined draw: top strip (strip 0) + bottom strip (strip 1).
    // Cell data is packed contiguously via GPU-side copies (no CPU round-trip).
    if (ct || cb) {
        const unsigned int nH = (ct ? 1u : 0u) + (cb ? 1u : 0u);
        alloc_vao_buffer(vao_idx, (size_t)(sizeof(GPUCell) * nH * columns), padding_cell_data_buffer, GPU_UPDATE_OFTEN);
        alloc_vao_buffer(vao_idx, selection_stride * nH * columns, padding_selection_buffer, GPU_UPDATE_OFTEN);

        unsigned int sidx = 0u;
        if (ct) {
            copy_vao_buffer_region(
                vao_idx,
                cell_data_buffer,
                (size_t)(sizeof(GPUCell) * top_row * columns),
                padding_cell_data_buffer,
                (size_t)(sizeof(GPUCell) * sidx * columns),
                (size_t)(columns * sizeof(GPUCell)));
            copy_vao_buffer_region(
                vao_idx,
                selection_buffer,
                selection_stride * top_row * columns,
                padding_selection_buffer,
                selection_stride * sidx * columns,
                selection_stride * columns);
            sidx++;
        }
        if (cb) {
            copy_vao_buffer_region(
                vao_idx,
                cell_data_buffer,
                (size_t)(sizeof(GPUCell) * bottom_row * columns),
                padding_cell_data_buffer,
                (size_t)(sizeof(GPUCell) * sidx * columns),
                (size_t)(sizeof(GPUCell) * columns));
            copy_vao_buffer_region(
                vao_idx,
                selection_buffer,
                selection_stride * bottom_row * columns,
                padding_selection_buffer,
                selection_stride * sidx * columns,
                selection_stride * columns);
        }

        // Strip-0 is top (or bottom when only bottom exists); strip-1 is bottom.
        // For a single-strip draw base_instance2/across2 equal strip-0 values so
        // the shader lerp is a no-op for all instances (strip_f is always 0.0).
        const unsigned int base0 = (ct ? top_row : bottom_row) * columns;
        const unsigned int base1 = bottom_row * columns;
        param_1ui(PL(is_horizontal), 1u);
        param_1ui(PL(along_count), columns);
        param_1ui(PL(instance_step), 1u);
        param_1ui(PL(base_instance), base0);
        param_1ui(PL(base_instance2), base1);
        param_2f(PL(across), ct ? NY(T - ct) : NY(B), ct ? NY(T) : NY(B + cb));
        param_2f(PL(across2), NY(B), NY(B + cb));
        param_1f(PL(along_start), NX(fL));
        param_1f(PL(along_step), dx);
        param_2f(PL(along_clamp), NX(fL), NX(R));
        draw_quad(!for_final_output, nH * columns);
    }

    // Vertical combined draw: left strip (strip 0) + right strip (strip 1).
    // Column cells are non-contiguous in the cell buffer so we gather them
    // CPU-side by mapping the buffer for reading, then upload in one shot.
    if (cl || cr) {
        const unsigned int nV = (cl ? 1u : 0u) + (cr ? 1u : 0u);
        // VLA sizes: lines is bounded by the window height / cell height (~<500).
        GPUCell gathered_cells[2 * lines];
        uint8_t gathered_sel[2 * lines * selection_stride];

        const unsigned int strip0_col = cl ? 0u : (columns - 1u);
        const unsigned int strip1_col = columns - 1u;

        const GPUCell *cells = (const GPUCell *)map_vao_buffer_for_reading(vao_idx, cell_data_buffer);
        for (unsigned int i = 0; i < lines; i++) {
            gathered_cells[i] = cells[(top_row + i) * columns + strip0_col];
            if (nV == 2u) gathered_cells[lines + i] = cells[(top_row + i) * columns + strip1_col];
        }
        unmap_vao_buffer(vao_idx, cell_data_buffer);

        const uint8_t *sel = (const uint8_t *)map_vao_buffer_for_reading(vao_idx, selection_buffer);
#define SEL(idx) (sel + selection_stride * (idx))
        for (unsigned int i = 0; i < lines; i++) {
            memcpy(gathered_sel + selection_stride * i, SEL((top_row + i) * columns + strip0_col), selection_stride);
            if (nV == 2u) memcpy(gathered_sel + selection_stride * (lines + i), SEL((top_row + i) * columns + strip1_col), selection_stride);
        }
#undef SEL
        unmap_vao_buffer(vao_idx, selection_buffer);

        void *dst = alloc_and_map_vao_buffer(vao_idx, (size_t)(sizeof(GPUCell) * nV * lines), padding_cell_data_buffer);
        memcpy(dst, gathered_cells, sizeof(GPUCell) * nV * lines);
        unmap_vao_buffer(vao_idx, padding_cell_data_buffer);

        dst = alloc_and_map_vao_buffer(vao_idx, selection_stride * nV * lines, padding_selection_buffer);
        memcpy(dst, gathered_sel, selection_stride * nV * lines);
        unmap_vao_buffer(vao_idx, padding_selection_buffer);

        const unsigned int base0 = top_row * columns + (cl ? 0u : (columns - 1u));
        const unsigned int base1 = top_row * columns + (columns - 1u);
        param_1ui(PL(is_horizontal), 0u);
        param_1ui(PL(along_count), lines);
        param_1ui(PL(instance_step), columns);
        param_1ui(PL(base_instance), base0);
        param_1ui(PL(base_instance2), base1);
        param_2f(PL(across), cl ? NX(fL - cl) : NX(R), cl ? NX(fL) : NX(R + cr));
        param_2f(PL(across2), NX(R), NX(R + cr));
        param_1f(PL(along_start), NY(T));
        param_1f(PL(along_step), dy);
        param_2f(PL(along_clamp), NY(T - ct), NY(B + cb));
        draw_quad(!for_final_output, nV * lines);
    }

#undef PL
    if (for_final_output) gpu_set_srgb_output(false);
    // Restore the canonical cell attribute layout so subsequent cell rendering is unaffected.
    configure_cell_vao_attributes(vao_idx, 0u, 1u);
    unbind_program();
#undef NX
#undef NY
}

static void
draw_tint(const UIRenderData *ui) {
    bind_program(TINT_PROGRAM);
    color_vec4_premult(program_param(TINT_PROGRAM, "tint_color"), ui->background_color, OPT(background_tint));
    param_4f(program_param(TINT_PROGRAM, "edges"), -1, -1, 1, 1);
    draw_quad(true, 0);
}

// Draw a range of the image render data. Indexed color images need a
// different program, so when any are present, switch programs at the
// boundaries between runs of images that need different programs, preserving
// draw order.
static int
program_for_image(const ImageRenderData *rd) {
    if (!rd->indexed_px_sz) return GRAPHICS_PROGRAM;
    return rd->is_unscaled ? GRAPHICS_INDEXED_UNSCALED_PROGRAM : GRAPHICS_INDEXED_PROGRAM;
}

static void
draw_image_layer(const UIRenderData *ui, ssize_t vao_idx, uint32_t start, uint32_t count) {
    if (!ui->grd.num_of_indexed_refs) {
        draw_graphics(GRAPHICS_PROGRAM, ui->grd.images, start, count, ui->inactive_text_alpha);
        return;
    }
    CELL_BUFFERS;
    // The color table may not be bound yet, for example, when the window has a background image
    bind_vao_uniform_buffer(vao_idx, color_table_buffer, program_uniform_block(GRAPHICS_INDEXED_PROGRAM, "ColorTable").slot);
    const ImageRenderData *data = ui->grd.images;
    for (uint32_t run_start = start, end = start + count; run_start < end;) {
        const int program = program_for_image(data + run_start);
        uint32_t run_end = run_start + 1;
        while (run_end < end && program_for_image(data + run_end) == program) run_end++;
        draw_graphics(program, ui->grd.images, run_start, run_end - run_start, ui->inactive_text_alpha);
        run_start = run_end;
    }
}

static void
draw_cells_with_layers(const UIRenderData *ui, ssize_t vao_idx) {
    if (ui->has_background_image && OPT(background_tint) > 0) draw_tint(ui);
    const bool has_content_between_background_and_foreground = ui->window_logo != NULL || ui->grd.num_of_below_refs > 0 || ui->grd.num_of_negative_refs > 0;
    if (has_content_between_background_and_foreground) {
        if (!ui->has_background_image) call_cell_program(CELL_BG_PROGRAM, ui, vao_idx, false, DRAW_DEFAULT_BG);
        if (ui->window_logo != NULL) draw_window_logo(ui);
        if (ui->grd.num_of_below_refs > 0) draw_image_layer(ui, vao_idx, 0, ui->grd.num_of_below_refs);
        call_cell_program(CELL_BG_PROGRAM, ui, vao_idx, false, DRAW_NON_DEFAULT_BG);
        if (ui->grd.num_of_negative_refs) draw_image_layer(ui, vao_idx, ui->grd.num_of_below_refs, ui->grd.num_of_negative_refs);
        call_cell_program(CELL_FG_PROGRAM, ui, vao_idx, false, DRAW_NEITHER_BG);
    } else call_cell_program(CELL_PROGRAM, ui, vao_idx, false, ui->has_background_image ? DRAW_NON_DEFAULT_BG : DRAW_BOTH_BG);

    if (ui->grd.num_of_positive_refs > 0) draw_image_layer(ui, vao_idx, ui->grd.num_of_below_refs + ui->grd.num_of_negative_refs, ui->grd.num_of_positive_refs);

    draw_visual_bell(ui);
    draw_drag_preview_overlay(ui);
    draw_progress_bar(ui);
    draw_scrollbar(ui);
    draw_hyperlink_target(ui);
    draw_window_number(ui);
}

void
blank_canvas(float background_opacity, color_type color_in_srgb, bool for_final_output) {
    if (for_final_output) {
        // we need to write pre-multiplied sRGB color to framebuffer
#define C(shift) ((((color_in_srgb >> shift) & 0xFF) / 255.f) * background_opacity)
        gpu_clear(C(16), C(8), C(0), background_opacity);
#undef C
    } else {
        // we need to write pre-multiplied linear color to framebuffer
#define C(shift) srgb_color((color_in_srgb >> shift) & 0xFF) * background_opacity
        gpu_clear(C(16), C(8), C(0), background_opacity);
#undef C
    }
}

bool
send_cell_data_to_gpu(ssize_t vao_idx, Screen *screen, OSWindow *os_window) {
    bool changed = false;
    if (os_window->fonts_data) {
        if (cell_prepare_to_render(vao_idx, screen, os_window->fonts_data)) changed = true;
    }
    return changed;
}

void
draw_cells(
    const WindowRenderData *srd,
    OSWindow *os_window,
    bool is_active_window,
    bool is_tab_bar,
    bool is_single_window,
    Window *window,
    const Window *title_bar_of,
    monotonic_t now) {
    Screen *screen = srd->screen;
    CELL_BUFFERS;
    bind_vertex_array(srd->vao_idx);
    // When inactive_text_alpha is negative, its absolute value is used as the
    // opacity and fading is based only on whether the current window is active.
    const float inactive_text_alpha = fabsf(OPT(inactive_text_alpha));
    const bool use_active_window_only = OPT(inactive_text_alpha) < 0.f;
    float current_inactive_text_alpha =
        use_active_window_only
            ? (is_tab_bar || is_active_window ? 1.0f : inactive_text_alpha)
            : (is_tab_bar || (!is_single_window && is_active_window) || (is_single_window && screen->cursor_render_info.is_focused) ? 1.0f
                                                                                                                                    : inactive_text_alpha);
    float bg_alpha = effective_os_window_alpha(os_window);

    color_type default_bg = cell_update_uniform_block(
        srd->vao_idx, screen, uniform_buffer, color_table_buffer, &screen->cursor_render_info, os_window, current_inactive_text_alpha, bg_alpha);
    set_cell_uniforms(screen->reload_all_gpu_data);
    WindowLogoRenderData *wl;
    if (window && (wl = &window->window_logo) && wl->id && (wl->instance = find_window_logo(global_state.all_window_logos, wl->id)) &&
        wl->instance->load_from_disk_ok) {
        if (!window->window_logo.instance->texture_id) { set_on_gpu_state(window->window_logo.instance, true); }
    } else wl = NULL;
    GraphicsManager *grman = screen->paused_rendering.expires_at && screen->paused_rendering.grman ? screen->paused_rendering.grman : screen->grman;
    UIRenderData ui = {
        .screen_width = srd->geometry.right - srd->geometry.left,
        .screen_height = srd->geometry.bottom - srd->geometry.top,
        .cell_width = os_window->fonts_data->fcm.cell_width,
        .cell_height = os_window->fonts_data->fcm.cell_height,
        .screen_left = srd->geometry.left,
        .screen_top = srd->geometry.top,
        .full_framebuffer_width = os_window->viewport_width,
        .full_framebuffer_height = os_window->viewport_height,
        .window = window,
        .screen = screen,
        .os_window = os_window,
        .grd = grman_render_data(grman),
        .window_logo = wl,
        .inactive_text_alpha = current_inactive_text_alpha,
        .has_background_image = has_bgimage(os_window),
        .background_color = default_bg,
        .bg_alpha = effective_os_window_alpha(os_window),
        .now = now,
    };
    screen->reload_all_gpu_data = false;
    save_viewport(ui.screen_left, ui.screen_top, ui.screen_width, ui.screen_height);
    if (ui.os_window->needs_layers) draw_cells_with_layers(&ui, srd->vao_idx);
    else draw_cells_without_layers(&ui, srd->vao_idx);
    restore_viewport();
    // The compensatory padding lies outside the per-window cell viewport, so it
    // is drawn after restoring the full framebuffer viewport.
    if (window) {
        draw_window_padding(
            &ui,
            window->size_mismatch_padding.left,
            window->size_mismatch_padding.top,
            window->size_mismatch_padding.right,
            window->size_mismatch_padding.bottom,
            srd->vao_idx,
            !ui.os_window->needs_layers);
    } else if (title_bar_of) {
        // The left and right compensatory padding of a window extends alongside
        // its title bar. The layout ensures there is no compensatory padding
        // between the title bar and the window border.
        draw_window_padding(
            &ui, title_bar_of->size_mismatch_padding.left, 0, title_bar_of->size_mismatch_padding.right, 0, srd->vao_idx, !ui.os_window->needs_layers);
    }
}
// }}}

// Borders {{{

static void
populate_border_colors(uint32_t colors[9], color_type active_window_bg, unsigned int num_visible_windows, bool all_windows_have_same_bg, const OSWindow *w) {
    colors[0] = (num_visible_windows > 1 && !all_windows_have_same_bg) ? OPT(background) : active_window_bg;
    colors[1] = OPT(active_border_color);
    colors[2] = OPT(inactive_border_color);
    colors[3] = 0;
    colors[4] = OPT(bell_border_color);
    colors[5] = OPT(tab_bar_background);
    colors[6] = OPT(tab_bar_margin_color);
    colors[7] = w->tab_bar_edge_color.left;
    colors[8] = w->tab_bar_edge_color.right;
}

ssize_t
create_border_vao(void) {
    ssize_t vao_idx = create_vao();

    add_buffer_to_vao(vao_idx, GPU_BUFFER_VERTEX);
    add_attribute_to_vao(
        vao_idx,
        program_attribute_location(BORDERS_PROGRAM, "rect"),
        /*size=*/4,
        /*dtype=*/GPU_ATTRIB_F32,
        /*stride=*/sizeof(BorderRect),
        /*offset=*/offsetof(BorderRect, left),
        /*divisor=*/1);
    add_attribute_to_vao(
        vao_idx,
        program_attribute_location(BORDERS_PROGRAM, "rect_color"),
        /*size=*/1,
        /*dtype=*/GPU_ATTRIB_U32,
        /*stride=*/sizeof(BorderRect),
        /*offset=*/offsetof(BorderRect, color),
        /*divisor=*/1);

    return vao_idx;
}

void
draw_borders(
    ssize_t vao_idx,
    unsigned int num_border_rects,
    BorderRect *rect_buf,
    bool rect_data_is_dirty,
    color_type active_window_bg,
    unsigned int num_visible_windows,
    bool all_windows_have_same_bg,
    OSWindow *w) {
    float background_opacity = effective_os_window_alpha(w);
    if (!num_border_rects) return;
    bind_program(BORDERS_PROGRAM);
    bind_vertex_array(vao_idx);
    const bool has_background_image = has_bgimage(w);
    if (has_background_image) background_opacity = OPT(background_tint) * OPT(background_tint_gaps);
    if (rect_data_is_dirty) {
        const size_t sz = sizeof(BorderRect) * num_border_rects;
        void *borders_buf_address = alloc_and_map_vao_buffer(vao_idx, sz, 0);
        if (borders_buf_address) memcpy(borders_buf_address, rect_buf, sz);
        unmap_vao_buffer(vao_idx, 0);
    }
    uint32_t colors[9];
    populate_border_colors(colors, active_window_bg, num_visible_windows, all_windows_have_same_bg, w);
    void *colors_buf =
        map_vao_buffer_for_write_only(shader_globals_vao_idx, BORDER_COLORS_GLOBAL_BUFFER, 0, program_uniform_block(BORDERS_PROGRAM, "Colors").size);
    const ArrayInformation border_colors_array = program_uniform_array(BORDERS_PROGRAM, "colors");
    write_uint_array_to_ubo(colors_buf, colors, arraysz(colors), &border_colors_array);
    unmap_vao_buffer(shader_globals_vao_idx, BORDER_COLORS_GLOBAL_BUFFER);
    param_1f(program_param(BORDERS_PROGRAM, "background_opacity"), background_opacity);
    if (!w->needs_layers) gpu_set_srgb_output(true);
    draw_quad(has_background_image, num_border_rects);
    if (!w->needs_layers) gpu_set_srgb_output(false);
    unbind_program();
    unbind_vertex_array();
}

void
draw_rounded_borders(BorderRects *br, color_type active_window_bg, unsigned int num_visible_windows, bool all_windows_have_same_bg, OSWindow *w) {
    if (!br->num_rounded_rects) return;
    uint32_t colors[9];
    populate_border_colors(colors, active_window_bg, num_visible_windows, all_windows_have_same_bg, w);
    // The corner regions between the rounded outline and its bounding rect
    // must be painted every frame: when not rendering in layers the
    // framebuffer is never cleared, kitty relies on full pixel coverage.
    // Fill them with the default background at the same opacity draw_borders()
    // uses for non-border rects, so corners match the surrounding gaps.
    float corner_bg_alpha = has_bgimage(w) ? OPT(background_tint) * OPT(background_tint_gaps) : effective_os_window_alpha(w);
    bind_vertex_array(br->vao_idx);
    if (!w->needs_layers) gpu_set_srgb_output(true);
    for (unsigned i = 0; i < br->num_border_rects; i++) {
        const BorderRect *r = br->rect_buf + i;
        if (!r->radius || !r->thickness) continue;
        Viewport rect = {.left = r->px.left, .top = r->px.top, .width = r->px.right - r->px.left, .height = r->px.bottom - r->px.top};
        unsigned radius = MIN(r->radius, MIN(rect.width, rect.height) / 2);
        unsigned color_index = r->color & 0xff;
        color_type color = color_index == 3 ? r->color >> 8 : colors[MIN(color_index, 8u)];
        draw_rounded_rect(rect, (float)r->thickness, radius, color, 0, 0.f, colors[0], corner_bg_alpha);
    }
    if (!w->needs_layers) gpu_set_srgb_output(false);
    unbind_program();
    // Deliberately leave the VAO bound: this runs after all cell drawing and
    // subsequent draw_quad() calls (e.g. the fullscreen blit in
    // stop_os_window_rendering()) need some VAO bound in a core profile context.
}

// }}}

// Cursor Trail {{{
void
draw_cursor_trail(CursorTrail *trail, Window *active_window) {
    bind_program(TRAIL_PROGRAM);

    param_floats(program_param(TRAIL_PROGRAM, "x_coords"), 4, 1, trail->corner_x);
    param_floats(program_param(TRAIL_PROGRAM, "y_coords"), 4, 1, trail->corner_y);

    param_floats(program_param(TRAIL_PROGRAM, "cursor_edge_x"), 2, 1, trail->cursor_edge_x);
    param_floats(program_param(TRAIL_PROGRAM, "cursor_edge_y"), 2, 1, trail->cursor_edge_y);

    color_type trail_color = OPT(cursor_trail_color);
    if (trail_color == 0) { // 0 means "none" was specified
        trail_color = active_window ? active_window->render_data.screen->last_rendered.cursor_bg : OPT(foreground);
    }
    color_vec3(program_param(TRAIL_PROGRAM, "trail_color"), trail_color);

    param_1f(program_param(TRAIL_PROGRAM, "trail_opacity"), trail->opacity);

    draw_quad(true, 0);
    unbind_program();
}

// }}}

// OSWindow {{{
static void
draw_bg_image(OSWindow *os_window, Tab *tab) {
    BackgroundImage *bg = background_image_for_os_window(os_window);
    if (!bg) return;
    BackgroundImageLayout layout = os_window->background_image.has_layout ? os_window->background_image.layout : OPT(background_image_layout);
    BackgroundImageRenderSettings s = {
        .os_window.width = os_window->viewport_width,
        .os_window.height = os_window->viewport_height,
        .instance_id = bg->id,
        .layout = layout,
        .linear = OPT(background_image_linear),
        .bgcolor = OPT(background),
        .opacity = effective_os_window_alpha(os_window),
    };
    float iwidth = bg->width, iheight = bg->height;
    float vwidth = s.os_window.width, vheight = s.os_window.height;
    if (CENTER_SCALED == layout) {
        float ifrac = iwidth / iheight;
        if (ifrac > (vwidth / vheight)) {
            iheight = vheight;
            iwidth = iheight * ifrac;
        } else {
            iwidth = vwidth;
            iheight = iwidth / ifrac;
        }
    }
    float tiled = 0.f;
    ;
    float left = -1.0, top = -1.0, right = 1.0, bottom = 1.0;
    switch (layout) {
        case TILING:
        case MIRRORED:
        case CLAMPED: tiled = 1.f; break;
        case SCALED: break;
        case CENTER_CLAMPED:
        case CENTER_SCALED: {
            float wfrac = (vwidth - iwidth) / vwidth;
            float hfrac = (vheight - iheight) / vheight;
            left += wfrac;
            right -= wfrac;
            top += hfrac;
            bottom -= hfrac;
        } break;
    }
    bind_program(BGIMAGE_PROGRAM);
    // altough we dont use this VO we need to ensure *some* VAO is bound at this point.
    bind_vertex_array(tab->border_rects.vao_idx);
    param_4f(program_param(BGIMAGE_PROGRAM, "sizes"), vwidth, vheight, iwidth, iheight);
    param_1f(program_param(BGIMAGE_PROGRAM, "tiled"), tiled);
    param_4f(program_param(BGIMAGE_PROGRAM, "positions"), left, top, right, bottom);
    color_vec4(program_param(BGIMAGE_PROGRAM, "background"), s.bgcolor, s.opacity);
    gpu_bind_texture(program_texture_slot(BGIMAGE_PROGRAM, "image"), bg->texture_id);
    draw_quad(false, 0);
    unbind_program();
}

static void
gpu_data_for_centered_image(ImageRenderData *ans, unsigned int screen_width_px, unsigned int screen_height_px, unsigned int width, unsigned int height) {
    float width_frac = 2 * MIN(1, width / (float)screen_width_px), height_frac = 2 * MIN(1, height / (float)screen_height_px);
    float hmargin = (2 - width_frac) / 2;
    float vmargin = (2 - height_frac) / 2;
    gpu_data_for_image(ans, -1 + hmargin, -1 + vmargin, -1 + hmargin + width_frac, -1 + vmargin + height_frac);
}

// Colors are passed to the shader as linear values, unless linear is false,
// for render targets that do not encode the output to sRGB.
static void
draw_alpha_mask(ImageRenderData *data, color_type fg, color_type bg, float background_opacity, bool linear) {
    bind_program(GRAPHICS_ALPHA_MASK_PROGRAM);
    const int32_t fg_loc = program_param(GRAPHICS_ALPHA_MASK_PROGRAM, "amask_fg"), bg_loc = program_param(GRAPHICS_ALPHA_MASK_PROGRAM, "amask_bg_premult");
    if (linear) {
        color_vec3(fg_loc, fg);
        color_vec4_premult(bg_loc, bg, background_opacity);
    } else {
#define C(color, shift) (((color >> shift) & 0xff) / 255.f)
        param_3f(fg_loc, C(fg, 16), C(fg, 8), C(fg, 0));
        param_4f(bg_loc, C(bg, 16) * background_opacity, C(bg, 8) * background_opacity, C(bg, 0) * background_opacity, background_opacity);
#undef C
    }
    draw_graphics(GRAPHICS_ALPHA_MASK_PROGRAM, data, 0, 1, 1.0);
}

static void
draw_centered_alpha_mask(size_t screen_width, size_t screen_height, size_t width, size_t height, uint8_t *canvas, float background_opacity) {
    ImageRenderData *data = load_alpha_mask_texture(width, height, canvas);
    gpu_data_for_centered_image(data, screen_width, screen_height, width, height);
    draw_alpha_mask(data, OPT(foreground), OPT(background), background_opacity, true);
}

// Render lines of text, each centered horizontally, into a single alpha mask
// surrounded by padding pixels on every side. Returns a canvas with a NULL
// pointer on failure.
static StringCanvas
render_centered_lines(FONTS_DATA_HANDLE fonts_data, const char *const *lines, size_t num_lines, size_t padding) {
    StringCanvas ans = {0}, rendered[4] = {0};
    if (num_lines > arraysz(rendered)) return ans;
    size_t width = 0, height = 0;
    bool ok = true;
    for (size_t i = 0; i < num_lines && ok; i++) {
        rendered[i] = render_simple_text(fonts_data, lines[i]);
        if (!rendered[i].canvas) ok = false;
        else {
            width = MAX(width, rendered[i].width);
            height += rendered[i].height;
        }
    }
    if (ok) {
        ans.width = width + 2 * padding;
        ans.height = height + 2 * padding;
        ans.canvas = calloc(ans.width * ans.height, 1);
        if (ans.canvas) {
            size_t y = padding;
            for (size_t i = 0; i < num_lines; i++) {
                const size_t x = padding + (width - rendered[i].width) / 2;
                for (size_t r = 0; r < rendered[i].height; r++, y++)
                    memcpy(ans.canvas + y * ans.width + x, rendered[i].canvas + r * rendered[i].width, rendered[i].width);
            }
        }
    }
    for (size_t i = 0; i < num_lines; i++) free(rendered[i].canvas);
    if (!ans.canvas) ans = (StringCanvas){0};
    return ans;
}

// Tell the user that software rendering is in use, see the gpu_driver option.
// Shown at the top of every OS window for SOFTWARE_RENDERING_BANNER_DURATION
// after it is first rendered, render_os_window() redraws the window to remove it.
static void
draw_software_rendering_banner(OSWindow *w, monotonic_t now) {
    if (!global_state.software_rendering || w->software_rendering_banner.done || w->live_resize.in_progress || !w->fonts_data) return;
    if (!w->software_rendering_banner.shown) {
        w->software_rendering_banner.shown = true;
        w->software_rendering_banner.shown_at = now;
    }
    static const char *const lines[] = {"Software rendering is in use,", "so kitty will be slow"};
    const size_t padding = MAX(4u, w->fonts_data->fcm.cell_height / 2);
    StringCanvas banner = render_centered_lines(w->fonts_data, lines, arraysz(lines), padding);
    if (!banner.canvas) {
        log_error("Failed to render the software rendering banner");
        w->software_rendering_banner.done = true;
        return;
    }
    const float vw = (float)w->viewport_width, vh = (float)w->viewport_height;
    if (vw > 0 && vh > 0) {
        ImageRenderData *data = load_alpha_mask_texture(banner.width, banner.height, banner.canvas);
        // In normalized device coordinates, horizontally centered, a little below the top edge
        const float half_width = MIN(1.f, banner.width / vw);
        const float top = MIN(1.f, -1.f + 2.f * padding / vh), bottom = MIN(1.f, top + 2.f * banner.height / vh);
        gpu_data_for_image(data, -half_width, top, half_width, bottom);
        save_viewport(0, 0, w->viewport_width, w->viewport_height);
        // Drawn directly into the window, after any layers have been composited
        const bool srgb = global_state.supports_framebuffer_srgb;
        if (srgb) gpu_set_srgb_output(true);
        // Inverted colors, so that it stands out from the terminal contents
        draw_alpha_mask(data, OPT(background), OPT(foreground), 1.f, srgb);
        if (srgb) gpu_set_srgb_output(false);
        restore_viewport();
    }
    free(banner.canvas);
}

static void
draw_resizing_text(OSWindow *w) {
    if (monotonic() - w->created_at > ms_to_monotonic_t(1000) && w->live_resize.num_of_resize_events > 1) {
        char text[32] = {0};
        unsigned int width = w->live_resize.width, height = w->live_resize.height;
        snprintf(text, sizeof(text), "%u by %u cells", width / w->fonts_data->fcm.cell_width, height / w->fonts_data->fcm.cell_height);
        StringCanvas rendered = render_simple_text(w->fonts_data, text);
        if (rendered.canvas) {
            draw_centered_alpha_mask(width, height, rendered.width, rendered.height, rendered.canvas, MAX(0.2f, MIN(OPT(background_opacity), 0.8f)));
            free(rendered.canvas);
        }
    }
}

void
blank_os_window(OSWindow *osw) {
    color_type color = OPT(background);
    if (osw->num_tabs > 0) {
        Tab *t = osw->tabs + osw->active_tab;
        if (t->num_windows == 1) {
            Window *w = t->windows + t->active_window;
            Screen *s = w->render_data.screen;
            if (s) { color = colorprofile_to_color(s->color_profile, s->color_profile->overridden.default_bg, s->color_profile->configured.default_bg).rgb; }
        }
    }
    blank_canvas(effective_os_window_alpha(osw), color, true);
}

// (Re)create a render target that draws into texture, freeing any existing one
static void
create_render_target_for(gpu_render_target_t *fb, gpu_texture_t texture) {
    if (*fb) free_framebuffer(fb);
    *fb = gpu_render_target_create(texture);
    if (!*fb) fatal("Failed to create a GPU render target with error: %s", gpu_last_error());
}

static void
start_os_window_rendering(OSWindow *os_window, Tab *tab) {
    // note that during live resize rendering is done in layers
    if (os_window->live_resize.in_progress) blank_os_window(os_window);
    if (os_window->needs_layers) {
        // Ensure the global shared texture is large enough for this window
        if (global_state.layers_render_texture.width < os_window->viewport_width || global_state.layers_render_texture.height < os_window->viewport_height) {
            if (global_state.layers_render_texture.texture_id) free_texture(&global_state.layers_render_texture.texture_id);
            if (global_state.layers_render_texture.framebuffer_id) free_framebuffer(&global_state.layers_render_texture.framebuffer_id);
            if (global_state.layers_render_texture.extra_texture_id) free_texture(&global_state.layers_render_texture.extra_texture_id);
            if (global_state.layers_render_texture.extra_texture_setup_fbo_id) free_framebuffer(&global_state.layers_render_texture.extra_texture_setup_fbo_id);
            if (global_state.layers_render_texture.texture_a_id) free_texture(&global_state.layers_render_texture.texture_a_id);
            if (global_state.layers_render_texture.texture_a_fbo_id) free_framebuffer(&global_state.layers_render_texture.texture_a_fbo_id);
            if (global_state.layers_render_texture.texture_b_id) free_texture(&global_state.layers_render_texture.texture_b_id);
            if (global_state.layers_render_texture.texture_b_fbo_id) free_framebuffer(&global_state.layers_render_texture.texture_b_fbo_id);
            unsigned new_w = (unsigned)MAX(global_state.layers_render_texture.width, os_window->viewport_width);
            unsigned new_h = (unsigned)MAX(global_state.layers_render_texture.height, os_window->viewport_height);
            setup_texture_as_render_target(new_w, new_h, &global_state.layers_render_texture.texture_id, &global_state.layers_render_texture.framebuffer_id);
            global_state.layers_render_texture.width = (int)new_w;
            global_state.layers_render_texture.height = (int)new_h;
            global_state.layers_render_texture.texture_generation++;
        }
        // Create per-window framebuffer if needed and attach the global texture to it
        if (!os_window->indirect_output.framebuffer_id ||
            os_window->indirect_output.attached_texture_generation != global_state.layers_render_texture.texture_generation) {
            create_render_target_for(&os_window->indirect_output.framebuffer_id, global_state.layers_render_texture.texture_id);
            os_window->indirect_output.attached_texture_generation = global_state.layers_render_texture.texture_generation;
        }
        if (custom_shaders.end.num_groups > 1) {
            // Lazily create the global shared extra texture (ping-pong target for multi-group end shaders)
            if (!global_state.layers_render_texture.extra_texture_id) {
                setup_texture_as_render_target(
                    (unsigned)global_state.layers_render_texture.width,
                    (unsigned)global_state.layers_render_texture.height,
                    &global_state.layers_render_texture.extra_texture_id,
                    &global_state.layers_render_texture.extra_texture_setup_fbo_id);
            }
            // Create/re-attach per-window extra FBO when generation changes
            if (os_window->indirect_output.extra_fbo_generation != global_state.layers_render_texture.texture_generation) {
                create_render_target_for(&os_window->indirect_output.extra_fbo_id, global_state.layers_render_texture.extra_texture_id);
                os_window->indirect_output.extra_fbo_generation = global_state.layers_render_texture.texture_generation;
            }
        }
        // Named texture A: global shared, per-window FBO
        if (custom_shaders.end.textures & (1u << CUSTOM_SHADER_TEXTURE_A)) {
            if (!global_state.layers_render_texture.texture_a_id) {
                setup_texture_as_render_target(
                    (unsigned)global_state.layers_render_texture.width,
                    (unsigned)global_state.layers_render_texture.height,
                    &global_state.layers_render_texture.texture_a_id,
                    &global_state.layers_render_texture.texture_a_fbo_id);
            }
            if (os_window->indirect_output.fbo_a_generation != global_state.layers_render_texture.texture_generation) {
                create_render_target_for(&os_window->indirect_output.fbo_a_id, global_state.layers_render_texture.texture_a_id);
                os_window->indirect_output.fbo_a_generation = global_state.layers_render_texture.texture_generation;
            }
        } else {
            if (os_window->indirect_output.fbo_a_id) free_framebuffer(&os_window->indirect_output.fbo_a_id);
        }
        // Named texture B: global shared, per-window FBO
        if (custom_shaders.end.textures & (1u << CUSTOM_SHADER_TEXTURE_B)) {
            if (!global_state.layers_render_texture.texture_b_id) {
                setup_texture_as_render_target(
                    (unsigned)global_state.layers_render_texture.width,
                    (unsigned)global_state.layers_render_texture.height,
                    &global_state.layers_render_texture.texture_b_id,
                    &global_state.layers_render_texture.texture_b_fbo_id);
            }
            if (os_window->indirect_output.fbo_b_generation != global_state.layers_render_texture.texture_generation) {
                create_render_target_for(&os_window->indirect_output.fbo_b_id, global_state.layers_render_texture.texture_b_id);
                os_window->indirect_output.fbo_b_generation = global_state.layers_render_texture.texture_generation;
            }
        } else {
            if (os_window->indirect_output.fbo_b_id) free_framebuffer(&os_window->indirect_output.fbo_b_id);
        }
        // Named texture persist: per-window, recreated when global texture dimensions change
        if (custom_shaders.end.textures & (1u << CUSTOM_SHADER_TEXTURE_PERSIST)) {
            if (os_window->persist_texture_generation != global_state.layers_render_texture.texture_generation) {
                if (os_window->persist_texture_id) free_texture(&os_window->persist_texture_id);
                if (os_window->persist_fbo_id) free_framebuffer(&os_window->persist_fbo_id);
                setup_texture_as_render_target(
                    (unsigned)global_state.layers_render_texture.width,
                    (unsigned)global_state.layers_render_texture.height,
                    &os_window->persist_texture_id,
                    &os_window->persist_fbo_id);
                os_window->persist_texture_generation = global_state.layers_render_texture.texture_generation;
            }
        } else {
            if (os_window->persist_texture_id) {
                free_texture(&os_window->persist_texture_id);
                os_window->persist_texture_generation = 0;
            }
            if (os_window->persist_fbo_id) free_framebuffer(&os_window->persist_fbo_id);
        }
        set_framebuffer_to_use_for_output(os_window->indirect_output.framebuffer_id);
        bind_framebuffer_for_output(0);
        save_viewport(0, 0, os_window->viewport_width, os_window->viewport_height);
        clear_current_framebuffer();
        draw_bg_image(os_window, tab);
    }
}

// Bilinear lookup of the position u, v (viewport UV, clamped to [0, 1]) in a
// pointer map, replacing it with the position of the content shown there
static void
sample_pointer_map(const float *data, double *u, double *v) {
    const double last = POINTER_MAP_SIZE - 1;
    const double fx = MAX(0., MIN(*u, 1.)) * last, fy = MAX(0., MIN(*v, 1.)) * last;
    const unsigned x0 = MIN((unsigned)fx, POINTER_MAP_SIZE - 2), y0 = MIN((unsigned)fy, POINTER_MAP_SIZE - 2);
    const double tx = fx - x0, ty = fy - y0;
#define P(x, y, c) ((double)data[2 * ((y) * POINTER_MAP_SIZE + (x)) + (c)])
#define L(c) ((P(x0, y0, c) * (1 - tx) + P(x0 + 1, y0, c) * tx) * (1 - ty) + (P(x0, y0 + 1, c) * (1 - tx) + P(x0 + 1, y0 + 1, c) * tx) * ty)
    *u = L(0);
    *v = L(1);
#undef L
#undef P
}

// The groups whose pointer_map() functions currently apply: those that are
// always active and those turned on by events that are active right now
static uint32_t
active_pointer_map_groups(const OSWindow *os_window) {
    uint32_t ans = 0;
    for (size_t g = 0; g < custom_shaders.end.num_groups; g++) {
        if (!(custom_shaders.end.pointer_map_groups & (1u << g))) continue;
        if (!group_is_animated(custom_shaders.end.groups + g) || os_window->shader_group_anim[g].active) ans |= 1u << g;
    }
    return ans;
}

// Moves a pointer position, in viewport pixels with the origin at the top left,
// to the position of the content that custom shaders such as crt actually show
// there, so that clicks and selections land on what the user sees.
void
map_pointer_position(const OSWindow *os_window, double *x, double *y) {
    const float *data = os_window->pointer_map.data;
    if (!data || !custom_shaders.end.has_pointer_map || os_window->pointer_map.pipeline_generation != custom_shaders.generation) return;
    // The map is updated only when the custom shaders are drawn, which they
    // are not once every group has been turned off, so check that it is
    // still for the groups that are active
    const uint32_t groups = active_pointer_map_groups(os_window);
    if (!groups || groups != os_window->pointer_map.groups) return;
    const double width = os_window->viewport_width, height = os_window->viewport_height;
    if (width <= 0 || height <= 0) return;
    const double u = *x / width, v = 1. - *y / height;
    const double cu = MAX(0., MIN(u, 1.)), cv = MAX(0., MIN(v, 1.));
    double mu = cu, mv = cv;
    sample_pointer_map(data, &mu, &mv);
    // Positions outside the viewport, such as when drag selecting past its
    // edge, move along with the nearest edge
    *x = (mu + u - cu) * width;
    *y = (1. - (mv + v - cv)) * height;
}

// Renders the pointer_map() functions of the pipeline into a small texture
// and reads it back so that pointer events can be mapped without the GPU. A
// pointer map can depend only on the pipeline, the viewport size and which
// groups are active, so this is done only when those change.
static void
update_pointer_map(OSWindow *os_window, int32_t group_loc) {
    const uint32_t groups = active_pointer_map_groups(os_window);
    if (os_window->pointer_map.pipeline_generation == custom_shaders.generation && os_window->pointer_map.groups == groups &&
        (os_window->pointer_map.data || !groups)) {
        if (os_window->live_resize.in_progress) return; // avoid a GPU sync on every frame of a live resize
        if (os_window->pointer_map.viewport_width == os_window->viewport_width && os_window->pointer_map.viewport_height == os_window->viewport_height) return;
    }
    os_window->pointer_map.viewport_width = os_window->viewport_width;
    os_window->pointer_map.viewport_height = os_window->viewport_height;
    os_window->pointer_map.pipeline_generation = custom_shaders.generation;
    os_window->pointer_map.groups = 0;
    // No pointer_map() applies, such as when content moving groups are toggled off, so pointer events are not moved
    if (!groups) return;
    if (!os_window->pointer_map.data && !(os_window->pointer_map.data = malloc(sizeof(float) * 2 * POINTER_MAP_SIZE * POINTER_MAP_SIZE))) return;
    if (!pointer_map_target.framebuffer_id)
        setup_texture_as_render_target(POINTER_MAP_SIZE, POINTER_MAP_SIZE, &pointer_map_target.texture_id, &pointer_map_target.framebuffer_id);
    // The pointer map does not sample any textures, but every sampler must be bound to a valid one
    static const char *const names[] = {"backbuffer", "a", "b", "persist"};
    for (size_t i = 0; i < arraysz(names); i++) {
        uint32_t slot;
        if (try_program_texture_slot(CUSTOM_END_PROGRAM, names[i], &slot)) gpu_bind_texture(slot, global_state.layers_render_texture.texture_id);
    }
    bind_framebuffer_for_output(pointer_map_target.framebuffer_id);
    gpu_set_viewport(0, 0, POINTER_MAP_SIZE, POINTER_MAP_SIZE);
    param_1i(group_loc, -1);
    // Absent when no group with a pointer_map() is turned on and off by events
    int32_t active_groups_loc = try_program_param(CUSTOM_END_PROGRAM, "active_groups");
    if (active_groups_loc >= 0) param_1ui(active_groups_loc, groups);
    draw_quad(false, 0);
    static uint8_t pixels[POINTER_MAP_SIZE * POINTER_MAP_SIZE * 4];
    gpu_read_pixels(0, 0, POINTER_MAP_SIZE, POINTER_MAP_SIZE, pixels);
    // See encode_pointer_map() in pipeline.slang. Rows are read back top to
    // bottom, while rows of the pointer map are in order of increasing UV y,
    // that is, bottom to top.
    for (size_t row = 0; row < POINTER_MAP_SIZE; row++) {
        const uint8_t *src = pixels + 4 * POINTER_MAP_SIZE * row;
        float *dst = os_window->pointer_map.data + 2 * POINTER_MAP_SIZE * (POINTER_MAP_SIZE - 1 - row);
        for (size_t col = 0; col < POINTER_MAP_SIZE; col++) {
            const uint8_t *p = src + 4 * col;
            dst[2 * col] = (float)(p[0] * 256 + p[2]) / 65535.f;
            dst[2 * col + 1] = (float)(p[1] * 256 + p[3]) / 65535.f;
        }
    }
    os_window->pointer_map.groups = groups;
}

static void
free_pointer_map_target(void) {
    if (pointer_map_target.texture_id) free_texture(&pointer_map_target.texture_id);
    if (pointer_map_target.framebuffer_id) free_framebuffer(&pointer_map_target.framebuffer_id);
}

static void
run_custom_end_shader(OSWindow *os_window, float sx, float sy, monotonic_t now) {
    bind_program(CUSTOM_END_PROGRAM);
    struct GPUCustomEndData {
        float src_rect[4];
        float dest_rect[4];
        float background[4];
        float foreground[4];
        float active_window_background[4];
        float mouse_pos[4];
        float mouse_button_pressed[4];
        float active_window_geometry[4];
        float active_window_padding[4];
        float bell_window_geometry[4];
        float central_area[4];
        float cursor_trail_corners_x[4];
        float cursor_trail_corners_y[4];
        float cursor_trail_prev_corners_x[4];
        float cursor_trail_prev_corners_y[4];
        float cursor_trail_edge[4];
        float cursor_trail_prev_edge[4];
        float cursor_color[4];
        float cursor_trail_color[4];
        float cursor_trail_history_from[CURSOR_TRAIL_HISTORY_SIZE][4];
        float cursor_trail_history_to[CURSOR_TRAIL_HISTORY_SIZE][4];
        float cursor_trail_history_age[CURSOR_TRAIL_HISTORY_SIZE / 4][4];
        uint32_t viewport_size_pixels[2];
        float mouse_pointer_hidden;
        float cursor_trail_state;
        float timestamp, last_rendered_at;
        uint32_t frame_counter;
        float cursor_trail_change_time;
        uint32_t timestamp_seconds;
        float timestamp_fraction;
        float time_since_last_render;
        float cursor_trail_age;
        float active_window_alternate_screen;
        float active_window_command_running;
        float active_window_alternate_screen_age;
        float active_window_command_state_age;
    };
    // This struct is a hand written mirror of the std140 layout of
    // KittyCustomShaderData in types.slang, so check that they match once.
    const UniformBlock data_block = program_uniform_block(CUSTOM_END_PROGRAM, "KittyCustomShaderData");
    static bool data_block_size_checked = false;
    if (!data_block_size_checked) {
        data_block_size_checked = true;
        if ((size_t)data_block.size < sizeof(struct GPUCustomEndData))
            fatal(
                "The KittyCustomShaderData uniform block is %d bytes but the C struct mirroring it is %zu bytes",
                data_block.size,
                sizeof(struct GPUCustomEndData));
    }
    struct GPUCustomEndData *d = (struct GPUCustomEndData *)map_vao_buffer_for_write_only(custom_end_vao_idx, 0, 0, data_block.size);
    memset(d, 0, sizeof(struct GPUCustomEndData));
    // The viewport is in the top left corner of the texture, see gpu/api.h
    d->src_rect[2] = sx;
    d->src_rect[3] = sy;
    d->dest_rect[0] = -1;
    d->dest_rect[1] = -1;
    d->dest_rect[2] = 1;
    d->dest_rect[3] = 1;
#define FILL_COLOR(dst, c)                         \
    do {                                           \
        (dst)[0] = srgb_color(((c) >> 16) & 0xFF); \
        (dst)[1] = srgb_color(((c) >> 8) & 0xFF);  \
        (dst)[2] = srgb_color((c) & 0xFF);         \
        (dst)[3] = 1.f;                            \
    } while (0)
    FILL_COLOR(d->background, OPT(background));
    FILL_COLOR(d->foreground, OPT(foreground));
    color_type active_bg = OPT(background);
    color_type cursor_color = OPT(foreground);
    float cursor_opacity = 0.f;
    WindowGeometry active_win_geom = {0};
    d->active_window_alternate_screen_age = -1.f;
    d->active_window_command_state_age = -1.f;
    if (os_window->num_tabs > 0) {
        Tab *t = os_window->tabs + os_window->active_tab;
        if (t->num_windows) {
            Window *w = t->windows + t->active_window;
            active_win_geom = w->render_data.geometry;
            if (os_window->viewport_width && os_window->viewport_height) {
                const float width = (float)os_window->viewport_width, height = (float)os_window->viewport_height;
                // spaces is all the space the layout reserved around the window:
                // margin, border (only if the layout reserves it), padding and
                // cell-size compensation.
                const WindowGeometry *sg = &w->render_data.geometry;
                d->active_window_padding[0] = (float)sg->spaces.left / width;
                d->active_window_padding[1] = (float)sg->spaces.bottom / height;
                d->active_window_padding[2] = (float)sg->spaces.right / width;
                d->active_window_padding[3] = (float)sg->spaces.top / height;
                // The content geometry excludes the title bar. Include it before
                // extending to the outer padding, so the effect boundary cannot
                // cut through a title bar at either edge of the window.
                const WindowRenderData *trd = &w->window_title_render_data;
                if (trd->screen && trd->geometry.right > trd->geometry.left && trd->geometry.bottom > trd->geometry.top) {
                    if (trd->geometry.top < active_win_geom.top) d->active_window_padding[3] += (float)(active_win_geom.top - trd->geometry.top) / height;
                    if (trd->geometry.bottom > active_win_geom.bottom)
                        d->active_window_padding[1] += (float)(trd->geometry.bottom - active_win_geom.bottom) / height;
                }
            }
            Screen *s = w->render_data.screen;
            if (s) {
                active_bg = colorprofile_to_color(s->color_profile, s->color_profile->overridden.default_bg, s->color_profile->configured.default_bg).rgb;
                cursor_color = s->last_rendered.cursor_bg;
                cursor_opacity = MAX(0.f, MIN(s->cursor_render_info.cursor_opacity, 1.f));
                d->active_window_alternate_screen = s->linebuf == s->alt_linebuf ? 1.f : 0.f;
                d->active_window_command_running = s->command_state.running ? 1.f : 0.f;
                const monotonic_t alt_changed_at = MAX(s->alternate_screen.entered_at, s->alternate_screen.exited_at);
                if (alt_changed_at) d->active_window_alternate_screen_age = (float)monotonic_t_to_s_double(now - alt_changed_at);
                const monotonic_t cmd_changed_at = MAX(s->command_state.started_at, s->command_state.finished_at);
                if (cmd_changed_at) d->active_window_command_state_age = (float)monotonic_t_to_s_double(now - cmd_changed_at);
            }
        }
    }
    FILL_COLOR(d->active_window_background, active_bg);
#undef FILL_COLOR
    // NDC y increases downwards while UV y, as seen by custom shaders, increases upwards
#define NDC_TO_UV(v) (((v) + 1.0f) * 0.5f)
#define NDC_Y_TO_UV(v) ((1.0f - (v)) * 0.5f)
    // Convert to seconds via double, as float32 cannot represent times since
    // kitty started precisely once kitty has been running for a few hours.
#define SECONDS(t) ((float)monotonic_t_to_s_double(t))
    {
        CursorTrail *ct = NULL;
        d->cursor_trail_age = -1.f;
        for (int i = 0; i < CURSOR_TRAIL_HISTORY_SIZE; i++) d->cursor_trail_history_age[i / 4][i % 4] = -1.f;
        if (OPT(cursor_trail) && os_window->num_tabs > 0) {
            CursorTrail *candidate = &os_window->tabs[os_window->active_tab].cursor_trail;
            if (candidate->needs_render) ct = candidate;
            // The history outlives the trail so that effects started by a move can finish
            for (int i = 0; i < CURSOR_TRAIL_HISTORY_SIZE; i++) {
                const CursorMove *m = candidate->history + i;
                if (!m->at) break;
                for (int k = 0; k < 2; k++) {
                    d->cursor_trail_history_from[i][k] = NDC_TO_UV(m->from_x[k]);
                    d->cursor_trail_history_from[i][k + 2] = NDC_Y_TO_UV(m->from_y[k]);
                    d->cursor_trail_history_to[i][k] = NDC_TO_UV(m->to_x[k]);
                    d->cursor_trail_history_to[i][k + 2] = NDC_Y_TO_UV(m->to_y[k]);
                }
                d->cursor_trail_history_age[i / 4][i % 4] = SECONDS(now - m->at);
            }
        }
        if (ct) {
            for (int i = 0; i < 4; i++) {
                d->cursor_trail_corners_x[i] = NDC_TO_UV(ct->corner_x[i]);
                d->cursor_trail_corners_y[i] = NDC_Y_TO_UV(ct->corner_y[i]);
                d->cursor_trail_prev_corners_x[i] = NDC_TO_UV(ct->previous_corner_x[i]);
                d->cursor_trail_prev_corners_y[i] = NDC_Y_TO_UV(ct->previous_corner_y[i]);
            }
            d->cursor_trail_edge[0] = NDC_TO_UV(ct->cursor_edge_x[0]);   // left
            d->cursor_trail_edge[1] = NDC_TO_UV(ct->cursor_edge_x[1]);   // right
            d->cursor_trail_edge[2] = NDC_Y_TO_UV(ct->cursor_edge_y[0]); // top
            d->cursor_trail_edge[3] = NDC_Y_TO_UV(ct->cursor_edge_y[1]); // bottom
            if (ct->prev_edge_valid) {
                d->cursor_trail_prev_edge[0] = NDC_TO_UV(ct->prev_cursor_edge_x[0]);   // left
                d->cursor_trail_prev_edge[1] = NDC_TO_UV(ct->prev_cursor_edge_x[1]);   // right
                d->cursor_trail_prev_edge[2] = NDC_Y_TO_UV(ct->prev_cursor_edge_y[0]); // top
                d->cursor_trail_prev_edge[3] = NDC_Y_TO_UV(ct->prev_cursor_edge_y[1]); // bottom
            }
            d->cursor_trail_color[3] = ct->opacity;
            d->cursor_trail_state = 1.0f;
            if (ct->cursor_changed_at) {
                d->cursor_trail_change_time = SECONDS(ct->cursor_changed_at);
                d->cursor_trail_age = SECONDS(now - ct->cursor_changed_at);
            }
        }
    }
#undef NDC_TO_UV
#undef NDC_Y_TO_UV
#define FILL_COLOR3(dst, c)                        \
    do {                                           \
        (dst)[0] = srgb_color(((c) >> 16) & 0xFF); \
        (dst)[1] = srgb_color(((c) >> 8) & 0xFF);  \
        (dst)[2] = srgb_color((c) & 0xFF);         \
    } while (0)
    FILL_COLOR3(d->cursor_color, cursor_color);
    d->cursor_color[3] = cursor_opacity;
    {
        color_type trail_color = OPT(cursor_trail_color);
        if (trail_color == 0) trail_color = cursor_color;
        FILL_COLOR3(d->cursor_trail_color, trail_color);
    }
#undef FILL_COLOR3
    d->viewport_size_pixels[0] = (uint32_t)os_window->viewport_width;
    d->viewport_size_pixels[1] = (uint32_t)os_window->viewport_height;
    const float vpw = (float)os_window->viewport_width, vph = (float)os_window->viewport_height;
    if (vpw > 0 && vph > 0) {
        d->mouse_pos[0] = (float)os_window->mouse_x / vpw;
        d->mouse_pos[1] = 1.f - (float)os_window->mouse_y / vph;
        d->mouse_pos[2] = (float)os_window->mouse_left_press_x / vpw;
        d->mouse_pos[3] = 1.f - (float)os_window->mouse_left_press_y / vph;
    }
    d->mouse_button_pressed[0] = os_window->mouse_button_pressed[GLFW_MOUSE_BUTTON_LEFT];
    d->mouse_button_pressed[1] = os_window->mouse_button_pressed[GLFW_MOUSE_BUTTON_RIGHT];
    d->mouse_button_pressed[2] = os_window->mouse_button_pressed[GLFW_MOUSE_BUTTON_MIDDLE];
    d->mouse_button_pressed[3] = os_window->mouse_button_pressed[3];
    d->mouse_pointer_hidden = is_mouse_hidden(os_window) ? 1.f : 0.f;
    d->timestamp = SECONDS(now);
    d->last_rendered_at = SECONDS(os_window->last_rendered_at);
    d->timestamp_seconds = (uint32_t)(now / MONOTONIC_T_1e9);
    d->timestamp_fraction = (float)monotonic_t_to_s_double(now % MONOTONIC_T_1e9);
    if (os_window->last_rendered_at) d->time_since_last_render = SECONDS(now - os_window->last_rendered_at);
#undef SECONDS
    d->frame_counter = os_window->frame_counter;
    if (vpw > 0 && vph > 0 && active_win_geom.right > active_win_geom.left) {
        d->active_window_geometry[0] = (float)active_win_geom.left / vpw;
        d->active_window_geometry[1] = 1.f - (float)active_win_geom.bottom / vph;
        d->active_window_geometry[2] = (float)(active_win_geom.right - active_win_geom.left) / vpw;
        d->active_window_geometry[3] = (float)(active_win_geom.bottom - active_win_geom.top) / vph;
    }
    if (vpw > 0 && vph > 0) {
        Region central_rgn = {0}, tab_bar_rgn = {0};
        os_window_regions(os_window, &central_rgn, &tab_bar_rgn);
        d->central_area[0] = (float)central_rgn.left / vpw;
        d->central_area[1] = 1.f - (float)central_rgn.bottom / vph;
        d->central_area[2] = (float)(central_rgn.right - central_rgn.left) / vpw;
        d->central_area[3] = (float)(central_rgn.bottom - central_rgn.top) / vph;
    } else {
        d->central_area[2] = 1.f;
        d->central_area[3] = 1.f;
    }
    if (os_window->last_bell_window_id && os_window->num_tabs > 0 && vpw > 0 && vph > 0) {
        WindowGeometry bell_win_geom = {0};
        bool bell_win_found = false;
        Tab *bt = os_window->tabs + os_window->active_tab;
        for (unsigned i = 0; i < bt->num_windows; i++) {
            Window *bw = bt->windows + i;
            if (bw->id == os_window->last_bell_window_id && bw->visible) {
                bell_win_geom = bw->render_data.geometry;
                bell_win_found = true;
                break;
            }
        }
        if (bell_win_found && bell_win_geom.right > bell_win_geom.left) {
            d->bell_window_geometry[0] = (float)bell_win_geom.left / vpw;
            d->bell_window_geometry[1] = 1.f - (float)bell_win_geom.bottom / vph;
            d->bell_window_geometry[2] = (float)(bell_win_geom.right - bell_win_geom.left) / vpw;
            d->bell_window_geometry[3] = (float)(bell_win_geom.bottom - bell_win_geom.top) / vph;
        } else {
            memcpy(d->bell_window_geometry, d->central_area, sizeof(d->bell_window_geometry));
        }
    }
    unmap_vao_buffer(custom_end_vao_idx, 0);
    bind_vao_uniform_buffer(custom_end_vao_idx, 0, program_uniform_block(CUSTOM_END_PROGRAM, "KittyCustomShaderData").slot);

    // A custom shader need not reference any of these, in which case the driver
    // drops them and glUniform*() on the resulting -1 location is a no-op.
    int32_t group_loc = try_program_param(CUSTOM_END_PROGRAM, "group");
    int32_t viewport_loc = try_program_param(CUSTOM_END_PROGRAM, "viewport");
    int32_t anim_progress_loc = try_program_param(CUSTOM_END_PROGRAM, "animation_progress");
    int32_t convert_to_srgb_loc = try_program_param(CUSTOM_END_PROGRAM, "convert_to_srgb");
    if (custom_shaders.end.has_pointer_map && group_loc >= 0) update_pointer_map(os_window, group_loc);
    const unsigned num_groups = (unsigned)custom_shaders.end.num_groups;
    const unsigned textures_mask = custom_shaders.end.textures;
    const int vw = os_window->viewport_width, vh = os_window->viewport_height;

    // Named texture IDs and their render-target FBOs, indexed by NamedTexture enum value
    const gpu_texture_t named_tex_ids[4] = {
        0, // DEFAULT — unused
        global_state.layers_render_texture.texture_a_id,
        global_state.layers_render_texture.texture_b_id,
        os_window->persist_texture_id,
    };
    const gpu_render_target_t named_tex_fbos[4] = {
        0, // DEFAULT — unused
        os_window->indirect_output.fbo_a_id,
        os_window->indirect_output.fbo_b_id,
        os_window->persist_fbo_id,
    };
    // The binding slots of the named textures, indexed by NamedTexture enum
    // value, false in has_named_tex_slot when the program does not use the texture
    static const char *const named_tex_names[4] = {"backbuffer", "a", "b", "persist"};
    uint32_t named_tex_slots[4] = {0};
    bool has_named_tex_slot[4];
    for (size_t i = 0; i < arraysz(named_tex_names); i++)
        has_named_tex_slot[i] = try_program_texture_slot(CUSTOM_END_PROGRAM, named_tex_names[i], named_tex_slots + i);

    // Pre-scan to find the last group that will actually run this frame.
    // That group gets convert_to_srgb=true so its draw call replaces the
    // blit pass; all other groups write premultiplied linear RGB and skip it.
    int last_active_g = -1;
    for (unsigned g = 0; g < num_groups; g++) {
        const CustomShaderGroup *cg = &custom_shaders.end.groups[g];
        // Non-attached always-active groups always run; attached and animated groups run only when active.
        if (!group_is_animated(cg) || os_window->shader_group_anim[g].active) last_active_g = (int)g;
    }

    // Ping-pong state: when true, backbuffer = texture_id and the ping-pong
    // target is extra_texture_id; toggled each time a group outputs to DEFAULT.
    bool backbuffer_is_main = true;

    float anim_progress[MAX_CUSTOM_SHADER_GROUPS];
    custom_shader_group_progress(os_window, now, anim_progress);

    for (unsigned g = 0; g < num_groups; g++) {
        const CustomShaderGroup *cg = &custom_shaders.end.groups[g];
        const bool is_last = (last_active_g >= 0 && g == (unsigned)last_active_g);

        // Skip inactive groups. Non-attached, non-animated groups always run; all others require
        // shader_group_anim[g].active (set by update_custom_shader_animations, including attach logic).
        if (group_is_animated(cg) && !os_window->shader_group_anim[g].active) continue;
        const gpu_texture_t backbuffer =
            backbuffer_is_main ? global_state.layers_render_texture.texture_id : global_state.layers_render_texture.extra_texture_id;

        // Bind backbuffer to the backbuffer texture unit
        if (has_named_tex_slot[CUSTOM_SHADER_TEXTURE_DEFAULT]) gpu_bind_texture(named_tex_slots[CUSTOM_SHADER_TEXTURE_DEFAULT], backbuffer);

        // Bind each named texture to its own unit.
        // If the texture is the output for this group, or is not declared in the
        // pipeline, fall back to backbuffer so the sampler is always valid.
        for (int t = CUSTOM_SHADER_TEXTURE_A; t <= CUSTOM_SHADER_TEXTURE_PERSIST; t++) {
            gpu_texture_t tex;
            if (!is_last && cg->output_texture == (NamedTexture)t) {
                tex = backbuffer; // can't read from the render target we're writing to
            } else if (textures_mask & (1u << t)) {
                tex = named_tex_ids[t];
            } else {
                tex = backbuffer; // not present — fall back to backbuffer
            }
            if (has_named_tex_slot[t]) gpu_bind_texture(named_tex_slots[t], tex);
        }

        // Set the output framebuffer
        if (is_last) {
            set_framebuffer_to_use_for_output(0);
            bind_framebuffer_for_output(0);
        } else if (cg->output_texture != CUSTOM_SHADER_TEXTURE_DEFAULT) {
            // Output to named texture; backbuffer is unchanged for the next group
            bind_framebuffer_for_output(named_tex_fbos[cg->output_texture]);
        } else {
            // Ping-pong: output to the other texture, which becomes the new backbuffer
            bind_framebuffer_for_output(backbuffer_is_main ? os_window->indirect_output.extra_fbo_id : os_window->indirect_output.framebuffer_id);
            backbuffer_is_main = !backbuffer_is_main;
        }

        // Set the viewport
        float vp_x, vp_y, vp_w, vp_h;
        if (is_last) {
            // Last group always covers the full screen region
            if (os_window->live_resize.in_progress) {
                gpu_set_viewport(0, 0, vw, vh); // the top left corner of the larger framebuffer
            } else {
                gpu_set_viewport(0, 0, vw, vh);
            }
            vp_x = 0.f;
            vp_y = 0.f;
            vp_w = 1.f;
            vp_h = 1.f;
        } else {
            float px = cg->viewport_pos.x, py = cg->viewport_pos.y;
            float sw = cg->viewport_size.w, sh = cg->viewport_size.h;
            // viewport_pos/size are standard UV (origin at bottom-left, y increasing
            // upward), while the GPU viewport has its origin at the top left.
            int32_t x0 = MAX(0, (int32_t)(px * vw));
            int32_t y0 = MAX(0, (int32_t)(py * vh)); // from the bottom
            int32_t x1 = MIN(vw, (int32_t)((px + sw) * vw));
            int32_t y1 = MIN(vh, (int32_t)((py + sh) * vh)); // from the bottom
            gpu_set_viewport(x0, vh - y1, MAX(0, x1 - x0), MAX(0, y1 - y0));
            vp_x = px;
            vp_y = py;
            vp_w = sw;
            vp_h = sh;
        }

        param_1i(group_loc, (int32_t)g);
        param_4f(viewport_loc, vp_x, vp_y, vp_w, vp_h);
        param_1f(anim_progress_loc, anim_progress[g]);
        param_1i(convert_to_srgb_loc, is_last ? 1 : 0);
        // debug_rendering("Custom shader draw group %u: anim_progress=%.4f viewport=(%.2f,%.2f,%.2f,%.2f)\n", g, anim_progress[g], vp_x, vp_y, vp_w, vp_h);
        draw_quad(false, 0);
    }
}

static void
stop_os_window_rendering(OSWindow *os_window, Tab *tab, Window *active_window, monotonic_t now) {
    if (OPT(cursor_trail) && tab->cursor_trail.needs_render && !(custom_shaders.end.active && custom_shaders.end.bypass_builtin_trail))
        draw_cursor_trail(&tab->cursor_trail, active_window);
    if (os_window->needs_layers) {
        float sx = global_state.layers_render_texture.width > 0 ? (float)os_window->viewport_width / (float)global_state.layers_render_texture.width : 1.f;
        float sy = global_state.layers_render_texture.height > 0 ? (float)os_window->viewport_height / (float)global_state.layers_render_texture.height : 1.f;
        if (custom_shaders.end.active && os_window->shader_anim.has_active_shaders) {
            // debug_rendering("Custom end shader running (groups=%zu)\n", custom_shaders.end.num_groups);
            restore_viewport();
            if (os_window->live_resize.in_progress) save_viewport(0, 0, os_window->viewport_width, os_window->viewport_height);
            run_custom_end_shader(os_window, sx, sy, now);
        } else {
            // debug_rendering("Custom shaders inactive, falling back to blit\n");
            set_framebuffer_to_use_for_output(0);
            bind_framebuffer_for_output(0);
            bind_program(BLIT_PROGRAM);
            gpu_bind_texture(program_texture_slot(BLIT_PROGRAM, "image"), global_state.layers_render_texture.texture_id);
            param_4f(program_param(BLIT_PROGRAM, "src_rect"), 0, 0, sx, sy);
            param_4f(program_param(BLIT_PROGRAM, "dest_rect"), -1, -1, 1, 1);
            restore_viewport();
            if (os_window->live_resize.in_progress) save_viewport(0, 0, os_window->viewport_width, os_window->viewport_height);
            draw_quad(false, 0);
        }
        if (os_window->live_resize.in_progress) {
            restore_viewport();
            draw_resizing_text(os_window);
        }
    }
    draw_software_rendering_banner(os_window, now);
    os_window->last_rendered_at = now;
    os_window->frame_counter++;
}

void
setup_os_window_for_rendering(OSWindow *os_window, Tab *tab, Window *active_window, bool start, monotonic_t now) {
    if (start) start_os_window_rendering(os_window, tab);
    else stop_os_window_rendering(os_window, tab, active_window, now);
}

// Take a screenshot of the OS Window, must be called immediately after
// the OSWindow is rendered into the back buffer and before the buffers
// are swapped. If thumb_w or thumb_h are zero the are set to the corresponding
// dimension of the source region (viewport or central region without tab bar).
// Takes a screenshot of a rectangular region of the OSWindow's framebuffer.
// The region parameter specifies which part of the framebuffer to capture.
// Scaling is performed on the GPU using the SCREENSHOT_PROGRAM shader for better performance.
// The shader properly handles sRGB color space conversion and downscaling.
// Setting the thumbnail dimensions to zero disables scaling.
// If no_scaling is true, thumb_w/thumb_h are ignored and the region is read
// back directly from the framebuffer with no GPU resampling, for a pixel
// perfect capture. In both cases rows are output top to bottom.
void
take_screenshot_of_rectangular_region(OSWindow *os_window, Region region, unsigned char *dst_buf, unsigned *thumb_w, unsigned *thumb_h, bool no_scaling) {
    unsigned vh = os_window->viewport_height;

    // Calculate the source region dimensions
    unsigned src_height = region.bottom - region.top;
    unsigned src_width = region.right - region.left;

    if (no_scaling) {
        *thumb_w = src_width;
        *thumb_h = src_height;
        gpu_read_pixels((int32_t)region.left, (int32_t)region.top, src_width, src_height, dst_buf);
        return;
    }

    unsigned vw = os_window->viewport_width;
    if (!*thumb_w) *thumb_w = src_width;
    if (!*thumb_h) *thumb_h = src_height;
    *thumb_w = MIN(src_width, *thumb_w);
    *thumb_h = MIN(src_height, *thumb_h);

    // Create a texture to hold the current framebuffer content
    const GPUTextureDesc desc = {
        .kind = GPU_TEXTURE_2D, .format = GPU_FORMAT_RGBA8, .width = vw, .height = vh, .filter = GPU_FILTER_LINEAR, .wrap = GPU_WRAP_CLAMP_TO_EDGE};
    gpu_texture_t src_texture = create_texture_or_die(&desc, NULL);

    // Copy the current framebuffer to the texture
    gpu_copy_to_texture(src_texture, 0, 0, vw, vh);

    // Create a temporary framebuffer for GPU-based scaling
    gpu_texture_t temp_texture = 0;
    gpu_render_target_t temp_framebuffer = 0;
    setup_texture_as_render_target(*thumb_w, *thumb_h, &temp_texture, &temp_framebuffer);

    // Save current state
    gpu_render_target_t current_framebuffer = gpu_get_render_target();

    // Bind our temporary framebuffer for rendering
    bind_framebuffer_for_output(temp_framebuffer);
    save_viewport(0, 0, *thumb_w, *thumb_h);

    // Use the screenshot program to render the scaled framebuffer with proper color space handling
    bind_program(SCREENSHOT_PROGRAM);

    // Set source rectangle (normalized texture coordinates: 0 to 1, origin at top-left, like Region)
    float src_left_norm = (float)region.left / (float)vw;
    float src_right_norm = (float)region.right / (float)vw;
    float src_bottom_norm = (float)region.bottom / (float)vh;
    float src_top_norm = (float)region.top / (float)vh;
    param_4f(program_param(SCREENSHOT_PROGRAM, "src_rect"), src_left_norm, src_top_norm, src_right_norm, src_bottom_norm);

    // Set destination rectangle (NDC coordinates: -1 to 1)
    param_4f(program_param(SCREENSHOT_PROGRAM, "dest_rect"), -1.0f, -1.0f, 1.0f, 1.0f);

    // Set the source texture size for proper downscaling
    param_2f(program_param(SCREENSHOT_PROGRAM, "src_size"), (float)vw, (float)vh);

    // Bind the source texture
    gpu_bind_texture(program_texture_slot(SCREENSHOT_PROGRAM, "image"), src_texture);

    // Draw the scaled quad
    draw_quad(false, 0);

    // Read the scaled result
    gpu_read_pixels(0, 0, *thumb_w, *thumb_h, dst_buf);

    // Restore previous state
    gpu_set_render_target(current_framebuffer);
    restore_viewport();

    // Clean up temporary resources
    free_texture(&src_texture);
    free_texture(&temp_texture);
    free_framebuffer(&temp_framebuffer);
}
// }}}

// Python API {{{

static PyObject *
pygpu_driver_version_string(PyObject *self UNUSED, PyObject *args UNUSED) {
    return PyUnicode_FromString(gpu_version_string());
}

static PyObject *
pygpu_driver_name(PyObject *self UNUSED, PyObject *args UNUSED) {
    return PyUnicode_FromString(gpu_driver_name());
}

static PyObject *
pygpu_shader_target(PyObject *self UNUSED, PyObject *args UNUSED) {
    return PyUnicode_FromString(gpu_shader_target());
}

static PyObject *
pyload_gpu_driver(PyObject *self UNUSED, PyObject *args) {
    const char *path;
    int debug_rendering = 0;
    if (!PyArg_ParseTuple(args, "s|p", &path, &debug_rendering)) return NULL;
    const char *err = load_gpu_driver(path, debug_rendering != 0, GPU_RENDERER_ANY);
    if (err) {
        PyErr_SetString(PyExc_OSError, err);
        return NULL;
    }
    Py_RETURN_NONE;
}

static void
free_custom_shader_pipeline(CustomShaderPipeline *p) {
    for (size_t i = 0; i < p->num_groups; i++) {
        if (p->groups[i].animation_curve_is_shared) p->groups[i].animation_curve = NULL;
        else p->groups[i].animation_curve = free_animation(p->groups[i].animation_curve);
    }
}

static NamedTexture
named_texture_from_str(const char *s) {
    if (strcmp(s, "a") == 0) return CUSTOM_SHADER_TEXTURE_A;
    if (strcmp(s, "b") == 0) return CUSTOM_SHADER_TEXTURE_B;
    if (strcmp(s, "persist") == 0) return CUSTOM_SHADER_TEXTURE_PERSIST;
    return CUSTOM_SHADER_TEXTURE_DEFAULT;
}

static ShaderAnimEventMask
shader_anim_event_bit(const char *s, CustomShaderPipeline *p) {
    if (strcmp(s, "pointer-left-button-press") == 0) return 1u << SHADER_ANIM_EVENT_POINTER_LEFT_BUTTON_PRESS;
    if (strcmp(s, "os-window-focus-in") == 0) return 1u << SHADER_ANIM_EVENT_OS_WINDOW_FOCUS_IN;
    if (strcmp(s, "os-window-focus-out") == 0) return 1u << SHADER_ANIM_EVENT_OS_WINDOW_FOCUS_OUT;
    if (strcmp(s, "window-focus-in") == 0) return 1u << SHADER_ANIM_EVENT_WINDOW_FOCUS_IN;
    if (strcmp(s, "window-focus-out") == 0) return 1u << SHADER_ANIM_EVENT_WINDOW_FOCUS_OUT;
    if (strcmp(s, "tab-change") == 0) return 1u << SHADER_ANIM_EVENT_TAB_CHANGE;
    if (strcmp(s, "bell-in-window") == 0) return 1u << SHADER_ANIM_EVENT_BELL_IN_WINDOW;
    if (strcmp(s, "user-activity") == 0) return 1u << SHADER_ANIM_EVENT_USER_ACTIVITY;
    if (strcmp(s, "user-idle") == 0) return 1u << SHADER_ANIM_EVENT_USER_IDLE;
    if (strcmp(s, "cursor-trail-move") == 0) return 1u << SHADER_ANIM_EVENT_CURSOR_TRAIL_MOVE;
    if (strcmp(s, "cursor-trail-stop") == 0) return 1u << SHADER_ANIM_EVENT_CURSOR_TRAIL_STOP;
    if (strcmp(s, "command-start") == 0) return 1u << SHADER_ANIM_EVENT_COMMAND_START;
    if (strcmp(s, "command-finish") == 0) return 1u << SHADER_ANIM_EVENT_COMMAND_FINISH;
    if (strcmp(s, "alternate-screen-enter") == 0) return 1u << SHADER_ANIM_EVENT_ALTERNATE_SCREEN_ENTER;
    if (strcmp(s, "alternate-screen-exit") == 0) return 1u << SHADER_ANIM_EVENT_ALTERNATE_SCREEN_EXIT;
    static const char user_prefix[] = "user:";
    if (strncmp(s, user_prefix, sizeof(user_prefix) - 1) == 0) {
        const char *name = s + sizeof(user_prefix) - 1;
        if (!name[0] || strlen(name) > MAX_SHADER_ANIM_USER_EVENT_NAME_LEN) return 0;
        size_t i = 0;
        while (i < p->num_user_events && strcmp(p->user_events[i], name) != 0) i++;
        if (i == p->num_user_events) {
            if (i >= MAX_SHADER_ANIM_USER_EVENTS) return 0;
            memcpy(p->user_events[p->num_user_events++], name, strlen(name) + 1);
        }
        return 1ull << (SHADER_ANIM_FIRST_USER_EVENT + i);
    }
    return 0;
}

static ShaderAnimEventMask
parse_anim_event_sequence(PyObject *seq, CustomShaderPipeline *p) {
    ShaderAnimEventMask mask = 0;
    for (Py_ssize_t i = 0; i < PySequence_Fast_GET_SIZE(seq); i++) {
        PyObject *item = PySequence_Fast_GET_ITEM(seq, i);
        if (PyUnicode_Check(item)) mask |= shader_anim_event_bit(PyUnicode_AsUTF8(item), p);
    }
    return mask;
}

static bool
transfer_pipeline_to_struct(PyObject *pg, CustomShaderPipeline *p) {
#define is_seq(x) (x && (PyList_Check(x) || PyTuple_Check(x)))
    PyObject *textures = PyDict_GetItemString(pg, "textures");
    if (is_seq(textures)) {
        for (Py_ssize_t i = 0; i < PySequence_Fast_GET_SIZE(textures); i++) {
            PyObject *t = PySequence_Fast_GET_ITEM(textures, i);
            if (!PyUnicode_Check(t)) {
                PyErr_SetString(PyExc_TypeError, "pipeline textures must be strings");
                return false;
            }
            p->textures |= (1u << named_texture_from_str(PyUnicode_AsUTF8(t)));
        }
    }
    PyObject *groups = PyDict_GetItemString(pg, "groups");
    if (!is_seq(groups)) {
        PyErr_SetString(PyExc_TypeError, "pipeline groups must be a sequence");
        return false;
    }
    Py_ssize_t num_groups = PySequence_Fast_GET_SIZE(groups);
    if ((size_t)num_groups > arraysz(p->groups)) {
        PyErr_SetString(PyExc_ValueError, "too many pipeline groups");
        return false;
    }
    p->num_groups = (size_t)num_groups;
    for (Py_ssize_t i = 0; i < num_groups; i++) {
        PyObject *g = PySequence_Fast_GET_ITEM(groups, i);
        if (!PyDict_Check(g)) {
            PyErr_SetString(PyExc_TypeError, "pipeline group must be a dict");
            return false;
        }
        CustomShaderGroup *cg = &p->groups[i];
        PyObject *vp = PyDict_GetItemString(g, "viewport_pos");
        if (is_seq(vp) && PySequence_Fast_GET_SIZE(vp) == 2) {
            cg->viewport_pos.x = (float)PyFloat_AsDouble(PySequence_Fast_GET_ITEM(vp, 0));
            cg->viewport_pos.y = (float)PyFloat_AsDouble(PySequence_Fast_GET_ITEM(vp, 1));
        }
        PyObject *vs = PyDict_GetItemString(g, "viewport_size");
        if (is_seq(vs) && PySequence_Fast_GET_SIZE(vs) == 2) {
            cg->viewport_size.w = (float)PyFloat_AsDouble(PySequence_Fast_GET_ITEM(vs, 0));
            cg->viewport_size.h = (float)PyFloat_AsDouble(PySequence_Fast_GET_ITEM(vs, 1));
        }
        PyObject *ot = PyDict_GetItemString(g, "output_texture");
        if (ot && PyUnicode_Check(ot)) { cg->output_texture = named_texture_from_str(PyUnicode_AsUTF8(ot)); }

        PyObject *astart = PyDict_GetItemString(g, "animation_start");
        if (is_seq(astart)) cg->animation_start_events = parse_anim_event_sequence(astart, p);
        PyObject *atoggle = PyDict_GetItemString(g, "animation_toggle");
        if (is_seq(atoggle)) cg->animation_toggle_events = parse_anim_event_sequence(atoggle, p);

        PyObject *acurve = PyDict_GetItemString(g, "animation_curve");
        if (acurve && PyObject_IsTrue(acurve)) {
            if ((cg->animation_curve = alloc_animation()) != NULL) add_easing_function(cg->animation_curve, acurve, 0.0, 1.0);
            for (Py_ssize_t j = 0; j < i; j++) {
                if (animations_equal(p->groups[j].animation_curve, cg->animation_curve)) {
                    free_animation(cg->animation_curve);
                    cg->animation_curve = p->groups[j].animation_curve;
                    cg->animation_curve_is_shared = true;
                    break;
                }
            }
        }

        PyObject *astep = PyDict_GetItemString(g, "animation_step");
        cg->animation_step = (astep && PyLong_Check(astep)) ? (monotonic_t)PyLong_AsLong(astep) : ANIMATION_SAMPLE_WAIT;
        cg->animation_step = cg->animation_step == 0 ? MONOTONIC_T_MAX : MAX(cg->animation_step, OPT(repaint_delay));

        PyObject *ae_events = PyDict_GetItemString(g, "animation_end_events");
        if (is_seq(ae_events)) cg->animation_end_events = parse_anim_event_sequence(ae_events, p);

        PyObject *ae_dur = PyDict_GetItemString(g, "animation_end_duration");
        if (ae_dur && PyLong_Check(ae_dur)) cg->animation_end_duration = (monotonic_t)PyLong_AsLong(ae_dur);

        PyObject *a_dur = PyDict_GetItemString(g, "animation_duration");
        cg->animation_duration = (a_dur && PyLong_Check(a_dur)) ? (monotonic_t)PyLong_AsLong(a_dur) : -1;
        PyObject *a_rev = PyDict_GetItemString(g, "animation_reverse");
        cg->animation_reverse = (a_rev && PyLong_Check(a_rev)) ? (monotonic_t)PyLong_AsLong(a_rev) : 0;
        PyObject *a_loops = PyDict_GetItemString(g, "animation_loops");
        cg->animation_loops = (a_loops && PyLong_Check(a_loops)) ? (unsigned)PyLong_AsUnsignedLong(a_loops) : 1;

        PyObject *attached = PyDict_GetItemString(g, "attached");
        cg->attached = attached && PyObject_IsTrue(attached);
    }
    p->all_animation_start_events = 0;
    for (size_t i = 0; i < p->num_groups; i++) p->all_animation_start_events |= p->groups[i].animation_start_events | p->groups[i].animation_toggle_events;
    p->bypass_builtin_trail = (p->all_animation_start_events & (1u << SHADER_ANIM_EVENT_CURSOR_TRAIL_MOVE)) != 0;
#undef is_seq
    return true;
}

// Concatenate the tuple of source strings into a single string, the returned
// object owns the memory the string points to
// Join shader sources, which are either all text (str) or all binary (bytes),
// such as SPIR-V, into a single bytes object
static PyObject *
join_shader_sources(PyObject *sources) {
    bool all_bytes = true, all_text = true;
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(sources); i++) {
        PyObject *x = PyTuple_GET_ITEM(sources, i);
        all_bytes = all_bytes && PyBytes_Check(x);
        all_text = all_text && PyUnicode_Check(x);
    }
    if (!all_bytes && !all_text) {
        PyErr_SetString(PyExc_TypeError, "shaders must be all str or all bytes");
        return NULL;
    }
    if (all_bytes) {
        Py_ssize_t total = 0;
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(sources); i++) total += PyBytes_GET_SIZE(PyTuple_GET_ITEM(sources, i));
        PyObject *ans = PyBytes_FromStringAndSize(NULL, total);
        if (!ans) return NULL;
        char *dest = PyBytes_AS_STRING(ans);
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(sources); i++) {
            PyObject *x = PyTuple_GET_ITEM(sources, i);
            memcpy(dest, PyBytes_AS_STRING(x), PyBytes_GET_SIZE(x));
            dest += PyBytes_GET_SIZE(x);
        }
        return ans;
    }
    RAII_PyObject(empty, PyUnicode_FromString(""));
    if (!empty) return NULL;
    RAII_PyObject(text, PyUnicode_Join(empty, sources));
    return text ? PyUnicode_AsUTF8String(text) : NULL;
}

static PyObject *
compile_program(PyObject UNUSED *self, PyObject *args) {
    PyObject *vertex_shaders, *fragment_shaders, *metadata;
    int which, allow_recompile = 0;
    if (!PyArg_ParseTuple(
            args, "iO!O!O!|p", &which, &PyTuple_Type, &vertex_shaders, &PyTuple_Type, &fragment_shaders, &PyDict_Type, &metadata, &allow_recompile))
        return NULL;
    if (which == -1) {
        init_cell_program();
        Py_RETURN_NONE;
    }
    if (which == -2) {
        init_custom_programs();
        Py_RETURN_NONE;
    }
    if (which < 0 || which >= NUM_PROGRAMS) {
        PyErr_Format(PyExc_ValueError, "Unknown program: %d", which);
        return NULL;
    }
    if (!PyTuple_GET_SIZE(vertex_shaders)) {
        if (which == CUSTOM_END_PROGRAM) {
            free_custom_shader_pipeline(&custom_shaders.end);
            zero_at_ptr(&custom_shaders.end);
            custom_shaders.generation++;
        }
        free_program(which);
        Py_RETURN_NONE;
    }
    if (program_pipeline(which) && !allow_recompile) {
        PyErr_SetString(PyExc_ValueError, "program already compiled");
        return NULL;
    }
    RAII_PyObject(vertex_source, join_shader_sources(vertex_shaders));
    if (!vertex_source) return NULL;
    RAII_PyObject(fragment_source, join_shader_sources(fragment_shaders));
    if (!fragment_source) return NULL;
    Py_ssize_t vsz, fsz;
    char *vcode, *fcode;
    if (PyBytes_AsStringAndSize(vertex_source, &vcode, &vsz) != 0 || PyBytes_AsStringAndSize(fragment_source, &fcode, &fsz) != 0) return NULL;
    if (!compile_gpu_program(which, vcode, (size_t)vsz, fcode, (size_t)fsz, metadata)) return NULL;
    if (which == CUSTOM_END_PROGRAM) {
        free_custom_shader_pipeline(&custom_shaders.end);
        zero_at_ptr(&custom_shaders.end);
        PyObject *pg = PyDict_GetItemString(metadata, "pipeline");
        if (pg && !transfer_pipeline_to_struct(pg, &custom_shaders.end)) {
            free_program(which);
            return NULL;
        }
        custom_shaders.end.active = true;
        PyObject *has_pointer_map = PyDict_GetItemString(metadata, "has_pointer_map");
        custom_shaders.end.has_pointer_map = has_pointer_map && PyObject_IsTrue(has_pointer_map) == 1;
        PyObject *pointer_map_groups = PyDict_GetItemString(metadata, "pointer_map_groups");
        if (pointer_map_groups && (PyList_Check(pointer_map_groups) || PyTuple_Check(pointer_map_groups))) {
            for (Py_ssize_t i = 0; i < PySequence_Fast_GET_SIZE(pointer_map_groups); i++) {
                long g = PyLong_AsLong(PySequence_Fast_GET_ITEM(pointer_map_groups, i));
                if (g >= 0 && (size_t)g < custom_shaders.end.num_groups) custom_shaders.end.pointer_map_groups |= 1u << g;
            }
            if (PyErr_Occurred()) {
                free_program(which);
                return NULL;
            }
        }
        custom_shaders.generation++;
    }
    Py_RETURN_NONE;
}

static PyObject *
sprite_map_set_limits(PyObject UNUSED *self, PyObject *args) {
    unsigned int w, h;
    if (!PyArg_ParseTuple(args, "II", &w, &h)) return NULL;
    sprite_tracker_set_limits(w, h);
    max_texture_size = w;
    max_array_texture_layers = h;
    Py_RETURN_NONE;
}

// test only wrapper for decorations_map_new_size
static PyObject *
pydecorations_map_new_size(PyObject *self UNUSED, PyObject *args) {
    unsigned long count, current_capacity, max_size;
    if (!PyArg_ParseTuple(args, "kkk", &count, &current_capacity, &max_size)) return NULL;
    int32_t w, h;
    if (!decorations_map_new_size(count, current_capacity, max_size, &w, &h)) Py_RETURN_NONE;
    return Py_BuildValue("ii", (int)w, (int)h);
}

// Test only. Wraps custom_shader_needs_render() so the redraw decision can be
// exercised from the Python test suite without a GPU context. Each state is a
// (has_active_shaders, min_step, next_end_at) tuple.
static bool
parse_shader_anim_state(PyObject *obj, ShaderAnimState *ans) {
    int has_active;
    long long min_step, next_end_at;
    if (!PyArg_ParseTuple(obj, "pLL", &has_active, &min_step, &next_end_at)) return false;
    *ans = (ShaderAnimState){.has_active_shaders = has_active, .min_step = min_step, .next_end_at = next_end_at};
    return true;
}

static PyObject *
pycustom_shader_needs_render(PyObject *self UNUSED, PyObject *args) {
    PyObject *b, *a;
    unsigned long long event_mask;
    long long now;
    ShaderAnimState before, after;
    if (!PyArg_ParseTuple(args, "O!O!KL", &PyTuple_Type, &b, &PyTuple_Type, &a, &event_mask, &now)) return NULL;
    if (!parse_shader_anim_state(b, &before) || !parse_shader_anim_state(a, &after)) return NULL;
    if (custom_shader_needs_render(&before, &after, event_mask, now)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

// Test only. Runs the renderer's per-frame custom shader bookkeeping (the same
// sequence as prepare_to_render_os_window) against a freshly allocated, zero
// initialized OSWindow and returns whether each tick asked for a redraw. Used
// to assert that an idle OS window with no shader work pending stays idle.
static PyObject *
pysimulate_custom_shader_render_ticks(PyObject *self UNUSED, PyObject *args) {
    unsigned long num_ticks;
    unsigned long long event_mask = 0;
    int initialize = 0;
    if (!PyArg_ParseTuple(args, "k|Kp", &num_ticks, &event_mask, &initialize)) return NULL;
    RAII_ALLOC(OSWindow, osw, calloc(1, sizeof(OSWindow)));
    if (!osw) return PyErr_NoMemory();
    if (initialize) init_shader_animation_state(osw);
    RAII_PyObject(ans, PyList_New(0));
    if (!ans) return NULL;
    monotonic_t now = monotonic();
    for (unsigned long i = 0; i < num_ticks; i++, now += ms_to_monotonic_t(10ll)) {
        const ShaderAnimState before = osw->shader_anim;
        update_custom_shader_animations(event_mask, now, osw);
        PyObject *v = custom_shader_needs_render(&before, &osw->shader_anim, event_mask, now) ? Py_True : Py_False;
        if (PyList_Append(ans, v) != 0) return NULL;
    }
    return Py_NewRef(ans);
}

static PyObject *
pyfire_custom_shader_event(PyObject *self UNUSED, PyObject *args) {
    const char *name;
    unsigned long long os_window_id = 0;
    if (!PyArg_ParseTuple(args, "s|K", &name, &os_window_id)) return NULL;
    if (fire_custom_shader_user_event(name, os_window_id)) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

// Test only. Loads pipeline, a dict as sent by compile_program(), in place of
// the current one and runs the animation state machine over an OS window, one
// tick per item of ticks, each a sequence of event names, 10ms apart. Returns
// the active state of every group after each tick, or if with_progress is
// true, the animation_progress of active groups and None for inactive ones.
static PyObject *
pysimulate_custom_shader_animation(PyObject *self UNUSED, PyObject *args) {
    PyObject *pipeline, *ticks;
    int with_progress = 0;
    if (!PyArg_ParseTuple(args, "O!O!|p", &PyDict_Type, &pipeline, &PyList_Type, &ticks, &with_progress)) return NULL;
    RAII_ALLOC(OSWindow, osw, calloc(1, sizeof(OSWindow)));
    if (!osw) return PyErr_NoMemory();
    const CustomShaderPipeline saved = custom_shaders.end;
    const size_t saved_count = custom_shaders.count;
    zero_at_ptr(&custom_shaders.end);
    PyObject *ans = NULL;
    if (transfer_pipeline_to_struct(pipeline, &custom_shaders.end)) {
        custom_shaders.count = 1;
        init_shader_animation_state(osw);
        ans = PyList_New(0);
        monotonic_t now = monotonic();
        for (Py_ssize_t i = 0; ans && i < PyList_GET_SIZE(ticks); i++, now += ms_to_monotonic_t(10ll)) {
            PyObject *names = PyList_GET_ITEM(ticks, i);
            if (!PyTuple_Check(names) && !PyList_Check(names)) {
                PyErr_SetString(PyExc_TypeError, "each tick must be a sequence of event names");
                Py_CLEAR(ans);
                break;
            }
            update_custom_shader_animations(parse_anim_event_sequence(names, &custom_shaders.end), now, osw);
            RAII_PyObject(states, PyTuple_New(custom_shaders.end.num_groups));
            if (!states) {
                Py_CLEAR(ans);
                break;
            }
            float progress[MAX_CUSTOM_SHADER_GROUPS];
            custom_shader_group_progress(osw, now, progress);
            for (size_t g = 0; g < custom_shaders.end.num_groups; g++) {
                const CustomShaderGroup *cg = custom_shaders.end.groups + g;
                const bool active = !group_is_animated(cg) || osw->shader_group_anim[g].active;
                PyObject *state =
                    with_progress && active ? PyFloat_FromDouble(progress[g]) : Py_NewRef(with_progress ? Py_None : (active ? Py_True : Py_False));
                if (!state) break;
                PyTuple_SET_ITEM(states, g, state);
            }
            if (PyErr_Occurred()) {
                Py_CLEAR(ans);
                break;
            }
            if (PyList_Append(ans, states) != 0) Py_CLEAR(ans);
        }
    }
    free_custom_shader_pipeline(&custom_shaders.end);
    custom_shaders.end = saved;
    custom_shaders.count = saved_count;
    return ans;
}

// Test only. Looks up a position in a pointer map given as the bytes of
// POINTER_MAP_SIZE x POINTER_MAP_SIZE (x, y) float pairs.
static PyObject *
pysample_pointer_map(PyObject *self UNUSED, PyObject *args) {
    Py_buffer data;
    double u, v;
    if (!PyArg_ParseTuple(args, "y*dd", &data, &u, &v)) return NULL;
    if ((size_t)data.len != sizeof(float) * 2 * POINTER_MAP_SIZE * POINTER_MAP_SIZE) {
        PyBuffer_Release(&data);
        PyErr_SetString(PyExc_ValueError, "pointer map has the wrong size");
        return NULL;
    }
    sample_pointer_map(data.buf, &u, &v);
    PyBuffer_Release(&data);
    return Py_BuildValue("dd", u, v);
}

#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, NULL}
#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}
static PyMethodDef module_methods[] = {
    M(compile_program, METH_VARARGS),
    M(sprite_map_set_limits, METH_VARARGS),
    MW(gpu_driver_version_string, METH_NOARGS),
    MW(gpu_driver_name, METH_NOARGS),
    MW(gpu_shader_target, METH_NOARGS),
    MW(load_gpu_driver, METH_VARARGS),
    MW(custom_shader_needs_render, METH_VARARGS),
    MW(decorations_map_new_size, METH_VARARGS),
    MW(simulate_custom_shader_render_ticks, METH_VARARGS),
    MW(sample_pointer_map, METH_VARARGS),
    MW(fire_custom_shader_event, METH_VARARGS),
    MW(simulate_custom_shader_animation, METH_VARARGS),

    {NULL, NULL, 0, NULL} /* Sentinel */
};

bool
initialize_gpu(void) {
    if (initialize_gpu_driver()) return false;
    GPUCapabilities caps = {0};
    gpu_get_capabilities(&caps);
    global_state.supports_framebuffer_srgb = caps.supports_srgb_output;
    global_state.software_rendering = caps.is_software;
    if (caps.is_software) log_error("Using software rendering with the %s GPU driver, kitty will be slow", gpu_driver_name());
    selection_stride = MAX((size_t)1u, (size_t)caps.vertex_input_alignment);
    query_gpu_texture_limits();
    return true;
}

void
free_vao(ssize_t vao_idx) {
    remove_vao(vao_idx);
}

void
cleanup_shader_resources_on_terminate(void) {
    free_pointer_map_target();
    if (shader_globals_vao_idx != -1) {
        remove_vao(shader_globals_vao_idx);
        shader_globals_vao_idx = -1;
    }
}

static void
finalize(void) {
    default_visual_bell_animation = free_animation(default_visual_bell_animation);
    free_custom_shader_pipeline(&custom_shaders.end);
    free_program_layouts();
    unload_gpu_driver();
}

bool
init_shaders(PyObject *module) {
#define C(x)                                           \
    if (PyModule_AddIntConstant(module, #x, x) != 0) { \
        PyErr_NoMemory();                              \
        return false;                                  \
    }
    C(CELL_PROGRAM);
    C(CELL_FG_PROGRAM);
    C(CELL_BG_PROGRAM);
    C(BORDERS_PROGRAM);
    C(GRAPHICS_PROGRAM);
    C(GRAPHICS_PREMULT_PROGRAM);
    C(GRAPHICS_ALPHA_MASK_PROGRAM);
    C(GRAPHICS_INDEXED_PROGRAM);
    C(GRAPHICS_INDEXED_UNSCALED_PROGRAM);
    C(BGIMAGE_PROGRAM);
    C(TINT_PROGRAM);
    C(TRAIL_PROGRAM);
    C(BLIT_PROGRAM);
    C(SCREENSHOT_PROGRAM);
    C(ROUNDED_RECT_PROGRAM);
    C(PADDING_PROGRAM);
    C(CUSTOM_END_PROGRAM);
    C(MAX_CUSTOM_SHADER_GROUPS);
    C(MAX_SHADER_ANIM_USER_EVENTS);
    C(MAX_SHADER_ANIM_USER_EVENT_NAME_LEN);
    C(POINTER_MAP_SIZE);
    C(ANIMATION_SAMPLE_WAIT);

#undef C
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    register_at_exit_cleanup_func(SHADERS_CLEANUP_FUNC, finalize);
    return true;
}
// }}}
