#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// https://github.com/shader-slang/slang/issues/11874
// warnings-disable: 41012

import utils;
import hsluv;
import alpha_blend;
import linear2srgb;
import background;

extern static const uint FG_OVERRIDE_ALGO;
extern static const bool TEXT_NEW_GAMMA;
extern static const uint RENDER_MODE;

static const bool ONLY_FOREGROUND = RENDER_MODE == 2;
static const bool ONLY_BACKGROUND = RENDER_MODE == 1;

// The background color computation, the cell render data, color table and gamma
// LUT as well as most color utility functions live in the background module so
// that they can be shared with the padding shader.

uniform Sampler2D<uint4> sprite_decorations_map;

static const uint SPRITE_INDEX_MASK = 0x7fffffff;
static const uint SPRITE_COLORED_MASK = 0x80000000;
static const uint SPRITE_COLORED_SHIFT = 31u;

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

// Foreground utility functions {{{
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
// }}}

// Override foreground colors {{{
float3 fg_override_luminance(float colored_sprite, float under_luminance, float over_lumininace, float3 under, float3 over) {
    // If the difference in luminance is too small,
    // force the foreground color to be black or white.
    float diff_luminance = abs(under_luminance - over_lumininace);
	float override_level = (1.f - colored_sprite) * step(diff_luminance, crd.fg_override_threshold);
	float original_level = 1.f - override_level;
	return original_level * over + override_level * float3(step(under_luminance, 0.5f));
}

float3 fg_override_contrast(float under_luminance, float over_luminance, float3 under, float3 over) {
    float ratio = contrast_ratio(under_luminance, over_luminance);
    float3 diff = abs(under - over);
    float3 over_hsluv = rgbToHsluv(over);
    const float min_contrast_ratio = crd.fg_override_threshold;
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
    [[vk::location(0)]] uint3 colors,
    [[vk::location(1)]] uint2 sprite_idx,
    [[vk::location(2)]] uint  is_selected,
    uint vertex_id : SV_VertexID,
    uint instance_id : SV_InstanceID,
    uniform uint draw_bg_bitfield,
) {
    VertexOutput vo;

    BackgroundOutput bo = compute_background(colors, sprite_idx, is_selected, instance_id, vertex_id);
    vo.position = bo.position;
    float3 background_rgb = bo.background_rgb;
    float3 foreground = bo.foreground;
    uint fg_as_uint = bo.fg_as_uint;
    uint text_attrs = bo.text_attrs;
    CellData cell_data = bo.cell_data;

    // Foreground {{{
    if (!ONLY_BACKGROUND) { // background does not depend on foreground
        // The character sprite being rendered
        vo.sprite_pos = to_sprite_pos(cell_data.pos, sprite_idx[0] & SPRITE_INDEX_MASK);
        vo.colored_sprite = float((sprite_idx[0] & SPRITE_COLORED_MASK) >> SPRITE_COLORED_SHIFT);

        float has_dim = float((text_attrs >> DIM_SHIFT) & BIT_MASK), has_blink = float((text_attrs >> BLINK_SHIFT) & BIT_MASK);
        vo.effective_text_alpha = crd.inactive_text_alpha * if_one_then(has_dim, crd.dim_opacity, 1.0) * if_one_then(
                has_blink, crd.blink_opacity, 1.0);
        float in_url = float((is_selected >> 1) & BIT_MASK);
        vo.decoration_fg = if_one_then(in_url, color_to_vec(crd.url_color), to_color(colors[2], fg_as_uint));
        // Selection
        float3 selection_color = if_one_then(crd.use_cell_bg_for_selection_fg, bo.bg, color_to_vec(crd.highlight_fg));
        selection_color = if_one_then(crd.use_cell_fg_for_selection_fg, foreground, selection_color);
        foreground = if_one_then(float(is_selected & BIT_MASK), selection_color, foreground);
        vo.decoration_fg = if_one_then(float(is_selected & BIT_MASK), selection_color, vo.decoration_fg);
        // Underline and strike through (rendered via sprites)
        uint2 decs = get_decorations_indices(sprite_idx, uint(in_url), text_attrs);
        vo.strike_pos = to_sprite_pos(cell_data.pos, decs[0]);
        vo.underline_pos = to_sprite_pos(cell_data.pos, decs[1]);
        vo.underline_exclusion_pos = to_underline_exclusion_pos(sprite_idx);

        // Cursor
        vo.cursor_color_premult = float4(cell_data.cursor.bg * crd.cursor_opacity, crd.cursor_opacity);
        float3 final_cursor_text_color = lerp(foreground, cell_data.cursor.fg, crd.cursor_opacity);
        foreground = if_one_then(cell_data.has_block_cursor, final_cursor_text_color, foreground);
        vo.decoration_fg = if_one_then(cell_data.has_block_cursor, final_cursor_text_color, vo.decoration_fg);
        vo.cursor_pos = to_sprite_pos(cell_data.pos, cell_data.cursor_fg_sprite_idx * uint(cell_data.has_cursor));
    }
    // }}}

    vo.background = background_rgb;

    if (!ONLY_BACKGROUND && FG_OVERRIDE_ALGO > 0) {
        vo.decoration_fg = override_foreground_color(vo.decoration_fg, background_rgb, vo.colored_sprite);
        foreground = override_foreground_color(foreground, background_rgb, vo.colored_sprite);
    }

    if (!ONLY_FOREGROUND) {
        float4 bgpremul = vec4_premul(background_rgb, bo.bg_alpha);
        // draw_bg_bitfield has bit 0 set to draw default bg cells and bit 1 set to draw non-default bg cells
        float cell_has_non_default_bg = 1.f - bo.cell_has_default_bg;
        uint draw_bg_mask = uint(2.f * cell_has_non_default_bg + bo.cell_has_default_bg); // 1 if has default bg else 2
        float draw_bg = step(0.5, float(draw_bg_bitfield & draw_bg_mask));
        bgpremul *= draw_bg;
        vo.effective_background_premul = bgpremul;
    }

    if (!ONLY_BACKGROUND) vo.cell_foreground = foreground;

    return vo;
}

uniform Sampler2DArray sprites;
// Scaling factor for the extra text-alpha adjustment for luminance-difference.
static const float text_gamma_scaling = 0.5;

float clamp_to_unit_float(float x) {
    // Clamp value to suitable output range
    return clamp(x, 0.0f, 1.0f);
}

float4 foreground_contrast_new(float4 over, float3 under, float text_contrast, float text_gamma_adjustment) {
    float under_luminance = dot(under, Y);
    float over_lumininace = dot(over.rgb, Y);
    // Apply additional gamma-adjustment scaled by the luminance difference, the darker the foreground the more adjustment we apply.
    // A multiplicative contrast is also available to increase saturation.
    over.a = clamp_to_unit_float(lerp(over.a, pow(over.a, text_gamma_adjustment), (1 - over_lumininace + under_luminance) * text_gamma_scaling) * text_contrast);
    return over;
}

float4 foreground_contrast_old(float4 over, float3 under) {
    // Simulation of gamma-incorrect blending
    float under_luminance = dot(under, Y);
    float over_lumininace = dot(over.rgb, Y);
    // This is the original gamma-incorrect rendering, it is the solution of the following equation:
    //
    // linear2srgb(over * overA2 + under * (1 - overA2)) = linear2srgb(over) * over.a + linear2srgb(under) * (1 - over.a)
    // ^ gamma correct blending with new alpha             ^ gamma incorrect blending with old alpha
    over.a = clamp_to_unit_float((srgb2linear(linear2srgb(over_lumininace) * over.a + linear2srgb(under_luminance) * (1.0f - over.a)) - under_luminance) / (over_lumininace - under_luminance));
    return over;
}

float4 foreground_contrast(float4 over, float3 under, float text_contrast, float text_gamma_adjustment) {
    if (TEXT_NEW_GAMMA) return foreground_contrast_new(over, under, text_contrast, text_gamma_adjustment);
    return foreground_contrast_old(over, under);
}

float4 load_text_foreground_color(float3 sprite_pos, float colored_sprite, float3 cell_foreground) {
    // For colored sprites use the color from the sprite rather than the text foreground
    // Return non-premultiplied foreground color
    float4 text_fg = sprites.Sample(sprite_pos);
    return float4(lerp(cell_foreground, text_fg.xyz, colored_sprite), text_fg.w);
}

float4 calculate_premul_foreground_from_sprites(
    float3 sprite_pos, float3 underline_pos, float3 cursor_pos, float3 strike_pos, uint underline_exclusion_pos,
    float4 text_fg, float3 decoration_fg, float4 cursor_color_premult,
    float effective_text_alpha,
) {
    // Return premul foreground color from decorations (cursor, underline, strikethrough)
    int width, height, layer;
    sprites.GetDimensions(width, height, layer);
    float3 sz = float3(float(width), float(height), float(layer));

    float underline_alpha = sprites.Sample(underline_pos).w;
    int3 fetch_coord = int3(int(sprite_pos.x * sz.x), int(underline_exclusion_pos), int(sprite_pos.z));
    float underline_exclusion = sprites[fetch_coord].w;

    underline_alpha *= 1.0 - underline_exclusion;
    float strike_alpha = sprites.Sample(strike_pos).w;
    float cursor_alpha = sprites.Sample(cursor_pos).w;

    float combined_alpha = min(text_fg.w + strike_alpha, 1.0);

    float4 ans = alpha_blend(
        float4(text_fg.rgb, combined_alpha * effective_text_alpha),
        float4(decoration_fg, underline_alpha * effective_text_alpha)
    );

    return lerp(ans, cursor_color_premult, cursor_alpha * cursor_color_premult.w);
}

float4 adjust_foreground_contrast_with_background(float4 text_fg, float3 bg, float text_contrast, float text_gamma_adjustment) {
    return foreground_contrast(text_fg, bg, text_contrast, text_gamma_adjustment);
}

[shader("fragment")]
float4 fragment_main(
    VertexOutput vo,
    uniform float text_contrast,
    uniform float text_gamma_adjustment,
) : SV_Target {
    float4 ans_premul = 0;
    if (!ONLY_FOREGROUND) ans_premul = vo.effective_background_premul;

    if (!ONLY_BACKGROUND) {
        // blend in the foreground color
        float4 text_fg = load_text_foreground_color(vo.sprite_pos, vo.colored_sprite, vo.cell_foreground);
        text_fg = adjust_foreground_contrast_with_background(text_fg, vo.background, text_contrast, text_gamma_adjustment);
        float4 text_fg_premul = calculate_premul_foreground_from_sprites(
            vo.sprite_pos, vo.underline_pos, vo.cursor_pos, vo.strike_pos, vo.underline_exclusion_pos,
            text_fg, vo.decoration_fg, vo.cursor_color_premult, vo.effective_text_alpha);
        if (ONLY_FOREGROUND) ans_premul = text_fg_premul;
        else ans_premul = alpha_blend_premul(text_fg_premul, ans_premul);
    }
    return ans_premul;
}
