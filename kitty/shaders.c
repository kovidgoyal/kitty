/*
 * shaders.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "fonts.h"
#include "gl.h"
#include "colors.h"
#include <stddef.h>
#include "window_logo.h"

#define BLEND_ONTO_OPAQUE  glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);  // blending onto opaque colors
#define BLEND_ONTO_OPAQUE_WITH_OPAQUE_OUTPUT  glBlendFuncSeparate(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA, GL_ZERO, GL_ONE);  // blending onto opaque colors with final color having alpha 1
#define BLEND_PREMULT glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);  // blending of pre-multiplied colors

enum { CELL_PROGRAM, CELL_BG_PROGRAM, CELL_SPECIAL_PROGRAM, CELL_FG_PROGRAM, BORDERS_PROGRAM, GRAPHICS_PROGRAM, GRAPHICS_PREMULT_PROGRAM, GRAPHICS_ALPHA_MASK_PROGRAM, BLIT_PROGRAM, BGIMAGE_PROGRAM, TINT_PROGRAM, NUM_PROGRAMS };
enum { SPRITE_MAP_UNIT, GRAPHICS_UNIT, BLIT_UNIT, BGIMAGE_UNIT };

// Sprites {{{
typedef struct {
    unsigned int cell_width, cell_height;
    int xnum, ynum, x, y, z, last_num_of_layers, last_ynum;
    GLuint texture_id;
    GLint max_texture_size, max_array_texture_layers;
} SpriteMap;

static const SpriteMap NEW_SPRITE_MAP = { .xnum = 1, .ynum = 1, .last_num_of_layers = 1, .last_ynum = -1 };
static GLint max_texture_size = 0, max_array_texture_layers = 0;

extern GLint texture_internal_format;

// Generated using gen-srgb-lut
const GLfloat srgb_lut[256] = {
    0.00000f, 0.00030f, 0.00061f, 0.00091f, 0.00121f, 0.00152f, 0.00182f, 0.00212f, 0.00243f, 0.00273f, 0.00304f, 0.00335f, 0.00368f, 0.00402f, 0.00439f, 0.00478f,
    0.00518f, 0.00561f, 0.00605f, 0.00651f, 0.00700f, 0.00750f, 0.00802f, 0.00857f, 0.00913f, 0.00972f, 0.01033f, 0.01096f, 0.01161f, 0.01229f, 0.01298f, 0.01370f,
    0.01444f, 0.01521f, 0.01600f, 0.01681f, 0.01764f, 0.01850f, 0.01938f, 0.02029f, 0.02122f, 0.02217f, 0.02315f, 0.02416f, 0.02519f, 0.02624f, 0.02732f, 0.02843f,
    0.02956f, 0.03071f, 0.03190f, 0.03310f, 0.03434f, 0.03560f, 0.03689f, 0.03820f, 0.03955f, 0.04092f, 0.04231f, 0.04374f, 0.04519f, 0.04667f, 0.04817f, 0.04971f,
    0.05127f, 0.05286f, 0.05448f, 0.05613f, 0.05781f, 0.05951f, 0.06125f, 0.06301f, 0.06480f, 0.06663f, 0.06848f, 0.07036f, 0.07227f, 0.07421f, 0.07619f, 0.07819f,
    0.08022f, 0.08228f, 0.08438f, 0.08650f, 0.08866f, 0.09084f, 0.09306f, 0.09531f, 0.09759f, 0.09990f, 0.10224f, 0.10462f, 0.10702f, 0.10946f, 0.11193f, 0.11444f,
    0.11697f, 0.11954f, 0.12214f, 0.12477f, 0.12744f, 0.13014f, 0.13287f, 0.13563f, 0.13843f, 0.14126f, 0.14413f, 0.14703f, 0.14996f, 0.15293f, 0.15593f, 0.15896f,
    0.16203f, 0.16513f, 0.16827f, 0.17144f, 0.17465f, 0.17789f, 0.18116f, 0.18447f, 0.18782f, 0.19120f, 0.19462f, 0.19807f, 0.20156f, 0.20508f, 0.20864f, 0.21223f,
    0.21586f, 0.21953f, 0.22323f, 0.22697f, 0.23074f, 0.23455f, 0.23840f, 0.24228f, 0.24620f, 0.25016f, 0.25415f, 0.25818f, 0.26225f, 0.26636f, 0.27050f, 0.27468f,
    0.27889f, 0.28315f, 0.28744f, 0.29177f, 0.29614f, 0.30054f, 0.30499f, 0.30947f, 0.31399f, 0.31855f, 0.32314f, 0.32778f, 0.33245f, 0.33716f, 0.34191f, 0.34670f,
    0.35153f, 0.35640f, 0.36131f, 0.36625f, 0.37124f, 0.37626f, 0.38133f, 0.38643f, 0.39157f, 0.39676f, 0.40198f, 0.40724f, 0.41254f, 0.41789f, 0.42327f, 0.42869f,
    0.43415f, 0.43966f, 0.44520f, 0.45079f, 0.45641f, 0.46208f, 0.46778f, 0.47353f, 0.47932f, 0.48515f, 0.49102f, 0.49693f, 0.50289f, 0.50888f, 0.51492f, 0.52100f,
    0.52712f, 0.53328f, 0.53948f, 0.54572f, 0.55201f, 0.55834f, 0.56471f, 0.57112f, 0.57758f, 0.58408f, 0.59062f, 0.59720f, 0.60383f, 0.61050f, 0.61721f, 0.62396f,
    0.63076f, 0.63760f, 0.64448f, 0.65141f, 0.65837f, 0.66539f, 0.67244f, 0.67954f, 0.68669f, 0.69387f, 0.70110f, 0.70838f, 0.71569f, 0.72306f, 0.73046f, 0.73791f,
    0.74540f, 0.75294f, 0.76052f, 0.76815f, 0.77582f, 0.78354f, 0.79130f, 0.79910f, 0.80695f, 0.81485f, 0.82279f, 0.83077f, 0.83880f, 0.84687f, 0.85499f, 0.86316f,
    0.87137f, 0.87962f, 0.88792f, 0.89627f, 0.90466f, 0.91310f, 0.92158f, 0.93011f, 0.93869f, 0.94731f, 0.95597f, 0.96469f, 0.97345f, 0.98225f, 0.99110f, 1.00000f
};

GLfloat
srgb_color(uint8_t color) {
    return srgb_lut[color];
}

void
color_vec3(GLint location, color_type color) {
	glUniform3f(location, srgb_lut[(color >> 16) & 0xFF], srgb_lut[(color >> 8) & 0xFF], srgb_lut[color & 0xFF]);
}

SPRITE_MAP_HANDLE
alloc_sprite_map(unsigned int cell_width, unsigned int cell_height) {
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
    ans->cell_width = cell_width; ans->cell_height = cell_height;
    return (SPRITE_MAP_HANDLE)ans;
}

SPRITE_MAP_HANDLE
free_sprite_map(SPRITE_MAP_HANDLE sm) {
    SpriteMap *sprite_map = (SpriteMap*)sm;
    if (sprite_map) {
        if (sprite_map->texture_id) free_texture(&sprite_map->texture_id);
        free(sprite_map);
    }
    return NULL;
}

static bool copy_image_warned = false;

static void
copy_image_sub_data(GLuint src_texture_id, GLuint dest_texture_id, unsigned int width, unsigned int height, unsigned int num_levels) {
    if (!GLAD_GL_ARB_copy_image) {
        // ARB_copy_image not available, do a slow roundtrip copy
        if (!copy_image_warned) {
            copy_image_warned = true;
            log_error("WARNING: Your system's OpenGL implementation does not have glCopyImageSubData, falling back to a slower implementation");
        }
        size_t sz = (size_t)width * height * num_levels;
        pixel *src = malloc(sz * sizeof(pixel));
        if (src == NULL) { fatal("Out of memory."); }
        glBindTexture(GL_TEXTURE_2D_ARRAY, src_texture_id);
        glGetTexImage(GL_TEXTURE_2D_ARRAY, 0, GL_RGBA, GL_UNSIGNED_BYTE, src);
        glBindTexture(GL_TEXTURE_2D_ARRAY, dest_texture_id);
        glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
        glTexSubImage3D(GL_TEXTURE_2D_ARRAY, 0, 0, 0, 0, width, height, num_levels, GL_RGBA, GL_UNSIGNED_BYTE, src);
        free(src);
    } else {
        glCopyImageSubData(src_texture_id, GL_TEXTURE_2D_ARRAY, 0, 0, 0, 0, dest_texture_id, GL_TEXTURE_2D_ARRAY, 0, 0, 0, 0, width, height, num_levels);
    }
}


static void
realloc_sprite_texture(FONTS_DATA_HANDLE fg) {
    GLuint tex;
    glGenTextures(1, &tex);
    glBindTexture(GL_TEXTURE_2D_ARRAY, tex);
    // We use GL_NEAREST otherwise glyphs that touch the edge of the cell
    // often show a border between cells
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    unsigned int xnum, ynum, z, znum, width, height, src_ynum;
    sprite_tracker_current_layout(fg, &xnum, &ynum, &z);
    znum = z + 1;
    SpriteMap *sprite_map = (SpriteMap*)fg->sprite_map;
    width = xnum * sprite_map->cell_width; height = ynum * sprite_map->cell_height;
    glTexStorage3D(GL_TEXTURE_2D_ARRAY, 1, GL_RGBA8, width, height, znum);
    if (sprite_map->texture_id) {
        // need to re-alloc
        src_ynum = MAX(1, sprite_map->last_ynum);
        copy_image_sub_data(sprite_map->texture_id, tex, width, src_ynum * sprite_map->cell_height, sprite_map->last_num_of_layers);
        glDeleteTextures(1, &sprite_map->texture_id);
    }
    glBindTexture(GL_TEXTURE_2D_ARRAY, 0);
    sprite_map->last_num_of_layers = znum;
    sprite_map->last_ynum = ynum;
    sprite_map->texture_id = tex;
}

static void
ensure_sprite_map(FONTS_DATA_HANDLE fg) {
    SpriteMap *sprite_map = (SpriteMap*)fg->sprite_map;
    if (!sprite_map->texture_id) realloc_sprite_texture(fg);
    // We have to rebind since we don't know if the texture was ever bound
    // in the context of the current OSWindow
    glActiveTexture(GL_TEXTURE0 + SPRITE_MAP_UNIT);
    glBindTexture(GL_TEXTURE_2D_ARRAY, sprite_map->texture_id);
}

void
send_sprite_to_gpu(FONTS_DATA_HANDLE fg, unsigned int x, unsigned int y, unsigned int z, pixel *buf) {
    SpriteMap *sprite_map = (SpriteMap*)fg->sprite_map;
    unsigned int xnum, ynum, znum;
    sprite_tracker_current_layout(fg, &xnum, &ynum, &znum);
    if ((int)znum >= sprite_map->last_num_of_layers || (znum == 0 && (int)ynum > sprite_map->last_ynum)) realloc_sprite_texture(fg);
    glBindTexture(GL_TEXTURE_2D_ARRAY, sprite_map->texture_id);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
    x *= sprite_map->cell_width; y *= sprite_map->cell_height;
    glTexSubImage3D(GL_TEXTURE_2D_ARRAY, 0, x, y, z, sprite_map->cell_width, sprite_map->cell_height, 1, GL_RGBA, GL_UNSIGNED_INT_8_8_8_8, buf);
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
    glTexImage2D(GL_TEXTURE_2D, 0, texture_internal_format, width, height, 0, is_opaque ? GL_RGB : GL_RGBA, GL_UNSIGNED_BYTE, data);
}

// }}}

// Cell {{{

typedef struct CellRenderData {
    struct {
        GLfloat xstart, ystart, dx, dy, width, height;
    } gl;
    struct {
        GLint xstart, ystart;
        GLsizei width, height;
    } px;
} CellRenderData;

typedef struct {
    UniformBlock render_data;
    ArrayInformation color_table;
    ArrayInformation gamma_lut;
    GLint draw_bg_bitfield_location;
} CellProgramLayout;

static CellProgramLayout cell_program_layouts[NUM_PROGRAMS];
static ssize_t blit_vertex_array;
typedef struct {
    GLint image_location, tiled_location, sizes_location, positions_location, opacity_location, premult_location;
} BGImageProgramLayout;
static BGImageProgramLayout bgimage_program_layout = {0};
typedef struct {
    GLint tint_color_location, edges_location;
} TintProgramLayout;
static TintProgramLayout tint_program_layout = {0};

static void
init_cell_program(void) {
    for (int i = CELL_PROGRAM; i < BORDERS_PROGRAM; i++) {
        cell_program_layouts[i].render_data.index = block_index(i, "CellRenderData");
        cell_program_layouts[i].render_data.size = block_size(i, cell_program_layouts[i].render_data.index);
        cell_program_layouts[i].color_table.size = get_uniform_information(i, "color_table[0]", GL_UNIFORM_SIZE);
        cell_program_layouts[i].color_table.offset = get_uniform_information(i, "color_table[0]", GL_UNIFORM_OFFSET);
        cell_program_layouts[i].color_table.stride = get_uniform_information(i, "color_table[0]", GL_UNIFORM_ARRAY_STRIDE);
        cell_program_layouts[i].gamma_lut.size = get_uniform_information(i, "gamma_lut[0]", GL_UNIFORM_SIZE);
        cell_program_layouts[i].gamma_lut.offset = get_uniform_information(i, "gamma_lut[0]", GL_UNIFORM_OFFSET);
        cell_program_layouts[i].gamma_lut.stride = get_uniform_information(i, "gamma_lut[0]", GL_UNIFORM_ARRAY_STRIDE);
    }
    cell_program_layouts[CELL_BG_PROGRAM].draw_bg_bitfield_location = get_uniform_location(CELL_BG_PROGRAM, "draw_bg_bitfield");
    // Sanity check to ensure the attribute location binding worked
#define C(p, name, expected) { int aloc = attrib_location(p, #name); if (aloc != expected && aloc != -1) fatal("The attribute location for %s is %d != %d in program: %d", #name, aloc, expected, p); }
    for (int p = CELL_PROGRAM; p < BORDERS_PROGRAM; p++) {
        C(p, colors, 0); C(p, sprite_coords, 1); C(p, is_selected, 2);
    }
#undef C
    blit_vertex_array = create_vao();
    bgimage_program_layout.image_location = get_uniform_location(BGIMAGE_PROGRAM, "image");
    bgimage_program_layout.opacity_location = get_uniform_location(BGIMAGE_PROGRAM, "opacity");
    bgimage_program_layout.sizes_location = get_uniform_location(BGIMAGE_PROGRAM, "sizes");
    bgimage_program_layout.positions_location = get_uniform_location(BGIMAGE_PROGRAM, "positions");
    bgimage_program_layout.tiled_location = get_uniform_location(BGIMAGE_PROGRAM, "tiled");
    bgimage_program_layout.premult_location = get_uniform_location(BGIMAGE_PROGRAM, "premult");
    tint_program_layout.tint_color_location = get_uniform_location(TINT_PROGRAM, "tint_color");
    tint_program_layout.edges_location = get_uniform_location(TINT_PROGRAM, "edges");
}

#define CELL_BUFFERS enum { cell_data_buffer, selection_buffer, uniform_buffer };

ssize_t
create_cell_vao() {
    ssize_t vao_idx = create_vao();
#define A(name, size, dtype, offset, stride) \
    add_attribute_to_vao(CELL_PROGRAM, vao_idx, #name, \
            /*size=*/size, /*dtype=*/dtype, /*stride=*/stride, /*offset=*/offset, /*divisor=*/1);
#define A1(name, size, dtype, offset) A(name, size, dtype, (void*)(offsetof(GPUCell, offset)), sizeof(GPUCell))

    add_buffer_to_vao(vao_idx, GL_ARRAY_BUFFER);
    A1(sprite_coords, 4, GL_UNSIGNED_SHORT, sprite_x);
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
create_graphics_vao() {
    ssize_t vao_idx = create_vao();
    add_buffer_to_vao(vao_idx, GL_ARRAY_BUFFER);
    add_attribute_to_vao(GRAPHICS_PROGRAM, vao_idx, "src", 4, GL_FLOAT, 0, NULL, 0);
    return vao_idx;
}

struct CellUniformData {
    bool constants_set;
    GLint gploc, gpploc, cploc, cfploc, fg_loc, amask_premult_loc, amask_fg_loc, amask_image_loc;
    GLfloat prev_inactive_text_alpha;
};

static struct CellUniformData cell_uniform_data = {0, .prev_inactive_text_alpha=-1};

static void
send_graphics_data_to_gpu(size_t image_count, ssize_t gvao_idx, const ImageRenderData *render_data) {
    size_t sz = sizeof(GLfloat) * 16 * image_count;
    GLfloat *a = alloc_and_map_vao_buffer(gvao_idx, sz, 0, GL_STREAM_DRAW, GL_WRITE_ONLY);
    for (size_t i = 0; i < image_count; i++, a += 16) memcpy(a, render_data[i].vertices, sizeof(render_data[0].vertices));
    unmap_vao_buffer(gvao_idx, 0); a = NULL;
}

#define IS_SPECIAL_COLOR(name) (screen->color_profile->overridden.name.type == COLOR_IS_SPECIAL || (screen->color_profile->overridden.name.type == COLOR_NOT_SET && screen->color_profile->configured.name.type == COLOR_IS_SPECIAL))

static void
pick_cursor_color(Line *line, ColorProfile *color_profile, color_type cell_fg, color_type cell_bg, index_type cell_color_x, color_type *cursor_fg, color_type *cursor_bg, color_type default_fg, color_type default_bg) {
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

void
copy_gamma_lut_to_buffer(const GLfloat* lut, GLfloat* buf, int offset, size_t stride) {
    size_t i;
    stride = MAX(1u, stride);

    for(i = 0, buf = buf + offset; i < 256; i++, buf += stride) *buf = lut[i];
}

static void
cell_update_uniform_block(ssize_t vao_idx, Screen *screen, int uniform_buffer, const CellRenderData *crd, CursorRenderInfo *cursor, bool inverted, OSWindow *os_window) {
    struct GPUCellRenderData {
        GLfloat xstart, ystart, dx, dy, sprite_dx, sprite_dy, background_opacity, use_cell_bg_for_selection_fg, use_cell_fg_for_selection_color, use_cell_for_selection_bg;

        GLuint default_fg, default_bg, highlight_fg, highlight_bg, cursor_fg, cursor_bg, url_color, url_style, inverted;

        GLuint xnum, ynum, cursor_fg_sprite_idx;
        GLfloat cursor_x, cursor_y, cursor_w;
    };
    // Send the uniform data
    struct GPUCellRenderData *rd = (struct GPUCellRenderData*)map_vao_buffer(vao_idx, uniform_buffer, GL_WRITE_ONLY);
    if (UNLIKELY(screen->color_profile->dirty || screen->reload_all_gpu_data)) {
        copy_color_table_to_buffer(screen->color_profile, (GLuint*)rd, cell_program_layouts[CELL_PROGRAM].color_table.offset / sizeof(GLuint), cell_program_layouts[CELL_PROGRAM].color_table.stride / sizeof(GLuint));
        copy_gamma_lut_to_buffer(srgb_lut, (GLfloat*)rd, cell_program_layouts[CELL_PROGRAM].gamma_lut.offset / sizeof(GLfloat), cell_program_layouts[CELL_PROGRAM].gamma_lut.stride / sizeof(GLfloat));
    }
#define COLOR(name) colorprofile_to_color(screen->color_profile, screen->color_profile->overridden.name, screen->color_profile->configured.name).rgb
    rd->default_fg = COLOR(default_fg); rd->default_bg = COLOR(default_bg);
    rd->highlight_fg = COLOR(highlight_fg); rd->highlight_bg = COLOR(highlight_bg);
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
    enum { BLOCK_IDX = 0, BEAM_IDX = NUM_UNDERLINE_STYLES + 3, UNDERLINE_IDX = NUM_UNDERLINE_STYLES + 4, UNFOCUSED_IDX = NUM_UNDERLINE_STYLES + 5 };
    if (cursor->is_visible) {
        rd->cursor_x = screen->cursor->x, rd->cursor_y = screen->cursor->y;
        if (cursor->is_focused) {
            switch(cursor->shape) {
                default:
                    rd->cursor_fg_sprite_idx = BLOCK_IDX; break;
                case CURSOR_BEAM:
                    rd->cursor_fg_sprite_idx = BEAM_IDX; break;
                case CURSOR_UNDERLINE:
                    rd->cursor_fg_sprite_idx = UNDERLINE_IDX; break;
            }
        } else rd->cursor_fg_sprite_idx = UNFOCUSED_IDX;
        color_type cell_fg = rd->default_fg, cell_bg = rd->default_bg;
        index_type cell_color_x = screen->cursor->x;
        bool cursor_ok = screen->cursor->x < screen->columns && screen->cursor->y < screen->lines;
        if (cursor_ok) {
            linebuf_init_line(screen->linebuf, screen->cursor->y);
            colors_for_cell(screen->linebuf->line, screen->color_profile, &cell_color_x, &cell_fg, &cell_bg);
        }
        if (screen->color_profile->overridden.cursor_color.type == COLOR_IS_INDEX || screen->color_profile->overridden.cursor_color.type == COLOR_IS_RGB) {
            // since the program is controlling the cursor color we hope it has chosen one
            // that has good contrast with the text color of the cell
            rd->cursor_fg = cell_fg; rd->cursor_bg = COLOR(cursor_color);
        } else if (IS_SPECIAL_COLOR(cursor_color)) {
            if (cursor_ok) pick_cursor_color(screen->linebuf->line, screen->color_profile, cell_fg, cell_bg, cell_color_x, &rd->cursor_fg, &rd->cursor_bg, rd->default_fg, rd->default_bg);
            else { rd->cursor_fg = rd->default_bg; rd->cursor_bg = rd->default_fg; }
            if (cell_bg == cell_fg) {
                rd->cursor_fg = rd->default_bg; rd->cursor_bg = rd->default_fg;
            } else { rd->cursor_fg = cell_bg; rd->cursor_bg = cell_fg; }
        } else {
            rd->cursor_bg = COLOR(cursor_color);
            if (IS_SPECIAL_COLOR(cursor_text_color)) rd->cursor_fg = cell_bg;
            else rd->cursor_fg = COLOR(cursor_text_color);
        }
    } else rd->cursor_x = screen->columns, rd->cursor_y = screen->lines;
    rd->cursor_w = rd->cursor_x;
    if (
            (rd->cursor_fg_sprite_idx == BLOCK_IDX || rd->cursor_fg_sprite_idx == UNDERLINE_IDX) &&
            screen_current_char_width(screen) > 1
    ) rd->cursor_w += 1;

    rd->xnum = screen->columns; rd->ynum = screen->lines;

    rd->xstart = crd->gl.xstart; rd->ystart = crd->gl.ystart; rd->dx = crd->gl.dx; rd->dy = crd->gl.dy;
    unsigned int x, y, z;
    sprite_tracker_current_layout(os_window->fonts_data, &x, &y, &z);
    rd->sprite_dx = 1.0f / (float)x; rd->sprite_dy = 1.0f / (float)y;
    rd->inverted = inverted ? 1 : 0;
    rd->background_opacity = os_window->is_semi_transparent ? os_window->background_opacity : 1.0f;

#undef COLOR
    rd->url_color = OPT(url_color); rd->url_style = OPT(url_style);

    unmap_vao_buffer(vao_idx, uniform_buffer); rd = NULL;
}

static bool
cell_prepare_to_render(ssize_t vao_idx, ssize_t gvao_idx, Screen *screen, GLfloat xstart, GLfloat ystart, GLfloat dx, GLfloat dy, FONTS_DATA_HANDLE fonts_data) {
    size_t sz;
    CELL_BUFFERS;
    void *address;
    bool changed = false;

    ensure_sprite_map(fonts_data);

    bool cursor_pos_changed = screen->cursor->x != screen->last_rendered.cursor_x
                           || screen->cursor->y != screen->last_rendered.cursor_y;
    bool disable_ligatures = screen->disable_ligatures == DISABLE_LIGATURES_CURSOR;
    bool screen_resized = screen->last_rendered.columns != screen->columns || screen->last_rendered.lines != screen->lines;

    if (screen->reload_all_gpu_data || screen->scroll_changed || screen->is_dirty || screen_resized || (disable_ligatures && cursor_pos_changed)) {
        sz = sizeof(GPUCell) * screen->lines * screen->columns;
        address = alloc_and_map_vao_buffer(vao_idx, sz, cell_data_buffer, GL_STREAM_DRAW, GL_WRITE_ONLY);
        screen_update_cell_data(screen, address, fonts_data, disable_ligatures && cursor_pos_changed);
        unmap_vao_buffer(vao_idx, cell_data_buffer); address = NULL;
        changed = true;
    }

    if (cursor_pos_changed) {
        screen->last_rendered.cursor_x = screen->cursor->x;
        screen->last_rendered.cursor_y = screen->cursor->y;
    }

    if (screen->reload_all_gpu_data || screen_resized || screen_is_selection_dirty(screen)) {
        sz = (size_t)screen->lines * screen->columns;
        address = alloc_and_map_vao_buffer(vao_idx, sz, selection_buffer, GL_STREAM_DRAW, GL_WRITE_ONLY);
        screen_apply_selection(screen, address, sz);
        unmap_vao_buffer(vao_idx, selection_buffer); address = NULL;
        changed = true;
    }

    if (gvao_idx && grman_update_layers(screen->grman, screen->scrolled_by, xstart, ystart, dx, dy, screen->columns, screen->lines, screen->cell_size)) {
        send_graphics_data_to_gpu(screen->grman->count, gvao_idx, screen->grman->render_data);
        changed = true;
    }
    screen->last_rendered.scrolled_by = screen->scrolled_by;
    screen->last_rendered.columns = screen->columns;
    screen->last_rendered.lines = screen->lines;
    return changed;
}

static void
draw_bg(OSWindow *w) {
    blank_canvas(w->is_semi_transparent ? OPT(background_opacity) : 1.0f, OPT(background));
    bind_program(BGIMAGE_PROGRAM);
    bind_vertex_array(blit_vertex_array);

    glUniform1i(bgimage_program_layout.image_location, BGIMAGE_UNIT);
    glUniform1f(bgimage_program_layout.opacity_location, OPT(background_opacity));
    glUniform4f(bgimage_program_layout.sizes_location,
        (GLfloat)w->viewport_width, (GLfloat)w->viewport_height, (GLfloat)w->bgimage->width, (GLfloat)w->bgimage->height);
    glUniform1f(bgimage_program_layout.premult_location, w->is_semi_transparent ? 1.f : 0.f);
    GLfloat tiled = 0.f;;
    GLfloat left = -1.0, top = 1.0, right = 1.0, bottom = -1.0;
    switch (OPT(background_image_layout)) {
        case TILING: case MIRRORED: case CLAMPED:
            tiled = 1.f; break;
        case SCALED:
            tiled = 0.f; break;
        case CENTER_CLAMPED:
            tiled = 1.f;
            if (w->viewport_width > (int)w->bgimage->width) {
                GLfloat frac = (w->viewport_width - w->bgimage->width) / (GLfloat)w->viewport_width;
                left += frac; right += frac;
            }
            if (w->viewport_height > (int)w->bgimage->height) {
                GLfloat frac = (w->viewport_height - w->bgimage->height) / (GLfloat)w->viewport_height;
                top -= frac; bottom -= frac;
            }
            break;
    }
    glUniform1f(bgimage_program_layout.tiled_location, tiled);
    glUniform4f(bgimage_program_layout.positions_location, left, top, right, bottom);
    glActiveTexture(GL_TEXTURE0 + BGIMAGE_UNIT);
    glBindTexture(GL_TEXTURE_2D, w->bgimage->texture_id);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    unbind_vertex_array();
    unbind_program();
}

static void
draw_graphics(int program, ssize_t vao_idx, ssize_t gvao_idx, ImageRenderData *data, GLuint start, GLuint count) {
    bind_program(program);
    bind_vertex_array(gvao_idx);
    glActiveTexture(GL_TEXTURE0 + GRAPHICS_UNIT);

    GLuint base = 4 * start;
    glEnable(GL_SCISSOR_TEST);
    for (GLuint i=0; i < count;) {
        ImageRenderData *rd = data + start + i;
        glBindTexture(GL_TEXTURE_2D, rd->texture_id);
        // You could reduce the number of draw calls by using
        // glDrawArraysInstancedBaseInstance but Apple chose to abandon OpenGL
        // before implementing it.
        for (GLuint k=0; k < rd->group_count; k++, base += 4, i++) glDrawArrays(GL_TRIANGLE_FAN, base, 4);
    }
    glDisable(GL_SCISSOR_TEST);
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

void
draw_centered_alpha_mask(OSWindow *os_window, size_t screen_width, size_t screen_height, size_t width, size_t height, uint8_t *canvas) {
    ImageRenderData *data = load_alpha_mask_texture(width, height, canvas);
    gpu_data_for_centered_image(data, screen_width, screen_height, width, height);
    bind_program(GRAPHICS_ALPHA_MASK_PROGRAM);
    glUniform1i(cell_uniform_data.amask_image_loc, GRAPHICS_UNIT);
    color_vec3(cell_uniform_data.amask_fg_loc, OPT(foreground));
    glUniform1f(cell_uniform_data.amask_premult_loc, os_window->is_semi_transparent ? 1.f : 0.f);
    send_graphics_data_to_gpu(1, os_window->gvao_idx, data);
    glEnable(GL_BLEND);
    if (os_window->is_semi_transparent) {
        BLEND_PREMULT;
    } else {
        BLEND_ONTO_OPAQUE;
    }
    glScissor(0, 0, screen_width, screen_height);
    draw_graphics(GRAPHICS_ALPHA_MASK_PROGRAM, 0, os_window->gvao_idx, data, 0, 1);
    glDisable(GL_BLEND);
}

static void
draw_cells_simple(ssize_t vao_idx, ssize_t gvao_idx, Screen *screen) {
    bind_program(CELL_PROGRAM);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    if (screen->grman->count) {
        glEnable(GL_BLEND);
        BLEND_ONTO_OPAQUE;
        draw_graphics(GRAPHICS_PROGRAM, vao_idx, gvao_idx, screen->grman->render_data, 0, screen->grman->count);
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
    glUniform4f(tint_program_layout.tint_color_location, C(16), C(8), C(0), OPT(background_tint));
#undef C
    glUniform4f(tint_program_layout.edges_location, crd->gl.xstart, crd->gl.ystart - crd->gl.height, crd->gl.xstart + crd->gl.width, crd->gl.ystart);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
}

static void
set_cell_uniforms(float current_inactive_text_alpha, bool force) {
    if (!cell_uniform_data.constants_set || force) {
        cell_uniform_data.gploc = glGetUniformLocation(program_id(GRAPHICS_PROGRAM), "inactive_text_alpha");
        cell_uniform_data.gpploc = glGetUniformLocation(program_id(GRAPHICS_PREMULT_PROGRAM), "inactive_text_alpha");
        cell_uniform_data.cploc = glGetUniformLocation(program_id(CELL_PROGRAM), "inactive_text_alpha");
        cell_uniform_data.cfploc = glGetUniformLocation(program_id(CELL_FG_PROGRAM), "inactive_text_alpha");
        cell_uniform_data.amask_premult_loc = glGetUniformLocation(program_id(GRAPHICS_ALPHA_MASK_PROGRAM), "alpha_mask_premult");
        cell_uniform_data.amask_fg_loc = glGetUniformLocation(program_id(GRAPHICS_ALPHA_MASK_PROGRAM), "amask_fg");
        cell_uniform_data.amask_image_loc = glGetUniformLocation(program_id(GRAPHICS_ALPHA_MASK_PROGRAM), "image");
#define S(prog, name, val, type) { bind_program(prog); glUniform##type(glGetUniformLocation(program_id(prog), #name), val); }
        S(GRAPHICS_PROGRAM, image, GRAPHICS_UNIT, 1i);
        S(GRAPHICS_PREMULT_PROGRAM, image, GRAPHICS_UNIT, 1i);
        S(CELL_PROGRAM, sprites, SPRITE_MAP_UNIT, 1i); S(CELL_FG_PROGRAM, sprites, SPRITE_MAP_UNIT, 1i);
        S(CELL_PROGRAM, dim_opacity, OPT(dim_opacity), 1f); S(CELL_FG_PROGRAM, dim_opacity, OPT(dim_opacity), 1f);
        S(CELL_BG_PROGRAM, defaultbg, OPT(background), 1f);
#undef S
        cell_uniform_data.constants_set = true;
    }
    if (current_inactive_text_alpha != cell_uniform_data.prev_inactive_text_alpha || force) {
        cell_uniform_data.prev_inactive_text_alpha = current_inactive_text_alpha;
#define S(prog, loc) { bind_program(prog); glUniform1f(cell_uniform_data.loc, current_inactive_text_alpha); }
        S(CELL_PROGRAM, cploc); S(CELL_FG_PROGRAM, cfploc); S(GRAPHICS_PROGRAM, gploc); S(GRAPHICS_PREMULT_PROGRAM, gpploc);
#undef S
    }
}

static GLfloat
render_window_title(OSWindow *os_window, Screen *screen UNUSED, GLfloat xstart, GLfloat ystart, GLfloat width, Window *window, GLfloat left, GLfloat right) {
    unsigned bar_height = os_window->fonts_data->cell_height + 2;
    if (!bar_height || right <= left) return 0;
    unsigned bar_width = (unsigned)ceilf(right - left);
    if (!window->title_bar_data.buf || window->title_bar_data.width != bar_width || window->title_bar_data.height != bar_height) {
        free(window->title_bar_data.buf);
        Py_CLEAR(window->title_bar_data.last_drawn_title_object_id);
        window->title_bar_data.buf = malloc((size_t)4 * bar_width * bar_height);
        if (!window->title_bar_data.buf) return 0;
        window->title_bar_data.height = bar_height;
        window->title_bar_data.width = bar_width;
    }
    static char title[2048] = {0};
    if (window->title_bar_data.last_drawn_title_object_id != window->title) {
        snprintf(title, arraysz(title), " %s", PyUnicode_AsUTF8(window->title));
#define RGBCOL(which, fallback) ( 0xff000000 | colorprofile_to_color_with_fallback(screen->color_profile, screen->color_profile->overridden.which, screen->color_profile->configured.which, screen->color_profile->overridden.fallback, screen->color_profile->configured.fallback))
        if (!draw_window_title(os_window, title, RGBCOL(highlight_fg, default_fg), RGBCOL(highlight_bg, default_bg), window->title_bar_data.buf, bar_width, bar_height)) return 0;
#undef RGBCOL
        window->title_bar_data.last_drawn_title_object_id = window->title;
        Py_INCREF(window->title_bar_data.last_drawn_title_object_id);
    }
    static ImageRenderData data = {.group_count=1};
    xstart = clamp_position_to_nearest_pixel(xstart, os_window->viewport_width);
    ystart = clamp_position_to_nearest_pixel(ystart, os_window->viewport_height);
    GLfloat height_gl = gl_size(bar_height, os_window->viewport_height);
    gpu_data_for_image(&data, xstart, ystart, xstart + width, ystart - height_gl);
    if (!data.texture_id) { glGenTextures(1, &data.texture_id); }
    glBindTexture(GL_TEXTURE_2D, data.texture_id);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    glTexImage2D(GL_TEXTURE_2D, 0, texture_internal_format, bar_width, bar_height, 0, GL_RGBA, GL_UNSIGNED_BYTE, window->title_bar_data.buf);
    set_cell_uniforms(1.f, false);
    bind_program(GRAPHICS_PROGRAM);
    send_graphics_data_to_gpu(1, os_window->gvao_idx, &data);
    glEnable(GL_BLEND);
    if (os_window->is_semi_transparent) { BLEND_PREMULT; } else { BLEND_ONTO_OPAQUE; }
    draw_graphics(GRAPHICS_PROGRAM, 0, os_window->gvao_idx, &data, 0, 1);
    glDisable(GL_BLEND);
    return height_gl;
}

static void
draw_window_logo(ssize_t vao_idx, OSWindow *os_window, const WindowLogoRenderData *wl, const CellRenderData *crd) {
    if (os_window->live_resize.in_progress) return;
    BLEND_PREMULT;
    GLfloat logo_width_gl = gl_size(wl->instance->width, os_window->viewport_width);
    GLfloat logo_height_gl = gl_size(wl->instance->height, os_window->viewport_height);
    GLfloat logo_left_gl = clamp_position_to_nearest_pixel(
            crd->gl.xstart + crd->gl.width * wl->position.canvas_x - logo_width_gl * wl->position.image_x, os_window->viewport_width);
    GLfloat logo_top_gl = clamp_position_to_nearest_pixel(
            crd->gl.ystart - crd->gl.height * wl->position.canvas_y + logo_height_gl * wl->position.image_y, os_window->viewport_height);
    static ImageRenderData ird = {.group_count=1};
    ird.texture_id = wl->instance->texture_id;
    gpu_data_for_image(&ird, logo_left_gl, logo_top_gl, logo_left_gl + logo_width_gl, logo_top_gl - logo_height_gl);
    send_graphics_data_to_gpu(1, os_window->gvao_idx, &ird);
    bind_program(GRAPHICS_PREMULT_PROGRAM);
    glUniform1f(cell_uniform_data.gpploc, cell_uniform_data.prev_inactive_text_alpha * wl->alpha);
    draw_graphics(GRAPHICS_PREMULT_PROGRAM, vao_idx, os_window->gvao_idx, &ird, 0, 1);
    glUniform1f(cell_uniform_data.gpploc, cell_uniform_data.prev_inactive_text_alpha);
}

static void
draw_window_number(OSWindow *os_window, Screen *screen, const CellRenderData *crd, Window *window) {
    GLfloat left = os_window->viewport_width * (crd->gl.xstart + 1.f) / 2.f;
    GLfloat right = left + os_window->viewport_width * crd->gl.width / 2.f;
    GLfloat title_bar_height = 0;
    size_t requested_height = (size_t)(os_window->viewport_height * crd->gl.height / 2.f);
    if (window->title && PyUnicode_Check(window->title) && (requested_height > (os_window->fonts_data->cell_height + 1) * 2)) {
        title_bar_height = render_window_title(os_window, screen, crd->gl.xstart, crd->gl.ystart, crd->gl.width, window, left, right);
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
    glUniform1i(cell_uniform_data.amask_image_loc, GRAPHICS_UNIT);
    color_type digit_color = colorprofile_to_color_with_fallback(screen->color_profile, screen->color_profile->overridden.highlight_bg, screen->color_profile->configured.highlight_bg, screen->color_profile->overridden.default_fg, screen->color_profile->configured.default_fg);
    color_vec3(cell_uniform_data.amask_fg_loc, digit_color);
    glUniform1f(cell_uniform_data.amask_premult_loc, 1.f);
    send_graphics_data_to_gpu(1, os_window->gvao_idx, ird);
    draw_graphics(GRAPHICS_ALPHA_MASK_PROGRAM, 0, os_window->gvao_idx, ird, 0, 1);
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
    glUniform4f(tint_program_layout.tint_color_location, C(r), C(g), C(b), C(1));
#undef C
    glUniform4f(tint_program_layout.edges_location, crd->gl.xstart, crd->gl.ystart - crd->gl.height, crd->gl.xstart + crd->gl.width, crd->gl.ystart);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    glDisable(GL_BLEND);
}

static void
draw_cells_interleaved(ssize_t vao_idx, ssize_t gvao_idx, Screen *screen, OSWindow *w, const CellRenderData *crd, const WindowLogoRenderData *wl) {
    glEnable(GL_BLEND);
    BLEND_ONTO_OPAQUE;

    // draw background for all cells
    if (!has_bgimage(w)) {
        bind_program(CELL_BG_PROGRAM);
        glUniform1ui(cell_program_layouts[CELL_BG_PROGRAM].draw_bg_bitfield_location, 3);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    } else if (OPT(background_tint) > 0) {
        draw_tint(false, screen, crd);
        BLEND_ONTO_OPAQUE;
    }

    if (screen->grman->num_of_below_refs || has_bgimage(w) || wl) {
        if (wl) {
            draw_window_logo(vao_idx, w, wl, crd);
            BLEND_ONTO_OPAQUE;
        }
        bind_program(CELL_BG_PROGRAM);
        if (screen->grman->num_of_below_refs) draw_graphics(
                GRAPHICS_PROGRAM, vao_idx, gvao_idx, screen->grman->render_data, 0, screen->grman->num_of_below_refs);
        // draw background for non-default bg cells
        glUniform1ui(cell_program_layouts[CELL_BG_PROGRAM].draw_bg_bitfield_location, 2);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    }

    if (screen->grman->num_of_negative_refs) draw_graphics(GRAPHICS_PROGRAM, vao_idx, gvao_idx, screen->grman->render_data, screen->grman->num_of_below_refs, screen->grman->num_of_negative_refs);

    bind_program(CELL_SPECIAL_PROGRAM);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);

    bind_program(CELL_FG_PROGRAM);
    BLEND_PREMULT;
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    BLEND_ONTO_OPAQUE;

    if (screen->grman->num_of_positive_refs) draw_graphics(GRAPHICS_PROGRAM, vao_idx, gvao_idx, screen->grman->render_data, screen->grman->num_of_negative_refs + screen->grman->num_of_below_refs, screen->grman->num_of_positive_refs);

    glDisable(GL_BLEND);
}

static void
draw_cells_interleaved_premult(ssize_t vao_idx, ssize_t gvao_idx, Screen *screen, OSWindow *os_window, const CellRenderData *crd, const WindowLogoRenderData *wl) {
    if (OPT(background_tint) > 0.f) {
        glEnable(GL_BLEND);
        draw_tint(true, screen, crd);
        glDisable(GL_BLEND);
    }
    if (!os_window->offscreen_texture_id) {
        glGenFramebuffers(1, &os_window->offscreen_framebuffer);
        glGenTextures(1, &os_window->offscreen_texture_id);
        glBindTexture(GL_TEXTURE_2D, os_window->offscreen_texture_id);
        glTexImage2D(GL_TEXTURE_2D, 0, texture_internal_format, os_window->viewport_width, os_window->viewport_height, 0, GL_RGBA, GL_UNSIGNED_BYTE, 0);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
    }
    glBindTexture(GL_TEXTURE_2D, 0);
    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, os_window->offscreen_framebuffer);
    glFramebufferTexture(GL_DRAW_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, os_window->offscreen_texture_id, 0);
    /* if (glCheckFramebufferStatus(GL_DRAW_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) fatal("Offscreen framebuffer not complete"); */
    bind_program(CELL_BG_PROGRAM);
    if (!has_bgimage(os_window)) {
        // draw background for all cells
        glUniform1ui(cell_program_layouts[CELL_BG_PROGRAM].draw_bg_bitfield_location, 3);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    } else blank_canvas(0, 0);
    glEnable(GL_BLEND);
    BLEND_PREMULT;

    if (screen->grman->num_of_below_refs || has_bgimage(os_window) || wl) {
        if (wl) {
            draw_window_logo(vao_idx, os_window, wl, crd);
            BLEND_PREMULT;
        }
        if (screen->grman->num_of_below_refs) draw_graphics(
            GRAPHICS_PREMULT_PROGRAM, vao_idx, gvao_idx, screen->grman->render_data, 0, screen->grman->num_of_below_refs);
        bind_program(CELL_BG_PROGRAM);
        // Draw background for non-default bg cells
        glUniform1ui(cell_program_layouts[CELL_BG_PROGRAM].draw_bg_bitfield_location, 2);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    } else {
        // Apply background_opacity
        glUniform1ui(cell_program_layouts[CELL_BG_PROGRAM].draw_bg_bitfield_location, 0);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    }

    if (screen->grman->num_of_negative_refs) {
        draw_graphics(GRAPHICS_PREMULT_PROGRAM, vao_idx, gvao_idx, screen->grman->render_data, screen->grman->num_of_below_refs, screen->grman->num_of_negative_refs);
    }

    bind_program(CELL_SPECIAL_PROGRAM);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);

    bind_program(CELL_FG_PROGRAM);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);

    if (screen->grman->num_of_positive_refs) draw_graphics(GRAPHICS_PREMULT_PROGRAM, vao_idx, gvao_idx, screen->grman->render_data, screen->grman->num_of_negative_refs + screen->grman->num_of_below_refs, screen->grman->num_of_positive_refs);

    glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
    if (!has_bgimage(os_window)) glDisable(GL_BLEND);
    glEnable(GL_SCISSOR_TEST);

    // Now render the framebuffer to the screen
    bind_program(BLIT_PROGRAM); bind_vertex_array(blit_vertex_array);
    static bool blit_constants_set = false;
    if (!blit_constants_set) {
        glUniform1i(glGetUniformLocation(program_id(BLIT_PROGRAM), "image"), BLIT_UNIT);
        blit_constants_set = true;
    }
    glActiveTexture(GL_TEXTURE0 + BLIT_UNIT);
    glBindTexture(GL_TEXTURE_2D, os_window->offscreen_texture_id);
    glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
    glDisable(GL_SCISSOR_TEST);
    glDisable(GL_BLEND);
}

void
blank_canvas(float background_opacity, color_type color) {
    // See https://github.com/glfw/glfw/issues/1538 for why we use pre-multiplied alpha
#define C(shift) (srgb_color((color >> shift) & 0xFF) * background_opacity)
    glClearColor(C(16), C(8), C(0), background_opacity);
#undef C
    glClear(GL_COLOR_BUFFER_BIT);
}

bool
send_cell_data_to_gpu(ssize_t vao_idx, ssize_t gvao_idx, GLfloat xstart, GLfloat ystart, GLfloat dx, GLfloat dy, Screen *screen, OSWindow *os_window) {
    bool changed = false;
    if (os_window->fonts_data) {
        if (cell_prepare_to_render(vao_idx, gvao_idx, screen, xstart, ystart, dx, dy, os_window->fonts_data)) changed = true;
    }
    return changed;
}

static float
ease_out_cubic(float phase) {
    return 1.0f - powf(1.0f - phase, 3.0f);
}

static float
ease_in_out_cubic(float phase) {
    return phase < 0.5f ?
        4.0f * powf(phase, 3.0f) :
        1.0f - powf(-2.0f * phase + 2.0f, 3.0f) / 2.0f;
}

static float
visual_bell_intensity(float phase) {
    static const float peak = 0.2f;
    const float fade = 1.0f - peak;
    return phase < peak ? ease_out_cubic(phase / peak) : ease_in_out_cubic((1.0f - phase) / fade);
}

static float
get_visual_bell_intensity(Screen *screen) {
    if (screen->start_visual_bell_at > 0) {
        monotonic_t progress = monotonic() - screen->start_visual_bell_at;
        monotonic_t duration = OPT(visual_bell_duration);
        if (progress <= duration) return visual_bell_intensity((float)progress / duration);
        screen->start_visual_bell_at = 0;
    }
    return 0.0f;
}

void
draw_cells(ssize_t vao_idx, ssize_t gvao_idx, const ScreenRenderData *srd, float x_ratio, float y_ratio, OSWindow *os_window, bool is_active_window, bool can_be_focused, Window *window) {
    Screen *screen = srd->screen;
    CELL_BUFFERS;
    bool inverted = screen_invert_colors(screen);
    CellRenderData crd = {.gl={.xstart = srd->xstart, .ystart = srd->ystart, .dx = srd->dx * x_ratio, .dy = srd->dy * y_ratio} };
    crd.gl.width = crd.gl.dx * screen->columns; crd.gl.height = crd.gl.dy * screen->lines;
    // The scissor limits below are calculated to ensure that they do not
    // overlap with the pixels outside the draw area. We cant use the actual pixel window dimensions
    // because of the mapping of opengl's float based co-ord system to pixels.
    // for a test case (scissor is also used to blit framebuffer in draw_cells_interleaved_premult) run:
    // kitty -o background=cyan -o background_opacity=0.7 -o cursor_blink_interval=0 -o window_margin_width=40 -o remember_initial_window_size=n -o initial_window_width=401 kitty +kitten icat --hold logo/kitty.png
    // Repeat incrementing window width by 1px each time over cursor_width number of pixels and see if any lines
    // appear at the borders of the content area
#define SCALE(w, x) ((GLfloat)(os_window->viewport_##w) * (GLfloat)(x))
    /* printf("columns=%d dx=%f w=%f vw=%d vh=%d left=%f width=%f\n", screen->columns, dx, w, os_window->viewport_width, os_window->viewport_height, SCALE(width, (xstart + 1.f)/2.f), SCALE(width, w / 2.f)); */

        crd.px.xstart = (GLint)roundf(SCALE(width, (crd.gl.xstart + 1.f)/2.f));
        crd.px.ystart = (GLint)roundf(SCALE(height, (crd.gl.ystart - crd.gl.height + 1.f)/2.f));
        crd.px.width  = (GLsizei)roundf(SCALE(width, crd.gl.width / 2.f));
        crd.px.height = (GLsizei)roundf(SCALE(height, crd.gl.height / 2.f));
#undef SCALE
    glScissor(crd.px.xstart, crd.px.ystart, crd.px.width, crd.px.height);

    cell_update_uniform_block(vao_idx, screen, uniform_buffer, &crd, &screen->cursor_render_info, inverted, os_window);

    bind_vao_uniform_buffer(vao_idx, uniform_buffer, cell_program_layouts[CELL_PROGRAM].render_data.index);
    bind_vertex_array(vao_idx);

    float current_inactive_text_alpha = (!can_be_focused || screen->cursor_render_info.is_focused) && is_active_window ? 1.0f : (float)OPT(inactive_text_alpha);
    set_cell_uniforms(current_inactive_text_alpha, screen->reload_all_gpu_data);
    screen->reload_all_gpu_data = false;
    bool has_underlying_image = has_bgimage(os_window);
    WindowLogoRenderData *wl;
    if (window && (wl = &window->window_logo) && wl->id && (wl->instance = find_window_logo(global_state.all_window_logos, wl->id)) && wl->instance && wl->instance->load_from_disk_ok) {
        has_underlying_image = true;
        set_on_gpu_state(window->window_logo.instance, true);
    } else wl = NULL;
    if (os_window->is_semi_transparent) {
        if (screen->grman->count || has_underlying_image) draw_cells_interleaved_premult(
                vao_idx, gvao_idx, screen, os_window, &crd, wl);
        else draw_cells_simple(vao_idx, gvao_idx, screen);
    } else {
        if (screen->grman->num_of_negative_refs || screen->grman->num_of_below_refs || has_underlying_image) draw_cells_interleaved(
                vao_idx, gvao_idx, screen, os_window, &crd, wl);
        else draw_cells_simple(vao_idx, gvao_idx, screen);
    }

    if (screen->start_visual_bell_at) {
        GLfloat intensity = get_visual_bell_intensity(screen);
        if (intensity > 0.0f) draw_visual_bell_flash(intensity, &crd, screen);
    }

    if (window && screen->display_window_char) draw_window_number(os_window, screen, &crd, window);
}
// }}}

// Borders {{{
enum BorderUniforms { BORDER_viewport, BORDER_background_opacity, BORDER_tint_opacity, BORDER_tint_premult, BORDER_default_bg, BORDER_active_border_color, BORDER_inactive_border_color, BORDER_bell_border_color, BORDER_tab_bar_bg, BORDER_tab_bar_margin_color, BORDER_gamma_lut, NUM_BORDER_UNIFORMS };
static GLint border_uniform_locations[NUM_BORDER_UNIFORMS] = {0};

static void
init_borders_program(void) {
#define SET_LOC(which) border_uniform_locations[BORDER_##which] = get_uniform_location(BORDERS_PROGRAM, #which);
        SET_LOC(viewport)
        SET_LOC(background_opacity)
        SET_LOC(tint_opacity)
        SET_LOC(tint_premult)
        SET_LOC(default_bg)
        SET_LOC(active_border_color)
        SET_LOC(inactive_border_color)
        SET_LOC(bell_border_color)
        SET_LOC(tab_bar_bg)
        SET_LOC(tab_bar_margin_color)
        SET_LOC(gamma_lut)
#undef SET_LOC
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
    if (has_bgimage(w)) {
        glEnable(GL_BLEND);
        BLEND_ONTO_OPAQUE;
        draw_bg(w);
        BLEND_ONTO_OPAQUE;
        background_opacity = 1.0f;
        tint_opacity = OPT(background_tint);
        tint_premult = w->is_semi_transparent ? OPT(background_tint) : 1.0f;
    }

    if (num_border_rects) {
        bind_vertex_array(vao_idx);
        bind_program(BORDERS_PROGRAM);
        if (rect_data_is_dirty) {
            const size_t sz = sizeof(BorderRect) * num_border_rects;
            void *borders_buf_address = alloc_and_map_vao_buffer(vao_idx, sz, 0, GL_STATIC_DRAW, GL_WRITE_ONLY);
            if (borders_buf_address) memcpy(borders_buf_address, rect_buf, sz);
            unmap_vao_buffer(vao_idx, 0);
        }
        glUniform1f(border_uniform_locations[BORDER_background_opacity], background_opacity);
        glUniform1f(border_uniform_locations[BORDER_tint_opacity], tint_opacity);
        glUniform1f(border_uniform_locations[BORDER_tint_premult], tint_premult);
        color_vec3(border_uniform_locations[BORDER_active_border_color], OPT(active_border_color));
        color_vec3(border_uniform_locations[BORDER_inactive_border_color], OPT(inactive_border_color));
        color_vec3(border_uniform_locations[BORDER_bell_border_color], OPT(bell_border_color));
        color_vec3(border_uniform_locations[BORDER_tab_bar_bg], OPT(tab_bar_background));
        color_vec3(border_uniform_locations[BORDER_tab_bar_margin_color], OPT(tab_bar_margin_color));
        glUniform2ui(border_uniform_locations[BORDER_viewport], viewport_width, viewport_height);
        color_type default_bg = (num_visible_windows > 1 && !all_windows_have_same_bg) ? OPT(background) : active_window_bg;
        color_vec3(border_uniform_locations[BORDER_default_bg], default_bg);
        glUniform1fv(border_uniform_locations[BORDER_gamma_lut], 256, srgb_lut);
        if (has_bgimage(w)) {
            if (w->is_semi_transparent) { BLEND_PREMULT; }
            else { BLEND_ONTO_OPAQUE_WITH_OPAQUE_OUTPUT; }
        }
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, num_border_rects);
        unbind_vertex_array();
        unbind_program();
    }
    if (has_bgimage(w)) glDisable(GL_BLEND);
}

// }}}

// Python API {{{
static PyObject*
compile_program(PyObject UNUSED *self, PyObject *args) {
    const char *vertex_shader, *fragment_shader;
    int which;
    GLuint vertex_shader_id = 0, fragment_shader_id = 0;
    if (!PyArg_ParseTuple(args, "iss", &which, &vertex_shader, &fragment_shader)) return NULL;
    if (which < 0 || which >= NUM_PROGRAMS) { PyErr_Format(PyExc_ValueError, "Unknown program: %d", which); return NULL; }
    Program *program = program_ptr(which);
    if (program->id != 0) { PyErr_SetString(PyExc_ValueError, "program already compiled"); return NULL; }
    program->id = glCreateProgram();
    vertex_shader_id = compile_shader(GL_VERTEX_SHADER, vertex_shader);
    fragment_shader_id = compile_shader(GL_FRAGMENT_SHADER, fragment_shader);
    glAttachShader(program->id, vertex_shader_id);
    glAttachShader(program->id, fragment_shader_id);
    glLinkProgram(program->id);
    GLint ret = GL_FALSE;
    glGetProgramiv(program->id, GL_LINK_STATUS, &ret);
    if (ret != GL_TRUE) {
        GLsizei len;
        static char glbuf[4096];
        glGetProgramInfoLog(program->id, sizeof(glbuf), &len, glbuf);
        log_error("Failed to compile GLSL shader!\n%s", glbuf);
        PyErr_SetString(PyExc_ValueError, "Failed to compile shader");
        goto end;
    }
    init_uniforms(which);

end:
    if (vertex_shader_id != 0) glDeleteShader(vertex_shader_id);
    if (fragment_shader_id != 0) glDeleteShader(fragment_shader_id);
    if (PyErr_Occurred()) { glDeleteProgram(program->id); program->id = 0; return NULL;}
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

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_shaders(PyObject *module) {
#define C(x) if (PyModule_AddIntConstant(module, #x, x) != 0) { PyErr_NoMemory(); return false; }
    C(CELL_PROGRAM); C(CELL_BG_PROGRAM); C(CELL_SPECIAL_PROGRAM); C(CELL_FG_PROGRAM); C(BORDERS_PROGRAM); C(GRAPHICS_PROGRAM); C(GRAPHICS_PREMULT_PROGRAM); C(GRAPHICS_ALPHA_MASK_PROGRAM); C(BLIT_PROGRAM); C(BGIMAGE_PROGRAM); C(TINT_PROGRAM);
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
    return true;
}
// }}}
