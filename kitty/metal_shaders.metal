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
    float2 strike_uv [[attribute(7)]];
    float4 decoration_fg [[attribute(8)]];
    float effective_alpha [[attribute(9)]];
};

struct CellOutExt {
    float4 pos [[position]];
    float2 uv;
    float4 fg;
    float4 bg;
    float sprite_z;
    float colored;
    float2 underline_uv;
    float2 strike_uv;
    float4 decoration_fg;
    float effective_alpha;
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
        
        float under_lum = dot(in.bg.rgb / max(in.bg.a, 0.001), Y);
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
// ============================================================================

struct BorderVertex {
    float4 rect [[attribute(0)]];      // left, top, right, bottom
    uint rect_color [[attribute(1)]];
};

struct BorderOut {
    float4 pos [[position]];
    float4 color_premul;
};

struct BorderParams {
    uint colors[9];
    float background_opacity;
    float gamma_lut[256];
};

vertex BorderOut border_vertex(BorderVertex in [[stage_in]],
                               uint vid [[vertex_id]],
                               constant BorderParams &params [[buffer(0)]]) {
    uint2 pos_map[4] = {uint2(2, 1), uint2(2, 3), uint2(0, 3), uint2(0, 1)};
    uint2 pos = pos_map[vid];
    
    BorderOut out;
    out.pos = float4(in.rect[pos.x], in.rect[pos.y], 0, 1);
    
    // Extract color
    uint rc = in.rect_color & 0xFF;
    uint window_bg_packed = in.rect_color >> 8;
    
    float3 window_bg = float3(
        params.gamma_lut[(window_bg_packed >> 16) & 0xFF],
        params.gamma_lut[(window_bg_packed >> 8) & 0xFF],
        params.gamma_lut[window_bg_packed & 0xFF]
    );
    
    uint color_packed = params.colors[rc];
    float3 color3 = float3(
        params.gamma_lut[(color_packed >> 16) & 0xFF],
        params.gamma_lut[(color_packed >> 8) & 0xFF],
        params.gamma_lut[color_packed & 0xFF]
    );
    
    // Check if this is window background placeholder
    float is_window_bg = 1.0 - step(0.5, abs(float(rc) - 3.0));
    color3 = mix(color3, window_bg, is_window_bg);
    
    // Borders (1, 2, 4) are always opaque
    float is_border = step(0.5, abs(float(rc) - 1.0) * abs(float(rc) - 2.0) * abs(float(rc) - 4.0));
    float final_opacity = mix(1.0, params.background_opacity, is_border);
    
    out.color_premul = vec4_premul(color3, final_opacity);
    return out;
}

fragment float4 border_fragment(BorderOut in [[stage_in]]) {
    return in.color_premul;
}
