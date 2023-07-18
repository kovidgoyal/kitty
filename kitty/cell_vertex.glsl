#extension GL_ARB_explicit_attrib_location : require
#pragma kitty_include_shader <cell_defines.glsl>


// Inputs {{{
layout(std140) uniform CellRenderData {
    float xstart, ystart, dx, dy, sprite_dx, sprite_dy, background_opacity, use_cell_bg_for_selection_fg, use_cell_fg_for_selection_fg, use_cell_for_selection_bg;

    uint default_fg, default_bg, highlight_fg, highlight_bg, cursor_fg, cursor_bg, url_color, url_style, inverted;

    uint xnum, ynum, cursor_fg_sprite_idx;
    float cursor_x, cursor_y, cursor_w;

    uint color_table[NUM_COLORS + MARK_MASK + MARK_MASK + 2];
};
#if (PHASE == PHASE_BACKGROUND)
uniform uint draw_bg_bitfield;
#endif

// Have to use fixed locations here as all variants of the cell program share the same VAO
layout(location=0) in uvec3 colors;
layout(location=1) in uvec4 sprite_coords;
layout(location=2) in uint is_selected;
uniform float gamma_lut[256];


const int fg_index_map[] = int[3](0, 1, 0);
const uvec2 cell_pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);
// }}}


out vec3 background;
out float draw_bg;
out float bg_alpha;

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

vec3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return vec3(gamma_lut[r], gamma_lut[g], gamma_lut[b]);
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

struct CellData {
    float has_cursor, has_block_cursor;
    uvec2 pos;
} cell_data;

CellData set_vertex_position() {
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
#ifdef NEEDS_FOREGROUND
    // The character sprite being rendered
    sprite_pos = to_sprite_pos(pos, sprite_coords.x, sprite_coords.y, sprite_coords.z & Z_MASK);
    colored_sprite = float((sprite_coords.z & COLOR_MASK) >> 14);
#endif
    float is_block_cursor = step(float(cursor_fg_sprite_idx), 0.5);
    float has_cursor = is_cursor(c, r);
    return CellData(has_cursor, has_cursor * is_block_cursor, pos);
}

void main() {

    CellData cell_data = set_vertex_position();

    // set cell color indices {{{
    uvec2 default_colors = uvec2(default_fg, default_bg);
    uint text_attrs = sprite_coords[3];
    uint is_reversed = ((text_attrs >> REVERSE_SHIFT) & ONE);
    uint is_inverted = is_reversed + inverted;
    int fg_index = fg_index_map[is_inverted];
    int bg_index = 1 - fg_index;
    int mark = int(text_attrs >> MARK_SHIFT) & MARK_MASK;
    uint has_mark = uint(step(1, float(mark)));
    uint bg_as_uint = resolve_color(colors[bg_index], default_colors[bg_index]);
    bg_as_uint = has_mark * color_table[NUM_COLORS + mark] + (ONE - has_mark) * bg_as_uint;
    vec3 bg = color_to_vec(bg_as_uint);
    uint fg_as_uint = resolve_color(colors[fg_index], default_colors[fg_index]);
    // }}}

    // Foreground {{{
#ifdef NEEDS_FOREGROUND


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
    underline_pos = choose_color(in_url, to_sprite_pos(cell_data.pos, url_style, ZERO, ZERO), to_sprite_pos(cell_data.pos, (text_attrs >> DECORATION_SHIFT) & DECORATION_MASK, ZERO, ZERO));
    strike_pos = to_sprite_pos(cell_data.pos, ((text_attrs >> STRIKE_SHIFT) & ONE) * STRIKE_SPRITE_INDEX, ZERO, ZERO);

    // Cursor
    cursor_color_vec = vec4(color_to_vec(cursor_bg), 1.0);
    vec3 final_cursor_text_color = color_to_vec(cursor_fg);
    foreground = choose_color(cell_data.has_block_cursor, final_cursor_text_color, foreground);
    decoration_fg = choose_color(cell_data.has_block_cursor, final_cursor_text_color, decoration_fg);
    cursor_pos = to_sprite_pos(cell_data.pos, cursor_fg_sprite_idx * uint(cell_data.has_cursor), ZERO, ZERO);
#endif
    // }}}

    // Background {{{
    float cell_has_non_default_bg = step(1, float(abs(bg_as_uint - default_colors[1])));
    draw_bg = 1;

#if (PHASE == PHASE_BACKGROUND)
    // draw_bg_bitfield has bit 0 set to draw default bg cells and bit 1 set to draw non-default bg cells
    uint draw_bg_mask = uint(2 * cell_has_non_default_bg + (1 - cell_has_non_default_bg));
    draw_bg = step(1, float(draw_bg_bitfield & draw_bg_mask));
#endif

    bg_alpha = 1.f;
#ifdef TRANSPARENT
    // Set bg_alpha to background_opacity on cells that have the default background color
    // Which means they must not have a block cursor or a selection or reverse video
    // On other cells it should be 1. For the SPECIAL program it should be 1 on cells with
    // selections/block cursor and 0 everywhere else.
    float is_special_cell = cell_data.has_block_cursor + float(is_selected & ONE);
#if (PHASE != PHASE_SPECIAL)
    is_special_cell += cell_has_non_default_bg + float(is_reversed);
#endif
    bg_alpha = step(0.5, is_special_cell);
#if (PHASE != PHASE_SPECIAL)
    bg_alpha = bg_alpha + (1.0f - bg_alpha) * background_opacity;
    bg_alpha *= draw_bg;
#endif
#endif

    // Selection and cursor
    bg = choose_color(float(is_selected & ONE), choose_color(use_cell_for_selection_bg, color_to_vec(fg_as_uint), color_to_vec(highlight_bg)), bg);
    background = choose_color(cell_data.has_block_cursor, color_to_vec(cursor_bg), bg);
#if !defined(TRANSPARENT) && (PHASE == PHASE_SPECIAL)
    float is_special_cell = cell_data.has_block_cursor + float(is_selected & ONE);
    bg_alpha = step(0.5, is_special_cell);
#endif

    // }}}

}
