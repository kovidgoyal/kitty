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

#define BLEND_ONTO_OPAQUE  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);  // blending onto opaque colors
#define BLEND_ONTO_OPAQUE_WITH_OPAQUE_OUTPUT  glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ZERO, GL_ONE);  // blending onto opaque colors with final color having alpha 1
#define BLEND_PREMULT glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);  // blending of pre-multiplied colors

enum { CELL_PROGRAM, CELL_BG_PROGRAM, CELL_SPECIAL_PROGRAM, CELL_FG_PROGRAM, BORDERS_PROGRAM, GRAPHICS_PROGRAM, GRAPHICS_PREMULT_PROGRAM, GRAPHICS_ALPHA_MASK_PROGRAM, BGIMAGE_PROGRAM, TINT_PROGRAM, TRAIL_PROGRAM, NUM_PROGRAMS };
enum { SPRITE_MAP_UNIT, GRAPHICS_UNIT, BGIMAGE_UNIT, SPRITE_DECORATIONS_MAP_UNIT };

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

typedef struct CellRenderData {
    struct {
        GLfloat xstart, ystart, dx, dy, width, height;
    } gl;
    float x_ratio, y_ratio;
} CellRenderData;

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
    for (int i = CELL_PROGRAM; i < BORDERS_PROGRAM; i++) {
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
    for (int p = CELL_PROGRAM; p < BORDERS_PROGRAM; p++) {
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

static void
cell_update_uniform_block(ssize_t vao_idx, Screen *screen, int uniform_buffer, const CellRenderData *crd, CursorRenderInfo *cursor, OSWindow *os_window) {
    struct GPUCellRenderData {
        GLfloat xstart, ystart, dx, dy, use_cell_bg_for_selection_fg, use_cell_fg_for_selection_color, use_cell_for_selection_bg;

        GLuint default_fg, highlight_fg, highlight_bg, cursor_fg, cursor_bg, url_color, url_style, inverted;

        GLuint xnum, ynum, sprites_xnum, sprites_ynum, cursor_fg_sprite_idx, cell_height;
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
#define SETBG(which) colorprofile_to_transparent_color(cp, which - 1, &rd->bg_colors##which, &rd->bg_opacities##which)
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

    rd->xnum = screen->columns; rd->ynum = screen->lines;

    rd->xstart = crd->gl.xstart; rd->ystart = crd->gl.ystart; rd->dx = crd->gl.dx; rd->dy = crd->gl.dy;
    unsigned int x, y, z;
    sprite_tracker_current_layout(os_window->fonts_data, &x, &y, &z);
    rd->sprites_xnum = x; rd->sprites_ynum = y;
    rd->inverted = screen_invert_colors(screen) ? 1 : 0;
    rd->cell_height = os_window->fonts_data->fcm.cell_height;

#undef COLOR
    rd->url_color = OPT(url_color); rd->url_style = OPT(url_style);

    unmap_vao_buffer(vao_idx, uniform_buffer); rd = NULL;
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
draw_background_image(OSWindow *w) {
    blank_canvas(w->is_semi_transparent ? OPT(background_opacity) : 1.0f, OPT(background));
    bind_program(BGIMAGE_PROGRAM);

    glUniform1i(bgimage_program_layout.uniforms.image, BGIMAGE_UNIT);
    glUniform1f(bgimage_program_layout.uniforms.opacity, OPT(background_opacity));
#ifdef __APPLE__
    int window_width = w->window_width, window_height = w->window_height;
#else
    int window_width = w->viewport_width, window_height = w->viewport_height;
#endif
    GLfloat iwidth = (GLfloat)w->bgimage->width;
    GLfloat iheight = (GLfloat)w->bgimage->height;
    GLfloat vwidth = (GLfloat)window_width;
    GLfloat vheight = (GLfloat)window_height;
    if (CENTER_SCALED == OPT(background_image_layout)) {
        GLfloat ifrac = iwidth / iheight;
        if (ifrac > (vwidth / vheight)) {
            iheight = vheight;
            iwidth = iheight * ifrac;
        } else {
            iwidth = vwidth;
            iheight = iwidth / ifrac;
        }
    }
    glUniform4f(bgimage_program_layout.uniforms.sizes,
        vwidth, vheight, iwidth, iheight);
    glUniform1f(bgimage_program_layout.uniforms.premult, w->is_semi_transparent ? 1.f : 0.f);
    GLfloat tiled = 0.f;;
    GLfloat left = -1.0, top = 1.0, right = 1.0, bottom = -1.0;
    switch (OPT(background_image_layout)) {
        case TILING: case MIRRORED: case CLAMPED:
            tiled = 1.f; break;
        case SCALED:
            break;
        case CENTER_CLAMPED:
        case CENTER_SCALED: {
            GLfloat wfrac = (vwidth - iwidth) / vwidth;
            GLfloat hfrac = (vheight - iheight) / vheight;
            left += wfrac;
            right -= wfrac;
            top -= hfrac;
            bottom += hfrac;
        } break;
    }
    glUniform1f(bgimage_program_layout.uniforms.tiled, tiled);
    glUniform4f(bgimage_program_layout.uniforms.positions, left, top, right, bottom);
    glActiveTexture(GL_TEXTURE0 + BGIMAGE_UNIT);
    glBindTexture(GL_TEXTURE_2D, w->bgimage->texture_id);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    unbind_program();
}

static void
draw_graphics(int program, ssize_t vao_idx, ImageRenderData *data, GLuint start, GLuint count, ImageRect viewport) {
    bind_program(program);
    glActiveTexture(GL_TEXTURE0 + GRAPHICS_UNIT);
    GraphicsUniforms *u = &graphics_program_layouts[program].uniforms;
    glUniform4f(u->viewport, viewport.left, viewport.top, viewport.right, viewport.bottom);
    glEnable(GL_CLIP_DISTANCE0); glEnable(GL_CLIP_DISTANCE1); glEnable(GL_CLIP_DISTANCE2); glEnable(GL_CLIP_DISTANCE3);
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
    glDisable(GL_CLIP_DISTANCE0); glDisable(GL_CLIP_DISTANCE1); glDisable(GL_CLIP_DISTANCE2); glDisable(GL_CLIP_DISTANCE3);
    bind_vertex_array(vao_idx);
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
    draw_graphics(GRAPHICS_ALPHA_MASK_PROGRAM, 0, data, 0, 1, (ImageRect){-1, 1, 1, -1});
    glDisable(GL_BLEND);
}

static ImageRect
viewport_for_cells(const CellRenderData *crd) {
    return (ImageRect){crd->gl.xstart, crd->gl.ystart, crd->gl.xstart + crd->gl.width, crd->gl.ystart - crd->gl.height};
}

static void
draw_cells_simple(ssize_t vao_idx, Screen *screen, const CellRenderData *crd, GraphicsRenderData grd, bool is_semi_transparent) {
    bind_program(CELL_PROGRAM);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    if (grd.count) {
        glEnable(GL_BLEND);
        int program = GRAPHICS_PROGRAM;
        if (is_semi_transparent) { BLEND_PREMULT; program = GRAPHICS_PREMULT_PROGRAM; } else { BLEND_ONTO_OPAQUE; }
        draw_graphics(program, vao_idx, grd.images, 0, grd.count, viewport_for_cells(crd));
        glDisable(GL_BLEND);
    }
}

static bool
has_bgimage(OSWindow *w) {
    return w->bgimage && w->bgimage->texture_id > 0;
}

static void
draw_tint(bool premult, Screen *screen, const CellRenderData *crd) {
    if (premult) { BLEND_PREMULT } else { BLEND_ONTO_OPAQUE_WITH_OPAQUE_OUTPUT }
    bind_program(TINT_PROGRAM);
    color_type window_bg = colorprofile_to_color(screen->color_profile, screen->color_profile->overridden.default_bg, screen->color_profile->configured.default_bg).rgb;
#define C(shift) srgb_color((window_bg >> shift) & 0xFF) * premult_factor
    GLfloat premult_factor = premult ? OPT(background_tint) : 1.0f;
    glUniform4f(tint_program_layout.uniforms.tint_color, C(16), C(8), C(0), OPT(background_tint));
#undef C
    glUniform4f(tint_program_layout.uniforms.edges, crd->gl.xstart, crd->gl.ystart - crd->gl.height, crd->gl.xstart + crd->gl.width, crd->gl.ystart);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
}

static bool
draw_scroll_indicator(bool premult, Screen *screen, const CellRenderData *crd) {
    if (OPT(scrollback_indicator_opacity) <= 0 || screen->linebuf != screen->main_linebuf || !screen->scrolled_by) return false;
    glEnable(GL_BLEND);
    if (premult) { BLEND_PREMULT } else { BLEND_ONTO_OPAQUE }
    bind_program(TINT_PROGRAM);
    const color_type bar_color = colorprofile_to_color(screen->color_profile, screen->color_profile->overridden.highlight_bg, screen->color_profile->configured.highlight_bg).rgb;
    GLfloat alpha = OPT(scrollback_indicator_opacity);
    float frac = (float)screen->scrolled_by / (float)screen->historybuf->count;
    const GLfloat bar_height = crd->gl.dy;
    GLfloat bottom = (crd->gl.ystart - crd->gl.height);
    bottom += MAX(0, crd->gl.height - bar_height) * frac;
#define C(shift) srgb_color((bar_color >> shift) & 0xFF) * premult_factor
    GLfloat premult_factor = premult ? alpha : 1.0f;
    glUniform4f(tint_program_layout.uniforms.tint_color, C(16), C(8), C(0), alpha);
#undef C
    GLfloat width = 0.5f * crd->gl.dx;
    GLfloat left = (GLfloat)(crd->gl.xstart + (screen->columns * crd->gl.dx - width));
    glUniform4f(tint_program_layout.uniforms.edges, left, bottom, left + width, bottom + bar_height);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    glDisable(GL_BLEND);
    return true;
}


static float prev_inactive_text_alpha = -1;

static void
set_cell_uniforms(float current_inactive_text_alpha, bool force) {
    static bool constants_set = false;
    if (!constants_set || force) {
        float text_contrast = 1.0f + OPT(text_contrast) * 0.01f;
        float text_gamma_adjustment = OPT(text_gamma_adjustment) < 0.01f ? 1.0f : 1.0f / OPT(text_gamma_adjustment);

        for (int i = GRAPHICS_PROGRAM; i <= GRAPHICS_PREMULT_PROGRAM; i++) {
            bind_program(i); glUniform1i(graphics_program_layouts[i].uniforms.image, GRAPHICS_UNIT);
        }
        for (int i = CELL_PROGRAM; i <= CELL_FG_PROGRAM; i++) {
            bind_program(i); const CellUniforms *cu = &cell_program_layouts[i].uniforms;
            switch(i) {
                case CELL_PROGRAM: case CELL_FG_PROGRAM:
                    glUniform1i(cu->sprites, SPRITE_MAP_UNIT);
                    glUniform1i(cu->sprite_decorations_map, SPRITE_DECORATIONS_MAP_UNIT);
                    glUniform1f(cu->dim_opacity, OPT(dim_opacity));
                    glUniform1f(cu->text_contrast, text_contrast);
                    glUniform1f(cu->text_gamma_adjustment, text_gamma_adjustment);
                    break;
            }
        }
        constants_set = true;
    }
    if (current_inactive_text_alpha != prev_inactive_text_alpha || force) {
        prev_inactive_text_alpha = current_inactive_text_alpha;
        for (int i = GRAPHICS_PROGRAM; i <= GRAPHICS_PREMULT_PROGRAM; i++) {
            bind_program(i); glUniform1f(graphics_program_layouts[i].uniforms.inactive_text_alpha, current_inactive_text_alpha);
        }
#define S(prog, loc) bind_program(prog); glUniform1f(cell_program_layouts[prog].uniforms.inactive_text_alpha, current_inactive_text_alpha);
        S(CELL_PROGRAM, cploc); S(CELL_FG_PROGRAM, cfploc);
#undef S
    }
}

static GLfloat
render_a_bar(OSWindow *os_window, Screen *screen, const CellRenderData *crd, WindowBarData *bar, PyObject *title, bool along_bottom) {
    GLfloat left = os_window->viewport_width * (crd->gl.xstart + 1.f) / 2.f;
    GLfloat right = left + os_window->viewport_width * crd->gl.width / 2.f;
    unsigned bar_height = os_window->fonts_data->fcm.cell_height + 2;
    if (!bar_height || right <= left) return 0;
    unsigned bar_width = (unsigned)ceilf(right - left);
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
#define RGBCOL(which, fallback) ( 0xff000000 | colorprofile_to_color_with_fallback(screen->color_profile, screen->color_profile->overridden.which, screen->color_profile->configured.which, screen->color_profile->overridden.fallback, screen->color_profile->configured.fallback))
        if (!draw_window_title(os_window, titlebuf, RGBCOL(highlight_fg, default_fg), RGBCOL(highlight_bg, default_bg), bar->buf, bar_width, bar_height)) return 0;
#undef RGBCOL
        Py_CLEAR(bar->last_drawn_title_object_id);
        bar->last_drawn_title_object_id = title;
        Py_INCREF(bar->last_drawn_title_object_id);
    }
    static ImageRenderData data = {.group_count=1};
    GLfloat xstart, ystart;
    xstart = clamp_position_to_nearest_pixel(crd->gl.xstart, os_window->viewport_width);
    GLfloat height_gl = gl_size(bar_height, os_window->viewport_height);
    if (along_bottom) ystart = crd->gl.ystart - crd->gl.height + height_gl;
    else ystart = clamp_position_to_nearest_pixel(crd->gl.ystart, os_window->viewport_height);
    gpu_data_for_image(&data, xstart, ystart, xstart + crd->gl.width, ystart - height_gl);
    if (!data.texture_id) { glGenTextures(1, &data.texture_id); }
    glBindTexture(GL_TEXTURE_2D, data.texture_id);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, GL_SRGB_ALPHA, bar_width, bar_height, 0, GL_RGBA, GL_UNSIGNED_BYTE, bar->buf);
    set_cell_uniforms(1.f, false);
    bind_program(GRAPHICS_PROGRAM);
    glEnable(GL_BLEND);
    if (os_window->is_semi_transparent) { BLEND_PREMULT; } else { BLEND_ONTO_OPAQUE; }
    draw_graphics(GRAPHICS_PROGRAM, 0, &data, 0, 1, viewport_for_cells(crd));
    glDisable(GL_BLEND);
    return height_gl;
}

static void
draw_hyperlink_target(OSWindow *os_window, Screen *screen, const CellRenderData *crd, Window *window) {
    WindowBarData *bd = &window->url_target_bar_data;
    if (bd->hyperlink_id_for_title_object != screen->current_hyperlink_under_mouse.id) {
        bd->hyperlink_id_for_title_object = screen->current_hyperlink_under_mouse.id;
        Py_CLEAR(bd->last_drawn_title_object_id);
        const char *url = get_hyperlink_for_id(screen->hyperlink_pool, bd->hyperlink_id_for_title_object, true);
        if (url == NULL) url = "";
        bd->last_drawn_title_object_id = PyObject_CallMethod(global_state.boss, "sanitize_url_for_dispay_to_user", "s", url);
        if (bd->last_drawn_title_object_id == NULL) { PyErr_Print(); return; }
        bd->needs_render = true;
    }
    if (bd->last_drawn_title_object_id == NULL) return;
    const bool along_bottom = screen->current_hyperlink_under_mouse.y < 3;
    PyObject *ref = bd->last_drawn_title_object_id;
    Py_INCREF(ref);
    render_a_bar(os_window, screen, crd, &window->title_bar_data, bd->last_drawn_title_object_id, along_bottom);
    Py_DECREF(ref);
}

static void
draw_window_logo(ssize_t vao_idx, OSWindow *os_window, const WindowLogoRenderData *wl, const CellRenderData *crd) {
    if (os_window->live_resize.in_progress) return;
    BLEND_PREMULT;
    GLfloat logo_width_gl = gl_size(wl->instance->width, os_window->viewport_width);
    GLfloat logo_height_gl = gl_size(wl->instance->height, os_window->viewport_height);

    if (OPT(window_logo_scale.width) > 0 || OPT(window_logo_scale.height) > 0) {
        unsigned int scaled_wl_width = os_window->viewport_width;
        unsigned int scaled_wl_height = os_window->viewport_height;

        // [sx] Scales logo to sx % of the viewports shortest dimension, preserving aspect ratio
        if (OPT(window_logo_scale.height) < 0) {
            if (os_window->viewport_height < os_window->viewport_width) {
                scaled_wl_height = (int)(os_window->viewport_height * OPT(window_logo_scale.width) / 100);
                scaled_wl_width = wl->instance->width * scaled_wl_height / wl->instance->height;
            } else {
                scaled_wl_width = (int)(os_window->viewport_width * OPT(window_logo_scale.width) / 100);
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

        logo_height_gl = gl_size(scaled_wl_height, os_window->viewport_height);
        logo_width_gl = gl_size(scaled_wl_width, os_window->viewport_width);
    }

    GLfloat logo_left_gl = clamp_position_to_nearest_pixel(
            crd->gl.xstart + crd->gl.width * wl->position.canvas_x - logo_width_gl * wl->position.image_x, os_window->viewport_width);
    GLfloat logo_top_gl = clamp_position_to_nearest_pixel(
            crd->gl.ystart - crd->gl.height * wl->position.canvas_y + logo_height_gl * wl->position.image_y, os_window->viewport_height);
    static ImageRenderData ird = {.group_count=1};
    ird.texture_id = wl->instance->texture_id;
    gpu_data_for_image(&ird, logo_left_gl, logo_top_gl, logo_left_gl + logo_width_gl, logo_top_gl - logo_height_gl);
    bind_program(GRAPHICS_PREMULT_PROGRAM);
    glUniform1f(graphics_program_layouts[GRAPHICS_PREMULT_PROGRAM].uniforms.inactive_text_alpha, prev_inactive_text_alpha * wl->alpha);
    draw_graphics(GRAPHICS_PREMULT_PROGRAM, vao_idx, &ird, 0, 1, viewport_for_cells(crd));
    glUniform1f(graphics_program_layouts[GRAPHICS_PREMULT_PROGRAM].uniforms.inactive_text_alpha, prev_inactive_text_alpha);
}

static void
draw_window_number(OSWindow *os_window, Screen *screen, const CellRenderData *crd, Window *window) {
    GLfloat left = os_window->viewport_width * (crd->gl.xstart + 1.f) / 2.f;
    GLfloat right = left + os_window->viewport_width * crd->gl.width / 2.f;
    GLfloat title_bar_height = 0;
    size_t requested_height = (size_t)(os_window->viewport_height * crd->gl.height / 2.f);
    if (window->title && PyUnicode_Check(window->title) && (requested_height > (os_window->fonts_data->fcm.cell_height + 1) * 2)) {
        title_bar_height = render_a_bar(os_window, screen, crd, &window->title_bar_data, window->title, false);
    }
    GLfloat ystart = crd->gl.ystart, height = crd->gl.height, xstart = crd->gl.xstart, width = crd->gl.width;
    if (title_bar_height > 0) {
        ystart -= title_bar_height;
        height -= title_bar_height;
    }
    ystart -= crd->gl.dy / 2.f; height -= crd->gl.dy;  // top and bottom margins
    xstart += crd->gl.dx / 2.f; width -= crd->gl.dx;  // left and right margins
    GLfloat height_gl = MIN(MIN(12 * crd->gl.dy, height), width);
    requested_height = (size_t)(os_window->viewport_height * height_gl / 2.f);
    if (requested_height < 4) return;
#define lr screen->last_rendered_window_char
    if (!lr.canvas || lr.ch != screen->display_window_char || lr.requested_height != requested_height) {
        free(lr.canvas); lr.canvas = NULL;
        lr.requested_height = requested_height; lr.height_px = requested_height; lr.ch = 0;
        lr.canvas = draw_single_ascii_char(screen->display_window_char, &lr.width_px, &lr.height_px);
        if (lr.height_px < 4 || lr.width_px < 4 || !lr.canvas) return;
        lr.ch = screen->display_window_char;
    }

    GLfloat width_gl = gl_size(lr.width_px, os_window->viewport_width);
    height_gl = gl_size(lr.height_px, os_window->viewport_height);
    left = xstart + (width - width_gl) / 2.f;
    left = clamp_position_to_nearest_pixel(left, os_window->viewport_width);
    right = left + width_gl;
    GLfloat top = ystart - (height - height_gl) / 2.f;
    top = clamp_position_to_nearest_pixel(top, os_window->viewport_height);
    GLfloat bottom = top - height_gl;
    bind_program(GRAPHICS_ALPHA_MASK_PROGRAM);
    ImageRenderData *ird = load_alpha_mask_texture(lr.width_px, lr.height_px, lr.canvas);
#undef lr
    gpu_data_for_image(ird, left, top, right, bottom);
    glEnable(GL_BLEND);
    BLEND_PREMULT;
    glUniform1i(graphics_program_layouts[GRAPHICS_ALPHA_MASK_PROGRAM].uniforms.image, GRAPHICS_UNIT);
    color_type digit_color = colorprofile_to_color_with_fallback(screen->color_profile, screen->color_profile->overridden.highlight_bg, screen->color_profile->configured.highlight_bg, screen->color_profile->overridden.default_fg, screen->color_profile->configured.default_fg);
    color_vec3(graphics_program_layouts[GRAPHICS_ALPHA_MASK_PROGRAM].uniforms.amask_fg, digit_color);
    glUniform4f(graphics_program_layouts[GRAPHICS_ALPHA_MASK_PROGRAM].uniforms.amask_bg_premult, 0.f, 0.f, 0.f, 0.f);
    draw_graphics(GRAPHICS_ALPHA_MASK_PROGRAM, 0, ird, 0, 1, viewport_for_cells(crd));
    glDisable(GL_BLEND);
}

static void
draw_visual_bell_flash(GLfloat intensity, const CellRenderData *crd, Screen *screen) {
    glEnable(GL_BLEND);
    // BLEND_PREMULT
    glBlendFuncSeparate(GL_ONE, GL_ONE_MINUS_SRC_ALPHA, GL_ZERO, GL_ONE);
    bind_program(TINT_PROGRAM);
    GLfloat attenuation = 0.4f;
#define COLOR(name, fallback) colorprofile_to_color_with_fallback(screen->color_profile, screen->color_profile->overridden.name, screen->color_profile->configured.name, screen->color_profile->overridden.fallback, screen->color_profile->configured.fallback)
    const color_type flash = !IS_SPECIAL_COLOR(highlight_bg) ? COLOR(visual_bell_color, highlight_bg) : COLOR(visual_bell_color, default_fg);
#undef COLOR
#define C(shift) srgb_color((flash >> shift) & 0xFF)
    const GLfloat r = C(16), g = C(8), b = C(0);
    const GLfloat max_channel = r > g ? (r > b ? r : b) : (g > b ? g : b);
#undef C
#define C(x) (x * intensity * attenuation)
    if (max_channel > 0.45) attenuation = 0.6f;  // light color
    glUniform4f(tint_program_layout.uniforms.tint_color, C(r), C(g), C(b), C(1));
#undef C
    glUniform4f(tint_program_layout.uniforms.edges, crd->gl.xstart, crd->gl.ystart - crd->gl.height, crd->gl.xstart + crd->gl.width, crd->gl.ystart);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    glDisable(GL_BLEND);
}

static void
draw_cells_interleaved(ssize_t vao_idx, Screen *screen, OSWindow *w, const CellRenderData *crd, GraphicsRenderData grd, const WindowLogoRenderData *wl) {
    glEnable(GL_BLEND);
    BLEND_ONTO_OPAQUE;

    // draw background for all cells
    if (!has_bgimage(w)) {
        bind_program(CELL_BG_PROGRAM);
        glUniform1ui(cell_program_layouts[CELL_BG_PROGRAM].uniforms.draw_bg_bitfield, 3);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    } else if (OPT(background_tint) > 0) {
        draw_tint(false, screen, crd);
        BLEND_ONTO_OPAQUE;
    }

    if (grd.num_of_below_refs || has_bgimage(w) || wl) {
        if (wl) {
            draw_window_logo(vao_idx, w, wl, crd);
            BLEND_ONTO_OPAQUE;
        }
        if (grd.num_of_below_refs) draw_graphics(
                GRAPHICS_PROGRAM, vao_idx, grd.images, 0, grd.num_of_below_refs, viewport_for_cells(crd));
        bind_program(CELL_BG_PROGRAM);
        // draw background for non-default bg cells
        glUniform1ui(cell_program_layouts[CELL_BG_PROGRAM].uniforms.draw_bg_bitfield, 2);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    }

    if (grd.num_of_negative_refs) draw_graphics(GRAPHICS_PROGRAM, vao_idx, grd.images, grd.num_of_below_refs, grd.num_of_negative_refs, viewport_for_cells(crd));

    bind_program(CELL_SPECIAL_PROGRAM);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);

    bind_program(CELL_FG_PROGRAM);
    BLEND_PREMULT;
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    BLEND_ONTO_OPAQUE;

    if (grd.num_of_positive_refs) draw_graphics(GRAPHICS_PROGRAM, vao_idx, grd.images, grd.num_of_negative_refs + grd.num_of_below_refs, grd.num_of_positive_refs, viewport_for_cells(crd));

    glDisable(GL_BLEND);
}

static void
draw_cells_interleaved_premult(ssize_t vao_idx, Screen *screen, OSWindow *os_window, const CellRenderData *crd, GraphicsRenderData grd, const WindowLogoRenderData *wl) {
    if (OPT(background_tint) > 0.f) {
        glEnable(GL_BLEND);
        draw_tint(true, screen, crd);
        glDisable(GL_BLEND);
    }
    bind_program(CELL_BG_PROGRAM);
    if (!has_bgimage(os_window)) {
        // draw background for all cells
        glUniform1ui(cell_program_layouts[CELL_BG_PROGRAM].uniforms.draw_bg_bitfield, 3);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    }
    glEnable(GL_BLEND);
    BLEND_PREMULT;

    if (grd.num_of_below_refs || has_bgimage(os_window) || wl) {
        if (wl) {
            draw_window_logo(vao_idx, os_window, wl, crd);
            BLEND_PREMULT;
        }
        if (grd.num_of_below_refs) draw_graphics(
            GRAPHICS_PREMULT_PROGRAM, vao_idx, grd.images, 0, grd.num_of_below_refs, viewport_for_cells(crd));
        bind_program(CELL_BG_PROGRAM);
        // Draw background for non-default bg cells
        glUniform1ui(cell_program_layouts[CELL_BG_PROGRAM].uniforms.draw_bg_bitfield, 2);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    } else {
        // Apply background_opacity
        glUniform1ui(cell_program_layouts[CELL_BG_PROGRAM].uniforms.draw_bg_bitfield, 0);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    }

    if (grd.num_of_negative_refs) {
        draw_graphics(GRAPHICS_PREMULT_PROGRAM, vao_idx, grd.images, grd.num_of_below_refs, grd.num_of_negative_refs, viewport_for_cells(crd));
    }

    bind_program(CELL_SPECIAL_PROGRAM);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);

    bind_program(CELL_FG_PROGRAM);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);

    if (grd.num_of_positive_refs) draw_graphics(GRAPHICS_PREMULT_PROGRAM, vao_idx, grd.images, grd.num_of_negative_refs + grd.num_of_below_refs, grd.num_of_positive_refs, viewport_for_cells(crd));

    glDisable(GL_BLEND);
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

void
draw_cells(ssize_t vao_idx, const WindowRenderData *srd, OSWindow *os_window, bool is_active_window, bool is_tab_bar, bool is_single_window, Window *window) {
    float x_ratio = 1., y_ratio = 1.;
    if (os_window->live_resize.in_progress) {
        x_ratio = (float) os_window->viewport_width / (float) os_window->live_resize.width;
        y_ratio = (float) os_window->viewport_height / (float) os_window->live_resize.height;
    }
    Screen *screen = srd->screen;
    CELL_BUFFERS;
    CellRenderData crd = {
        .gl={.xstart = srd->xstart, .ystart = srd->ystart, .dx = srd->dx * x_ratio, .dy = srd->dy * y_ratio},
        .x_ratio=x_ratio, .y_ratio=y_ratio
    };
    crd.gl.width = crd.gl.dx * screen->columns; crd.gl.height = crd.gl.dy * screen->lines;
    cell_update_uniform_block(vao_idx, screen, uniform_buffer, &crd, &screen->cursor_render_info, os_window);

    bind_vao_uniform_buffer(vao_idx, uniform_buffer, cell_program_layouts[CELL_PROGRAM].render_data.index);
    bind_vertex_array(vao_idx);

    // We draw with inactive text alpha if:
    // - We're not drawing the tab bar
    // - There's only a single window and the os window is not focused
    // - There are multiple windows and the current window is not active
    float current_inactive_text_alpha = is_tab_bar || (!is_single_window && is_active_window) || (is_single_window && screen->cursor_render_info.is_focused) ? 1.0f : (float)OPT(inactive_text_alpha);
    set_cell_uniforms(current_inactive_text_alpha, screen->reload_all_gpu_data);
    screen->reload_all_gpu_data = false;
    bool has_underlying_image = has_bgimage(os_window);
    WindowLogoRenderData *wl;
    if (window && (wl = &window->window_logo) && wl->id && (wl->instance = find_window_logo(global_state.all_window_logos, wl->id)) && wl->instance && wl->instance->load_from_disk_ok) {
        has_underlying_image = true;
        set_on_gpu_state(window->window_logo.instance, true);
    } else wl = NULL;
    ImageRenderData *scaled_render_data = NULL;
    GraphicsManager *grman = screen->paused_rendering.expires_at && screen->paused_rendering.grman ? screen->paused_rendering.grman : screen->grman;
    GraphicsRenderData grd = grman_render_data(grman);
    if (os_window->live_resize.in_progress && grd.count && (crd.x_ratio != 1 || crd.y_ratio != 1)) {
        scaled_render_data = malloc(sizeof(scaled_render_data[0]) * grd.count);
        if (scaled_render_data) {
            memcpy(scaled_render_data, grd.images, sizeof(scaled_render_data[0]) * grd.count);
            grd.images = scaled_render_data;
            for (size_t i = 0; i < grd.count; i++)
                scale_rendered_graphic(grd.images + i, srd->xstart, srd->ystart, crd.x_ratio, crd.y_ratio);
        }
    }
    bool use_premult = false;
    has_underlying_image |= grd.num_of_below_refs > 0 || grd.num_of_negative_refs > 0;
    if (os_window->is_semi_transparent) {
        if (has_underlying_image) { draw_cells_interleaved_premult(vao_idx, screen, os_window, &crd, grd, wl); use_premult = true; }
        else draw_cells_simple(vao_idx, screen, &crd, grd, os_window->is_semi_transparent);
    } else {
        if (has_underlying_image) draw_cells_interleaved(vao_idx, screen, os_window, &crd, grd, wl);
        else draw_cells_simple(vao_idx, screen, &crd, grd, os_window->is_semi_transparent);
    }
    draw_scroll_indicator(use_premult, screen, &crd);

    if (screen->start_visual_bell_at) {
        GLfloat intensity = get_visual_bell_intensity(screen);
        if (intensity > 0.0f) draw_visual_bell_flash(intensity, &crd, screen);
    }

    if (window && screen->display_window_char) draw_window_number(os_window, screen, &crd, window);
    if (OPT(show_hyperlink_targets) && window && screen->current_hyperlink_under_mouse.id && !is_mouse_hidden(os_window)) draw_hyperlink_target(os_window, screen, &crd, window);
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
    float tint_opacity = background_opacity;
    float tint_premult = background_opacity;
    bind_vertex_array(vao_idx);
    if (has_bgimage(w)) {
        glEnable(GL_BLEND);
        BLEND_ONTO_OPAQUE;
        draw_background_image(w);
        BLEND_ONTO_OPAQUE;
        background_opacity = 1.0f;
        tint_opacity = OPT(background_tint) * OPT(background_tint_gaps);
        tint_premult = w->is_semi_transparent ? OPT(background_tint) : 1.0f;
    }

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
        glUniform1f(border_program_layout.uniforms.tint_opacity, tint_opacity);
        glUniform1f(border_program_layout.uniforms.tint_premult, tint_premult);
        glUniform2ui(border_program_layout.uniforms.viewport, viewport_width, viewport_height);
        if (has_bgimage(w)) {
            if (w->is_semi_transparent) { BLEND_PREMULT; }
            else { BLEND_ONTO_OPAQUE_WITH_OPAQUE_OUTPUT; }
        }
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
    C(CELL_PROGRAM); C(CELL_BG_PROGRAM); C(CELL_SPECIAL_PROGRAM); C(CELL_FG_PROGRAM); C(BORDERS_PROGRAM); C(GRAPHICS_PROGRAM); C(GRAPHICS_PREMULT_PROGRAM); C(GRAPHICS_ALPHA_MASK_PROGRAM); C(BGIMAGE_PROGRAM); C(TINT_PROGRAM); C(TRAIL_PROGRAM);
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
    C(GL_TEXTURE0); C(GL_TEXTURE1); C(GL_TEXTURE2); C(GL_TEXTURE3); C(GL_TEXTURE4); C(GL_TEXTURE5); C(GL_TEXTURE6); C(GL_TEXTURE7); C(GL_TEXTURE8);
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
