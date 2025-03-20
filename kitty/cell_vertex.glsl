#extension GL_ARB_explicit_attrib_location : require
#pragma kitty_include_shader <cell_defines.glsl>


// Inputs {{{
layout(std140) uniform CellRenderData {
    float xstart, ystart, dx, dy, use_cell_bg_for_selection_fg, use_cell_fg_for_selection_fg, use_cell_for_selection_bg;

    uint default_fg, highlight_fg, highlight_bg, cursor_fg, cursor_bg, url_color, url_style, inverted;

    uint xnum, ynum, sprites_xnum, sprites_ynum, cursor_fg_sprite_idx, cell_height;
    uint cursor_x1, cursor_x2, cursor_y1, cursor_y2;
    float cursor_opacity;

    // must have unique entries with 0 being default_bg and unset being UINT32_MAX
    uint bg_colors0, bg_colors1, bg_colors2, bg_colors3, bg_colors4, bg_colors5, bg_colors6, bg_colors7;
    float bg_opacities0, bg_opacities1, bg_opacities2, bg_opacities3, bg_opacities4, bg_opacities5, bg_opacities6, bg_opacities7;
    uint color_table[NUM_COLORS + MARK_MASK + MARK_MASK + 2];
};
uniform float gamma_lut[256];
#ifdef NEEDS_FOREGROUND
uniform usampler2D sprite_decorations_map;
#endif
#if (PHASE == PHASE_BACKGROUND)
uniform uint draw_bg_bitfield;
#endif

// Have to use fixed locations here as all variants of the cell program share the same VAOs
layout(location=0) in uvec3 colors;
layout(location=1) in uvec2 sprite_idx;
layout(location=2) in uint is_selected;

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
out vec4 cursor_color_premult;
out vec3 strike_pos;
flat out uint underline_exclusion_pos;
out vec3 foreground;
out vec3 decoration_fg;
out float colored_sprite;
out float effective_text_alpha;
#endif


// Utility functions {{{
const uint BYTE_MASK = uint(0xFF);
const uint SPRITE_INDEX_MASK = uint(0x7fffffff);
const uint SPRITE_COLORED_MASK = uint(0x80000000);
const uint SPRITE_COLORED_SHIFT = uint(31);
const uint ZERO = uint(0);
const uint ONE = uint(1);
const uint TWO = uint(2);
const uint DECORATION_MASK = uint({DECORATION_MASK});

vec3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return vec3(gamma_lut[r], gamma_lut[g], gamma_lut[b]);
}

float one_if_equal_zero_otherwise(int a, int b) {
    return 1.0f - clamp(abs(float(a) - float(b)), 0.0f, 1.0f);
}

float one_if_equal_zero_otherwise(uint a, uint b) {
    return 1.0f - clamp(abs(float(a) - float(b)), 0.0f, 1.0f);
}


uint resolve_color(uint c, uint defval) {
    // Convert a cell color to an actual color based on the color table
    int t = int(c & BYTE_MASK);
    uint is_one = uint(one_if_equal_zero_otherwise(t, 1));
    uint is_two = uint(one_if_equal_zero_otherwise(t, 2));
    uint is_neither_one_nor_two = 1u - is_one - is_two;
    return is_one * color_table[(c >> 8) & BYTE_MASK] + is_two * (c >> 8) + is_neither_one_nor_two * defval;
}

vec3 to_color(uint c, uint defval) {
    return color_to_vec(resolve_color(c, defval));
}

#ifdef NEEDS_FOREGROUND

uvec3 to_sprite_coords(uint idx) {
    uint sprites_per_page = sprites_xnum * sprites_ynum;
    uint z = idx / sprites_per_page;
    uint num_on_last_page = idx - sprites_per_page * z;
    uint y = num_on_last_page / sprites_xnum;
    uint x = num_on_last_page - sprites_xnum * y;
    return uvec3(x, y, z);
}

vec3 to_sprite_pos(uvec2 pos, uint idx) {
    uvec3 c = to_sprite_coords(idx);
    vec2 s_xpos = vec2(c.x, float(c.x) + 1.0f) * (1.0f / float(sprites_xnum));
    vec2 s_ypos = vec2(c.y, float(c.y) + 1.0f) * (1.0f / float(sprites_ynum));
    uint texture_height_px = (cell_height + 1u) * sprites_ynum;
    float row_height = 1.0f / float(texture_height_px);
    s_ypos[1] -= row_height;  // skip the decorations_exclude row
    return vec3(s_xpos[pos.x], s_ypos[pos.y], c.z);
}

uint to_underline_exclusion_pos() {
    uvec3 c = to_sprite_coords(sprite_idx[0]);
    uint cell_top_px = c.y * (cell_height + 1u);
    return cell_top_px + cell_height;
}

uint read_sprite_decorations_idx() {
    int idx = int(sprite_idx[0] & SPRITE_INDEX_MASK);
    ivec2 sz = textureSize(sprite_decorations_map, 0);
    int y = idx / sz[0];
    int x = idx - y * sz[0];
    return texelFetch(sprite_decorations_map, ivec2(x, y), 0).r;
}

uvec2 get_decorations_indices(uint in_url /* [0, 1] */, uint text_attrs) {
    uint decorations_idx = read_sprite_decorations_idx();
    uint strike_style = ((text_attrs >> STRIKE_SHIFT) & ONE); // 0 or 1
    uint strike_idx = decorations_idx * strike_style;
    uint underline_style = ((text_attrs >> DECORATION_SHIFT) & DECORATION_MASK);
    underline_style = in_url * url_style + (1u - in_url) * underline_style; // [0, 5]
    uint has_underline = uint(step(0.5f, float(underline_style)));  // [0, 1]
    return uvec2(strike_idx, has_underline * (decorations_idx + underline_style));
}
#endif

vec3 choose_color(float q, vec3 a, vec3 b) {
    return mix(b, a, q);
}

float choose_alpha(float q, float a, float b) {
    return mix(b, a, q);
}


float is_cursor(uint x, uint y) {
    uint clamped_x = clamp(x, cursor_x1, cursor_x2);
    uint clamped_y = clamp(y, cursor_y1, cursor_y2);
    return one_if_equal_zero_otherwise(x, clamped_x) * one_if_equal_zero_otherwise(y, clamped_y);
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
    sprite_pos = to_sprite_pos(pos, sprite_idx[0] & SPRITE_INDEX_MASK);
    colored_sprite = float((sprite_idx[0] & SPRITE_COLORED_MASK) >> SPRITE_COLORED_SHIFT);
#endif
    float is_block_cursor = step(float(cursor_fg_sprite_idx), 0.5);
    float has_cursor = is_cursor(c, r);
    return CellData(has_cursor, has_cursor * is_block_cursor, pos);
}

float background_opacity_for(uint bg, uint colorval, float opacity_if_matched) {  // opacity_if_matched if bg == colorval else 1
    float not_matched = step(1.f, abs(float(colorval - bg)));  // not_matched = 0 if bg == colorval else 1
    return not_matched + opacity_if_matched * (1.f - not_matched);
}

float calc_background_opacity(uint bg) {
    return (
        background_opacity_for(bg, bg_colors0, bg_opacities0) *
        background_opacity_for(bg, bg_colors1, bg_opacities1) *
        background_opacity_for(bg, bg_colors2, bg_opacities2) *
        background_opacity_for(bg, bg_colors3, bg_opacities3) *
        background_opacity_for(bg, bg_colors4, bg_opacities4) *
        background_opacity_for(bg, bg_colors5, bg_opacities5) *
        background_opacity_for(bg, bg_colors6, bg_opacities6) *
        background_opacity_for(bg, bg_colors7, bg_opacities7)
    );
}

// Overriding of foreground colors for contrast requirements {{{
#if defined(NEEDS_FOREGROUND) && DO_FG_OVERRIDE == 1
#define OVERRIDE_FG_COLORS
#pragma kitty_include_shader <hsluv.glsl>
#if (FG_OVERRIDE_ALGO == 1)
vec3 fg_override(float under_luminance, float over_lumininace, vec3 under, vec3 over) {
    // If the difference in luminance is too small,
    // force the foreground color to be black or white.
    float diff_luminance = abs(under_luminance - over_lumininace);
	float override_level = (1.f - colored_sprite) * step(diff_luminance, FG_OVERRIDE_THRESHOLD);
	float original_level = 1.f - override_level;
	return original_level * over + override_level * vec3(step(under_luminance, 0.5f));
}

#else

float contrast_ratio(float under_luminance, float over_luminance) {
    return clamp((max(under_luminance, over_luminance) + 0.05f) / (min(under_luminance, over_luminance) + 0.05f), 1.f, 21.f);
}

vec3 fg_override(float under_luminance, float over_luminance, vec3 under, vec3 over) {
    float ratio = contrast_ratio(under_luminance, over_luminance);
    vec3 diff = abs(under - over);
    vec3 over_hsluv = rgbToHsluv(over);
    const float min_contrast_ratio = FG_OVERRIDE_THRESHOLD;
    float target_lum_a = clamp((under_luminance + 0.05f) * min_contrast_ratio - 0.05f, 0.f, 1.f);
    float target_lum_b = clamp((under_luminance + 0.05f) / min_contrast_ratio - 0.05f, 0.f, 1.f);
    vec3 result_a = clamp(hsluvToRgb(vec3(over_hsluv.x, over_hsluv.y, target_lum_a * 100.f)), 0.f, 1.f);
    vec3 result_b = clamp(hsluvToRgb(vec3(over_hsluv.x, over_hsluv.y, target_lum_b * 100.f)), 0.f, 1.f);
    float result_a_ratio = contrast_ratio(under_luminance, dot(result_a, Y));
    float result_b_ratio = contrast_ratio(under_luminance, dot(result_b, Y));
    vec3 result = mix(result_a, result_b, step(result_a_ratio, result_b_ratio));
    return mix(result, over, max(step(diff.r + diff.g + diff.g, 0.001f), step(min_contrast_ratio, ratio)));
}
#endif

vec3 override_foreground_color(vec3 over, vec3 under) {
    float under_luminance = dot(under, Y);
    float over_lumininace = dot(over.rgb, Y);
    return fg_override(under_luminance, over_lumininace, under, over);
}
#endif
// }}}

void main() {

    CellData cell_data = set_vertex_position();

    // set cell color indices {{{
    uvec2 default_colors = uvec2(default_fg, bg_colors0);
    uint text_attrs = sprite_idx[1];
    uint is_reversed = ((text_attrs >> REVERSE_SHIFT) & ONE);
    uint is_inverted = is_reversed + inverted;
    int fg_index = fg_index_map[is_inverted];
    int bg_index = 1 - fg_index;
    int mark = int(text_attrs >> MARK_SHIFT) & MARK_MASK;
    uint has_mark = uint(step(1, float(mark)));
    uint bg_as_uint = resolve_color(colors[bg_index], default_colors[bg_index]);
    bg_as_uint = has_mark * color_table[NUM_COLORS + mark - 1] + (ONE - has_mark) * bg_as_uint;
    vec3 bg = color_to_vec(bg_as_uint);
    uint fg_as_uint = resolve_color(colors[fg_index], default_colors[fg_index]);
    // }}}

    // Foreground {{{
#ifdef NEEDS_FOREGROUND
    // Foreground
    fg_as_uint = has_mark * color_table[NUM_COLORS + MARK_MASK + mark] + (ONE - has_mark) * fg_as_uint;
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
    uvec2 decs = get_decorations_indices(uint(in_url), text_attrs);
    strike_pos = to_sprite_pos(cell_data.pos, decs[0]);
    underline_pos = to_sprite_pos(cell_data.pos, decs[1]);
    underline_exclusion_pos = to_underline_exclusion_pos();

    // Cursor
    cursor_color_premult = vec4(color_to_vec(cursor_bg) * cursor_opacity, cursor_opacity);
    vec3 final_cursor_text_color = mix(foreground, color_to_vec(cursor_fg), cursor_opacity);
    foreground = choose_color(cell_data.has_block_cursor, final_cursor_text_color, foreground);
    decoration_fg = choose_color(cell_data.has_block_cursor, final_cursor_text_color, decoration_fg);
    cursor_pos = to_sprite_pos(cell_data.pos, cursor_fg_sprite_idx * uint(cell_data.has_cursor));
#endif
    // }}}

    // Background {{{
    float orig_bg_alpha = 1;
#if PHASE == PHASE_BOTH && !defined(TRANSPARENT)  // fast case single pass opaque background
    bg_alpha = 1;
    draw_bg = 1;
#else
    bg_alpha = calc_background_opacity(bg_as_uint);
    orig_bg_alpha = bg_alpha;
#if (PHASE == PHASE_BACKGROUND)
    // draw_bg_bitfield has bit 0 set to draw default bg cells and bit 1 set to draw non-default bg cells
    float cell_has_non_default_bg = step(1.f, abs(float(bg_as_uint - bg_colors0))); // 0 if has default bg else 1
    uint draw_bg_mask = uint(2.f * cell_has_non_default_bg + (1.f - cell_has_non_default_bg)); // 1 if has default bg else 2
    draw_bg = step(0.5, float(draw_bg_bitfield & draw_bg_mask));
#else
    draw_bg = 1;
#endif

    float is_special_cell = cell_data.has_block_cursor + float(is_selected & ONE);
#if PHASE == PHASE_SPECIAL
    // Only special cells must be drawn and they must have bg_alpha 1
    bg_alpha = step(0.5, is_special_cell); // bg_alpha = 1 if is_special_cell else 0
#else
    is_special_cell += float(is_reversed);  // bg_alpha should be 1 for reverse video cells as well
    is_special_cell = step(0.5, is_special_cell);  // is_special_cell = 1 if is_special_cell else 0
    bg_alpha = bg_alpha * (1. - float(is_special_cell)) + is_special_cell;  // bg_alpha = 1 if is_special_cell else bg_alpha
#endif
    bg_alpha *= draw_bg;
#endif  // ends fast case #if else

    // Selection and cursor
    bg = choose_color(float(is_selected & ONE), choose_color(use_cell_for_selection_bg, color_to_vec(fg_as_uint), color_to_vec(highlight_bg)), bg);
    background = choose_color(cell_data.has_block_cursor, mix(bg, color_to_vec(cursor_bg), cursor_opacity), bg);
    // we use max so that opacity of the block cursor cell background goes from orig_bg_alpha to 1
    float effective_cursor_opacity = max(cursor_opacity, orig_bg_alpha) * draw_bg;
    bg_alpha = choose_alpha(cell_data.has_block_cursor, effective_cursor_opacity, bg_alpha);
    // }}}

#ifdef OVERRIDE_FG_COLORS
    decoration_fg = override_foreground_color(decoration_fg, background);
    foreground = override_foreground_color(foreground, background);
#endif
}
