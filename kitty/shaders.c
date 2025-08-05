/*
 * shaders.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"
#include "gl.h"
#include "cleanup.h"
#include "colors.h"
#include <stddef.h>
#include "window_logo.h"
#include "srgb_gamma.h"
#include "uniforms_generated.h"
#include "png-reader.h"

/*
 * TODO: for shader refactoring
 * Port graphics rendering to start use a dummy 1 pixel empty texture then possibly replace with defines so that the most
 * common use case of no graphics has zero performance overhead.
 * Convert all images loaded to GPU to linear space for correct blending or alternately do conversion to linear space in
 * the new graphics shader.
 * background image with tint and various layout options in both cell and borders shaders
 * test graphics in all 3 layers
 * window logo image that is in the under foreground layer I think? need to check
 * test that window numbering and URL hover rendering both still work
 * test cursor trail rendering
 * remove startx, starty, dx, dy from WindowRenderData
 * fix rendering during live resize check the window size label and stretching of window content
 */
#define BLEND_ONTO_OPAQUE  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);  // blending onto opaque colors
#define BLEND_ONTO_OPAQUE_WITH_OPAQUE_OUTPUT  glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ZERO, GL_ONE);  // blending onto opaque colors with final color having alpha 1
#define BLEND_PREMULT glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);  // blending of pre-multiplied colors

enum {
    CELL_PROGRAM, CELL_TRANSPARENT_PROGRAM, CELL_LAYERS_PROGRAM, CELL_LAYERS_TRANSPARENT_PROGRAM, CELL_PROGRAM_SENTINEL,
    BORDERS_PROGRAM,
    GRAPHICS_PROGRAM, GRAPHICS_ALPHA_MASK_PROGRAM,
    BGIMAGE_PROGRAM,
    TINT_PROGRAM,
    TRAIL_PROGRAM,
    NUM_PROGRAMS
};
enum { SPRITE_MAP_UNIT, GRAPHICS_UNIT, BGIMAGE_UNIT, SPRITE_DECORATIONS_MAP_UNIT, UNDER_BG_LAYER_UNIT, UNDER_FG_LAYER_UNIT, OVER_FG_LAYER_UNIT, UI_LAYER_UNIT };

typedef struct UIRenderData {
    unsigned screen_width, screen_height, cell_width, cell_height, screen_left, screen_top, full_framebuffer_width, full_framebuffer_height;
    Window *window; Screen *screen; OSWindow *os_window;
    GraphicsRenderData grd;
    WindowLogoRenderData *window_logo;
    float inactive_text_alpha;
    bool has_under_bg, has_under_fg, has_over_fg, has_ui;
} UIRenderData;

// Sprites {{{
typedef struct {
    int xnum, ynum, x, y, z, last_num_of_layers, last_ynum;
    GLuint texture_id;
    GLint max_texture_size, max_array_texture_layers;
    struct decorations_map {
        GLuint texture_id;
        unsigned width, height;
        size_t count;
    } decorations_map;
} SpriteMap;

static const SpriteMap NEW_SPRITE_MAP = { .xnum = 1, .ynum = 1, .last_num_of_layers = 1, .last_ynum = -1 };
static GLint max_texture_size = 0, max_array_texture_layers = 0;

static GLfloat
srgb_color(uint8_t color) {
    return srgb_lut[color];
}

static void
color_vec3(GLint location, color_type color) {
    glUniform3f(location, srgb_lut[(color >> 16) & 0xFF], srgb_lut[(color >> 8) & 0xFF], srgb_lut[color & 0xFF]);
}

static void
color_vec4_premult(GLint location, color_type color, GLfloat alpha) {
    glUniform4f(location, srgb_lut[(color >> 16) & 0xFF]*alpha, srgb_lut[(color >> 8) & 0xFF]*alpha, srgb_lut[color & 0xFF]*alpha, alpha);
}


SPRITE_MAP_HANDLE
alloc_sprite_map(void) {
    if (!max_texture_size) {
        glGetIntegerv(GL_MAX_TEXTURE_SIZE, &(max_texture_size));
        glGetIntegerv(GL_MAX_ARRAY_TEXTURE_LAYERS, &(max_array_texture_layers));
#ifdef __APPLE__
        // Since on Apple we could have multiple GPUs, with different capabilities,
        // upper bound the values according to the data from https://developer.apple.com/graphicsimaging/opengl/capabilities/
        max_texture_size = MIN(8192, max_texture_size);
        max_array_texture_layers = MIN(512, max_array_texture_layers);
#endif
        sprite_tracker_set_limits(max_texture_size, max_array_texture_layers);
    }
    SpriteMap *ans = calloc(1, sizeof(SpriteMap));
    if (!ans) fatal("Out of memory allocating a sprite map");
    *ans = NEW_SPRITE_MAP;
    ans->max_texture_size = max_texture_size;
    ans->max_array_texture_layers = max_array_texture_layers;
    return (SPRITE_MAP_HANDLE)ans;
}

void
free_sprite_data(FONTS_DATA_HANDLE fg) {
    SpriteMap *sprite_map = (SpriteMap*)fg->sprite_map;
    if (sprite_map) {
        if (sprite_map->texture_id) free_texture(&sprite_map->texture_id);
        if (sprite_map->decorations_map.texture_id) free_texture(&sprite_map->texture_id);
        free(sprite_map);
        fg->sprite_map = NULL;
    }
}


static void
copy_32bit_texture(GLuint old_texture, GLuint new_texture, GLenum texture_type) {
    // requires new texture to be at least as big as old texture. Assumes textures are 32bits per pixel
    GLint width, height, layers;
    glBindTexture(texture_type, old_texture);
    glGetTexLevelParameteriv(texture_type, 0, GL_TEXTURE_WIDTH, &width);
    glGetTexLevelParameteriv(texture_type, 0, GL_TEXTURE_HEIGHT, &height);
    glGetTexLevelParameteriv(texture_type, 0, GL_TEXTURE_DEPTH, &layers);
    if (GLAD_GL_ARB_copy_image) { glCopyImageSubData(old_texture, texture_type, 0, 0, 0, 0, new_texture, texture_type, 0, 0, 0, 0, width, height, layers); return; }

    static bool copy_image_warned = false;
    // ARB_copy_image not available, do a slow roundtrip copy
    if (!copy_image_warned) {
        copy_image_warned = true;
        log_error("WARNING: Your system's OpenGL implementation does not have glCopyImageSubData, falling back to a slower implementation");
    }

    GLint internal_format;
    glGetTexLevelParameteriv(texture_type, 0, GL_TEXTURE_INTERNAL_FORMAT, &internal_format);
    GLenum format, type;
    switch(internal_format) {
        case GL_R8UI: case GL_R8I: case GL_R16UI: case GL_R16I: case GL_R32UI: case GL_R32I: case GL_RG8UI: case GL_RG8I:
        case GL_RG16UI: case GL_RG16I: case GL_RG32UI: case GL_RG32I: case GL_RGB8UI: case GL_RGB8I: case GL_RGB16UI:
        case GL_RGB16I: case GL_RGB32UI: case GL_RGB32I: case GL_RGBA8UI: case GL_RGBA8I: case GL_RGBA16UI: case GL_RGBA16I:
        case GL_RGBA32UI: case GL_RGBA32I:
            format = GL_RED_INTEGER;
            type = GL_UNSIGNED_INT;
            break;
        default:
            format = GL_RGBA;
            type = GL_UNSIGNED_INT_8_8_8_8;
            break;
    }
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    RAII_ALLOC(uint8_t, pixels, malloc((size_t)width * height * layers * 4u));
    if (!pixels) fatal("Out of memory");
    glGetTexImage(texture_type, 0, format, type, pixels);
    glBindTexture(texture_type, new_texture);
    glPixelStorei(GL_PACK_ALIGNMENT, 4);
    if (texture_type == GL_TEXTURE_2D_ARRAY) glTexSubImage3D(GL_TEXTURE_2D_ARRAY, 0, 0, 0, 0, width, height, layers, format, type, pixels);
    else glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, width, height, format, type, pixels);
}

static GLuint
setup_new_sprites_texture(GLenum texture_type) {
    GLuint tex;
    glGenTextures(1, &tex);
    glBindTexture(texture_type, tex);
    // We use GL_NEAREST otherwise glyphs that touch the edge of the cell
    // often show a border between cells
    glTexParameteri(texture_type, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(texture_type, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(texture_type, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(texture_type, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    return tex;
}

static void
realloc_sprite_decorations_texture_if_needed(FONTS_DATA_HANDLE fg) {
#define dm (sm->decorations_map)
    SpriteMap *sm = (SpriteMap*)fg->sprite_map;
    size_t current_capacity = (size_t)dm.width * dm.height;
    if (dm.count < current_capacity && dm.texture_id) return;
    GLint new_capacity = dm.count + 256;
    GLint width = new_capacity, height = 1;
    if (new_capacity > sm->max_texture_size) {
        width = sm->max_texture_size;
        height = 1 + new_capacity / width;
    }
    if (height > sm->max_texture_size) fatal("Max texture size too small for sprite decorations map, maybe switch to using a GL_TEXTURE_2D_ARRAY");
    const GLenum texture_type = GL_TEXTURE_2D;
    GLuint tex = setup_new_sprites_texture(texture_type);
    glTexImage2D(texture_type, 0, GL_R32UI, width, height, 0, GL_RED_INTEGER, GL_UNSIGNED_INT, NULL);
    if (dm.texture_id) {  // copy data from old texture
        copy_32bit_texture(dm.texture_id, tex, texture_type);
        glDeleteTextures(1, &dm.texture_id);
    }
    glBindTexture(texture_type, 0);
    dm.texture_id = tex; dm.width = width; dm.height = height;
#undef dm
}

static void
realloc_sprite_texture(FONTS_DATA_HANDLE fg) {
    unsigned int xnum, ynum, z, znum, width, height;
    sprite_tracker_current_layout(fg, &xnum, &ynum, &z);
    znum = z + 1;
    SpriteMap *sprite_map = (SpriteMap*)fg->sprite_map;
    width = xnum * fg->fcm.cell_width; height = ynum * (fg->fcm.cell_height + 1);
    const GLenum texture_type = GL_TEXTURE_2D_ARRAY;
    GLuint tex = setup_new_sprites_texture(texture_type);
    glTexStorage3D(texture_type, 1, GL_SRGB8_ALPHA8, width, height, znum);
    if (sprite_map->texture_id) { // copy old texture data into new texture
        copy_32bit_texture(sprite_map->texture_id, tex, texture_type);
        glDeleteTextures(1, &sprite_map->texture_id);
    }
    glBindTexture(texture_type, 0);
    sprite_map->last_num_of_layers = znum;
    sprite_map->last_ynum = ynum;
    sprite_map->texture_id = tex;
}

static void
ensure_sprite_map(FONTS_DATA_HANDLE fg) {
    SpriteMap *sprite_map = (SpriteMap*)fg->sprite_map;
    if (!sprite_map->texture_id) realloc_sprite_texture(fg);
    if (!sprite_map->decorations_map.texture_id) realloc_sprite_decorations_texture_if_needed(fg);
    // We have to rebind since we don't know if the texture was ever bound
    // in the context of the current OSWindow
    glActiveTexture(GL_TEXTURE0 + SPRITE_DECORATIONS_MAP_UNIT);
    glBindTexture(GL_TEXTURE_2D, sprite_map->decorations_map.texture_id);
    glActiveTexture(GL_TEXTURE0 + SPRITE_MAP_UNIT);
    glBindTexture(GL_TEXTURE_2D_ARRAY, sprite_map->texture_id);
}

void
send_sprite_to_gpu(FONTS_DATA_HANDLE fg, sprite_index idx, pixel *buf, sprite_index decoration_idx) {
    SpriteMap *sprite_map = (SpriteMap*)fg->sprite_map;
    unsigned int xnum, ynum, znum, x, y, z;
#define dm (sprite_map->decorations_map)
    if (idx >= dm.count) dm.count = idx + 1;
    realloc_sprite_decorations_texture_if_needed(fg);
    div_t d = div(idx, dm.width);
    x = d.rem; y = d.quot;
    glActiveTexture(GL_TEXTURE0 + SPRITE_DECORATIONS_MAP_UNIT);
    glBindTexture(GL_TEXTURE_2D, dm.texture_id);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    glTexSubImage2D(GL_TEXTURE_2D, 0, x, y, 1, 1, GL_RED_INTEGER, GL_UNSIGNED_INT, &decoration_idx);
#undef dm
    sprite_tracker_current_layout(fg, &xnum, &ynum, &znum);
    if ((int)znum >= sprite_map->last_num_of_layers || (znum == 0 && (int)ynum > sprite_map->last_ynum)) {
        realloc_sprite_texture(fg);
        sprite_tracker_current_layout(fg, &xnum, &ynum, &znum);
    }
    glActiveTexture(GL_TEXTURE0 + SPRITE_MAP_UNIT);
    glBindTexture(GL_TEXTURE_2D_ARRAY, sprite_map->texture_id);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    sprite_index_to_pos(idx, xnum, ynum, &x, &y, &z);
    x *= fg->fcm.cell_width; y *= (fg->fcm.cell_height + 1);
    glTexSubImage3D(GL_TEXTURE_2D_ARRAY, 0, x, y, z, fg->fcm.cell_width, fg->fcm.cell_height + 1, 1, GL_RGBA, GL_UNSIGNED_INT_8_8_8_8, buf);
}

void
send_image_to_gpu(GLuint *tex_id, const void* data, GLsizei width, GLsizei height, bool is_opaque, bool is_4byte_aligned, bool linear, RepeatStrategy repeat) {
    if (!(*tex_id)) { glGenTextures(1, tex_id);  }
    glBindTexture(GL_TEXTURE_2D, *tex_id);
    glPixelStorei(GL_UNPACK_ALIGNMENT, is_4byte_aligned ? 4 : 1);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, linear ? GL_LINEAR : GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, linear ? GL_LINEAR : GL_NEAREST);
    RepeatStrategy r;
    switch (repeat) {
        case REPEAT_MIRROR:
            r = GL_MIRRORED_REPEAT; break;
        case REPEAT_CLAMP: {
            static const GLfloat border_color[4] = {0};
            glTexParameterfv(GL_TEXTURE_2D, GL_TEXTURE_BORDER_COLOR, border_color);
            r = GL_CLAMP_TO_BORDER;
            break;
        }
        default:
            r = GL_REPEAT;
    }
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, r);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, r);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_SRGB_ALPHA, width, height, 0, is_opaque ? GL_RGB : GL_RGBA, GL_UNSIGNED_BYTE, data);
}

// }}}

// Cell {{{

typedef struct {
    UniformBlock render_data;
    ArrayInformation color_table;
    CellUniforms uniforms;
} CellProgramLayout;
static CellProgramLayout cell_program_layouts[NUM_PROGRAMS];

typedef struct {
    GraphicsUniforms uniforms;
} GraphicsProgramLayout;
static GraphicsProgramLayout graphics_program_layouts[NUM_PROGRAMS];

typedef struct {
    BgimageUniforms uniforms;
} BGImageProgramLayout;
static BGImageProgramLayout bgimage_program_layout;

typedef struct {
    TintUniforms uniforms;
} TintProgramLayout;
static TintProgramLayout tint_program_layout;

static void
init_cell_program(void) {
    for (int i = CELL_PROGRAM; i < CELL_PROGRAM_SENTINEL; i++) {
        cell_program_layouts[i].render_data.index = block_index(i, "CellRenderData");
        cell_program_layouts[i].render_data.size = block_size(i, cell_program_layouts[i].render_data.index);
        cell_program_layouts[i].color_table.size = get_uniform_information(i, "color_table[0]", GL_UNIFORM_SIZE);
        cell_program_layouts[i].color_table.offset = get_uniform_information(i, "color_table[0]", GL_UNIFORM_OFFSET);
        cell_program_layouts[i].color_table.stride = get_uniform_information(i, "color_table[0]", GL_UNIFORM_ARRAY_STRIDE);
        get_uniform_locations_cell(i, &cell_program_layouts[i].uniforms);
        bind_program(i);
        glUniform1fv(cell_program_layouts[i].uniforms.gamma_lut, arraysz(srgb_lut), srgb_lut);
    }

    // Sanity check to ensure the attribute location binding worked
#define C(p, name, expected) { int aloc = attrib_location(p, #name); if (aloc != expected && aloc != -1) fatal("The attribute location for %s is %d != %d in program: %d", #name, aloc, expected, p); }
    for (int p = CELL_PROGRAM; p < CELL_PROGRAM_SENTINEL; p++) {
        C(p, colors, 0); C(p, sprite_idx, 1); C(p, is_selected, 2); C(p, decorations_sprite_map, 3);
    }
#undef C
    for (int i = GRAPHICS_PROGRAM; i <= GRAPHICS_ALPHA_MASK_PROGRAM; i++) {
        get_uniform_locations_graphics(i, &graphics_program_layouts[i].uniforms);
    }
    get_uniform_locations_bgimage(BGIMAGE_PROGRAM, &bgimage_program_layout.uniforms);
    get_uniform_locations_tint(TINT_PROGRAM, &tint_program_layout.uniforms);
}

#define CELL_BUFFERS enum { cell_data_buffer, selection_buffer, uniform_buffer };

ssize_t
create_cell_vao(void) {
    ssize_t vao_idx = create_vao();
#define A(name, size, dtype, offset, stride) \
    add_attribute_to_vao(CELL_PROGRAM, vao_idx, #name, \
            /*size=*/size, /*dtype=*/dtype, /*stride=*/stride, /*offset=*/offset, /*divisor=*/1);
#define A1(name, size, dtype, offset) A(name, size, dtype, (void*)(offsetof(GPUCell, offset)), sizeof(GPUCell))

    add_buffer_to_vao(vao_idx, GL_ARRAY_BUFFER);
    A1(sprite_idx, 2, GL_UNSIGNED_INT, sprite_idx);
    A1(colors, 3, GL_UNSIGNED_INT, fg);

    add_buffer_to_vao(vao_idx, GL_ARRAY_BUFFER);
    A(is_selected, 1, GL_UNSIGNED_BYTE, NULL, 0);

    size_t bufnum = add_buffer_to_vao(vao_idx, GL_UNIFORM_BUFFER);
    alloc_vao_buffer(vao_idx, cell_program_layouts[CELL_PROGRAM].render_data.size, bufnum, GL_STREAM_DRAW);

    return vao_idx;
#undef A
#undef A1
}

ssize_t
create_graphics_vao(void) {
    ssize_t vao_idx = create_vao();
    add_buffer_to_vao(vao_idx, GL_ARRAY_BUFFER);
    add_attribute_to_vao(GRAPHICS_PROGRAM, vao_idx, "src", 4, GL_FLOAT, 0, NULL, 0);
    return vao_idx;
}

#define IS_SPECIAL_COLOR(name) (screen->color_profile->overridden.name.type == COLOR_IS_SPECIAL || (screen->color_profile->overridden.name.type == COLOR_NOT_SET && screen->color_profile->configured.name.type == COLOR_IS_SPECIAL))

static void
pick_cursor_color(Line *line, const ColorProfile *color_profile, color_type cell_fg, color_type cell_bg, index_type cell_color_x, color_type *cursor_fg, color_type *cursor_bg, color_type default_fg, color_type default_bg) {
    ARGB32 fg, bg, dfg, dbg;
    (void) line; (void) color_profile; (void) cell_color_x;
    fg.rgb = cell_fg; bg.rgb = cell_bg;
    *cursor_fg = cell_bg; *cursor_bg = cell_fg;
    double cell_contrast = rgb_contrast(fg, bg);
    if (cell_contrast < 2.5) {
        dfg.rgb = default_fg; dbg.rgb = default_bg;
        if (rgb_contrast(dfg, dbg) > cell_contrast) {
            *cursor_fg = default_bg; *cursor_bg = default_fg;
        }
    }
}

static float
cell_update_uniform_block(ssize_t vao_idx, Screen *screen, int uniform_buffer, CursorRenderInfo *cursor, OSWindow *os_window) {
    struct GPUCellRenderData {
        GLfloat use_cell_bg_for_selection_fg, use_cell_fg_for_selection_color, use_cell_for_selection_bg;

        GLuint default_fg, highlight_fg, highlight_bg, cursor_fg, cursor_bg, url_color, url_style, inverted;

        GLuint columns, lines, sprites_xnum, sprites_ynum, cursor_fg_sprite_idx, cell_width, cell_height;
        GLuint cursor_x1, cursor_x2, cursor_y1, cursor_y2;
        GLfloat cursor_opacity;

        GLuint bg_colors0, bg_colors1, bg_colors2, bg_colors3, bg_colors4, bg_colors5, bg_colors6, bg_colors7;
        GLfloat bg_opacities0, bg_opacities1, bg_opacities2, bg_opacities3, bg_opacities4, bg_opacities5, bg_opacities6, bg_opacities7;
    };
    // Send the uniform data
    struct GPUCellRenderData *rd = (struct GPUCellRenderData*)map_vao_buffer(vao_idx, uniform_buffer, GL_WRITE_ONLY);
    ColorProfile *cp = screen->paused_rendering.expires_at ? &screen->paused_rendering.color_profile : screen->color_profile;
    if (UNLIKELY(cp->dirty || screen->reload_all_gpu_data)) {
        copy_color_table_to_buffer(cp, (GLuint*)rd, cell_program_layouts[CELL_PROGRAM].color_table.offset / sizeof(GLuint), cell_program_layouts[CELL_PROGRAM].color_table.stride / sizeof(GLuint));
    }
#define COLOR(name) colorprofile_to_color(cp, cp->overridden.name, cp->configured.name).rgb
    rd->default_fg = COLOR(default_fg);
    rd->highlight_fg = COLOR(highlight_fg); rd->highlight_bg = COLOR(highlight_bg);
    rd->bg_colors0 = COLOR(default_bg);
    rd->bg_opacities0 = os_window->is_semi_transparent ? os_window->background_opacity : 1.0f;
    float min_bg_opacity = rd->bg_opacities0;
#define SETBG(which) { \
    colorprofile_to_transparent_color(cp, which - 1, &rd->bg_colors##which, &rd->bg_opacities##which); \
    if (rd->bg_opacities##which < min_bg_opacity) min_bg_opacity = rd->bg_opacities##which;}
    SETBG(1); SETBG(2); SETBG(3); SETBG(4); SETBG(5); SETBG(6); SETBG(7);
#undef SETBG
    // selection
    if (IS_SPECIAL_COLOR(highlight_fg)) {
        if (IS_SPECIAL_COLOR(highlight_bg)) {
            rd->use_cell_bg_for_selection_fg = 1.f; rd->use_cell_fg_for_selection_color = 0.f;
        } else {
            rd->use_cell_bg_for_selection_fg = 0.f; rd->use_cell_fg_for_selection_color = 1.f;
        }
    } else {
        rd->use_cell_bg_for_selection_fg = 0.f; rd->use_cell_fg_for_selection_color = 0.f;
    }
    rd->use_cell_for_selection_bg = IS_SPECIAL_COLOR(highlight_bg) ? 1. : 0.;
    // Cursor position
    enum { BLOCK_IDX = 0, BEAM_IDX = 2, UNDERLINE_IDX = 3, UNFOCUSED_IDX = 4 };
    Line *line_for_cursor = NULL;
    if (cursor->opacity > 0) {
        rd->cursor_x1 = cursor->x, rd->cursor_y1 = cursor->y;
        rd->cursor_x2 = cursor->x, rd->cursor_y2 = cursor->y;
        rd->cursor_opacity = cursor->opacity;
        CursorShape cs = (cursor->is_focused || OPT(cursor_shape_unfocused) == NO_CURSOR_SHAPE) ? cursor->shape : OPT(cursor_shape_unfocused);
        switch(cs) {
            case CURSOR_BEAM:
                rd->cursor_fg_sprite_idx = BEAM_IDX; break;
            case CURSOR_UNDERLINE:
                rd->cursor_fg_sprite_idx = UNDERLINE_IDX; break;
            case CURSOR_BLOCK: case NUM_OF_CURSOR_SHAPES: case NO_CURSOR_SHAPE:
                rd->cursor_fg_sprite_idx = BLOCK_IDX; break;
            case CURSOR_HOLLOW:
                rd->cursor_fg_sprite_idx = UNFOCUSED_IDX; break;
        };
        color_type cell_fg = rd->default_fg, cell_bg = rd->bg_colors0;
        index_type cell_color_x = cursor->x;
        bool reversed = false;
        if (cursor->x < screen->columns && cursor->y < screen->lines) {
            if (screen->paused_rendering.expires_at) {
                linebuf_init_line(screen->paused_rendering.linebuf, cursor->y); line_for_cursor = screen->paused_rendering.linebuf->line;
            } else {
                linebuf_init_line(screen->linebuf, cursor->y); line_for_cursor = screen->linebuf->line;
            }
        }
        if (line_for_cursor) {
            colors_for_cell(line_for_cursor, cp, &cell_color_x, &cell_fg, &cell_bg, &reversed);
            const CPUCell *cursor_cell;
            const bool large_cursor = ((cursor_cell = &line_for_cursor->cpu_cells[cursor->x])->is_multicell) && cursor_cell->x == 0 && cursor_cell->y == 0;
            if (large_cursor) {
                switch(cs) {
                    case CURSOR_BEAM:
                        rd->cursor_y2 += cursor_cell->scale - 1; break;
                    case CURSOR_UNDERLINE:
                        rd->cursor_y1 += cursor_cell->scale - 1;
                        rd->cursor_y2 = rd->cursor_y1;
                        rd->cursor_x2 += mcd_x_limit(cursor_cell) - 1;
                        break;
                    case CURSOR_BLOCK:
                        rd->cursor_y2 += cursor_cell->scale - 1;
                        rd->cursor_x2 += mcd_x_limit(cursor_cell) - 1;
                        break;
                    case CURSOR_HOLLOW: case NUM_OF_CURSOR_SHAPES: case NO_CURSOR_SHAPE: break;
                };
            }
        }
        if (IS_SPECIAL_COLOR(cursor_color)) {
            if (line_for_cursor) pick_cursor_color(line_for_cursor, cp, cell_fg, cell_bg, cell_color_x, &rd->cursor_fg, &rd->cursor_bg, rd->default_fg, rd->bg_colors0);
            else { rd->cursor_fg = rd->bg_colors0; rd->cursor_bg = rd->default_fg; }
            if (cell_bg == cell_fg) {
                rd->cursor_fg = rd->bg_colors0; rd->cursor_bg = rd->default_fg;
            } else { rd->cursor_fg = cell_bg; rd->cursor_bg = cell_fg; }
        } else {
            rd->cursor_bg = COLOR(cursor_color);
            if (IS_SPECIAL_COLOR(cursor_text_color)) rd->cursor_fg = cell_bg;
            else rd->cursor_fg = COLOR(cursor_text_color);
        }
        // store last rendered cursor color for trail rendering
        screen->last_rendered.cursor_bg = rd->cursor_bg;
    } else {
        rd->cursor_x1 = screen->columns + 1; rd->cursor_x2 = screen->columns;
        rd->cursor_y1 = screen->lines + 1; rd->cursor_y2 = screen->lines;
    }

    rd->columns = screen->columns; rd->lines = screen->lines;

    unsigned int x, y, z;
    sprite_tracker_current_layout(os_window->fonts_data, &x, &y, &z);
    rd->sprites_xnum = x; rd->sprites_ynum = y;
    rd->inverted = screen_invert_colors(screen) ? 1 : 0;
    rd->cell_width = os_window->fonts_data->fcm.cell_width;
    rd->cell_height = os_window->fonts_data->fcm.cell_height;

#undef COLOR
    rd->url_color = OPT(url_color); rd->url_style = OPT(url_style);

    unmap_vao_buffer(vao_idx, uniform_buffer); rd = NULL;
    return min_bg_opacity;
}

static bool
cell_prepare_to_render(ssize_t vao_idx, Screen *screen, GLfloat xstart, GLfloat ystart, GLfloat dx, GLfloat dy, FONTS_DATA_HANDLE fonts_data) {
    size_t sz;
    CELL_BUFFERS;
    void *address;
    bool changed = false;

    ensure_sprite_map(fonts_data);
    const Cursor *cursor = screen->paused_rendering.expires_at ? &screen->paused_rendering.cursor : screen->cursor;

    bool cursor_pos_changed = cursor->x != screen->last_rendered.cursor_x
                           || cursor->y != screen->last_rendered.cursor_y;
    bool disable_ligatures = screen->disable_ligatures == DISABLE_LIGATURES_CURSOR;
    bool screen_resized = screen->last_rendered.columns != screen->columns || screen->last_rendered.lines != screen->lines;

#define update_cell_data { \
        sz = sizeof(GPUCell) * screen->lines * screen->columns; \
        address = alloc_and_map_vao_buffer(vao_idx, sz, cell_data_buffer, GL_STREAM_DRAW, GL_WRITE_ONLY); \
        screen_update_cell_data(screen, address, fonts_data, disable_ligatures && cursor_pos_changed); \
        unmap_vao_buffer(vao_idx, cell_data_buffer); address = NULL; \
        changed = true; \
}

    if (screen->paused_rendering.expires_at) {
        if (!screen->paused_rendering.cell_data_updated) update_cell_data;
    } else if (screen->reload_all_gpu_data || screen->scroll_changed || screen->is_dirty || screen_resized || (disable_ligatures && cursor_pos_changed)) update_cell_data;

    if (cursor_pos_changed) {
        screen->last_rendered.cursor_x = cursor->x;
        screen->last_rendered.cursor_y = cursor->y;
    }

#define update_selection_data { \
    sz = (size_t)screen->lines * screen->columns; \
    address = alloc_and_map_vao_buffer(vao_idx, sz, selection_buffer, GL_STREAM_DRAW, GL_WRITE_ONLY); \
    screen_apply_selection(screen, address, sz); \
    unmap_vao_buffer(vao_idx, selection_buffer); address = NULL; \
    changed = true; \
}

#define update_graphics_data(grman) \
    grman_update_layers(grman, screen->scrolled_by, xstart, ystart, dx, dy, screen->columns, screen->lines, screen->cell_size)

    if (screen->paused_rendering.expires_at) {
        if (!screen->paused_rendering.cell_data_updated) {
            update_selection_data; update_graphics_data(screen->paused_rendering.grman);
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

    return changed;
}

static void
draw_graphics(int program, ImageRenderData *data, GLuint start, GLuint count, float inactive_text_alpha) {
    bind_program(program);
    glUniform1f(graphics_program_layouts[program].uniforms.inactive_text_alpha, inactive_text_alpha);
    glActiveTexture(GL_TEXTURE0 + GRAPHICS_UNIT);
    GraphicsUniforms *u = &graphics_program_layouts[program].uniforms;
    for (GLuint i=0; i < count;) {
        ImageRenderData *group = data + start + i;
        glBindTexture(GL_TEXTURE_2D, group->texture_id);
        if (group->group_count == 0) { i++; continue; }
        for (GLuint k=0; k < group->group_count; k++, i++) {
            ImageRenderData *rd = data + start + i;
            glUniform4f(u->src_rect, rd->src_rect.left, rd->src_rect.top, rd->src_rect.right, rd->src_rect.bottom);
            glUniform4f(u->dest_rect, rd->dest_rect.left, rd->dest_rect.top, rd->dest_rect.right, rd->dest_rect.bottom);
            glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
        }
    }
}

static ImageRenderData*
load_alpha_mask_texture(size_t width, size_t height, uint8_t *canvas) {
    static ImageRenderData data = {.group_count=1};
    if (!data.texture_id) { glGenTextures(1, &data.texture_id); }
    glBindTexture(GL_TEXTURE_2D, data.texture_id);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RED, width, height, 0, GL_RED, GL_UNSIGNED_BYTE, canvas);
    return &data;
}

static void
gpu_data_for_centered_image(ImageRenderData *ans, unsigned int screen_width_px, unsigned int screen_height_px, unsigned int width, unsigned int height) {
    float width_frac = 2 * MIN(1, width / (float)screen_width_px), height_frac = 2 * MIN(1, height / (float)screen_height_px);
    float hmargin = (2 - width_frac) / 2;
    float vmargin = (2 - height_frac) / 2;
    gpu_data_for_image(ans, -1 + hmargin, 1 - vmargin, -1 + hmargin + width_frac, 1 - vmargin - height_frac);
}


void
draw_centered_alpha_mask(OSWindow *os_window, size_t screen_width, size_t screen_height, size_t width, size_t height, uint8_t *canvas, float background_opacity) {
    ImageRenderData *data = load_alpha_mask_texture(width, height, canvas);
    gpu_data_for_centered_image(data, screen_width, screen_height, width, height);
    bind_program(GRAPHICS_ALPHA_MASK_PROGRAM);
    glUniform1i(graphics_program_layouts[GRAPHICS_ALPHA_MASK_PROGRAM].uniforms.image, GRAPHICS_UNIT);
    color_vec3(graphics_program_layouts[GRAPHICS_ALPHA_MASK_PROGRAM].uniforms.amask_fg, OPT(foreground));
    color_vec4_premult(graphics_program_layouts[GRAPHICS_ALPHA_MASK_PROGRAM].uniforms.amask_bg_premult, OPT(background), background_opacity);
    glEnable(GL_BLEND);
    if (os_window->is_semi_transparent) {
        BLEND_PREMULT;
    } else {
        BLEND_ONTO_OPAQUE;
    }
    draw_graphics(GRAPHICS_ALPHA_MASK_PROGRAM, data, 0, 1, 1.0);
    glDisable(GL_BLEND);
}

static bool
has_bgimage(OSWindow *w) {
    return w->bgimage && w->bgimage->texture_id > 0;
}

static GLuint
ensure_blank_texture(void) {
    static GLuint texture_id = 0;  // we leak this texture it will be cleaned up on exit and is one pixel size anyway
    if (!texture_id) {
        glGenTextures(1, &texture_id);
        // upload dummy 1 pixel blank texture to GPU
        glBindTexture(GL_TEXTURE_2D, texture_id);
        unsigned char data[4] = {0, 0, 0, 0};
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, data);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glBindTexture(GL_TEXTURE_2D, 0);
    }
    return texture_id;
}

static bool
ensure_layer_ready_to_render(const UIRenderData *ui, ScreenLayer *which) {
    bool needs_redraw = false;
    if (which->width != ui->screen_width || which->height != ui->screen_height) {
        if (which->id) free_texture(&which->id);
        if (which->framebuffer_id) free_framebuffer(&which->framebuffer_id);
    }
    if (!which->id) {
        glGenTextures(1, &which->id);
        glGenFramebuffers(1, &which->framebuffer_id);
        which->width = ui->screen_width; which->height = ui->screen_height;
        glBindTexture(GL_TEXTURE_2D, which->id);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, which->width, which->height, 0, GL_RGBA, GL_UNSIGNED_BYTE, NULL);
        glBindFramebuffer(GL_FRAMEBUFFER, which->framebuffer_id);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, which->id, 0);
        check_framebuffer_status_or_die();
        needs_redraw = true;
    }
    glBindFramebuffer(GL_FRAMEBUFFER, which->framebuffer_id);
    return needs_redraw;
}

static void
save_texture_as_png(GLuint texture_id, unsigned width, unsigned height, const char *filename) {
    glBindTexture(GL_TEXTURE_2D, texture_id);
    size_t sz = width * height * sizeof(uint32_t);
    uint32_t* data = malloc(sz);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE, data);
    const char *png = png_from_32bit_rgba(data, width, height, &sz, true);
    if (!sz) fatal("Failed to save PNG to %s with error: %s", filename, png);
    free(data);
    FILE* file = fopen(filename, "wb");
    fwrite(png, 1, sz, file);
    fclose(file);
}

static void
set_cell_uniforms(bool force) {
    static bool constants_set = false;
    if (!constants_set || force) {
        float text_contrast = 1.0f + OPT(text_contrast) * 0.01f;
        float text_gamma_adjustment = OPT(text_gamma_adjustment) < 0.01f ? 1.0f : 1.0f / OPT(text_gamma_adjustment);
        for (int i = GRAPHICS_PROGRAM; i <= GRAPHICS_ALPHA_MASK_PROGRAM; i++) {
            bind_program(i); glUniform1i(graphics_program_layouts[i].uniforms.image, GRAPHICS_UNIT);
        }
        for (int i = CELL_PROGRAM; i < CELL_PROGRAM_SENTINEL; i++) {
            bind_program(i); const CellUniforms *cu = &cell_program_layouts[i].uniforms;
            glUniform1i(cu->sprites, SPRITE_MAP_UNIT);
            glUniform1i(cu->under_bg_layer, UNDER_BG_LAYER_UNIT);
            glUniform1i(cu->under_fg_layer, UNDER_FG_LAYER_UNIT);
            glUniform1i(cu->over_fg_layer, OVER_FG_LAYER_UNIT);
            glUniform1i(cu->ui_layer, UI_LAYER_UNIT);
            glUniform1i(cu->sprite_decorations_map, SPRITE_DECORATIONS_MAP_UNIT);
            glUniform1f(cu->dim_opacity, OPT(dim_opacity));
            glUniform1f(cu->text_contrast, text_contrast);
            glUniform1f(cu->text_gamma_adjustment, text_gamma_adjustment);
        }
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
draw_visual_bell_flash(GLfloat intensity, const color_type flash) {
    glEnable(GL_BLEND);
    BLEND_PREMULT;
    bind_program(TINT_PROGRAM);
    GLfloat attenuation = 0.4f;
#define C(shift) srgb_color((flash >> shift) & 0xFF)
    const GLfloat r = C(16), g = C(8), b = C(0);
    const GLfloat max_channel = r > g ? (r > b ? r : b) : (g > b ? g : b);
#undef C
#define C(x) (x * intensity * attenuation)
    if (max_channel > 0.45) attenuation = 0.6f;  // light color
    glUniform4f(tint_program_layout.uniforms.tint_color, C(r), C(g), C(b), C(1));
#undef C
    glUniform4f(tint_program_layout.uniforms.edges, -1, 1, 1, -1);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    glDisable(GL_BLEND);
}

static bool
draw_scroll_indicator(color_type bar_color, GLfloat alpha, float frac, const UIRenderData *ui) {
    glEnable(GL_BLEND);
    BLEND_PREMULT;
    bind_program(TINT_PROGRAM);
#define C(shift) srgb_color((bar_color >> shift) & 0xFF) * alpha
    glUniform4f(tint_program_layout.uniforms.tint_color, C(16), C(8), C(0), alpha);
#undef C
    float bar_width = 0.5f * gl_size(ui->cell_width, ui->screen_width);
    float bar_height = gl_size(ui->cell_height, ui->screen_height);
    float bottom = -1.f + MAX(0, 2.f - bar_height) * frac;
    glUniform4f(tint_program_layout.uniforms.edges, 1.f - bar_width, bottom + bar_height, 1.f, bottom);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    glDisable(GL_BLEND);
    return true;
}

static unsigned
render_a_bar(const UIRenderData *ui, WindowBarData *bar, PyObject *title, bool along_bottom) {
    unsigned bar_height = ui->cell_height + 2;
    unsigned bar_width = ui->screen_width;
    if (!bar->buf || bar->width != bar_width || bar->height != bar_height) {
        free(bar->buf);
        bar->buf = malloc((size_t)4 * bar_width * bar_height);
        if (!bar->buf) return 0;
        bar->height = bar_height;
        bar->width = bar_width;
        bar->needs_render = true;
    }

    if (bar->last_drawn_title_object_id != title || bar->needs_render) {
        static char titlebuf[2048] = {0};
        if (!title) return 0;
        snprintf(titlebuf, arraysz(titlebuf), " %s", PyUnicode_AsUTF8(title));
#define RGBCOL(which, fallback) ( 0xff000000 | colorprofile_to_color_with_fallback(ui->screen->color_profile, ui->screen->color_profile->overridden.which, ui->screen->color_profile->configured.which, ui->screen->color_profile->overridden.fallback, ui->screen->color_profile->configured.fallback))
        if (!draw_window_title(ui->os_window->fonts_data->font_sz_in_pts, ui->os_window->fonts_data->logical_dpi_y, titlebuf, RGBCOL(highlight_fg, default_fg), RGBCOL(highlight_bg, default_bg), bar->buf, bar_width, bar_height)) return 0;
#undef RGBCOL
        Py_CLEAR(bar->last_drawn_title_object_id);
        bar->last_drawn_title_object_id = Py_NewRef(title);
    }
    static ImageRenderData data = {.group_count=1};
    gpu_data_for_image(&data, -1, 1, 1, -1);
    glGenTextures(1, &data.texture_id);
    glBindTexture(GL_TEXTURE_2D, data.texture_id);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_SRGB_ALPHA, bar_width, bar_height, 0, GL_RGBA, GL_UNSIGNED_BYTE, bar->buf);
    bind_program(GRAPHICS_PROGRAM);
    glEnable(GL_BLEND);
    BLEND_PREMULT;
    // current viewport is (0, 0, ui->screen_width, ui->screen_height) coz we are rendering to FBO texture
    if (along_bottom) save_viewport_using_bottom_left_origin(0, 0, ui->screen_width, bar_height);
    else save_viewport_using_top_left_origin(0, 0, ui->screen_width, bar_height, ui->screen_height);
    draw_graphics(GRAPHICS_PROGRAM, &data, 0, 1, 1.f);
    restore_viewport();
    free_texture(&data.texture_id);
    glDisable(GL_BLEND);
    return bar_height;
}

static void
draw_hyperlink_target(Screen *screen, const UIRenderData *ui, const bool along_bottom) {
    Window *window = ui->window;
    WindowBarData *bd = &window->url_target_bar_data;
    if (bd->hyperlink_id_for_title_object != screen->current_hyperlink_under_mouse.id) {
        bd->hyperlink_id_for_title_object = screen->current_hyperlink_under_mouse.id;
        Py_CLEAR(bd->last_drawn_title_object_id);
        const char *url = get_hyperlink_for_id(screen->hyperlink_pool, bd->hyperlink_id_for_title_object, true);
        if (url == NULL) url = "";
        bd->last_drawn_title_object_id = PyObject_CallMethod(global_state.boss, "sanitize_url_for_display_to_user", "s", url);
        if (bd->last_drawn_title_object_id == NULL) { PyErr_Print(); return; }
        bd->needs_render = true;
    }
    if (bd->last_drawn_title_object_id == NULL) return;
    PyObject *ref = Py_NewRef(bd->last_drawn_title_object_id);  // render_a_bar clears bd->last_drawn_title_object_id
    render_a_bar(ui, &window->title_bar_data, bd->last_drawn_title_object_id, along_bottom);
    Py_DECREF(ref);
}

static void
draw_window_number(const UIRenderData *ui) {
    unsigned title_bar_height = 0, requested_height = ui->screen_height;
    if (ui->window->title && PyUnicode_Check(ui->window->title) && (requested_height > (ui->cell_height + 1) * 2)) {
        title_bar_height = render_a_bar(ui, &ui->window->title_bar_data, ui->window->title, false);
    }
    unsigned height_for_letter = ui->screen_height - title_bar_height - ui->cell_height;
    unsigned width_for_letter = ui->screen_width - ui->cell_width;
    requested_height = MIN(12 * ui->cell_height, MIN(height_for_letter, width_for_letter));
    if (requested_height < 4) return;
#define lr ui->screen->last_rendered_window_char
    if (!lr.canvas || lr.ch != ui->screen->display_window_char || lr.requested_height != requested_height) {
        free(lr.canvas); lr.canvas = NULL;
        lr.requested_height = requested_height; lr.height_px = requested_height; lr.ch = 0;
        lr.canvas = draw_single_ascii_char(ui->screen->display_window_char, &lr.width_px, &lr.height_px);
        if (lr.height_px < 4 || lr.width_px < 4 || !lr.canvas) return;
        lr.ch = ui->screen->display_window_char;
    }
    unsigned letter_x = 0, letter_y = title_bar_height;
    if (lr.width_px < ui->screen_width) letter_x = (ui->screen_width - lr.width_px) / 2;
    if (lr.height_px + title_bar_height < ui->screen_height) letter_y += (ui->screen_height - lr.height_px - title_bar_height) / 2;
    bind_program(GRAPHICS_ALPHA_MASK_PROGRAM);
    ImageRenderData *ird = load_alpha_mask_texture(lr.width_px, lr.height_px, lr.canvas);
    gpu_data_for_image(ird, -1, 1, 1, -1);
    glEnable(GL_BLEND);
    BLEND_PREMULT;
    glUniform1i(graphics_program_layouts[GRAPHICS_ALPHA_MASK_PROGRAM].uniforms.image, GRAPHICS_UNIT);
    color_type digit_color = colorprofile_to_color_with_fallback(ui->screen->color_profile, ui->screen->color_profile->overridden.highlight_bg, ui->screen->color_profile->configured.highlight_bg, ui->screen->color_profile->overridden.default_fg, ui->screen->color_profile->configured.default_fg);
    color_vec3(graphics_program_layouts[GRAPHICS_ALPHA_MASK_PROGRAM].uniforms.amask_fg, digit_color);
    glUniform4f(graphics_program_layouts[GRAPHICS_ALPHA_MASK_PROGRAM].uniforms.amask_bg_premult, 0.f, 0.f, 0.f, 0.f);
    save_viewport_using_top_left_origin(letter_x, letter_y, lr.width_px, lr.height_px, ui->screen_height);
    draw_graphics(GRAPHICS_ALPHA_MASK_PROGRAM, ird, 0, 1, 1.f);
    restore_viewport();
    glDisable(GL_BLEND);
#undef lr
}

static bool
update_ui_layer(const UIRenderData *ui) {
    Screen *screen = ui->screen;
    bool visual_bell_drawn = screen->start_visual_bell_at > 0;
    bool scrollback_indicator_drawn = !(OPT(scrollback_indicator_opacity) <= 0 || screen->linebuf != screen->main_linebuf || !screen->scrolled_by);
    bool hyperlink_target_drawn = OPT(show_hyperlink_targets) && screen->current_hyperlink_under_mouse.id && ui->window && !is_mouse_hidden(ui->os_window);
    bool window_number_drawn = ui->window && screen->display_window_char;
    bool ui_layer_present = visual_bell_drawn || scrollback_indicator_drawn || hyperlink_target_drawn || window_number_drawn;
    if (!ui_layer_present) return false;
    bool needs_redraw = ensure_layer_ready_to_render(ui, &screen->textures.ui);

#define last_ui screen->last_rendered.ui_layer
#define lvb last_ui.visual_bell
    GLfloat intensity = 0; color_type flash = 0;
    if (visual_bell_drawn) {
        intensity = get_visual_bell_intensity(screen);
#define COLOR(name, fallback) colorprofile_to_color_with_fallback(screen->color_profile, screen->color_profile->overridden.name, screen->color_profile->configured.name, screen->color_profile->overridden.fallback, screen->color_profile->configured.fallback)
    flash = !IS_SPECIAL_COLOR(highlight_bg) ? COLOR(visual_bell_color, highlight_bg) : COLOR(visual_bell_color, default_fg);
#undef COLOR
    }
    bool visual_bell_needs_redraw = visual_bell_drawn != lvb.was_drawn || intensity != lvb.intensity || flash != lvb.color;
    lvb.intensity = intensity; lvb.color = flash; lvb.was_drawn = visual_bell_drawn;

#define lsb last_ui.scroll_bar
    color_type bar_color = 0;
    GLfloat bar_alpha = OPT(scrollback_indicator_opacity);
    float bar_frac = 0;
    if (scrollback_indicator_drawn) {
        bar_color = colorprofile_to_color(screen->color_profile, screen->color_profile->overridden.highlight_bg, screen->color_profile->configured.highlight_bg).rgb;
        bar_frac = (float)screen->scrolled_by / (float)screen->historybuf->count;
    }
    bool scrollbar_needs_redraw = (
        lsb.was_drawn != scrollback_indicator_drawn || lsb.frac != bar_frac || lsb.color != bar_color ||
        lsb.cell_height != ui->cell_height || lsb.alpha != bar_alpha || lsb.cell_width != ui->cell_width);
    lsb.alpha = bar_alpha; lsb.cell_height = ui->cell_height; lsb.cell_width = ui->cell_width; lsb.color = bar_color;
    lsb.frac = bar_frac; lsb.was_drawn = scrollback_indicator_drawn;

#define ht last_ui.hyperlink_target
    bool along_bottom = screen->current_hyperlink_under_mouse.y < 3;
    bool hyperlink_target_needs_redraw = (
        ht.was_drawn != hyperlink_target_drawn || ht.link != screen->current_hyperlink_under_mouse.id ||
        ht.along_bottom != along_bottom);
    ht.link = screen->current_hyperlink_under_mouse.id; ht.along_bottom = along_bottom;
    ht.was_drawn = hyperlink_target_drawn;

#define wn last_ui.window_number
    bool window_number_needs_redraw = (
        wn.was_drawn != window_number_drawn || wn.ch != screen->display_window_char);
    wn.was_drawn = window_number_drawn; wn.ch = screen->display_window_char;

    needs_redraw |= scrollbar_needs_redraw || visual_bell_needs_redraw || hyperlink_target_needs_redraw || window_number_needs_redraw;
    if (needs_redraw) {
        blank_canvas(0, 0);  // clear the framebuffer
        if (visual_bell_drawn && intensity > 0) draw_visual_bell_flash(lvb.intensity, lvb.color);
        if (scrollback_indicator_drawn) draw_scroll_indicator(bar_color, bar_alpha, bar_frac, ui);
        if (hyperlink_target_drawn) draw_hyperlink_target(screen, ui, ht.along_bottom);
        if (window_number_drawn) draw_window_number(ui);
        if (0) save_texture_as_png(screen->textures.ui.id, ui->screen_width, ui->screen_height, "/tmp/ui.png");
    }
    return true;
#undef wn
#undef ht
#undef lsb
#undef lvb
#undef last_ui
}
// }}}

static bool
update_under_bg_layer(const UIRenderData *ui) {
    bool has_background_image = has_bgimage(ui->os_window);
    if (!has_background_image && !ui->grd.num_of_below_refs) return false;
    return true;
}

static bool
update_under_fg_layer(const UIRenderData *ui) {
    if (!ui->window_logo && !ui->grd.num_of_below_refs) return false;
    return true;
}

static bool
update_over_fg_layer(const UIRenderData *ui) {
    if (!ui->grd.num_of_positive_refs) return false;
    return true;
}

static void
update_screen_layers(UIRenderData *ui) {
    save_viewport_using_bottom_left_origin(0, 0, ui->screen_width, ui->screen_height);
    ui->has_under_bg = update_under_bg_layer(ui);
    ui->has_under_fg = update_under_fg_layer(ui);
    ui->has_over_fg = update_over_fg_layer(ui);
    ui->has_ui = update_ui_layer(ui);
    glBindFramebuffer(GL_FRAMEBUFFER, 0);
    restore_viewport();
}

static void
draw_cells_with_layers(bool for_final_output, const UIRenderData *ui, ssize_t vao_idx, bool is_semi_transparent) {
    GLuint blank_texture = ensure_blank_texture();
    bool has_layers = false;

#define B(which, unit) \
    glActiveTexture(GL_TEXTURE0 + unit); \
    if (ui->has_##which) { has_layers = true; glBindTexture(GL_TEXTURE_2D, ui->screen->textures.which.id); } \
    else { \
        if (ui->screen->textures.which.id) free_texture(&ui->screen->textures.which.id); \
        if (ui->screen->textures.which.framebuffer_id) free_framebuffer(&ui->screen->textures.which.framebuffer_id); \
        glBindTexture(GL_TEXTURE_2D, blank_texture); \
    }

    B(under_bg, UNDER_BG_LAYER_UNIT); B(under_fg, UNDER_FG_LAYER_UNIT); B(over_fg, OVER_FG_LAYER_UNIT);
    B(ui, UI_LAYER_UNIT);
#undef B

    int program;
    if (is_semi_transparent) {
        bind_program((program = has_layers ? CELL_LAYERS_TRANSPARENT_PROGRAM : CELL_TRANSPARENT_PROGRAM));
        glUniform1f(cell_program_layouts[CELL_PROGRAM].uniforms.for_final_output, for_final_output ? 1. : 0.);
        if (for_final_output) {
            glDisable(GL_BLEND);
        } else {
            glEnable(GL_BLEND);
            BLEND_PREMULT;
        }
    } else {
        bind_program((program = has_layers ? CELL_LAYERS_PROGRAM : CELL_PROGRAM));
        glDisable(GL_BLEND);
        if (for_final_output) glEnable(GL_FRAMEBUFFER_SRGB);
    }
    glUniform1f(cell_program_layouts[program].uniforms.has_under_bg, ui->has_under_bg);
    glUniform1f(cell_program_layouts[program].uniforms.inactive_text_alpha, ui->inactive_text_alpha);
    CELL_BUFFERS;
    bind_vao_uniform_buffer(vao_idx, uniform_buffer, cell_program_layouts[program].render_data.index);
    save_viewport_using_top_left_origin(
        ui->screen_left, ui->screen_top, ui->screen_width, ui->screen_height, ui->full_framebuffer_height);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, ui->screen->lines * ui->screen->columns);
    restore_viewport();
    glDisable(GL_FRAMEBUFFER_SRGB);
}

void
blank_canvas(float background_opacity, color_type color) {
    // See https://github.com/glfw/glfw/issues/1538 for why we use pre-multiplied alpha
#define C(shift) srgb_color((color >> shift) & 0xFF)
    glClearColor(C(16), C(8), C(0), background_opacity);
#undef C
    glClear(GL_COLOR_BUFFER_BIT);
}

bool
send_cell_data_to_gpu(ssize_t vao_idx, GLfloat xstart, GLfloat ystart, GLfloat dx, GLfloat dy, Screen *screen, OSWindow *os_window) {
    bool changed = false;
    if (os_window->fonts_data) {
        if (cell_prepare_to_render(vao_idx, screen, xstart, ystart, dx, dy, os_window->fonts_data)) changed = true;
    }
    return changed;
}

void
draw_cells(bool for_final_output, const WindowRenderData *srd, OSWindow *os_window, bool is_active_window, bool is_tab_bar, bool is_single_window, Window *window) {
    // float x_ratio = 1., y_ratio = 1.;
    // if (os_window->live_resize.in_progress) {
    //     x_ratio = (float) os_window->viewport_width / (float) os_window->live_resize.width;
    //     y_ratio = (float) os_window->viewport_height / (float) os_window->live_resize.height;
    // }
    Screen *screen = srd->screen;
    CELL_BUFFERS;
    bind_vertex_array(srd->vao_idx);
    float min_bg_opacity = cell_update_uniform_block(
            srd->vao_idx, screen, uniform_buffer, &screen->cursor_render_info, os_window);
    // We draw with inactive text alpha if:
    // - We're not drawing the tab bar
    // - There's only a single window and the os window is not focused
    // - There are multiple windows and the current window is not active
    float current_inactive_text_alpha = is_tab_bar || (!is_single_window && is_active_window) || (is_single_window && screen->cursor_render_info.is_focused) ? 1.0f : (float)OPT(inactive_text_alpha);
    bool is_semi_transparent = os_window->is_semi_transparent && min_bg_opacity < 1.;
    WindowLogoRenderData *wl;
    if (window && (wl = &window->window_logo) && wl->id && (wl->instance = find_window_logo(global_state.all_window_logos, wl->id)) && wl->instance && wl->instance->load_from_disk_ok) {
        set_on_gpu_state(window->window_logo.instance, true);
    } else wl = NULL;
    GraphicsManager *grman = screen->paused_rendering.expires_at && screen->paused_rendering.grman ? screen->paused_rendering.grman : screen->grman;
    GraphicsRenderData grd = grman_render_data(grman);
    // if (os_window->live_resize.in_progress && grd.count && (crd.x_ratio != 1 || crd.y_ratio != 1)) {
    //     scaled_render_data = malloc(sizeof(scaled_render_data[0]) * grd.count);
    //     if (scaled_render_data) {
    //         memcpy(scaled_render_data, grd.images, sizeof(scaled_render_data[0]) * grd.count);
    //         grd.images = scaled_render_data;
    //         for (size_t i = 0; i < grd.count; i++)
    //             scale_rendered_graphic(grd.images + i, srd->xstart, srd->ystart, crd.x_ratio, crd.y_ratio);
    //     }
    // }
    UIRenderData ui = {
        .screen_width = srd->geometry.right - srd->geometry.left,
        .screen_height = srd->geometry.bottom - srd->geometry.top,
        .cell_width = os_window->fonts_data->fcm.cell_width,
        .cell_height = os_window->fonts_data->fcm.cell_height,
        .screen_left = srd->geometry.left, .screen_top = srd->geometry.top,
        .full_framebuffer_width = os_window->viewport_width, .full_framebuffer_height = os_window->viewport_height,
        .window = window, .screen = screen, .os_window = os_window, .grd = grd, .window_logo = wl,
        .inactive_text_alpha = current_inactive_text_alpha,
    };
    update_screen_layers(&ui);

    set_cell_uniforms(screen->reload_all_gpu_data);
    screen->reload_all_gpu_data = false;
    ImageRenderData *scaled_render_data = NULL;
    draw_cells_with_layers(for_final_output, &ui, srd->vao_idx, is_semi_transparent);
    free(scaled_render_data);
}
// }}}

// Borders {{{

typedef struct BorderProgramLayout {
    BorderUniforms uniforms;
} BorderProgramLayout;
static BorderProgramLayout border_program_layout;

static void
init_borders_program(void) {
    get_uniform_locations_border(BORDERS_PROGRAM, &border_program_layout.uniforms);
    bind_program(BORDERS_PROGRAM);
    glUniform1fv(border_program_layout.uniforms.gamma_lut, 256, srgb_lut);
}

ssize_t
create_border_vao(void) {
    ssize_t vao_idx = create_vao();

    add_buffer_to_vao(vao_idx, GL_ARRAY_BUFFER);
    add_attribute_to_vao(BORDERS_PROGRAM, vao_idx, "rect",
            /*size=*/4, /*dtype=*/GL_FLOAT, /*stride=*/sizeof(BorderRect), /*offset=*/(void*)offsetof(BorderRect, left), /*divisor=*/1);
    add_attribute_to_vao(BORDERS_PROGRAM, vao_idx, "rect_color",
            /*size=*/1, /*dtype=*/GL_UNSIGNED_INT, /*stride=*/sizeof(BorderRect), /*offset=*/(void*)(offsetof(BorderRect, color)), /*divisor=*/1);

    return vao_idx;
}

void
draw_borders(ssize_t vao_idx, unsigned int num_border_rects, BorderRect *rect_buf, bool rect_data_is_dirty, uint32_t viewport_width, uint32_t viewport_height, color_type active_window_bg, unsigned int num_visible_windows, bool all_windows_have_same_bg, OSWindow *w) {
    float background_opacity = w->is_semi_transparent ? w->background_opacity: 1.0f;
    bind_vertex_array(vao_idx);
    if (num_border_rects) {
        bind_program(BORDERS_PROGRAM);
        if (rect_data_is_dirty) {
            const size_t sz = sizeof(BorderRect) * num_border_rects;
            void *borders_buf_address = alloc_and_map_vao_buffer(vao_idx, sz, 0, GL_STATIC_DRAW, GL_WRITE_ONLY);
            if (borders_buf_address) memcpy(borders_buf_address, rect_buf, sz);
            unmap_vao_buffer(vao_idx, 0);
        }
        color_type default_bg = (num_visible_windows > 1 && !all_windows_have_same_bg) ? OPT(background) : active_window_bg;
        GLuint colors[9] = {
            default_bg, OPT(active_border_color), OPT(inactive_border_color), 0,
            OPT(bell_border_color), OPT(tab_bar_background), OPT(tab_bar_margin_color),
            w->tab_bar_edge_color.left, w->tab_bar_edge_color.right
        };
        glUniform1uiv(border_program_layout.uniforms.colors, arraysz(colors), colors);
        glUniform1f(border_program_layout.uniforms.background_opacity, background_opacity);
        glUniform2ui(border_program_layout.uniforms.viewport, viewport_width, viewport_height);
        glDisable(GL_BLEND);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, num_border_rects);
        unbind_program();
    }
    unbind_vertex_array();
    if (has_bgimage(w)) glDisable(GL_BLEND);
}

// }}}

// Cursor Trail {{{
typedef struct {
    TrailUniforms uniforms;
} TrailProgramLayout;
static TrailProgramLayout trail_program_layout;

static void
init_trail_program(void) {
    get_uniform_locations_trail(TRAIL_PROGRAM, &trail_program_layout.uniforms);
}

void
draw_cursor_trail(CursorTrail *trail, Window *active_window) {
    bind_program(TRAIL_PROGRAM);
    glEnable(GL_BLEND);
    BLEND_ONTO_OPAQUE;

    glUniform4fv(trail_program_layout.uniforms.x_coords, 1, trail->corner_x);
    glUniform4fv(trail_program_layout.uniforms.y_coords, 1, trail->corner_y);

    glUniform2fv(trail_program_layout.uniforms.cursor_edge_x, 1, trail->cursor_edge_x);
    glUniform2fv(trail_program_layout.uniforms.cursor_edge_y, 1, trail->cursor_edge_y);

    color_type trail_color = OPT(cursor_trail_color);
    if (trail_color == 0) {  // 0 means "none" was specified
        trail_color = active_window ? active_window->render_data.screen->last_rendered.cursor_bg : OPT(foreground);
    }
    color_vec3(trail_program_layout.uniforms.trail_color, trail_color);

    glUniform1fv(trail_program_layout.uniforms.trail_opacity, 1, &trail->opacity);

    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    glDisable(GL_BLEND);
    unbind_program();
}

// }}}

// Python API {{{

static bool
attach_shaders(PyObject *sources, GLuint program_id, GLenum shader_type) {
    RAII_ALLOC(const GLchar*, c_sources, calloc(PyTuple_GET_SIZE(sources), sizeof(GLchar*)));
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(sources); i++) {
        PyObject *temp = PyTuple_GET_ITEM(sources, i);
        if (!PyUnicode_Check(temp)) { PyErr_SetString(PyExc_TypeError, "shaders must be strings"); return false; }
        c_sources[i] = PyUnicode_AsUTF8(temp);
    }
    GLuint shader_id = compile_shaders(shader_type, PyTuple_GET_SIZE(sources), c_sources);
    if (shader_id == 0) return false;
    glAttachShader(program_id, shader_id);
    glDeleteShader(shader_id);
    return true;
}

static PyObject*
compile_program(PyObject UNUSED *self, PyObject *args) {
    PyObject *vertex_shaders, *fragment_shaders;
    int which, allow_recompile = 0;
    if (!PyArg_ParseTuple(args, "iO!O!|p", &which, &PyTuple_Type, &vertex_shaders, &PyTuple_Type, &fragment_shaders, &allow_recompile)) return NULL;
    if (which < 0 || which >= NUM_PROGRAMS) { PyErr_Format(PyExc_ValueError, "Unknown program: %d", which); return NULL; }
    Program *program = program_ptr(which);
    if (program->id != 0) {
        if (allow_recompile) { glDeleteProgram(program->id); program->id = 0; }
        else { PyErr_SetString(PyExc_ValueError, "program already compiled"); return NULL; }
    }
#define fail_compile() { glDeleteProgram(program->id); return NULL; }
    program->id = glCreateProgram();
    if (!attach_shaders(vertex_shaders, program->id, GL_VERTEX_SHADER)) fail_compile();
    if (!attach_shaders(fragment_shaders, program->id, GL_FRAGMENT_SHADER)) fail_compile();
    glLinkProgram(program->id);
    GLint ret = GL_FALSE;
    glGetProgramiv(program->id, GL_LINK_STATUS, &ret);
    if (ret != GL_TRUE) {
        GLsizei len;
        static char glbuf[4096];
        glGetProgramInfoLog(program->id, sizeof(glbuf), &len, glbuf);
        PyErr_Format(PyExc_ValueError, "Failed to link GLSL shaders:\n%s", glbuf);
        fail_compile();
    }
#undef fail_compile
    init_uniforms(which);
    return Py_BuildValue("I", program->id);
}

#define PYWRAP0(name) static PyObject* py##name(PYNOARG)
#define PYWRAP1(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args)
#define PA(fmt, ...) if(!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;
#define ONE_INT(name) PYWRAP1(name) { name(PyLong_AsSsize_t(args)); Py_RETURN_NONE; }
#define TWO_INT(name) PYWRAP1(name) { int a, b; PA("ii", &a, &b); name(a, b); Py_RETURN_NONE; }
#define NO_ARG(name) PYWRAP0(name) { name(); Py_RETURN_NONE; }
#define NO_ARG_INT(name) PYWRAP0(name) { return PyLong_FromSsize_t(name()); }

ONE_INT(bind_program)
NO_ARG(unbind_program)

PYWRAP0(create_vao) {
    int ans = create_vao();
    if (ans < 0) return NULL;
    return Py_BuildValue("i", ans);
}

ONE_INT(bind_vertex_array)
NO_ARG(unbind_vertex_array)
TWO_INT(unmap_vao_buffer)

NO_ARG(init_borders_program)

NO_ARG(init_cell_program)

NO_ARG(init_trail_program)

static PyObject*
sprite_map_set_limits(PyObject UNUSED *self, PyObject *args) {
    unsigned int w, h;
    if(!PyArg_ParseTuple(args, "II", &w, &h)) return NULL;
    sprite_tracker_set_limits(w, h);
    max_texture_size = w; max_array_texture_layers = h;
    Py_RETURN_NONE;
}



#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, NULL}
#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}
static PyMethodDef module_methods[] = {
    M(compile_program, METH_VARARGS),
    M(sprite_map_set_limits, METH_VARARGS),
    MW(create_vao, METH_NOARGS),
    MW(bind_vertex_array, METH_O),
    MW(unbind_vertex_array, METH_NOARGS),
    MW(unmap_vao_buffer, METH_VARARGS),
    MW(bind_program, METH_O),
    MW(unbind_program, METH_NOARGS),
    MW(init_borders_program, METH_NOARGS),
    MW(init_cell_program, METH_NOARGS),
    MW(init_trail_program, METH_NOARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static void
finalize(void) {
    default_visual_bell_animation = free_animation(default_visual_bell_animation);
}

bool
init_shaders(PyObject *module) {
#define C(x) if (PyModule_AddIntConstant(module, #x, x) != 0) { PyErr_NoMemory(); return false; }
    C(CELL_PROGRAM); C(CELL_TRANSPARENT_PROGRAM); C(CELL_LAYERS_PROGRAM); C(CELL_LAYERS_TRANSPARENT_PROGRAM);
    C(BORDERS_PROGRAM); C(GRAPHICS_PROGRAM); C(GRAPHICS_ALPHA_MASK_PROGRAM); C(BGIMAGE_PROGRAM); C(TINT_PROGRAM); C(TRAIL_PROGRAM);
    C(GLSL_VERSION);
    C(GL_VERSION);
    C(GL_VENDOR);
    C(GL_SHADING_LANGUAGE_VERSION);
    C(GL_RENDERER);
    C(GL_TRIANGLE_FAN); C(GL_TRIANGLE_STRIP); C(GL_TRIANGLES); C(GL_LINE_LOOP);
    C(GL_COLOR_BUFFER_BIT);
    C(GL_VERTEX_SHADER);
    C(GL_FRAGMENT_SHADER);
    C(GL_TRUE);
    C(GL_FALSE);
    C(GL_COMPILE_STATUS);
    C(GL_LINK_STATUS);
    C(GL_MAX_ARRAY_TEXTURE_LAYERS); C(GL_TEXTURE_BINDING_BUFFER); C(GL_MAX_TEXTURE_BUFFER_SIZE);
    C(GL_MAX_TEXTURE_SIZE);
    C(GL_TEXTURE_2D_ARRAY);
    C(GL_LINEAR); C(GL_CLAMP_TO_EDGE); C(GL_NEAREST);
    C(GL_TEXTURE_MIN_FILTER); C(GL_TEXTURE_MAG_FILTER);
    C(GL_TEXTURE_WRAP_S); C(GL_TEXTURE_WRAP_T);
    C(GL_UNPACK_ALIGNMENT);
    C(GL_R8); C(GL_RED); C(GL_UNSIGNED_BYTE); C(GL_UNSIGNED_SHORT); C(GL_R32UI); C(GL_RGB32UI); C(GL_RGBA);
    C(GL_TEXTURE_BUFFER); C(GL_STATIC_DRAW); C(GL_STREAM_DRAW); C(GL_DYNAMIC_DRAW);
    C(GL_SRC_ALPHA); C(GL_ONE_MINUS_SRC_ALPHA);
    C(GL_WRITE_ONLY); C(GL_READ_ONLY); C(GL_READ_WRITE);
    C(GL_BLEND); C(GL_FLOAT); C(GL_UNSIGNED_INT); C(GL_ARRAY_BUFFER); C(GL_UNIFORM_BUFFER);

#undef C
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    register_at_exit_cleanup_func(SHADERS_CLEANUP_FUNC, finalize);
    return true;
}
// }}}
