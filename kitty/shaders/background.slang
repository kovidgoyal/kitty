#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// https://github.com/shader-slang/slang/issues/11874
// warnings-disable: 41012

module background;

import utils;

#define NUM_COLORS 256

// Inputs {{{
public struct CellRenderData
{
    public float use_cell_bg_for_selection_fg, use_cell_fg_for_selection_fg, use_cell_for_selection_bg;

    public uint default_fg, highlight_fg, highlight_bg, main_cursor_fg, main_cursor_bg, url_color, url_style, inverted, extra_cursor_fg, extra_cursor_bg;

    public uint columns, lines, sprites_xnum, sprites_ynum, cursor_shape, cell_width, cell_height;
    public uint cursor_x1, cursor_x2, cursor_y1, cursor_y2;
    public float cursor_opacity, inactive_text_alpha, fg_override_threshold, row_offset, dim_opacity, blink_opacity;

    // must have unique entries with 0 being default_bg and unset being UINT32_MAX
    public uint bg_colors0, bg_colors1, bg_colors2, bg_colors3, bg_colors4, bg_colors5, bg_colors6, bg_colors7;
    public float bg_opacities0, bg_opacities1, bg_opacities2, bg_opacities3, bg_opacities4, bg_opacities5, bg_opacities6, bg_opacities7;
};

// Uniform Blocks (adjust binding slots as needed for your pipeline layout)
public ConstantBuffer<CellRenderData> crd;

public struct ColorTable {
    uint color_table[NUM_COLORS + MARK_MASK + MARK_MASK + 2];
};

public ConstantBuffer<ColorTable> ctb;
#define color_table ctb.color_table

public struct GammaLUT {
    float gamma_lut[256];
};

public ConstantBuffer<GammaLUT> glt;
#define gamma_lut glt.gamma_lut
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

// }}}

// Utility functions {{{

public static const uint BYTE_MASK = 0xFF;
public static const uint BIT_MASK = 1u;
// Linear space luminance values
public static const float3 Y = float3(0.2126, 0.7152, 0.0722);

public float3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return float3(gamma_lut[r], gamma_lut[g], gamma_lut[b]);
}

public float one_if_equal_zero_otherwise(float a, float b) {
    return (1.0f - zero_or_one(abs(float(a) - float(b))));
}

// We need an integer variant to accommodate GPU driver bugs, see
// https://github.com/kovidgoyal/kitty/issues/9072
public uint one_if_equal_zero_otherwise(int a, int b) {
    return (1u - uint(zero_or_one(abs(float(a) - float(b)))));
}

public uint one_if_equal_zero_otherwise(uint a, uint b) {
    return (1u - uint(zero_or_one(abs(float(a) - float(b)))));
}

public uint resolve_color(uint c, uint defval) {
    int t = int(c & BYTE_MASK);
    uint is_one = one_if_equal_zero_otherwise(t, 1);
    uint is_two = one_if_equal_zero_otherwise(t, 2);
    uint is_neither_one_nor_two = 1u - is_one - is_two;
    return is_one * color_table[(c >> 8) & BYTE_MASK] + is_two * (c >> 8) + is_neither_one_nor_two * defval;
}

public float3 to_color(uint c, uint defval) {
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

public float contrast_ratio(float under_luminance, float over_luminance) {
    return clamp((max(under_luminance, over_luminance) + 0.05f) / (min(under_luminance, over_luminance) + 0.05f), 1.f, 21.f);
}

public float contrast_ratio(float3 a, float3 b) {
    return contrast_ratio(dot(a, Y), dot(b, Y));
}

public struct ColorPair {
    public float3 bg, fg;
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

uint is_cursor(uint x, uint y) {
    uint clamped_x = clamp(x, crd.cursor_x1, crd.cursor_x2);
    uint clamped_y = clamp(y, crd.cursor_y1, crd.cursor_y2);
    return one_if_equal_zero_otherwise(x, clamped_x) * one_if_equal_zero_otherwise(y, clamped_y);
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
// }}}

public struct CellData {
    public float has_cursor;
    public float has_block_cursor;
    public uint2 pos;
    public uint cursor_fg_sprite_idx;
    public ColorPair cursor;
};

// The complete per-cell background computation, shared by the cell shader and
// the padding shader. It computes the cell position and the final background
// color (accounting for marks, reverse video, selection and the block cursor),
// plus the intermediate data the cell foreground pass needs.
public struct BackgroundOutput {
    public float4 position;
    public float3 background_rgb;    // final background color (linear, post cursor/selection)
    public float bg_alpha;           // final alpha, post special-cell opacity (pre draw_bg_bitfield mask)
    public float cell_has_default_bg;
    public float3 bg;                // original background color, pre selection/cursor (used for selection fg)
    public float3 foreground;        // resolved foreground color, pre selection/override
    public uint fg_as_uint;
    public uint text_attrs;
    public uint is_reversed;
    public CellData cell_data;
};

public BackgroundOutput compute_background(
    uint3 colors, uint2 sprite_idx, uint is_selected, uint instance_id, uint vertex_id
) {
    BackgroundOutput bo;

    // set cell color indices {{{
    uint2 default_colors = uint2(crd.default_fg, crd.bg_colors0);
    uint text_attrs = sprite_idx[1];
    uint is_reversed = ((text_attrs >> REVERSE_SHIFT) & BIT_MASK);
    uint is_inverted = is_reversed + crd.inverted;
    int fg_index = fg_index_map[is_inverted];
    int bg_index = 1 - fg_index;
    int mark = int(text_attrs >> MARK_SHIFT) & MARK_MASK;
    uint has_mark = uint(step(1, float(mark)));
    uint bg_as_uint = resolve_color(colors[bg_index], default_colors[bg_index]);
    bg_as_uint = has_mark * color_table[NUM_COLORS + mark - 1] + (BIT_MASK - has_mark) * bg_as_uint;
    float cell_has_default_bg = 1.f - step(1.f, abs(float(bg_as_uint - crd.bg_colors0))); // 1 if has default bg else 0
    float3 bg = color_to_vec(bg_as_uint);
    float3 cell_bg = bg;  // preserve original bg for the selection foreground color
    uint fg_as_uint = resolve_color(colors[fg_index], default_colors[fg_index]);
    fg_as_uint = has_mark * color_table[NUM_COLORS + MARK_MASK + mark] + (1u - has_mark) * fg_as_uint;
    float3 foreground = color_to_vec(fg_as_uint);
    // }}}

    // Cell position {{{
    float dx = 2.0 / float(crd.columns);
    float dy = 2.0 / float(crd.lines);

    // The current cell being rendered
    uint row = instance_id / crd.columns;
    uint column = instance_id - row * crd.columns;

    // The position of this vertex, at a corner of the cell
    float left = -1.0 + float(column) * dx;
    float top = 1.0 - (float(row) + crd.row_offset) * dy;

    uint2 pos = cell_pos_map[vertex_id];

    float2 select_x = float2(left, left + dx);
    float2 select_y = float2(top, top - dy);
    bo.position = float4(select_x[pos.x], select_y[pos.y], 0.0, 1.0);
    // }}}

    // Cursor shape and colors {{{
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

    ColorPair extra_cursor = resolve_extra_cursor_colors(cell_bg, foreground, main_cursor);
    ColorPair cursor = if_one_then_pair(has_main_cursor, main_cursor, extra_cursor);

    CellData cell_data;
    cell_data.has_cursor = has_cursor;
    cell_data.has_block_cursor = is_block_cursor;
    cell_data.pos = pos;
    cell_data.cursor_fg_sprite_idx = cursor_shape_map[int(final_cursor_shape)];
    cell_data.cursor = cursor;
    // }}}

    // Background {{{
    float bg_alpha = calc_background_opacity(bg_as_uint);
    // we use max so that opacity of the block cursor cell background goes from bg_alpha to 1
    float effective_cursor_opacity = max(crd.cursor_opacity, bg_alpha);
    // is_special_cell is either 0 or 1
    float is_special_cell = cell_data.has_block_cursor + float(is_selected & BIT_MASK);
    is_special_cell += float(is_reversed);  // reverse video cells should be opaque as well
    is_special_cell = zero_or_one(is_special_cell);
    cell_has_default_bg = if_one_then(is_special_cell, 0., cell_has_default_bg);

    // special cells must always be fully opaque, otherwise leave bg_alpha untouched
    bg_alpha = if_one_then(is_special_cell, 1.f, bg_alpha);
    // Selection and cursor
    bg_alpha = if_one_then(cell_data.has_block_cursor, effective_cursor_opacity, bg_alpha);
    bg = if_one_then(float(is_selected & BIT_MASK), if_one_then(crd.use_cell_for_selection_bg, color_to_vec(fg_as_uint), color_to_vec(crd.highlight_bg)), bg);
    float3 background_rgb = if_one_then(cell_data.has_block_cursor, lerp(bg, cell_data.cursor.bg, crd.cursor_opacity), bg);
    // }}}

    bo.background_rgb = background_rgb;
    bo.bg_alpha = bg_alpha;
    bo.cell_has_default_bg = cell_has_default_bg;
    bo.bg = cell_bg;
    bo.foreground = foreground;
    bo.fg_as_uint = fg_as_uint;
    bo.text_attrs = text_attrs;
    bo.is_reversed = is_reversed;
    bo.cell_data = cell_data;
    return bo;
}

// Return the premultiplied background color for a cell, used by the padding
// shader to color padding regions to match their neighboring cell. This is the
// same as the cell background pass but without the draw_bg_bitfield masking, so
// the padding is always drawn. The premultiplied alpha ensures padding matches
// its neighboring cell under a semi-transparent OS window.
public float4 padding_background_premul(uint3 colors, uint2 sprite_idx, uint is_selected, uint instance_id) {
    BackgroundOutput bo = compute_background(colors, sprite_idx, is_selected, instance_id, 0u);
    return vec4_premul(bo.background_rgb, bo.bg_alpha);
}
