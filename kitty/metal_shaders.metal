/*
 * metal_shaders.metal - Complete Metal shaders for kitty terminal
 * Ported from OpenGL GLSL shaders
 */

#include <metal_stdlib>
using namespace metal;

// ============================================================================
// Color Space Conversion Functions (from linear2srgb.glsl)
// ============================================================================

inline float srgb2linear(float x) {
    float lower = x / 12.92;
    float upper = pow((x + 0.055f) / 1.055f, 2.4f);
    return mix(lower, upper, step(0.04045f, x));
}

inline float linear2srgb(float x) {
    float lower = 12.92 * x;
    float upper = 1.055 * pow(x, 1.0f / 2.4f) - 0.055f;
    return mix(lower, upper, step(0.0031308f, x));
}

inline float3 linear2srgb(float3 x) {
    float3 lower = 12.92 * x;
    float3 upper = 1.055 * pow(x, float3(1.0f / 2.4f)) - 0.055f;
    return mix(lower, upper, step(0.0031308f, x));
}

inline float3 srgb2linear(float3 c) {
    return float3(srgb2linear(c.r), srgb2linear(c.g), srgb2linear(c.b));
}

// ============================================================================
// Alpha Blending Functions (from alpha_blend.glsl)
// ============================================================================

inline float4 alpha_blend(float4 over, float4 under) {
    float alpha = mix(under.a, 1.0f, over.a);
    float3 combined_color = mix(under.rgb * under.a, over.rgb, over.a);
    return float4(combined_color, alpha);
}

inline float4 alpha_blend_premul(float4 over, float4 under) {
    float inv_over_alpha = 1.0f - over.a;
    float alpha = over.a + under.a * inv_over_alpha;
    return float4(over.rgb + under.rgb * inv_over_alpha, alpha);
}

inline float4 alpha_blend_premul(float4 over, float3 under) {
    float inv_over_alpha = 1.0f - over.a;
    return float4(over.rgb + under.rgb * inv_over_alpha, 1.0);
}

// ============================================================================
// Utility Functions (from utils.glsl)
// ============================================================================

inline float zero_or_one(float x) { return step(1.0f, x); }
inline float if_one_then(float condition, float thenval, float elseval) {
    return mix(elseval, thenval, condition);
}
inline float3 if_one_then(float condition, float3 thenval, float3 elseval) {
    return mix(elseval, thenval, condition);
}
inline float4 if_one_then(float condition, float4 thenval, float4 elseval) {
    return mix(elseval, thenval, condition);
}

inline float4 vec4_premul(float3 rgb, float a) {
    return float4(rgb * a, a);
}

inline float4 vec4_premul(float4 rgba) {
    return float4(rgba.rgb * rgba.a, rgba.a);
}

// Luminance vector for linear space
constant float3 Y = float3(0.2126, 0.7152, 0.0722);

// ============================================================================
// HSLUV Color Space Conversion (from hsluv.glsl)
// Human-friendly alternative to HSL for contrast adjustment
// ============================================================================

inline float hsluv_divide(float num, float denom) {
    return num / (abs(denom) + 1e-15) * sign(denom);
}

inline float3 hsluv_divide(float3 num, float3 denom) {
    return num / (abs(denom) + 1e-15) * sign(denom);
}

inline float3 hsluv_intersectLineLine(float3 line1x, float3 line1y, float3 line2x, float3 line2y) {
    return (line1y - line2y) / (line2x - line1x);
}

inline float3 hsluv_distanceFromPole(float3 pointx, float3 pointy) {
    return sqrt(pointx * pointx + pointy * pointy);
}

inline float3 hsluv_lengthOfRayUntilIntersect(float theta, float3 x, float3 y) {
    float3 len = hsluv_divide(y, sin(theta) - x * cos(theta));
    len = mix(len, float3(1000.0), step(len, float3(0.0)));
    return len;
}

inline float hsluv_maxSafeChromaForL(float L) {
    constant float3x3 m2 = float3x3(
         3.2409699419045214,  -0.96924363628087983,  0.055630079696993609,
        -1.5373831775700935,   1.8759675015077207,  -0.20397695888897657,
        -0.49861076029300328,  0.041555057407175613, 1.0569715142428786
    );
    float sub0 = L + 16.0;
    float sub1 = sub0 * sub0 * sub0 * 0.000000641;
    float sub2 = mix(L / 903.2962962962963, sub1, step(0.0088564516790356308, sub1));

    float3 top1   = (284517.0 * m2[0] - 94839.0  * m2[2]) * sub2;
    float3 bottom = (632260.0 * m2[2] - 126452.0 * m2[1]) * sub2;
    float3 top2   = (838422.0 * m2[2] + 769860.0 * m2[1] + 731718.0 * m2[0]) * L * sub2;

    float3 bounds0x = top1 / bottom;
    float3 bounds0y = top2 / bottom;
    float3 bounds1x = top1 / (bottom + 126452.0);
    float3 bounds1y = (top2 - 769860.0 * L) / (bottom + 126452.0);

    float3 xs0 = hsluv_intersectLineLine(bounds0x, bounds0y, -1.0 / bounds0x, float3(0.0));
    float3 xs1 = hsluv_intersectLineLine(bounds1x, bounds1y, -1.0 / bounds1x, float3(0.0));

    float3 lengths0 = hsluv_distanceFromPole(xs0, bounds0y + xs0 * bounds0x);
    float3 lengths1 = hsluv_distanceFromPole(xs1, bounds1y + xs1 * bounds1x);

    return min(lengths0.r, min(lengths1.r, min(lengths0.g, min(lengths1.g, min(lengths0.b, lengths1.b)))));
}

inline float hsluv_maxChromaForLH(float L, float H) {
    float hrad = radians(H);
    constant float3x3 m2 = float3x3(
         3.2409699419045214,  -0.96924363628087983,  0.055630079696993609,
        -1.5373831775700935,   1.8759675015077207,  -0.20397695888897657,
        -0.49861076029300328,  0.041555057407175613, 1.0569715142428786
    );
    float sub1 = pow(L + 16.0, 3.0) / 1560896.0;
    float sub2 = mix(L / 903.2962962962963, sub1, step(0.0088564516790356308, sub1));

    float3 top1   = (284517.0 * m2[0] - 94839.0  * m2[2]) * sub2;
    float3 bottom = (632260.0 * m2[2] - 126452.0 * m2[1]) * sub2;
    float3 top2   = (838422.0 * m2[2] + 769860.0 * m2[1] + 731718.0 * m2[0]) * L * sub2;

    float3 bound0x = top1 / bottom;
    float3 bound0y = top2 / bottom;
    float3 bound1x = top1 / (bottom + 126452.0);
    float3 bound1y = (top2 - 769860.0 * L) / (bottom + 126452.0);

    float3 lengths0 = hsluv_lengthOfRayUntilIntersect(hrad, bound0x, bound0y);
    float3 lengths1 = hsluv_lengthOfRayUntilIntersect(hrad, bound1x, bound1y);

    return min(lengths0.r, min(lengths1.r, min(lengths0.g, min(lengths1.g, min(lengths0.b, lengths1.b)))));
}

inline float3 hsluv_fromLinear(float3 c) {
    return mix(c * 12.92, 1.055 * pow(max(c, float3(0)), float3(1.0 / 2.4)) - 0.055, step(0.0031308, c));
}

inline float3 hsluv_toLinear(float3 c) {
    return mix(c / 12.92, pow(max((c + 0.055) / 1.055, float3(0)), float3(2.4)), step(0.04045, c));
}

inline float hsluv_yToL(float Y_val) {
    return mix(Y_val * 903.2962962962963, 116.0 * pow(max(Y_val, 0.0f), 1.0 / 3.0) - 16.0, step(0.0088564516790356308, Y_val));
}

inline float hsluv_lToY(float L) {
    return mix(L / 903.2962962962963, pow((max(L, 0.0f) + 16.0) / 116.0, 3.0), step(8.0, L));
}

inline float3 xyzToRgb(float3 tuple) {
    constant float3x3 m = float3x3(
        3.2409699419045214,  -1.5373831775700935, -0.49861076029300328,
       -0.96924363628087983,  1.8759675015077207,  0.041555057407175613,
        0.055630079696993609,-0.20397695888897657, 1.0569715142428786
    );
    return hsluv_fromLinear(tuple * m);
}

inline float3 rgbToXyz(float3 tuple) {
    constant float3x3 m = float3x3(
        0.41239079926595948,  0.35758433938387796, 0.18048078840183429,
        0.21263900587151036,  0.71516867876775593, 0.072192315360733715,
        0.019330818715591851, 0.11919477979462599, 0.95053215224966058
    );
    return hsluv_toLinear(tuple) * m;
}

inline float3 xyzToLuv(float3 tuple) {
    float X = tuple.x;
    float Y_val = tuple.y;
    float Z = tuple.z;
    float L = hsluv_yToL(Y_val);
    float div_val = 1.0 / max(dot(tuple, float3(1, 15, 3)), 1e-15);
    return float3(1.0, (52.0 * (X * div_val) - 2.57179), (117.0 * (Y_val * div_val) - 6.08816)) * L;
}

inline float3 luvToXyz(float3 tuple) {
    float L = tuple.x;
    float U = hsluv_divide(tuple.y, 13.0 * L) + 0.19783000664283681;
    float V = hsluv_divide(tuple.z, 13.0 * L) + 0.468319994938791;
    float Y_val = hsluv_lToY(L);
    float X = 2.25 * U * Y_val / V;
    float Z = (3.0 / V - 5.0) * Y_val - (X / 3.0);
    return float3(X, Y_val, Z);
}

inline float3 luvToLch(float3 tuple) {
    float L = tuple.x;
    float U = tuple.y;
    float V = tuple.z;
    float C = length(tuple.yz);
    float H = degrees(atan2(V, U));
    H += 360.0 * step(H, 0.0);
    return float3(L, C, H);
}

inline float3 lchToLuv(float3 tuple) {
    float hrad = radians(tuple.z);
    return float3(tuple.x, cos(hrad) * tuple.y, sin(hrad) * tuple.y);
}

inline float3 hsluvToLch(float3 tuple) {
    float3 result;
    result.x = tuple.z;  // L
    result.y = tuple.y * hsluv_maxChromaForLH(tuple.z, tuple.x) * 0.01;  // C
    result.z = tuple.x;  // H
    return result;
}

inline float3 lchToHsluv(float3 tuple) {
    float3 result;
    result.x = tuple.z;  // H
    result.y = hsluv_divide(tuple.y, hsluv_maxChromaForLH(tuple.x, tuple.z) * 0.01);  // S
    result.z = tuple.x;  // L
    return result;
}

inline float3 lchToRgb(float3 tuple) {
    return xyzToRgb(luvToXyz(lchToLuv(tuple)));
}

inline float3 rgbToLch(float3 tuple) {
    return luvToLch(xyzToLuv(rgbToXyz(tuple)));
}

inline float3 hsluvToRgb(float3 tuple) {
    return lchToRgb(hsluvToLch(tuple));
}

inline float3 rgbToHsluv(float3 tuple) {
    return lchToHsluv(rgbToLch(tuple));
}

// ============================================================================
// Foreground Override Functions (for contrast adjustment)
// ============================================================================

inline float contrast_ratio(float under_luminance, float over_luminance) {
    return clamp((max(under_luminance, over_luminance) + 0.05) / (min(under_luminance, over_luminance) + 0.05), 1.0, 21.0);
}

inline float contrast_ratio_vec(float3 a, float3 b) {
    return contrast_ratio(dot(a, Y), dot(b, Y));
}

// Algorithm 1: Simple luminance-based override (force black or white)
inline float3 fg_override_simple(float under_luminance, float over_luminance, float3 under, float3 over, float threshold, float is_colored) {
    float diff_luminance = abs(under_luminance - over_luminance);
    float override_level = (1.0 - is_colored) * step(diff_luminance, threshold);
    float original_level = 1.0 - override_level;
    return original_level * over + override_level * float3(step(under_luminance, 0.5));
}

// Algorithm 2: HSLUV-based override (preserve hue, adjust luminance)
inline float3 fg_override_hsluv(float under_luminance, float over_luminance, float3 under, float3 over, float min_contrast_ratio) {
    float ratio = contrast_ratio(under_luminance, over_luminance);
    float3 diff = abs(under - over);
    float3 over_hsluv = rgbToHsluv(over);
    
    float target_lum_a = clamp((under_luminance + 0.05) * min_contrast_ratio - 0.05, 0.0, 1.0);
    float target_lum_b = clamp((under_luminance + 0.05) / min_contrast_ratio - 0.05, 0.0, 1.0);
    
    float3 result_a = clamp(hsluvToRgb(float3(over_hsluv.x, over_hsluv.y, target_lum_a * 100.0)), 0.0, 1.0);
    float3 result_b = clamp(hsluvToRgb(float3(over_hsluv.x, over_hsluv.y, target_lum_b * 100.0)), 0.0, 1.0);
    
    float result_a_ratio = contrast_ratio(under_luminance, dot(result_a, Y));
    float result_b_ratio = contrast_ratio(under_luminance, dot(result_b, Y));
    
    float3 result = mix(result_a, result_b, step(result_a_ratio, result_b_ratio));
    return mix(result, over, max(step(diff.r + diff.g + diff.b, 0.001), step(min_contrast_ratio, ratio)));
}

inline float3 override_foreground_color(float3 over, float3 under, float threshold, int algorithm, float is_colored) {
    float under_luminance = dot(under, Y);
    float over_luminance = dot(over, Y);
    
    if (algorithm == 1) {
        return fg_override_simple(under_luminance, over_luminance, under, over, threshold, is_colored);
    } else {
        return fg_override_hsluv(under_luminance, over_luminance, under, over, threshold);
    }
}

// ============================================================================
// Cell Rendering Structures
// ============================================================================

struct CellVertex {
    float2 pos [[attribute(0)]];
    float2 uv [[attribute(1)]];
    float4 fg [[attribute(2)]];
    float4 bg [[attribute(3)]];
    float sprite_z [[attribute(4)]];
    float colored [[attribute(5)]];
};

struct CellOut {
    float4 pos [[position]];
    float2 uv;
    float4 fg;
    float4 bg;
    float sprite_z;
    float colored;
};

// Extended cell vertex with decoration support
struct CellVertexExt {
    float2 pos [[attribute(0)]];
    float2 uv [[attribute(1)]];
    float4 fg [[attribute(2)]];
    float4 bg [[attribute(3)]];
    float sprite_z [[attribute(4)]];
    float colored [[attribute(5)]];
    float2 underline_uv [[attribute(6)]];
    float underline_z [[attribute(7)]];
    float2 strike_uv [[attribute(8)]];
    float strike_z [[attribute(9)]];
    float2 cursor_uv [[attribute(10)]];
    float cursor_z [[attribute(11)]];
    float4 decoration_fg [[attribute(12)]];
    float4 cursor_color [[attribute(13)]];
    float effective_alpha [[attribute(14)]];
    uint underline_exclusion_row [[attribute(15)]];
};

struct CellOutExt {
    float4 pos [[position]];
    float2 uv;
    float4 fg;
    float4 bg;
    float sprite_z;
    float colored;
    float2 underline_uv;
    float underline_z;
    float2 strike_uv;
    float strike_z;
    float2 cursor_uv;
    float cursor_z;
    float4 decoration_fg;
    float4 cursor_color;
    float effective_alpha;
    uint underline_exclusion_row [[flat]];
};

// Cell render data uniform buffer (equivalent to GLSL UBO CellRenderData)
struct CellRenderData {
    // Selection flags
    float use_cell_bg_for_selection_fg;
    float use_cell_fg_for_selection_fg;
    float use_cell_for_selection_bg;
    float padding1;
    
    // Colors (packed as uint, unpacked in shader)
    uint default_fg;
    uint highlight_fg;
    uint highlight_bg;
    uint main_cursor_fg;
    uint main_cursor_bg;
    uint url_color;
    uint url_style;
    uint inverted;
    uint extra_cursor_fg;
    uint extra_cursor_bg;
    uint padding2[2];
    
    // Dimensions
    uint columns;
    uint lines;
    uint sprites_xnum;
    uint sprites_ynum;
    uint cursor_shape;
    uint cell_width;
    uint cell_height;
    uint padding3;
    
    // Cursor position
    uint cursor_x1;
    uint cursor_x2;
    uint cursor_y1;
    uint cursor_y2;
    
    // Opacity values
    float cursor_opacity;
    float inactive_text_alpha;
    float dim_opacity;
    float blink_opacity;
    
    // Background colors (8 configurable)
    uint bg_colors[8];
    float bg_opacities[8];
};

// Foreground override parameters
struct FgOverrideParams {
    float enabled;           // 0 or 1
    float threshold;         // contrast threshold
    int algorithm;           // 1 = simple, 2 = hsluv
    float padding;
};

// ============================================================================
// Rectangle Structures (borders, cursors, selections)
// ============================================================================

struct RectVertex {
    float2 pos [[attribute(0)]];
    float4 color [[attribute(1)]];
};

struct RectOut {
    float4 pos [[position]];
    float4 color;
};

// ============================================================================
// Image/Graphics Structures
// ============================================================================

struct ImageVertex {
    float2 pos [[attribute(0)]];
    float2 uv [[attribute(1)]];
};

struct ImageOut {
    float4 pos [[position]];
    float2 uv;
};

// ============================================================================
// Rounded Rectangle Structures
// ============================================================================

struct RoundedRectParams {
    float4 rect;           // x, y, width, height
    float2 params;         // thickness, corner_radius
    float4 color;
    float4 background_color;
};

// ============================================================================
// Cell Shaders
// ============================================================================

vertex CellOut cell_vertex(CellVertex in [[stage_in]]) {
    CellOut out;
    out.pos = float4(in.pos, 0.0, 1.0);
    out.uv = in.uv;
    out.fg = in.fg;
    out.bg = in.bg;
    out.sprite_z = in.sprite_z;
    out.colored = in.colored;
    return out;
}

fragment float4 cell_bg_fragment(CellOut in [[stage_in]]) {
    return in.bg;
}

fragment float4 cell_fg_fragment(CellOut in [[stage_in]],
                                  texture2d_array<float> sprites [[texture(0)]],
                                  sampler samp [[sampler(0)]]) {
    if (in.uv.x == 0.0 && in.uv.y == 0.0 && in.sprite_z == 0.0) {
        discard_fragment();
    }
    float4 tex = sprites.sample(samp, in.uv, uint(in.sprite_z));
    float alpha = tex.r;
    if (in.colored > 0.5) {
        return float4(tex.a * alpha, tex.b * alpha, tex.g * alpha, alpha);
    }
    float final_alpha = in.fg.a * alpha;
    return float4(in.fg.rgb * final_alpha, final_alpha);
}

// Combined cell shader with text contrast adjustment
fragment float4 cell_combined_fragment(CellOut in [[stage_in]],
                                       texture2d_array<float> sprites [[texture(0)]],
                                       sampler samp [[sampler(0)]],
                                       constant float2 &contrast_params [[buffer(0)]]) {
    float4 bg_premul = in.bg;
    
    if (in.uv.x == 0.0 && in.uv.y == 0.0 && in.sprite_z == 0.0) {
        return bg_premul;
    }
    
    float4 tex = sprites.sample(samp, in.uv, uint(in.sprite_z));
    float alpha = tex.r;
    
    float4 fg_color;
    if (in.colored > 0.5) {
        fg_color = float4(tex.a, tex.b, tex.g, alpha);
    } else {
        // Apply text contrast adjustment
        float text_contrast = contrast_params.x;
        float text_gamma = contrast_params.y;
        
        float under_lum = dot(bg_premul.rgb / max(bg_premul.a, 0.001), Y);
        float over_lum = dot(in.fg.rgb, Y);
        float adjusted_alpha = clamp(
            mix(alpha, pow(alpha, text_gamma), (1.0 - over_lum + under_lum) * 0.5) * text_contrast,
            0.0, 1.0);
        fg_color = float4(in.fg.rgb, adjusted_alpha * in.fg.a);
    }
    
    float4 fg_premul = vec4_premul(fg_color);
    return alpha_blend_premul(fg_premul, bg_premul);
}

// ============================================================================
// Extended Cell Shaders with Full Decoration Support
// ============================================================================

vertex CellOutExt cell_vertex_ext(CellVertexExt in [[stage_in]]) {
    CellOutExt out;
    out.pos = float4(in.pos, 0.0, 1.0);
    out.uv = in.uv;
    out.fg = in.fg;
    out.bg = in.bg;
    out.sprite_z = in.sprite_z;
    out.colored = in.colored;
    out.underline_uv = in.underline_uv;
    out.underline_z = in.underline_z;
    out.strike_uv = in.strike_uv;
    out.strike_z = in.strike_z;
    out.cursor_uv = in.cursor_uv;
    out.cursor_z = in.cursor_z;
    out.decoration_fg = in.decoration_fg;
    out.cursor_color = in.cursor_color;
    out.effective_alpha = in.effective_alpha;
    out.underline_exclusion_row = in.underline_exclusion_row;
    return out;
}

// Full cell fragment shader with decorations, contrast adjustment, and foreground override
fragment float4 cell_full_fragment(CellOutExt in [[stage_in]],
                                   texture2d_array<float> sprites [[texture(0)]],
                                   sampler samp [[sampler(0)]],
                                   constant float2 &contrast_params [[buffer(0)]],
                                   constant FgOverrideParams &fg_override [[buffer(1)]]) {
    float4 bg_premul = in.bg;
    float3 background_rgb = bg_premul.rgb / max(bg_premul.a, 0.001);
    
    // Load text foreground color
    float4 text_tex = sprites.sample(samp, in.uv, uint(in.sprite_z));
    float text_alpha = text_tex.r;
    
    // Check if this is an empty cell (no sprite)
    bool is_empty = (in.uv.x == 0.0 && in.uv.y == 0.0 && in.sprite_z == 0.0);
    
    float3 fg_rgb;
    if (in.colored > 0.5) {
        // Colored sprite - use sprite colors (BGRA format in texture)
        fg_rgb = float3(text_tex.a, text_tex.b, text_tex.g);
    } else {
        fg_rgb = in.fg.rgb;
        
        // Apply foreground override for contrast if enabled
        if (fg_override.enabled > 0.5) {
            fg_rgb = override_foreground_color(fg_rgb, background_rgb, fg_override.threshold, 
                                               fg_override.algorithm, in.colored);
        }
    }
    
    // Apply text contrast adjustment
    float text_contrast = contrast_params.x;
    float text_gamma = contrast_params.y;
    
    float under_lum = dot(background_rgb, Y);
    float over_lum = dot(fg_rgb, Y);
    float adjusted_alpha = clamp(
        mix(text_alpha, pow(text_alpha, text_gamma), (1.0 - over_lum + under_lum) * 0.5) * text_contrast,
        0.0, 1.0);
    
    // Apply effective alpha (dim, blink, inactive)
    adjusted_alpha *= in.effective_alpha;
    
    float4 text_fg = float4(fg_rgb, adjusted_alpha * in.fg.a);
    
    // Load decoration sprites
    float underline_alpha = 0.0;
    float strike_alpha = 0.0;
    float cursor_alpha = 0.0;
    
    if (in.underline_z > 0.0 || (in.underline_uv.x != 0.0 || in.underline_uv.y != 0.0)) {
        underline_alpha = sprites.sample(samp, in.underline_uv, uint(in.underline_z)).a;
        
        // Apply underline exclusion (where text descenders exist)
        if (in.underline_exclusion_row > 0) {
            int3 sz = int3(sprites.get_width(), sprites.get_height(), sprites.get_array_size());
            int excl_x = int(in.uv.x * float(sz.x));
            float exclusion = sprites.read(uint2(excl_x, in.underline_exclusion_row), uint(in.sprite_z)).a;
            underline_alpha *= 1.0 - exclusion;
        }
    }
    
    if (in.strike_z > 0.0 || (in.strike_uv.x != 0.0 || in.strike_uv.y != 0.0)) {
        strike_alpha = sprites.sample(samp, in.strike_uv, uint(in.strike_z)).a;
    }
    
    if (in.cursor_z > 0.0 || (in.cursor_uv.x != 0.0 || in.cursor_uv.y != 0.0)) {
        cursor_alpha = sprites.sample(samp, in.cursor_uv, uint(in.cursor_z)).a;
    }
    
    // Combine text and strikethrough (same color, add alphas)
    float combined_alpha = is_empty ? 0.0 : min(text_fg.a + strike_alpha * in.effective_alpha, 1.0);
    
    // Get decoration foreground color (may be different for underline)
    float3 dec_fg = in.decoration_fg.rgb;
    if (fg_override.enabled > 0.5) {
        dec_fg = override_foreground_color(dec_fg, background_rgb, fg_override.threshold,
                                           fg_override.algorithm, 0.0);
    }
    
    // Alpha blend text+strike with underline
    float4 fg_combined = alpha_blend(
        float4(fg_rgb, combined_alpha),
        float4(dec_fg, underline_alpha * in.effective_alpha)
    );
    
    // Blend with cursor
    float4 fg_with_cursor = mix(fg_combined, in.cursor_color, cursor_alpha * in.cursor_color.a);
    
    // Premultiply and blend with background
    float4 fg_premul = vec4_premul(fg_with_cursor);
    return alpha_blend_premul(fg_premul, bg_premul);
}

// Background-only fragment for extended cells
fragment float4 cell_bg_ext_fragment(CellOutExt in [[stage_in]]) {
    return in.bg;
}

// Foreground-only fragment for extended cells (for multi-pass rendering)
fragment float4 cell_fg_ext_fragment(CellOutExt in [[stage_in]],
                                     texture2d_array<float> sprites [[texture(0)]],
                                     sampler samp [[sampler(0)]],
                                     constant float2 &contrast_params [[buffer(0)]],
                                     constant FgOverrideParams &fg_override [[buffer(1)]]) {
    float3 background_rgb = in.bg.rgb / max(in.bg.a, 0.001);
    
    // Check if this is an empty cell
    if (in.uv.x == 0.0 && in.uv.y == 0.0 && in.sprite_z == 0.0) {
        discard_fragment();
    }
    
    float4 text_tex = sprites.sample(samp, in.uv, uint(in.sprite_z));
    float text_alpha = text_tex.r;
    
    float3 fg_rgb;
    if (in.colored > 0.5) {
        fg_rgb = float3(text_tex.a, text_tex.b, text_tex.g);
    } else {
        fg_rgb = in.fg.rgb;
        if (fg_override.enabled > 0.5) {
            fg_rgb = override_foreground_color(fg_rgb, background_rgb, fg_override.threshold,
                                               fg_override.algorithm, in.colored);
        }
    }
    
    // Apply contrast adjustment
    float text_contrast = contrast_params.x;
    float text_gamma = contrast_params.y;
    float under_lum = dot(background_rgb, Y);
    float over_lum = dot(fg_rgb, Y);
    float adjusted_alpha = clamp(
        mix(text_alpha, pow(text_alpha, text_gamma), (1.0 - over_lum + under_lum) * 0.5) * text_contrast,
        0.0, 1.0);
    adjusted_alpha *= in.effective_alpha;
    
    // Load decorations
    float strike_alpha = 0.0;
    float underline_alpha = 0.0;
    float cursor_alpha = 0.0;
    
    if (in.strike_z > 0.0 || (in.strike_uv.x != 0.0 || in.strike_uv.y != 0.0)) {
        strike_alpha = sprites.sample(samp, in.strike_uv, uint(in.strike_z)).a;
    }
    
    if (in.underline_z > 0.0 || (in.underline_uv.x != 0.0 || in.underline_uv.y != 0.0)) {
        underline_alpha = sprites.sample(samp, in.underline_uv, uint(in.underline_z)).a;
        if (in.underline_exclusion_row > 0) {
            int3 sz = int3(sprites.get_width(), sprites.get_height(), sprites.get_array_size());
            int excl_x = int(in.uv.x * float(sz.x));
            float exclusion = sprites.read(uint2(excl_x, in.underline_exclusion_row), uint(in.sprite_z)).a;
            underline_alpha *= 1.0 - exclusion;
        }
    }
    
    if (in.cursor_z > 0.0 || (in.cursor_uv.x != 0.0 || in.cursor_uv.y != 0.0)) {
        cursor_alpha = sprites.sample(samp, in.cursor_uv, uint(in.cursor_z)).a;
    }
    
    // Combine
    float combined_alpha = min(adjusted_alpha * in.fg.a + strike_alpha * in.effective_alpha, 1.0);
    
    float3 dec_fg = in.decoration_fg.rgb;
    if (fg_override.enabled > 0.5) {
        dec_fg = override_foreground_color(dec_fg, background_rgb, fg_override.threshold,
                                           fg_override.algorithm, 0.0);
    }
    
    float4 fg_combined = alpha_blend(
        float4(fg_rgb, combined_alpha),
        float4(dec_fg, underline_alpha * in.effective_alpha)
    );
    
    float4 fg_with_cursor = mix(fg_combined, in.cursor_color, cursor_alpha * in.cursor_color.a);
    
    float final_alpha = fg_with_cursor.a;
    return float4(fg_with_cursor.rgb * final_alpha, final_alpha);
}

// ============================================================================
// Rectangle Shaders (borders, cursors, selections)
// ============================================================================

vertex RectOut rect_vertex(RectVertex in [[stage_in]]) {
    RectOut out;
    out.pos = float4(in.pos, 0.0, 1.0);
    out.color = in.color;
    return out;
}

fragment float4 rect_fragment(RectOut in [[stage_in]]) {
    return in.color;
}

// ============================================================================
// Tint Shader (visual bell, background tint)
// ============================================================================

vertex float4 tint_vertex(uint vid [[vertex_id]],
                          constant float4 &edges [[buffer(0)]]) {
    float left = edges[0];
    float top = edges[1];
    float right = edges[2];
    float bottom = edges[3];
    float2 positions[4] = {
        float2(left, top),
        float2(left, bottom),
        float2(right, bottom),
        float2(right, top)
    };
    return float4(positions[vid], 0.0, 1.0);
}

fragment float4 tint_fragment(constant float4 &color [[buffer(0)]]) {
    return color;
}

// Full-screen tint (simpler version)
vertex float4 fullscreen_tint_vertex(uint vid [[vertex_id]]) {
    float2 positions[4] = {float2(-1,-1), float2(1,-1), float2(-1,1), float2(1,1)};
    return float4(positions[vid], 0.0, 1.0);
}

// ============================================================================
// Cursor Trail Shader (from trail_vertex.glsl, trail_fragment.glsl)
// ============================================================================

struct TrailParams {
    float4 x_coords;
    float4 y_coords;
    float2 cursor_edge_x;
    float2 cursor_edge_y;
    float3 trail_color;
    float trail_opacity;
};

struct TrailOut {
    float4 pos [[position]];
    float2 frag_pos;
};

vertex TrailOut trail_vertex(uint vid [[vertex_id]],
                             constant TrailParams &params [[buffer(0)]]) {
    TrailOut out;
    float2 pos = float2(params.x_coords[vid], params.y_coords[vid]);
    out.pos = float4(pos, 1.0, 1.0);
    out.frag_pos = pos;
    return out;
}

fragment float4 trail_fragment(TrailOut in [[stage_in]],
                               constant TrailParams &params [[buffer(0)]]) {
    float opacity = params.trail_opacity;
    float in_x = step(params.cursor_edge_x[0], in.frag_pos.x) * 
                 step(in.frag_pos.x, params.cursor_edge_x[1]);
    float in_y = step(params.cursor_edge_y[1], in.frag_pos.y) * 
                 step(in.frag_pos.y, params.cursor_edge_y[0]);
    opacity *= 1.0f - in_x * in_y;
    return float4(params.trail_color * opacity, opacity);
}

// ============================================================================
// Image/Graphics Shaders (from graphics_vertex.glsl, graphics_fragment.glsl)
// ============================================================================

struct GraphicsParams {
    float4 src_rect;
    float4 dest_rect;
    float extra_alpha;
};

vertex ImageOut image_vertex(uint vid [[vertex_id]],
                             constant GraphicsParams &params [[buffer(0)]]) {
    // Vertex positions: right-top, right-bottom, left-bottom, left-top
    int2 pos_map[4] = {int2(2, 1), int2(2, 3), int2(0, 3), int2(0, 1)};
    int2 pos = pos_map[vid];
    
    ImageOut out;
    out.uv = float2(params.src_rect[pos.x], params.src_rect[pos.y]);
    out.pos = float4(params.dest_rect[pos.x], params.dest_rect[pos.y], 0, 1);
    return out;
}

fragment float4 image_fragment(ImageOut in [[stage_in]],
                               texture2d<float> tex [[texture(0)]],
                               sampler samp [[sampler(0)]],
                               constant float &extra_alpha [[buffer(0)]]) {
    float4 color = tex.sample(samp, in.uv);
    color.a *= extra_alpha;
    return vec4_premul(color);
}

// Premultiplied image (already has premultiplied alpha)
fragment float4 image_premult_fragment(ImageOut in [[stage_in]],
                                       texture2d<float> tex [[texture(0)]],
                                       sampler samp [[sampler(0)]],
                                       constant float &extra_alpha [[buffer(0)]]) {
    float4 color = tex.sample(samp, in.uv);
    return color * extra_alpha;
}

// Alpha mask mode (for text overlays)
struct AlphaMaskParams {
    float3 fg_color;
    float4 bg_premult;
};

fragment float4 image_alpha_mask_fragment(ImageOut in [[stage_in]],
                                          texture2d<float> tex [[texture(0)]],
                                          sampler samp [[sampler(0)]],
                                          constant AlphaMaskParams &params [[buffer(0)]]) {
    float4 color = tex.sample(samp, in.uv);
    float4 fg = float4(params.fg_color, color.r);
    fg = vec4_premul(fg);
    return alpha_blend_premul(fg, params.bg_premult);
}

// ============================================================================
// Background Image Shader (from bgimage_vertex.glsl, bgimage_fragment.glsl)
// ============================================================================

struct BgImageParams {
    float tiled;
    float4 sizes;      // window_width, window_height, image_width, image_height
    float4 positions;  // left, top, right, bottom
    float4 background;
};

struct BgImageOut {
    float4 pos [[position]];
    float2 texcoord;
};

vertex BgImageOut bgimage_vertex(uint vid [[vertex_id]],
                                 constant BgImageParams &params [[buffer(0)]]) {
    float2 tex_map[4] = {float2(0, 0), float2(0, 1), float2(1, 1), float2(1, 0)};
    float2 pos_map[4] = {
        float2(params.positions[0], params.positions[1]),
        float2(params.positions[0], params.positions[3]),
        float2(params.positions[2], params.positions[3]),
        float2(params.positions[2], params.positions[1])
    };
    
    float2 tex_coords = tex_map[vid];
    float scale_x = params.tiled * (params.sizes[0] / params.sizes[2]) + (1.0 - params.tiled);
    float scale_y = params.tiled * (params.sizes[1] / params.sizes[3]) + (1.0 - params.tiled);
    
    BgImageOut out;
    out.texcoord = float2(tex_coords.x * scale_x, tex_coords.y * scale_y);
    out.pos = float4(pos_map[vid], 0, 1);
    return out;
}

fragment float4 bgimage_fragment(BgImageOut in [[stage_in]],
                                 texture2d<float> image [[texture(0)]],
                                 sampler samp [[sampler(0)]],
                                 constant BgImageParams &params [[buffer(0)]]) {
    float4 color = image.sample(samp, in.texcoord);
    return alpha_blend(color, params.background);
}

// ============================================================================
// Blit Shader (final compositing with sRGB conversion)
// ============================================================================

vertex ImageOut blit_vertex(uint vid [[vertex_id]],
                            constant float4 &src_rect [[buffer(0)]],
                            constant float4 &dest_rect [[buffer(1)]]) {
    int2 pos_map[4] = {int2(2, 1), int2(2, 3), int2(0, 3), int2(0, 1)};
    int2 pos = pos_map[vid];
    
    ImageOut out;
    out.uv = float2(src_rect[pos.x], src_rect[pos.y]);
    out.pos = float4(dest_rect[pos.x], dest_rect[pos.y], 0, 1);
    return out;
}

fragment float4 blit_fragment(ImageOut in [[stage_in]],
                              texture2d<float> image [[texture(0)]],
                              sampler samp [[sampler(0)]]) {
    float4 color_premul = image.sample(samp, in.uv);
    // Convert from linear to sRGB
    float3 rgb = color_premul.rgb / max(color_premul.a, 0.001);
    return vec4_premul(linear2srgb(rgb), color_premul.a);
}

// ============================================================================
// Rounded Rectangle Shader (from rounded_rect_fragment.glsl)
// ============================================================================

struct RoundedRectOut {
    float4 pos [[position]];
};

vertex RoundedRectOut rounded_rect_vertex(uint vid [[vertex_id]]) {
    float2 positions[4] = {float2(1, 1), float2(1, -1), float2(-1, -1), float2(-1, 1)};
    RoundedRectOut out;
    out.pos = float4(positions[vid], 0, 1);
    return out;
}

// Signed distance function for rounded rectangle
inline float rounded_rectangle_sdf(float2 p, float2 b, float r) {
    float2 q = abs(p) - b;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

fragment float4 rounded_rect_fragment(RoundedRectOut in [[stage_in]],
                                      constant RoundedRectParams &params [[buffer(0)]]) {
    float2 size = params.rect.ba;
    float2 origin = params.rect.xy;
    float thickness = params.params[0];
    float corner_radius = params.params[1];
    
    float2 position = in.pos.xy - size / 2.0 - origin;
    float dist = rounded_rectangle_sdf(position, size * 0.5 - corner_radius, corner_radius);
    
    float outer_edge = -dist;
    float inner_edge = outer_edge - thickness;
    
    const float step_size = 1.0;
    float alpha = smoothstep(-step_size, step_size, outer_edge) - 
                  smoothstep(-step_size, step_size, inner_edge);
    
    float4 ans = params.color;
    ans.a *= alpha;
    return alpha_blend(ans, params.background_color);
}

// Filled rounded rectangle (no border, just filled)
fragment float4 rounded_rect_filled_fragment(RoundedRectOut in [[stage_in]],
                                             constant RoundedRectParams &params [[buffer(0)]]) {
    float2 size = params.rect.ba;
    float2 origin = params.rect.xy;
    float corner_radius = params.params[1];
    
    float2 position = in.pos.xy - size / 2.0 - origin;
    float dist = rounded_rectangle_sdf(position, size * 0.5 - corner_radius, corner_radius);
    
    float alpha = 1.0 - smoothstep(0.0, 1.0, dist);
    float4 ans = params.color;
    ans.a *= alpha;
    return alpha_blend(ans, params.background_color);
}

// ============================================================================
// Border Shader (from border_vertex.glsl, border_fragment.glsl)
// Full implementation with gamma LUT and color palette
// ============================================================================

// Border color indices (matching GLSL defines)
constant uint BORDER_COLOR_DEFAULT_BG = 0;
constant uint BORDER_COLOR_ACTIVE_BORDER = 1;
constant uint BORDER_COLOR_INACTIVE_BORDER = 2;
constant uint BORDER_COLOR_WINDOW_BG_PLACEHOLDER = 3;
constant uint BORDER_COLOR_BELL_BORDER = 4;

struct BorderVertex {
    float4 rect [[attribute(0)]];      // left, top, right, bottom
    uint rect_color [[attribute(1)]];   // color index | (window_bg << 8)
};

struct BorderOut {
    float4 pos [[position]];
    float4 color_premul;
};

struct BorderParams {
    uint colors[9];              // Color palette
    float background_opacity;    // Background opacity
    float gamma_lut[256];        // Gamma lookup table for sRGB conversion
};

// Simplified border params without gamma LUT (for when gamma is pre-applied)
struct BorderParamsSimple {
    packed_float3 colors[9];     // Pre-converted colors
    float background_opacity;
};

inline float3 apply_gamma_lut(uint color_packed, constant float *gamma_lut) {
    return float3(
        gamma_lut[(color_packed >> 16) & 0xFF],
        gamma_lut[(color_packed >> 8) & 0xFF],
        gamma_lut[color_packed & 0xFF]
    );
}

vertex BorderOut border_vertex(BorderVertex in [[stage_in]],
                               uint vid [[vertex_id]],
                               constant BorderParams &params [[buffer(0)]]) {
    // Map vertex ID to rectangle corner
    uint2 pos_map[4] = {uint2(2, 1), uint2(2, 3), uint2(0, 3), uint2(0, 1)};
    uint2 pos = pos_map[vid];
    
    BorderOut out;
    out.pos = float4(in.rect[pos.x], in.rect[pos.y], 0, 1);
    
    // Extract color index and window background
    uint rc = in.rect_color & 0xFF;
    uint window_bg_packed = in.rect_color >> 8;
    
    // Convert window background using gamma LUT
    float3 window_bg = apply_gamma_lut(window_bg_packed, params.gamma_lut);
    
    // Get color from palette and convert using gamma LUT
    uint color_packed = params.colors[min(rc, 8u)];
    float3 color3 = apply_gamma_lut(color_packed, params.gamma_lut);
    
    // Check if this is window background placeholder (rc == 3)
    float is_window_bg = 1.0 - step(0.5, abs(float(rc) - float(BORDER_COLOR_WINDOW_BG_PLACEHOLDER)));
    color3 = mix(color3, window_bg, is_window_bg);
    
    // Determine opacity: borders (1, 2, 4) are always opaque, backgrounds use background_opacity
    // rc == 0 (default bg), rc == 3 (window bg placeholder) use background_opacity
    float is_bg = step(abs(float(rc) - 0.0), 0.5) + step(abs(float(rc) - 3.0), 0.5);
    is_bg = min(is_bg, 1.0);
    float final_opacity = mix(1.0, params.background_opacity, is_bg);
    
    out.color_premul = vec4_premul(color3, final_opacity);
    return out;
}

// Simplified border vertex for pre-converted colors
vertex BorderOut border_vertex_simple(BorderVertex in [[stage_in]],
                                      uint vid [[vertex_id]],
                                      constant BorderParamsSimple &params [[buffer(0)]]) {
    uint2 pos_map[4] = {uint2(2, 1), uint2(2, 3), uint2(0, 3), uint2(0, 1)};
    uint2 pos = pos_map[vid];
    
    BorderOut out;
    out.pos = float4(in.rect[pos.x], in.rect[pos.y], 0, 1);
    
    uint rc = in.rect_color & 0xFF;
    uint window_bg_packed = in.rect_color >> 8;
    
    // Simple color extraction (assuming pre-converted)
    float3 window_bg = float3(
        float((window_bg_packed >> 16) & 0xFF) / 255.0,
        float((window_bg_packed >> 8) & 0xFF) / 255.0,
        float(window_bg_packed & 0xFF) / 255.0
    );
    
    float3 color3 = float3(params.colors[min(rc, 8u)]);
    
    float is_window_bg = 1.0 - step(0.5, abs(float(rc) - float(BORDER_COLOR_WINDOW_BG_PLACEHOLDER)));
    color3 = mix(color3, window_bg, is_window_bg);
    
    float is_bg = step(abs(float(rc) - 0.0), 0.5) + step(abs(float(rc) - 3.0), 0.5);
    is_bg = min(is_bg, 1.0);
    float final_opacity = mix(1.0, params.background_opacity, is_bg);
    
    out.color_premul = vec4_premul(color3, final_opacity);
    return out;
}

fragment float4 border_fragment(BorderOut in [[stage_in]]) {
    return in.color_premul;
}
