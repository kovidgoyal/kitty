#extension GL_ARB_explicit_attrib_location : require
#pragma kitty_include_shader <cell_defines.glsl>
#pragma kitty_include_shader <utils.glsl>


// Inputs {{{
layout(std140) uniform CellRenderData {
    float use_cell_bg_for_selection_fg, use_cell_fg_for_selection_fg, use_cell_for_selection_bg;

    uint default_fg, highlight_fg, highlight_bg, main_cursor_fg, main_cursor_bg, url_color, url_style, inverted, extra_cursor_fg, extra_cursor_bg;

    uint columns, lines, sprites_xnum, sprites_ynum, cursor_shape, cell_width, cell_height;
    uint cursor_x1, cursor_x2, cursor_y1, cursor_y2;
    float cursor_opacity, inactive_text_alpha, dim_opacity, blink_opacity;

    // must have unique entries with 0 being default_bg and unset being UINT32_MAX
    uint bg_colors0, bg_colors1, bg_colors2, bg_colors3, bg_colors4, bg_colors5, bg_colors6, bg_colors7;
    float bg_opacities0, bg_opacities1, bg_opacities2, bg_opacities3, bg_opacities4, bg_opacities5, bg_opacities6, bg_opacities7;
    uint color_table[NUM_COLORS + MARK_MASK + MARK_MASK + 2];
};
uniform float gamma_lut[256];
uniform uint draw_bg_bitfield;
uniform usampler2D sprite_decorations_map;
uniform float row_offset;

// Have to use fixed locations here as all variants of the cell program share the same VAOs
layout(location=0) in uvec3 colors;
layout(location=1) in uvec2 sprite_idx;
layout(location=2) in uint is_selected;
// }}}

const int fg_index_map[] = int[3](0, 1, 0);
const uvec2 cell_pos_map[] = uvec2[4](
    uvec2(1u, 0u),  // right, top
    uvec2(1u, 1u),  // right, bottom
    uvec2(0u, 1u),  // left, bottom
    uvec2(0u, 0u)   // left, top
);
const uint cursor_shape_map[] = uint[5](  // maps cursor shape to foreground sprite index
   0u,  // NO_CURSOR
   0u,  // BLOCK  (this is rendered as background)
   2u,  // BEAM
   3u,  // UNDERLINE
   4u   // UNFOCUSED
);


out vec3 background;
out vec4 effective_background_premul;
#ifndef ONLY_BACKGROUND
out float effective_text_alpha;
out vec3 sprite_pos;
out vec3 underline_pos;
out vec3 cursor_pos;
out vec3 strike_pos;
flat out uint underline_exclusion_pos;
out vec3 cell_foreground;
out vec4 cursor_color_premult;
out vec3 decoration_fg;
out float colored_sprite;
#endif


// Utility functions {{{
const uint BYTE_MASK = uint(0xFF);
const uint SPRITE_INDEX_MASK = uint(0x7fffffff);
const uint SPRITE_COLORED_MASK = uint(0x80000000);
const uint SPRITE_COLORED_SHIFT = 31u;
const uint BIT_MASK = 1u;
const uint DECORATION_MASK = uint({DECORATION_MASK});

vec3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return vec3(gamma_lut[r], gamma_lut[g], gamma_lut[b]);
}

float one_if_equal_zero_otherwise(float a, float b) { return (1.0f - zero_or_one(abs(float(a) - float(b)))); }
// Wee need an integer variant to accommodate GPU driver bugs, see
// https://github.com/kovidgoyal/kitty/issues/9072
uint one_if_equal_zero_otherwise(int a, int b) { return (1u - uint(zero_or_one(abs(float(a) - float(b))))); }
uint one_if_equal_zero_otherwise(uint a, uint b) { return (1u - uint(zero_or_one(abs(float(a) - float(b))))); }


uint resolve_color(uint c, uint defval) {
    // Convert a cell color to an actual color based on the color table
    int t = int(c & BYTE_MASK);
    uint is_one = one_if_equal_zero_otherwise(t, 1);
    uint is_two = one_if_equal_zero_otherwise(t, 2);
    uint is_neither_one_nor_two = 1u - is_one - is_two;
    return is_one * color_table[(c >> 8) & BYTE_MASK] + is_two * (c >> 8) + is_neither_one_nor_two * defval;
}

vec3 to_color(uint c, uint defval) {
    return color_to_vec(resolve_color(c, defval));
}

vec3 resolve_dynamic_color(uint c, vec3 special_val, vec3 defval) {
    float type = float((c >> 24) & BYTE_MASK);
#define q(which, val) one_if_equal_zero_otherwise(type, float(which)) * val
    return (
        q(COLOR_IS_RGB, color_to_vec(c)) + q(COLOR_IS_INDEX, color_to_vec(color_table[c & BYTE_MASK])) +
        q(COLOR_IS_SPECIAL, special_val) + q(COLOR_NOT_SET, defval)
    );
#undef q
}

float contrast_ratio(float under_luminance, float over_luminance) {
    return clamp((max(under_luminance, over_luminance) + 0.05f) / (min(under_luminance, over_luminance) + 0.05f), 1.f, 21.f);
}

float contrast_ratio(vec3 a, vec3 b) {
    return contrast_ratio(dot(a, Y), dot(b, Y));
}

struct ColorPair {
    vec3 bg, fg;
};

float contrast_ratio(ColorPair a) { return contrast_ratio(a.bg, a.fg); }

ColorPair if_less_than_pair(float a, float b, ColorPair thenval, ColorPair elseval) {
    return ColorPair(if_less_than(a, b, thenval.bg, elseval.bg),
            if_less_than(a, b, thenval.fg, elseval.fg));
}

ColorPair if_one_then_pair(float condition, ColorPair thenval, ColorPair elseval) {
    return ColorPair(if_one_then(condition, thenval.bg, elseval.bg),
            if_one_then(condition, thenval.fg, elseval.fg));
}

ColorPair resolve_extra_cursor_colors_for_special_cursor(vec3 cell_bg, vec3 cell_fg) {
    ColorPair cell = ColorPair(cell_fg, cell_bg), base = ColorPair(color_to_vec(default_fg), color_to_vec(bg_colors0));
    float cr = contrast_ratio(cell), br = contrast_ratio(base);
    ColorPair higher_contrast_pair = if_less_than_pair(cr, br, base, cell);
    return if_less_than_pair(cr, 2.5, higher_contrast_pair, cell);
}

ColorPair resolve_extra_cursor_colors(vec3 cell_bg, vec3 cell_fg, ColorPair main_cursor) {
    ColorPair ans = ColorPair(
        resolve_dynamic_color(extra_cursor_bg, main_cursor.bg, main_cursor.bg),
        resolve_dynamic_color(extra_cursor_fg, cell_bg, main_cursor.fg)
    );
    ColorPair special = resolve_extra_cursor_colors_for_special_cursor(cell_bg, cell_fg);
    return if_one_then_pair(zero_or_one(abs(float(extra_cursor_bg & BYTE_MASK) - COLOR_IS_SPECIAL)), ans, special);
}

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
    // decorations_idx == 0 means no decorations, for example, for a blank line
    // when drawing fractionally scaled text
    uint has_decorations = uint(zero_or_one(float(decorations_idx)));
    uint strike_style = ((text_attrs >> STRIKE_SHIFT) & BIT_MASK); // 0 or 1
    uint strike_idx = decorations_idx * strike_style;
    uint underline_style = ((text_attrs >> DECORATION_SHIFT) & DECORATION_MASK);
    underline_style = in_url * url_style + (1u - in_url) * underline_style; // [0, 5]
    uint has_underline = uint(step(0.5f, float(underline_style)));  // [0, 1]
    return has_decorations * uvec2(strike_idx, has_underline * (decorations_idx + underline_style));
}

uint is_cursor(uint x, uint y) {
    uint clamped_x = clamp(x, cursor_x1, cursor_x2);
    uint clamped_y = clamp(y, cursor_y1, cursor_y2);
    return one_if_equal_zero_otherwise(x, clamped_x) * one_if_equal_zero_otherwise(y, clamped_y);
}
// }}}

struct CellData {
    float has_cursor, has_block_cursor;
    uvec2 pos;
    uint cursor_fg_sprite_idx;
    ColorPair cursor;
} cell_data;

CellData set_vertex_position(vec3 cell_fg, vec3 cell_bg) {
    uint instance_id = uint(gl_InstanceID);
    float dx = 2.0 / float(columns);
    float dy = 2.0 / float(lines);
    /* The current cell being rendered */
    uint row = instance_id / columns;
    uint column = instance_id - row * columns;
    /* The position of this vertex, at a corner of the cell  */
    float left = -1.0 + column * dx;
    float top = 1.0 - (float(row) + row_offset) * dy;
    uvec2 pos = cell_pos_map[gl_VertexID];
    gl_Position = vec4(vec2(left, left + dx)[pos.x], vec2(top, top - dy)[pos.y], 0, 1);
    // The character sprite being rendered
#ifndef ONLY_BACKGROUND
    sprite_pos = to_sprite_pos(pos, sprite_idx[0] & SPRITE_INDEX_MASK);
    colored_sprite = float((sprite_idx[0] & SPRITE_COLORED_MASK) >> SPRITE_COLORED_SHIFT);
#endif
    // Cursor shape and colors
    float has_main_cursor = float(is_cursor(column, row));
    float multicursor_shape = float((is_selected >> 2) & 3u);
    float multicursor_uses_main_cursor_shape = float((is_selected >> 4) & BIT_MASK);
    multicursor_shape = if_one_then(multicursor_uses_main_cursor_shape, cursor_shape, multicursor_shape);
    float final_cursor_shape = if_one_then(has_main_cursor, cursor_shape, multicursor_shape);
    float has_cursor = zero_or_one(final_cursor_shape);
    float is_block_cursor = has_cursor * one_if_equal_zero_otherwise(final_cursor_shape, 1.0);
    ColorPair main_cursor = ColorPair(color_to_vec(main_cursor_bg), color_to_vec(main_cursor_fg));
    ColorPair extra_cursor = resolve_extra_cursor_colors(cell_bg, cell_fg, main_cursor);
    ColorPair cursor = if_one_then_pair(has_main_cursor, main_cursor, extra_cursor);
    return CellData(has_cursor, is_block_cursor, pos, cursor_shape_map[int(final_cursor_shape)], cursor);
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
#if DO_FG_OVERRIDE == 1 && !defined(ONLY_BACKGROUND)
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


    // set cell color indices {{{
    uvec2 default_colors = uvec2(default_fg, bg_colors0);
    uint text_attrs = sprite_idx[1];
    uint is_reversed = ((text_attrs >> REVERSE_SHIFT) & BIT_MASK);
    uint is_inverted = is_reversed + inverted;
    int fg_index = fg_index_map[is_inverted];
    int bg_index = 1 - fg_index;
    int mark = int(text_attrs >> MARK_SHIFT) & MARK_MASK;
    uint has_mark = uint(step(1, float(mark)));
    uint bg_as_uint = resolve_color(colors[bg_index], default_colors[bg_index]);
    bg_as_uint = has_mark * color_table[NUM_COLORS + mark - 1] + (BIT_MASK - has_mark) * bg_as_uint;
    float cell_has_default_bg = 1.f - step(1.f, abs(float(bg_as_uint - bg_colors0))); // 1 if has default bg else 0
    vec3 bg = color_to_vec(bg_as_uint);
    uint fg_as_uint = resolve_color(colors[fg_index], default_colors[fg_index]);
    fg_as_uint = has_mark * color_table[NUM_COLORS + MARK_MASK + mark] + (1u - has_mark) * fg_as_uint;
    vec3 foreground = color_to_vec(fg_as_uint);
    CellData cell_data = set_vertex_position(foreground, bg);
    // }}}

    // Foreground {{{
#ifndef ONLY_BACKGROUND // background does not depend on foreground
    float has_dim = float((text_attrs >> DIM_SHIFT) & BIT_MASK), has_blink = float((text_attrs >> BLINK_SHIFT) & BIT_MASK);
    effective_text_alpha = inactive_text_alpha * if_one_then(has_dim, dim_opacity, 1.0) * if_one_then(
            has_blink, blink_opacity, 1.0);
    float in_url = float((is_selected >> 1) & BIT_MASK);
    decoration_fg = if_one_then(in_url, color_to_vec(url_color), to_color(colors[2], fg_as_uint));
    // Selection
    vec3 selection_color = if_one_then(use_cell_bg_for_selection_fg, bg, color_to_vec(highlight_fg));
    selection_color = if_one_then(use_cell_fg_for_selection_fg, foreground, selection_color);
    foreground = if_one_then(float(is_selected & BIT_MASK), selection_color, foreground);
    decoration_fg = if_one_then(float(is_selected & BIT_MASK), selection_color, decoration_fg);
    // Underline and strike through (rendered via sprites)
    uvec2 decs = get_decorations_indices(uint(in_url), text_attrs);
    strike_pos = to_sprite_pos(cell_data.pos, decs[0]);
    underline_pos = to_sprite_pos(cell_data.pos, decs[1]);
    underline_exclusion_pos = to_underline_exclusion_pos();

    // Cursor
    cursor_color_premult = vec4(cell_data.cursor.bg * cursor_opacity, cursor_opacity);
    vec3 final_cursor_text_color = mix(foreground, cell_data.cursor.fg, cursor_opacity);
    foreground = if_one_then(cell_data.has_block_cursor, final_cursor_text_color, foreground);
    decoration_fg = if_one_then(cell_data.has_block_cursor, final_cursor_text_color, decoration_fg);
    cursor_pos = to_sprite_pos(cell_data.pos, cell_data.cursor_fg_sprite_idx * uint(cell_data.has_cursor));
#endif
    // }}}

    // Background {{{
    float bg_alpha = calc_background_opacity(bg_as_uint);
    // we use max so that opacity of the block cursor cell background goes from bg_alpha to 1
    float effective_cursor_opacity = max(cursor_opacity, bg_alpha);
    // is_special_cell is either 0 or 1
    float is_special_cell = cell_data.has_block_cursor + float(is_selected & BIT_MASK);
    is_special_cell += float(is_reversed);  // reverse video cells should be opaque as well
    is_special_cell = zero_or_one(is_special_cell);
    cell_has_default_bg = if_one_then(is_special_cell, 0., cell_has_default_bg);

    // special cells must always be fully opaque, otherwise leave bg_alpha untouched
    bg_alpha = if_one_then(is_special_cell, 1.f, bg_alpha);
    // Selection and cursor
    bg_alpha = if_one_then(cell_data.has_block_cursor, effective_cursor_opacity, bg_alpha);
    bg = if_one_then(float(is_selected & BIT_MASK), if_one_then(use_cell_for_selection_bg, color_to_vec(fg_as_uint), color_to_vec(highlight_bg)), bg);
    vec3 background_rgb = if_one_then(cell_data.has_block_cursor, mix(bg, cell_data.cursor.bg, cursor_opacity), bg);
    background = background_rgb;
    // }}}

#if !defined(ONLY_BACKGROUND) && defined(OVERRIDE_FG_COLORS)
    decoration_fg = override_foreground_color(decoration_fg, background_rgb);
    foreground = override_foreground_color(foreground, background_rgb);
#endif

#if !defined(ONLY_FOREGROUND)
    vec4 bgpremul = vec4_premul(background_rgb, bg_alpha);
    // draw_bg_bitfield has bit 0 set to draw default bg cells and bit 1 set to draw non-default bg cells
    float cell_has_non_default_bg = 1.f - cell_has_default_bg;
    uint draw_bg_mask = uint(2.f * cell_has_non_default_bg + cell_has_default_bg); // 1 if has default bg else 2
    float draw_bg = step(0.5, float(draw_bg_bitfield & draw_bg_mask));
    bgpremul *= draw_bg;
    effective_background_premul = bgpremul;
#endif

#ifndef ONLY_BACKGROUND
    cell_foreground = foreground;
#endif
}
