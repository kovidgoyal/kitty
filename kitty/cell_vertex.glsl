#version GLSL_VERSION
#define WHICH_PROGRAM
#define NOT_TRANSPARENT
#define DECORATION_SHIFT {DECORATION_SHIFT}
#define REVERSE_SHIFT {REVERSE_SHIFT}
#define STRIKE_SHIFT {STRIKE_SHIFT}
#define DIM_SHIFT {DIM_SHIFT}
#define MARK_SHIFT {MARK_SHIFT}
#define MARK_MASK {MARK_MASK}
#define USE_SELECTION_FG
#define NUM_COLORS 256

// Inputs {{{
layout(std140) uniform CellRenderData {
    float xstart, ystart, dx, dy, sprite_dx, sprite_dy, background_opacity, cursor_text_uses_bg;

    uint default_fg, default_bg, highlight_fg, highlight_bg, cursor_color, cursor_text_color, url_color, url_style, inverted;

    uint xnum, ynum, cursor_fg_sprite_idx;
    float cursor_x, cursor_y, cursor_w;

    uint color_table[NUM_COLORS + MARK_MASK + MARK_MASK + 2];
};
#ifdef BACKGROUND
uniform uint draw_bg_bitfield;
#endif

// Have to use fixed locations here as all variants of the cell program share the same VAO
layout(location=0) in uvec3 colors;
layout(location=1) in uvec4 sprite_coords;
layout(location=2) in uint is_selected;


const int fg_index_map[] = int[3](0, 1, 0);
const uvec2 cell_pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);
// }}}


#if defined(SIMPLE) || defined(BACKGROUND) || defined(SPECIAL)
#define NEEDS_BACKROUND
#endif

#if defined(SIMPLE) || defined(FOREGROUND)
#define NEEDS_FOREGROUND
#endif

#ifdef NEEDS_BACKROUND
out vec3 background;
out float draw_bg;
#if defined(TRANSPARENT) || defined(SPECIAL)
out float bg_alpha;
#endif
#endif

#ifdef NEEDS_FOREGROUND
uniform float inactive_text_alpha;
uniform float dim_opacity;
out vec3 sprite_pos;
out vec3 underline_pos;
out vec3 cursor_pos;
out vec4 cursor_color_vec;
out vec3 strike_pos;
out vec3 foreground;
out vec3 decoration_fg;
out float colored_sprite;
out float effective_text_alpha;
#endif


// Utility functions {{{
const uint BYTE_MASK = uint(0xFF);
const uint Z_MASK = uint(0xFFF);
const uint COLOR_MASK = uint(0x4000);
const uint ZERO = uint(0);
const uint ONE = uint(1);
const uint TWO = uint(2);
const uint THREE = uint(3);
const uint FOUR = uint(4);

vec3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return vec3(float(r) / 255.0, float(g) / 255.0, float(b) / 255.0);
}

uint resolve_color(uint c, uint defval) {
    // Convert a cell color to an actual color based on the color table
    int t = int(c & BYTE_MASK);
    uint r;
    switch(t) {
        case 1:
            r = color_table[(c >> 8) & BYTE_MASK];
            break;
        case 2:
            r = c >> 8;
            break;
        default:
            r = defval;
    }
    return r;
}

vec3 to_color(uint c, uint defval) {
    return color_to_vec(resolve_color(c, defval));
}

vec3 to_sprite_pos(uvec2 pos, uint x, uint y, uint z) {
    vec2 s_xpos = vec2(x, float(x) + 1.0) * sprite_dx;
    vec2 s_ypos = vec2(y, float(y) + 1.0) * sprite_dy;
    return vec3(s_xpos[pos.x], s_ypos[pos.y], z);
}

vec3 choose_color(float q, vec3 a, vec3 b) {
    return mix(b, a, q);
}

float are_integers_equal(float a, float b) { // return 1 if equal otherwise 0
    float delta = abs(a - b);  // delta can be 0, 1 or larger
    return step(delta, 0.5); // 0 if 0.5 < delta else 1
}

float is_cursor(uint xi, uint y) {
    float x = float(xi);
    float y_equal = are_integers_equal(float(y), cursor_y);
    float x1_equal = are_integers_equal(x, cursor_x);
    float x2_equal = are_integers_equal(x, cursor_w);
    float x_equal = step(0.5, x1_equal + x2_equal);
    return step(2.0, x_equal + y_equal);
}
// }}}


void main() {

    // set cell vertex position  {{{
    uint instance_id = uint(gl_InstanceID);
    /* The current cell being rendered */
    uint r = instance_id / xnum;
    uint c = instance_id - r * xnum;

    /* The position of this vertex, at a corner of the cell  */
    float left = xstart + c * dx;
    float top = ystart - r * dy;
    vec2 xpos = vec2(left, left + dx);
    vec2 ypos = vec2(top, top - dy);
    uvec2 pos = cell_pos_map[gl_VertexID];
    gl_Position = vec4(xpos[pos.x], ypos[pos.y], 0, 1);

    // }}}

    // set cell color indices {{{
    uvec2 default_colors = uvec2(default_fg, default_bg);
    uint text_attrs = sprite_coords[3];
    uint is_reversed = ((text_attrs >> REVERSE_SHIFT) & ONE);
    uint is_inverted = is_reversed + inverted;
    int fg_index = fg_index_map[is_inverted];
    int bg_index = 1 - fg_index;
    float cell_has_cursor = is_cursor(c, r);
    float is_block_cursor = step(float(cursor_fg_sprite_idx), 0.5);
    float cell_has_block_cursor = cell_has_cursor * is_block_cursor;
    int mark = int(text_attrs >> MARK_SHIFT) & MARK_MASK;
    uint has_mark = uint(step(1, float(mark)));
    uint bg_as_uint = resolve_color(colors[bg_index], default_colors[bg_index]);
    bg_as_uint = has_mark * color_table[NUM_COLORS + mark] + (ONE - has_mark) * bg_as_uint;
    vec3 bg = color_to_vec(bg_as_uint);
    // }}}

    // Foreground {{{
#ifdef NEEDS_FOREGROUND

    // The character sprite being rendered
    sprite_pos = to_sprite_pos(pos, sprite_coords.x, sprite_coords.y, sprite_coords.z & Z_MASK);
    colored_sprite = float((sprite_coords.z & COLOR_MASK) >> 14);

    // Foreground
    uint fg_as_uint = resolve_color(colors[fg_index], default_colors[fg_index]);
    fg_as_uint = has_mark * color_table[NUM_COLORS + MARK_MASK + 1 + mark] + (ONE - has_mark) * fg_as_uint;
    foreground = color_to_vec(fg_as_uint);
    float has_dim = float((text_attrs >> DIM_SHIFT) & ONE);
    effective_text_alpha = inactive_text_alpha * mix(1.0, dim_opacity, has_dim);
    float in_url = float((is_selected & TWO) >> 1);
    decoration_fg = choose_color(in_url, color_to_vec(url_color), to_color(colors[2], fg_as_uint));
#ifdef USE_SELECTION_FG
    // Selection
    vec3 selection_color = color_to_vec(highlight_fg);
    foreground = choose_color(float(is_selected & ONE), selection_color, foreground);
    decoration_fg = choose_color(float(is_selected & ONE), selection_color, decoration_fg);
#endif
    // Underline and strike through (rendered via sprites)
    underline_pos = choose_color(in_url, to_sprite_pos(pos, url_style, ZERO, ZERO), to_sprite_pos(pos, (text_attrs >> DECORATION_SHIFT) & THREE, ZERO, ZERO));
    strike_pos = to_sprite_pos(pos, ((text_attrs >> STRIKE_SHIFT) & ONE) * FOUR, ZERO, ZERO);

    // Cursor
    cursor_color_vec = vec4(color_to_vec(cursor_color), 1.0);
    vec3 final_cursor_text_color = mix(color_to_vec(cursor_text_color), bg, cursor_text_uses_bg);
    foreground = choose_color(cell_has_block_cursor, final_cursor_text_color, foreground);
    decoration_fg = choose_color(cell_has_block_cursor, final_cursor_text_color, decoration_fg);
    cursor_pos = to_sprite_pos(pos, cursor_fg_sprite_idx * uint(cell_has_cursor), ZERO, ZERO);
#endif
    // }}}

    // Background {{{
#ifdef NEEDS_BACKROUND
    float cell_has_non_default_bg = step(1, float(abs(bg_as_uint - default_colors[1])));
    draw_bg = 1;

#if defined(BACKGROUND)
    background = bg;
    // draw_bg_bitfield has bit 0 set to draw default bg cells and bit 1 set to draw non-default bg cells
    uint draw_bg_mask = uint(2 * cell_has_non_default_bg + (1 - cell_has_non_default_bg));
    draw_bg = step(1, float(draw_bg_bitfield & draw_bg_mask));
#endif

#ifdef TRANSPARENT
    // Set bg_alpha to background_opacity on cells that have the default background color
    // Which means they must not have a block cursor or a selection or reverse video
    // On other cells it should be 1. For the SPECIAL program it should be 1 on cells with
    // selections/block cursor and 0 everywhere else.
    float is_special_cell = cell_has_block_cursor + float(is_selected & ONE);
#ifndef SPECIAL
    is_special_cell += cell_has_non_default_bg + float(is_reversed);
#endif
    bg_alpha = step(0.5, is_special_cell);
#ifndef SPECIAL
    bg_alpha = bg_alpha + (1.0f - bg_alpha) * background_opacity;
    bg_alpha *= draw_bg;
#endif
#endif

#if defined(SPECIAL) || defined(SIMPLE)
    // Selection and cursor
    bg = choose_color(float(is_selected & ONE), color_to_vec(highlight_bg), bg);
    background = choose_color(cell_has_block_cursor, color_to_vec(cursor_color), bg);
#if !defined(TRANSPARENT) && defined(SPECIAL)
    float is_special_cell = cell_has_block_cursor + float(is_selected & ONE);
    bg_alpha = step(0.5, is_special_cell);
#endif
#endif

#endif
    // }}}

}
