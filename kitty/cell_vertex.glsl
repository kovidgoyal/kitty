#version GLSL_VERSION
#define {WHICH_PROGRAM}
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
    float xstart, ystart, dx, dy, sprite_dx, sprite_dy, background_opacity, use_cell_bg_for_selection_fg, use_cell_fg_for_selection_fg, use_cell_for_selection_bg;

    uint default_fg, default_bg, highlight_fg, highlight_bg, cursor_fg, cursor_bg, url_color, url_style, inverted;

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
const uint STRIKE_SPRITE_INDEX = uint({STRIKE_SPRITE_INDEX});
const uint DECORATION_MASK = uint({DECORATION_MASK});

// TODO: Move to a texture, configurable?
// Generated using build-srgb-lut
const float srgb_lut[256] = float[](
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
);

// Converts a byte-representation of sRGB to a vec3 in linear colorspace
vec3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;

    return vec3(srgb_lut[r], srgb_lut[g], srgb_lut[b]);
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
    uint fg_as_uint = resolve_color(colors[fg_index], default_colors[fg_index]);
    // }}}

    // Foreground {{{
#ifdef NEEDS_FOREGROUND

    // The character sprite being rendered
    sprite_pos = to_sprite_pos(pos, sprite_coords.x, sprite_coords.y, sprite_coords.z & Z_MASK);
    colored_sprite = float((sprite_coords.z & COLOR_MASK) >> 14);

    // Foreground
    fg_as_uint = has_mark * color_table[NUM_COLORS + MARK_MASK + 1 + mark] + (ONE - has_mark) * fg_as_uint;
    foreground = color_to_vec(fg_as_uint);
    float has_dim = float((text_attrs >> DIM_SHIFT) & ONE);
    effective_text_alpha = inactive_text_alpha * mix(1.0, dim_opacity, has_dim);
    float in_url = float((is_selected & TWO) >> 1);
    decoration_fg = choose_color(in_url, color_to_vec(url_color), to_color(colors[2], fg_as_uint));
    // Selection
    vec3 selection_color = choose_color(use_cell_bg_for_selection_fg, bg, color_to_vec(highlight_fg));
    selection_color = choose_color(use_cell_fg_for_selection_fg, foreground, selection_color);
    foreground = choose_color(float(is_selected & ONE), selection_color, foreground);
    decoration_fg = choose_color(float(is_selected & ONE), selection_color, decoration_fg);
    // Underline and strike through (rendered via sprites)
    underline_pos = choose_color(in_url, to_sprite_pos(pos, url_style, ZERO, ZERO), to_sprite_pos(pos, (text_attrs >> DECORATION_SHIFT) & DECORATION_MASK, ZERO, ZERO));
    strike_pos = to_sprite_pos(pos, ((text_attrs >> STRIKE_SHIFT) & ONE) * STRIKE_SPRITE_INDEX, ZERO, ZERO);

    // Cursor
    cursor_color_vec = vec4(color_to_vec(cursor_bg), 1.0);
    vec3 final_cursor_text_color = color_to_vec(cursor_fg);
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
    bg = choose_color(float(is_selected & ONE), choose_color(use_cell_for_selection_bg, color_to_vec(fg_as_uint), color_to_vec(highlight_bg)), bg);
    background = choose_color(cell_has_block_cursor, color_to_vec(cursor_bg), bg);
#if !defined(TRANSPARENT) && defined(SPECIAL)
    float is_special_cell = cell_has_block_cursor + float(is_selected & ONE);
    bg_alpha = step(0.5, is_special_cell);
#endif
#endif

#endif
    // }}}

}
