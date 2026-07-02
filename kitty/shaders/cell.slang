#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// https://github.com/shader-slang/slang/issues/11874
// warnings-disable: 41012

import utils;
import hsluv;

#define NUM_COLORS 256

extern static const bool DO_FG_OVERRIDE;
extern static const uint FG_OVERRIDE_ALGO;
extern static const float FG_OVERRIDE_THRESHOLD;
extern static const bool TEXT_NEW_GAMMA;
extern static const bool ONLY_FOREGROUND;
extern static const bool ONLY_BACKGROUND;
static const bool OVERRIDE_FG_COLORS = DO_FG_OVERRIDE == 1 && !ONLY_BACKGROUND;

// Inputs {{{
struct CellRenderDataStruct
{
    float use_cell_bg_for_selection_fg, use_cell_fg_for_selection_fg, use_cell_for_selection_bg;

    uint default_fg, highlight_fg, highlight_bg, main_cursor_fg, main_cursor_bg, url_color, url_style, inverted, extra_cursor_fg, extra_cursor_bg;

    uint columns, lines, sprites_xnum, sprites_ynum, cursor_shape, cell_width, cell_height;
    uint cursor_x1, cursor_x2, cursor_y1, cursor_y2;
    float cursor_opacity, inactive_text_alpha, dim_opacity, blink_opacity;

    // must have unique entries with 0 being default_bg and unset being UINT32_MAX
    uint bg_colors0, bg_colors1, bg_colors2, bg_colors3, bg_colors4, bg_colors5, bg_colors6, bg_colors7;
    float bg_opacities0, bg_opacities1, bg_opacities2, bg_opacities3, bg_opacities4, bg_opacities5, bg_opacities6, bg_opacities7;
};

// Uniform Blocks (adjust binding slots as needed for your pipeline layout)
ConstantBuffer<CellRenderDataStruct> crd;

struct ColorTableStruct
{
    uint color_table[NUM_COLORS + MARK_MASK + MARK_MASK + 2];
};

ConstantBuffer<ColorTableStruct> ColorTable;
#define color_table ColorTable.color_table

uniform float gamma_lut[256];
uniform Sampler2D<uint4> sprite_decorations_map;
//

static const int fg_index_map[3] = {0, 1, 0};
static const uint2 cell_pos_map[4] = {
    uint2(1u, 0u),  // right, top
    uint2(1u, 1u),  // right, bottom
    uint2(0u, 1u),  // left, bottom
    uint2(0u, 0u)   // left, top
};
static const uint cursor_shape_map[] = {  // maps cursor shape to foreground sprite index
   0u,  // NO_CURSOR
   0u,  // BLOCK  (this is rendered as background)
   2u,  // BEAM
   3u,  // UNDERLINE
   4u   // UNFOCUSED
};

// Vertex Input Attributes with explicit fixed locations
struct VertexInput
{
    [[vk::location(0)]] uint3 colors;
    [[vk::location(1)]] uint2 sprite_idx;
    [[vk::location(2)]] uint  is_selected;
};
// }}}

// Utility functions {{{

static const uint BYTE_MASK = 0xFF;
static const uint SPRITE_INDEX_MASK = 0x7fffffff;
static const uint SPRITE_COLORED_MASK = 0x80000000;
static const uint SPRITE_COLORED_SHIFT = 31u;
static const uint BIT_MASK = 1u;
// Linear space luminance values
static const float3 Y = float3(0.2126, 0.7152, 0.0722);

float3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return float3(gamma_lut[r], gamma_lut[g], gamma_lut[b]);
}

float one_if_equal_zero_otherwise(float a, float b) {
    return (1.0f - zero_or_one(abs(float(a) - float(b))));
}

// We need an integer variant to accommodate GPU driver bugs, see
// https://github.com/kovidgoyal/kitty/issues/9072
uint one_if_equal_zero_otherwise(int a, int b) {
    return (1u - uint(zero_or_one(abs(float(a) - float(b)))));
}

uint one_if_equal_zero_otherwise(uint a, uint b) {
    return (1u - uint(zero_or_one(abs(float(a) - float(b)))));
}

uint resolve_color(uint c, uint defval) {
    int t = int(c & BYTE_MASK);
    uint is_one = one_if_equal_zero_otherwise(t, 1);
    uint is_two = one_if_equal_zero_otherwise(t, 2);
    uint is_neither_one_nor_two = 1u - is_one - is_two;
    return is_one * color_table[(c >> 8) & BYTE_MASK] + is_two * (c >> 8) + is_neither_one_nor_two * defval;
}

float3 to_color(uint c, uint defval) {
    return color_to_vec(resolve_color(c, defval));
}

[ForceInline]
float3 q_func(float type_val, uint which, float3 val) {
    return one_if_equal_zero_otherwise(type_val, float(which)) * val;
}

float3 resolve_dynamic_color(uint c, float3 special_val, float3 defval) {
    float type_val = float((c >> 24) & BYTE_MASK);
    return (
        q_func(type_val, COLOR_IS_RGB, color_to_vec(c)) +
        q_func(type_val, COLOR_IS_INDEX, color_to_vec(color_table[c & BYTE_MASK])) +
        q_func(type_val, COLOR_IS_SPECIAL, special_val) +
        q_func(type_val, COLOR_NOT_SET, defval)
    );
}

float contrast_ratio(float under_luminance, float over_luminance) {
    return clamp((max(under_luminance, over_luminance) + 0.05f) / (min(under_luminance, over_luminance) + 0.05f), 1.f, 21.f);
}

float contrast_ratio(float3 a, float3 b) {
    return contrast_ratio(dot(a, Y), dot(b, Y));
}

struct ColorPair {
    float3 bg, fg;
};

float contrast_ratio(ColorPair a) {
    return contrast_ratio(a.bg, a.fg);
}

ColorPair if_less_than_pair(float a, float b, ColorPair thenval, ColorPair elseval) {
    return ColorPair(
        if_less_than(a, b, thenval.bg, elseval.bg),
        if_less_than(a, b, thenval.fg, elseval.fg)
    );
}

ColorPair if_one_then_pair(float condition, ColorPair thenval, ColorPair elseval) {
    return ColorPair(
        if_one_then(condition, thenval.bg, elseval.bg),
        if_one_then(condition, thenval.fg, elseval.fg)
    );
}

ColorPair resolve_extra_cursor_colors_for_special_cursor(float3 cell_bg, float3 cell_fg) {
    ColorPair cell = ColorPair(cell_fg, cell_bg);
    ColorPair base = ColorPair(color_to_vec(crd.default_fg), color_to_vec(crd.bg_colors0));
    float cr = contrast_ratio(cell);
    float br = contrast_ratio(base);
    ColorPair higher_contrast_pair = if_less_than_pair(cr, br, base, cell);
    return if_less_than_pair(cr, 2.5f, higher_contrast_pair, cell);
}

ColorPair resolve_extra_cursor_colors(float3 cell_bg, float3 cell_fg, ColorPair main_cursor) {
    ColorPair ans = ColorPair(
        resolve_dynamic_color(crd.extra_cursor_bg, main_cursor.bg, main_cursor.bg),
        resolve_dynamic_color(crd.extra_cursor_fg, cell_bg, main_cursor.fg)
    );
    ColorPair special = resolve_extra_cursor_colors_for_special_cursor(cell_bg, cell_fg);
    return if_one_then_pair(zero_or_one(abs(float(crd.extra_cursor_bg & BYTE_MASK) - float(COLOR_IS_SPECIAL))), ans, special);
}

uint3 to_sprite_coords(uint idx) {
    uint sprites_per_page = crd.sprites_xnum * crd.sprites_ynum;
    uint z = idx / sprites_per_page;
    uint num_on_last_page = idx - sprites_per_page * z;
    uint y = num_on_last_page / crd.sprites_xnum;
    uint x = num_on_last_page - crd.sprites_xnum * y;
    return uint3(x, y, z);
}

float3 to_sprite_pos(uint2 pos, uint idx) {
    uint3 c = to_sprite_coords(idx);
    float2 s_xpos = float2(float(c.x), float(c.x) + 1.0f) * (1.0f / float(crd.sprites_xnum));
    float2 s_ypos = float2(float(c.y), float(c.y) + 1.0f) * (1.0f / float(crd.sprites_ynum));
    uint texture_height_px = (crd.cell_height + 1u) * crd.sprites_ynum;
    float row_height = 1.0f / float(texture_height_px);
    s_ypos[1] -= row_height;  // skip the decorations_exclude row
    return float3(s_xpos[pos.x], s_ypos[pos.y], float(c.z));
}

uint to_underline_exclusion_pos(uint2 sprite_idx) {
    uint3 c = to_sprite_coords(sprite_idx[0]);
    uint cell_top_px = c.y * (crd.cell_height + 1u);
    return cell_top_px + crd.cell_height;
}

uint read_sprite_decorations_idx(uint2 sprite_idx) {
    int idx = int(sprite_idx[0] & SPRITE_INDEX_MASK);
    int width, height;
    sprite_decorations_map.GetDimensions(width, height);
    int2 sz = int2(width, height);
    int y = idx / sz[0];
    int x = idx - y * sz[0];
    return sprite_decorations_map[int2(x, y)].r;
}

uint2 get_decorations_indices(uint2 sprite_idx, uint in_url /* [0, 1] */, uint text_attrs) {
    uint decorations_idx = read_sprite_decorations_idx(sprite_idx);
    uint has_decorations = uint(zero_or_one(float(decorations_idx)));
    uint strike_style = ((text_attrs >> STRIKE_SHIFT) & BIT_MASK); // 0 or 1
    uint strike_idx = decorations_idx * strike_style;
    uint underline_style = ((text_attrs >> DECORATION_SHIFT) & DECORATION_MASK);
    underline_style = in_url * crd.url_style + (1u - in_url) * underline_style; // [0, 5]
    uint has_underline = uint(step(0.5f, float(underline_style)));  // [0, 1]
    return has_decorations * uint2(strike_idx, has_underline * (decorations_idx + underline_style));
}

uint is_cursor(uint x, uint y) {
    uint clamped_x = clamp(x, crd.cursor_x1, crd.cursor_x2);
    uint clamped_y = clamp(y, crd.cursor_y1, crd.cursor_y2);
    return one_if_equal_zero_otherwise(x, clamped_x) * one_if_equal_zero_otherwise(y, clamped_y);
}
// }}}

struct CellData {
    float has_cursor;
    float has_block_cursor;
    uint2 pos;
    uint cursor_fg_sprite_idx;
    ColorPair cursor;
};

struct VertexOutput {
    float4 position : SV_Position;

    float3 background;
    float4 effective_background_premul;
    float  effective_text_alpha;
    float3 sprite_pos;
    float3 underline_pos;
    float3 cursor_pos;
    float3 strike_pos;
    nointerpolation uint underline_exclusion_pos;
    float3 cell_foreground;
    float4 cursor_color_premult;
    float3 decoration_fg;
    float  colored_sprite;
};


CellData set_vertex_position(
    float3 cell_fg,
    float3 cell_bg,
    uint instance_id,
    uint vertex_id,
    float row_offset,
    uint2 sprite_idx,
    uint is_selected,
    inout VertexOutput vo,
) {
    CellData cell_out;
    float dx = 2.0 / float(crd.columns);
    float dy = 2.0 / float(crd.lines);

    // The current cell being rendered
    uint row = instance_id / crd.columns;
    uint column = instance_id - row * crd.columns;

    // The position of this vertex, at a corner of the cell
    float left = -1.0 + float(column) * dx;
    float top = 1.0 - (float(row) + row_offset) * dy;

    uint2 pos = cell_pos_map[vertex_id];

    float2 select_x = float2(left, left + dx);
    float2 select_y = float2(top, top - dy);
    float posX = select_x[pos.x];
    float posY = select_y[pos.y];
    vo.position = float4(posX, posY, 0.0, 1.0);

    // The character sprite being rendered
    if (!ONLY_BACKGROUND) {
        vo.sprite_pos = to_sprite_pos(pos, sprite_idx[0] & SPRITE_INDEX_MASK);
        vo.colored_sprite = float((sprite_idx[0] & SPRITE_COLORED_MASK) >> SPRITE_COLORED_SHIFT);
    }

    // Cursor shape and colors
    float has_main_cursor = float(is_cursor(column, row));
    float multicursor_shape = float((is_selected >> 2) & 3u);
    float multicursor_uses_main_cursor_shape = float((is_selected >> 4) & BIT_MASK);
    multicursor_shape = if_one_then(multicursor_uses_main_cursor_shape, crd.cursor_shape, multicursor_shape);

    float final_cursor_shape = if_one_then(has_main_cursor, crd.cursor_shape, multicursor_shape);
    float has_cursor = zero_or_one(final_cursor_shape);
    float is_block_cursor = has_cursor * one_if_equal_zero_otherwise(final_cursor_shape, 1.0);

    ColorPair main_cursor;
    main_cursor.bg = color_to_vec(crd.main_cursor_bg);
    main_cursor.fg = color_to_vec(crd.main_cursor_fg);

    ColorPair extra_cursor = resolve_extra_cursor_colors(cell_bg, cell_fg, main_cursor);
    ColorPair cursor = if_one_then_pair(has_main_cursor, main_cursor, extra_cursor);

    cell_out.has_cursor = has_cursor;
    cell_out.has_block_cursor = is_block_cursor;
    cell_out.pos = pos;
    cell_out.cursor_fg_sprite_idx = cursor_shape_map[int(final_cursor_shape)];
    cell_out.cursor = cursor;

    return cell_out;
}

float background_opacity_for(uint bg, uint colorval, float opacity_if_matched) {
    float not_matched = step(1.0, abs(float(colorval) - float(bg)));
    return not_matched + opacity_if_matched * (1.0 - not_matched);
}

float calc_background_opacity(uint bg) {
    return (
        background_opacity_for(bg, crd.bg_colors0, crd.bg_opacities0) *
        background_opacity_for(bg, crd.bg_colors1, crd.bg_opacities1) *
        background_opacity_for(bg, crd.bg_colors2, crd.bg_opacities2) *
        background_opacity_for(bg, crd.bg_colors3, crd.bg_opacities3) *
        background_opacity_for(bg, crd.bg_colors4, crd.bg_opacities4) *
        background_opacity_for(bg, crd.bg_colors5, crd.bg_opacities5) *
        background_opacity_for(bg, crd.bg_colors6, crd.bg_opacities6) *
        background_opacity_for(bg, crd.bg_colors7, crd.bg_opacities7)
    );
}

// Override foreground colors {{{
float3 fg_override_luminance(float colored_sprite, float under_luminance, float over_lumininace, float3 under, float3 over) {
    // If the difference in luminance is too small,
    // force the foreground color to be black or white.
    float diff_luminance = abs(under_luminance - over_lumininace);
	float override_level = (1.f - colored_sprite) * step(diff_luminance, FG_OVERRIDE_THRESHOLD);
	float original_level = 1.f - override_level;
	return original_level * over + override_level * float3(step(under_luminance, 0.5f));
}

float3 fg_override_contrast(float under_luminance, float over_luminance, float3 under, float3 over) {
    float ratio = contrast_ratio(under_luminance, over_luminance);
    float3 diff = abs(under - over);
    float3 over_hsluv = rgbToHsluv(over);
    const float min_contrast_ratio = FG_OVERRIDE_THRESHOLD;
    float target_lum_a = clamp((under_luminance + 0.05) * min_contrast_ratio - 0.05, 0.0, 1.0);
    float target_lum_b = clamp((under_luminance + 0.05) / min_contrast_ratio - 0.05, 0.0, 1.0);
    float3 result_a = clamp(hsluvToRgb(float3(over_hsluv.x, over_hsluv.y, target_lum_a * 100.0)), 0.0, 1.0);
    float3 result_b = clamp(hsluvToRgb(float3(over_hsluv.x, over_hsluv.y, target_lum_b * 100.0)), 0.0, 1.0);
    float result_a_ratio = contrast_ratio(under_luminance, dot(result_a, Y));
    float result_b_ratio = contrast_ratio(under_luminance, dot(result_b, Y));
    float3 result = lerp(result_a, result_b, step(result_a_ratio, result_b_ratio));
    float fallback_condition = max(step(diff.x + diff.y + diff.z, 0.001), step(min_contrast_ratio, ratio));
    return lerp(result, over, fallback_condition);
}

float3 override_foreground_color(float3 over, float3 under, float colored_sprite) {
    float under_luminance = dot(under, Y);
    float over_lumininace = dot(over.rgb, Y);
    if (FG_OVERRIDE_ALGO == 1) return fg_override_luminance(colored_sprite, under_luminance, over_lumininace, under, over);
    return fg_override_contrast(under_luminance, over_lumininace, under, over);
}
// }}}

[shader("vertex")]
VertexOutput vertex_main(
    VertexInput vi,
    uint vertex_id : SV_VertexID,
    uint instance_id : SV_InstanceID,
    uniform uint draw_bg_bitfield,
    uniform float row_offset,
) {
    VertexOutput vo;

    // set cell color indices {{{
    uint2 default_colors = uint2(crd.default_fg, crd.bg_colors0);
    uint text_attrs = vi.sprite_idx[1];
    uint is_reversed = ((text_attrs >> REVERSE_SHIFT) & BIT_MASK);
    uint is_inverted = is_reversed + crd.inverted;
    int fg_index = fg_index_map[is_inverted];
    int bg_index = 1 - fg_index;
    int mark = int(text_attrs >> MARK_SHIFT) & MARK_MASK;
    uint has_mark = uint(step(1, float(mark)));
    uint bg_as_uint = resolve_color(vi.colors[bg_index], default_colors[bg_index]);
    bg_as_uint = has_mark * color_table[NUM_COLORS + mark - 1] + (BIT_MASK - has_mark) * bg_as_uint;
    float cell_has_default_bg = 1.f - step(1.f, abs(float(bg_as_uint - crd.bg_colors0))); // 1 if has default bg else 0
    float3 bg = color_to_vec(bg_as_uint);
    uint fg_as_uint = resolve_color(vi.colors[fg_index], default_colors[fg_index]);
    fg_as_uint = has_mark * color_table[NUM_COLORS + MARK_MASK + mark] + (1u - has_mark) * fg_as_uint;
    float3 foreground = color_to_vec(fg_as_uint);
    CellData cell_data = set_vertex_position(foreground, bg, instance_id, vertex_id, row_offset, vi.sprite_idx, vi.is_selected, vo);
    // }}}


    // Foreground {{{
    if (!ONLY_BACKGROUND) { // background does not depend on foreground
        float has_dim = float((text_attrs >> DIM_SHIFT) & BIT_MASK), has_blink = float((text_attrs >> BLINK_SHIFT) & BIT_MASK);
        vo.effective_text_alpha = crd.inactive_text_alpha * if_one_then(has_dim, crd.dim_opacity, 1.0) * if_one_then(
                has_blink, crd.blink_opacity, 1.0);
        float in_url = float((vi.is_selected >> 1) & BIT_MASK);
        vo.decoration_fg = if_one_then(in_url, color_to_vec(crd.url_color), to_color(vi.colors[2], fg_as_uint));
        // Selection
        float3 selection_color = if_one_then(crd.use_cell_bg_for_selection_fg, bg, color_to_vec(crd.highlight_fg));
        selection_color = if_one_then(crd.use_cell_fg_for_selection_fg, foreground, selection_color);
        foreground = if_one_then(float(vi.is_selected & BIT_MASK), selection_color, foreground);
        vo.decoration_fg = if_one_then(float(vi.is_selected & BIT_MASK), selection_color, vo.decoration_fg);
        // Underline and strike through (rendered via sprites)
        uint2 decs = get_decorations_indices(vi.sprite_idx, uint(in_url), text_attrs);
        vo.strike_pos = to_sprite_pos(cell_data.pos, decs[0]);
        vo.underline_pos = to_sprite_pos(cell_data.pos, decs[1]);
        vo.underline_exclusion_pos = to_underline_exclusion_pos(vi.sprite_idx);

        // Cursor
        vo.cursor_color_premult = float4(cell_data.cursor.bg * crd.cursor_opacity, crd.cursor_opacity);
        float3 final_cursor_text_color = lerp(foreground, cell_data.cursor.fg, crd.cursor_opacity);
        foreground = if_one_then(cell_data.has_block_cursor, final_cursor_text_color, foreground);
        vo.decoration_fg = if_one_then(cell_data.has_block_cursor, final_cursor_text_color, vo.decoration_fg);
        vo.cursor_pos = to_sprite_pos(cell_data.pos, cell_data.cursor_fg_sprite_idx * uint(cell_data.has_cursor));
    }
    // }}}

    // Background {{{
    float bg_alpha = calc_background_opacity(bg_as_uint);
    // we use max so that opacity of the block cursor cell background goes from bg_alpha to 1
    float effective_cursor_opacity = max(crd.cursor_opacity, bg_alpha);
    // is_special_cell is either 0 or 1
    float is_special_cell = cell_data.has_block_cursor + float(vi.is_selected & BIT_MASK);
    is_special_cell += float(is_reversed);  // reverse video cells should be opaque as well
    is_special_cell = zero_or_one(is_special_cell);
    cell_has_default_bg = if_one_then(is_special_cell, 0., cell_has_default_bg);

    // special cells must always be fully opaque, otherwise leave bg_alpha untouched
    bg_alpha = if_one_then(is_special_cell, 1.f, bg_alpha);
    // Selection and cursor
    bg_alpha = if_one_then(cell_data.has_block_cursor, effective_cursor_opacity, bg_alpha);
    bg = if_one_then(float(vi.is_selected & BIT_MASK), if_one_then(crd.use_cell_for_selection_bg, color_to_vec(fg_as_uint), color_to_vec(crd.highlight_bg)), bg);
    float3 background_rgb = if_one_then(cell_data.has_block_cursor, lerp(bg, cell_data.cursor.bg, crd.cursor_opacity), bg);
    vo.background = background_rgb;
    // }}}

    if (!ONLY_BACKGROUND && OVERRIDE_FG_COLORS) {
        vo.decoration_fg = override_foreground_color(vo.decoration_fg, background_rgb, vo.colored_sprite);
        foreground = override_foreground_color(foreground, background_rgb, vo.colored_sprite);
    }

    if (!ONLY_FOREGROUND) {
        float4 bgpremul = vec4_premul(background_rgb, bg_alpha);
        // draw_bg_bitfield has bit 0 set to draw default bg cells and bit 1 set to draw non-default bg cells
        float cell_has_non_default_bg = 1.f - cell_has_default_bg;
        uint draw_bg_mask = uint(2.f * cell_has_non_default_bg + cell_has_default_bg); // 1 if has default bg else 2
        float draw_bg = step(0.5, float(draw_bg_bitfield & draw_bg_mask));
        bgpremul *= draw_bg;
        vo.effective_background_premul = bgpremul;
    }

    if (!ONLY_BACKGROUND) vo.cell_foreground = foreground;

    return vo;
}


