#include <metal_stdlib>
using namespace metal;

// ============================================================================
// MARK: - Constants and Shared Definitions
// ============================================================================

// Color type constants (must match data-types.h)
constant uint COLOR_NOT_SET = 0;
constant uint COLOR_IS_SPECIAL = 1;
constant uint COLOR_IS_INDEX = 2;
constant uint COLOR_IS_RGB = 3;

// Cell attribute bit positions (must match cell_defines.glsl)
constant uint DECORATION_SHIFT = 0;
constant uint DECORATION_MASK = 7;
constant uint BOLD_SHIFT = 3;
constant uint ITALIC_SHIFT = 4;
constant uint REVERSE_SHIFT = 5;
constant uint STRIKE_SHIFT = 6;
constant uint DIM_SHIFT = 7;
constant uint BLINK_SHIFT = 8;
constant uint MARK_SHIFT = 9;
constant uint MARK_MASK = 3;

// Cursor shapes
constant uint NO_CURSOR = 0;
constant uint CURSOR_BLOCK = 1;
constant uint CURSOR_BEAM = 2;
constant uint CURSOR_UNDERLINE = 3;
constant uint CURSOR_HOLLOW = 4;

// Number of colors in color table
constant uint NUM_COLORS = 256;

// Linear space luminance coefficients
constant float3 Y = float3(0.2126, 0.7152, 0.0722);

// ============================================================================
// MARK: - Utility Functions
// ============================================================================

inline float srgb_to_linear(float x) {
    return x <= 0.04045f ? x / 12.92f : pow((x + 0.055f) / 1.055f, 2.4f);
}

inline float linear_to_srgb(float x) {
    return x <= 0.0031308f ? 12.92f * x : 1.055f * pow(x, 1.0f / 2.4f) - 0.055f;
}

inline float3 srgb_to_linear(float3 c) {
    return float3(srgb_to_linear(c.r), srgb_to_linear(c.g), srgb_to_linear(c.b));
}

inline float3 linear_to_srgb(float3 c) {
    return float3(linear_to_srgb(c.r), linear_to_srgb(c.g), linear_to_srgb(c.b));
}

inline float4 vec4_premul(float3 rgb, float a) {
    return float4(rgb * a, a);
}

inline float4 vec4_premul(float4 rgba) {
    return float4(rgba.rgb * rgba.a, rgba.a);
}

inline float4 alpha_blend(float4 over, float4 under) {
    float alpha = mix(under.a, 1.0f, over.a);
    float3 combined = mix(under.rgb * under.a, over.rgb, over.a);
    return float4(combined, alpha);
}

inline float4 alpha_blend_premul(float4 over, float4 under) {
    float inv_over_alpha = 1.0f - over.a;
    float alpha = over.a + under.a * inv_over_alpha;
    return float4(over.rgb + under.rgb * inv_over_alpha, alpha);
}

inline float4 alpha_blend_premul(float4 over, float3 under) {
    float inv_over_alpha = 1.0f - over.a;
    return float4(over.rgb + under * inv_over_alpha, 1.0f);
}

inline float zero_or_one(float x) {
    return step(1.0f, x);
}

inline float if_one_then(float condition, float thenval, float elseval) {
    return mix(elseval, thenval, condition);
}

inline float3 if_one_then(float condition, float3 thenval, float3 elseval) {
    return mix(elseval, thenval, condition);
}

inline float4 if_one_then(float condition, float4 thenval, float4 elseval) {
    return mix(elseval, thenval, condition);
}

inline float3 color_to_vec(uint c, constant float *gamma_lut) {
    uint r = (c >> 16) & 0xFF;
    uint g = (c >> 8) & 0xFF;
    uint b = c & 0xFF;
    return float3(gamma_lut[r], gamma_lut[g], gamma_lut[b]);
}

inline float3 color_to_vec_direct(uint c) {
    float r = float((c >> 16) & 0xFF) / 255.0f;
    float g = float((c >> 8) & 0xFF) / 255.0f;
    float b = float(c & 0xFF) / 255.0f;
    return float3(r, g, b);
}

// ============================================================================
// MARK: - Cell Rendering Structures
// ============================================================================

struct CellUniforms {
    // Selection color handling
    float use_cell_bg_for_selection_fg;
    float use_cell_fg_for_selection_fg;
    float use_cell_for_selection_bg;
    
    // Colors
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
    
    // Grid dimensions
    uint columns;
    uint lines;
    uint sprites_xnum;
    uint sprites_ynum;
    uint cursor_shape;
    uint cell_width;
    uint cell_height;
    
    // Cursor position
    uint cursor_x1;
    uint cursor_x2;
    uint cursor_y1;
    uint cursor_y2;
    
    // Alpha values
    float cursor_opacity;
    float inactive_text_alpha;
    float dim_opacity;
    float blink_opacity;
    
    // Background colors and opacities (8 slots)
    uint bg_colors[8];
    float bg_opacities[8];
    
    // Draw control
    uint draw_bg_bitfield;
    float row_offset;
    
    // Text rendering
    float text_contrast;
    float text_gamma_adjustment;
};

struct CellVertex {
    float2 pos;             // clip-space position
    float2 uv;              // glyph UV coordinates
    float2 underline_uv;    // underline sprite UV
    float2 strike_uv;       // strikethrough sprite UV
    float2 cursor_uv;       // cursor sprite UV
    uint   layer;           // sprite atlas layer
    float4 fg_rgba;         // premultiplied foreground color
    float4 bg_rgba;         // premultiplied background color
    float4 deco_rgba;       // decoration color (premultiplied)
    float  text_alpha;      // per-vertex text alpha
    float  colored_sprite;  // 1.0 if sprite is colored (emoji)
    float  cursor_alpha;    // cursor visibility
};

struct CellVSOut {
    float4 pos [[position]];
    float2 uv;
    float2 underline_uv;
    float2 strike_uv;
    float2 cursor_uv;
    uint   layer;
    float4 fg_rgba;
    float4 bg_rgba;
    float4 deco_rgba;
    float  text_alpha;
    float  colored_sprite;
    float  cursor_alpha;
};

// ============================================================================
// MARK: - Cell Vertex Shader
// ============================================================================

vertex CellVSOut cell_vs(const device CellVertex* vbuf [[buffer(0)]],
                         uint vid [[vertex_id]]) {
    CellVSOut o;
    CellVertex v = vbuf[vid];
    o.pos = float4(v.pos, 0.0, 1.0);
    o.uv = v.uv;
    o.underline_uv = v.underline_uv;
    o.strike_uv = v.strike_uv;
    o.cursor_uv = v.cursor_uv;
    o.layer = v.layer;
    o.fg_rgba = v.fg_rgba;
    o.bg_rgba = v.bg_rgba;
    o.deco_rgba = v.deco_rgba;
    o.text_alpha = v.text_alpha;
    o.colored_sprite = v.colored_sprite;
    o.cursor_alpha = v.cursor_alpha;
    return o;
}

// ============================================================================
// MARK: - Cell Fragment Shader (Full - BG + FG)
// ============================================================================

fragment float4 cell_fs(CellVSOut in [[stage_in]],
                        texture2d_array<float> sprites [[texture(0)]],
                        texture2d<uint> decor_map [[texture(1)]],
                        sampler samp [[sampler(0)]],
                        constant CellUniforms &u [[buffer(0)]]) {
    // Sample glyph from sprite atlas
    float4 glyph = sprites.sample(samp, in.uv, in.layer);
    float text_alpha = glyph.a * in.text_alpha;
    
    // For colored sprites (emoji), use sprite color; otherwise use fg color
    float3 fg = mix(in.fg_rgba.rgb, glyph.rgb, in.colored_sprite);
    float4 premul_fg = float4(fg * text_alpha, text_alpha);
    
    // Sample decorations
    float underline_alpha = sprites.sample(samp, in.underline_uv, in.layer).a;
    float strike_alpha = sprites.sample(samp, in.strike_uv, in.layer).a;
    float cursor_tex = sprites.sample(samp, in.cursor_uv, in.layer).a;
    float cursor = clamp(cursor_tex * in.cursor_alpha, 0.0f, 1.0f);
    
    // Composite foreground
    float4 outp = premul_fg;
    
    // Add underline (blend with decoration color)
    float4 underline_color = float4(in.deco_rgba.rgb * underline_alpha, in.deco_rgba.a * underline_alpha);
    outp = alpha_blend_premul(underline_color, outp);
    
    // Add strikethrough (same color as text)
    float combined_alpha = min(outp.a + strike_alpha * in.text_alpha, 1.0f);
    outp = float4(outp.rgb, combined_alpha);
    
    // Apply cursor overlay
    outp = mix(outp, in.deco_rgba, cursor);
    
    // Composite over background (premultiplied alpha blending)
    float one_minus_a = 1.0f - outp.a;
    return float4(outp.rgb + in.bg_rgba.rgb * one_minus_a, outp.a + in.bg_rgba.a * one_minus_a);
}

// ============================================================================
// MARK: - Cell Fragment Shader (Background Only)
// ============================================================================

fragment float4 cell_bg_fs(CellVSOut in [[stage_in]]) {
    return in.bg_rgba;
}

// ============================================================================
// MARK: - Cell Fragment Shader (Foreground Only)
// ============================================================================

fragment float4 cell_fg_fs(CellVSOut in [[stage_in]],
                           texture2d_array<float> sprites [[texture(0)]],
                           texture2d<uint> decor_map [[texture(1)]],
                           sampler samp [[sampler(0)]],
                           constant CellUniforms &u [[buffer(0)]]) {
    // Sample glyph
    float4 glyph = sprites.sample(samp, in.uv, in.layer);
    float text_alpha = glyph.a * in.text_alpha;
    
    float3 fg = mix(in.fg_rgba.rgb, glyph.rgb, in.colored_sprite);
    float4 premul_fg = float4(fg * text_alpha, text_alpha);
    
    // Decorations
    float underline_alpha = sprites.sample(samp, in.underline_uv, in.layer).a;
    float strike_alpha = sprites.sample(samp, in.strike_uv, in.layer).a;
    float cursor_tex = sprites.sample(samp, in.cursor_uv, in.layer).a;
    float cursor = clamp(cursor_tex * in.cursor_alpha, 0.0f, 1.0f);
    
    float4 outp = premul_fg;
    
    // Underline
    float4 underline_color = float4(in.deco_rgba.rgb * underline_alpha, in.deco_rgba.a * underline_alpha);
    outp = alpha_blend_premul(underline_color, outp);
    
    // Strike
    float combined_alpha = min(outp.a + strike_alpha * in.text_alpha, 1.0f);
    outp = float4(outp.rgb, combined_alpha);
    
    // Cursor
    outp = mix(outp, in.deco_rgba, cursor);
    
    return outp;
}

// ============================================================================
// MARK: - Quad/Clear Shader
// ============================================================================

struct QuadUniforms {
    float4 bg_clear;
};

struct QuadVSOut {
    float4 pos [[position]];
};

vertex QuadVSOut quad_vs(uint vid [[vertex_id]]) {
    constexpr float2 pts[4] = { {-1,-1}, {1,-1}, {-1,1}, {1,1} };
    QuadVSOut o;
    o.pos = float4(pts[vid], 0.0, 1.0);
    return o;
}

fragment float4 quad_fs(QuadVSOut in [[stage_in]],
                        constant QuadUniforms &u [[buffer(0)]]) {
    return u.bg_clear;
}

// ============================================================================
// MARK: - Background Image Shader
// ============================================================================

struct BGImageUniforms {
    float4 sizes;      // window_width, window_height, image_width, image_height
    float4 positions;  // left, top, right, bottom
    float4 background; // background color with alpha
    float tiled;
};

struct BGImageVSOut {
    float4 pos [[position]];
    float2 texcoord;
};

vertex BGImageVSOut bgimage_vs(uint vid [[vertex_id]],
                               constant BGImageUniforms &u [[buffer(0)]]) {
    constexpr float2 tex_map[4] = { {0,0}, {0,1}, {1,1}, {1,0} };
    
    float2 pos_map[4] = {
        float2(u.positions[0], u.positions[1]),  // left, top
        float2(u.positions[0], u.positions[3]),  // left, bottom
        float2(u.positions[2], u.positions[3]),  // right, bottom
        float2(u.positions[2], u.positions[1])   // right, top
    };
    
    float2 tex_coords = tex_map[vid];
    
    // Apply tiling factor
    float x_tile = u.tiled * (u.sizes[0] / u.sizes[2]) + (1.0 - u.tiled);
    float y_tile = u.tiled * (u.sizes[1] / u.sizes[3]) + (1.0 - u.tiled);
    
    BGImageVSOut o;
    o.pos = float4(pos_map[vid], 0.0, 1.0);
    o.texcoord = float2(tex_coords.x * x_tile, tex_coords.y * y_tile);
    return o;
}

fragment float4 bgimage_fs(BGImageVSOut in [[stage_in]],
                           texture2d<float> image [[texture(0)]],
                           sampler samp [[sampler(0)]],
                           constant BGImageUniforms &u [[buffer(0)]]) {
    float4 color = image.sample(samp, in.texcoord);
    return alpha_blend(color, u.background);
}

// ============================================================================
// MARK: - Tint Shader (Visual Bell, Overlays)
// ============================================================================

struct TintUniforms {
    float4 tint_color;  // premultiplied RGBA
    float4 edges;       // left, top, right, bottom in clip space
};

struct TintVSOut {
    float4 pos [[position]];
};

vertex TintVSOut tint_vs(uint vid [[vertex_id]],
                         constant TintUniforms &u [[buffer(0)]]) {
    float left = u.edges[0];
    float top = u.edges[1];
    float right = u.edges[2];
    float bottom = u.edges[3];
    
    float2 pos_map[4] = {
        float2(left, top),
        float2(left, bottom),
        float2(right, bottom),
        float2(right, top)
    };
    
    TintVSOut o;
    o.pos = float4(pos_map[vid], 0.0, 1.0);
    return o;
}

fragment float4 tint_fs(TintVSOut in [[stage_in]],
                        constant TintUniforms &u [[buffer(0)]]) {
    return u.tint_color;
}

// ============================================================================
// MARK: - Graphics/Image Shader
// ============================================================================

struct GraphicsUniforms {
    float4 src_rect;   // left, top, right, bottom in texture coords
    float4 dest_rect;  // left, top, right, bottom in clip space
    float extra_alpha;
};

struct GraphicsVSOut {
    float4 pos [[position]];
    float2 texcoord;
};

vertex GraphicsVSOut graphics_vs(uint vid [[vertex_id]],
                                 constant GraphicsUniforms &u [[buffer(0)]]) {
    constexpr int2 vertex_pos_map[4] = { {2,1}, {2,3}, {0,3}, {0,1} };
    
    int2 pos = vertex_pos_map[vid];
    
    GraphicsVSOut o;
    o.texcoord = float2(u.src_rect[pos.x], u.src_rect[pos.y]);
    o.pos = float4(u.dest_rect[pos.x], u.dest_rect[pos.y], 0.0, 1.0);
    return o;
}

fragment float4 graphics_fs(GraphicsVSOut in [[stage_in]],
                            texture2d<float> image [[texture(0)]],
                            sampler samp [[sampler(0)]],
                            constant GraphicsUniforms &u [[buffer(0)]]) {
    float4 color = image.sample(samp, in.texcoord);
    color.a *= u.extra_alpha;
    return vec4_premul(color);
}

fragment float4 graphics_premult_fs(GraphicsVSOut in [[stage_in]],
                                    texture2d<float> image [[texture(0)]],
                                    sampler samp [[sampler(0)]],
                                    constant GraphicsUniforms &u [[buffer(0)]]) {
    float4 color = image.sample(samp, in.texcoord);
    color.a *= u.extra_alpha;
    // Already premultiplied
    return color;
}

// Alpha mask variant for window numbers, etc.
struct AlphaMaskUniforms {
    float4 src_rect;
    float4 dest_rect;
    float3 amask_fg;
    float4 amask_bg_premult;
};

fragment float4 graphics_alpha_mask_fs(GraphicsVSOut in [[stage_in]],
                                       texture2d<float> image [[texture(0)]],
                                       sampler samp [[sampler(0)]],
                                       constant AlphaMaskUniforms &u [[buffer(0)]]) {
    float4 color = image.sample(samp, in.texcoord);
    float4 fg = float4(u.amask_fg, color.r);
    fg = vec4_premul(fg);
    return alpha_blend_premul(fg, u.amask_bg_premult);
}

// ============================================================================
// MARK: - Border Shader
// ============================================================================

struct BorderUniforms {
    uint colors[9];     // DEFAULT_BG, ACTIVE_BORDER, INACTIVE_BORDER, WINDOW_BG, BELL_BORDER, TAB_BAR_BG, TAB_BAR_MARGIN, EDGE_LEFT, EDGE_RIGHT
    float background_opacity;
    float gamma_lut[256];
};

struct BorderVertex {
    float4 rect;        // left, top, right, bottom
    uint rect_color;    // color index in low byte, window bg in high bytes
};

struct BorderVSOut {
    float4 pos [[position]];
    float4 color_premul;
};

vertex BorderVSOut border_vs(const device BorderVertex* vbuf [[buffer(0)]],
                             constant BorderUniforms &u [[buffer(1)]],
                             uint vid [[vertex_id]],
                             uint iid [[instance_id]]) {
    constexpr uint2 pos_map[4] = { {2,1}, {2,3}, {0,3}, {0,1} };  // right-top, right-bottom, left-bottom, left-top
    
    BorderVertex v = vbuf[iid];
    uint2 pos = pos_map[vid];
    
    // Extract window background from high bytes
    float3 window_bg = color_to_vec(v.rect_color >> 8, u.gamma_lut);
    uint rc = v.rect_color & 0xFF;
    
    // Get color from color table
    float3 color3 = color_to_vec(u.colors[rc], u.gamma_lut);
    
    // Check if this is window background placeholder (index 3)
    float is_window_bg = (rc == 3) ? 1.0f : 0.0f;
    float is_default_bg = (rc == 0) ? 1.0f : 0.0f;
    
    color3 = if_one_then(is_window_bg, window_bg, color3);
    
    // Border quads (indices 1, 2, 4) must be opaque
    float is_not_a_border = (rc != 1 && rc != 2 && rc != 4) ? 1.0f : 0.0f;
    float final_opacity = if_one_then(is_not_a_border, u.background_opacity, 1.0f);
    
    BorderVSOut o;
    o.pos = float4(v.rect[pos.x], v.rect[pos.y], 0.0, 1.0);
    o.color_premul = vec4_premul(color3, final_opacity);
    return o;
}

fragment float4 border_fs(BorderVSOut in [[stage_in]]) {
    return in.color_premul;
}

// ============================================================================
// MARK: - Rounded Rectangle Shader (Scrollbar)
// ============================================================================

struct RoundedRectUniforms {
    float4 rect;            // x, y (bottom-left), width, height
    float2 params;          // thickness, corner_radius
    float4 color;           // fill color with alpha
    float4 background_color;
};

struct RoundedRectVSOut {
    float4 pos [[position]];
};

vertex RoundedRectVSOut rounded_rect_vs(uint vid [[vertex_id]]) {
    constexpr float4 dest_rect = float4(-1, 1, 1, -1);
    constexpr int2 vertex_pos_map[4] = { {2,1}, {2,3}, {0,3}, {0,1} };
    
    int2 pos = vertex_pos_map[vid];
    
    RoundedRectVSOut o;
    o.pos = float4(dest_rect[pos.x], dest_rect[pos.y], 0.0, 1.0);
    return o;
}

// Signed distance function for rounded rectangle
float rounded_rectangle_sdf(float2 p, float2 b, float r) {
    float2 q = abs(p) - b;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

fragment float4 rounded_rect_fs(RoundedRectVSOut in [[stage_in]],
                                constant RoundedRectUniforms &u [[buffer(0)]]) {
    float2 size = u.rect.zw;
    float2 origin = u.rect.xy;
    float thickness = u.params[0];
    float corner_radius = u.params[1];
    
    // Position relative to center of rectangle
    float2 position = in.pos.xy - size / 2.0 - origin;
    
    // Calculate distance to rounded rectangle
    float dist = rounded_rectangle_sdf(position, size * 0.5 - corner_radius, corner_radius);
    
    // Border is outer - inner rects
    float outer_edge = -dist;
    float inner_edge = outer_edge - thickness;
    
    // Smooth borders (anti-alias)
    constexpr float step_size = 1.0;
    float alpha = smoothstep(-step_size, step_size, outer_edge) - smoothstep(-step_size, step_size, inner_edge);
    
    float4 ans = u.color;
    ans.a *= alpha;
    
    return alpha_blend(ans, u.background_color);
}

// ============================================================================
// MARK: - Cursor Trail Shader
// ============================================================================

struct TrailUniforms {
    float4 x_coords;        // corner x coordinates
    float4 y_coords;        // corner y coordinates
    float2 cursor_edge_x;   // cursor exclusion zone x
    float2 cursor_edge_y;   // cursor exclusion zone y
    float3 trail_color;
    float trail_opacity;
};

struct TrailVSOut {
    float4 pos [[position]];
    float2 frag_pos;
};

vertex TrailVSOut trail_vs(uint vid [[vertex_id]],
                           constant TrailUniforms &u [[buffer(0)]]) {
    float2 pos = float2(u.x_coords[vid], u.y_coords[vid]);
    
    TrailVSOut o;
    o.pos = float4(pos, 1.0, 1.0);
    o.frag_pos = pos;
    return o;
}

fragment float4 trail_fs(TrailVSOut in [[stage_in]],
                         constant TrailUniforms &u [[buffer(0)]]) {
    float opacity = u.trail_opacity;
    
    // Don't render if fragment is within cursor area
    float in_x = step(u.cursor_edge_x[0], in.frag_pos.x) * step(in.frag_pos.x, u.cursor_edge_x[1]);
    float in_y = step(u.cursor_edge_y[1], in.frag_pos.y) * step(in.frag_pos.y, u.cursor_edge_y[0]);
    opacity *= 1.0f - in_x * in_y;
    
    return float4(u.trail_color * opacity, opacity);
}

// ============================================================================
// MARK: - Blit Shader (Final Composite)
// ============================================================================

struct BlitUniforms {
    float4 src_rect;
    float4 dest_rect;
};

struct BlitVSOut {
    float4 pos [[position]];
    float2 texcoord;
};

vertex BlitVSOut blit_vs(uint vid [[vertex_id]],
                         constant BlitUniforms &u [[buffer(0)]]) {
    constexpr int2 vertex_pos_map[4] = { {2,1}, {2,3}, {0,3}, {0,1} };
    
    int2 pos = vertex_pos_map[vid];
    
    BlitVSOut o;
    o.texcoord = float2(u.src_rect[pos.x], u.src_rect[pos.y]);
    o.pos = float4(u.dest_rect[pos.x], u.dest_rect[pos.y], 0.0, 1.0);
    return o;
}

fragment float4 blit_fs(BlitVSOut in [[stage_in]],
                        texture2d<float> image [[texture(0)]],
                        sampler samp [[sampler(0)]]) {
    return image.sample(samp, in.texcoord);
}

// ============================================================================
// MARK: - Background-only vertex shader (simplified)
// ============================================================================

struct BGVertex {
    float2 pos;
    float4 bg_rgba;
};

struct BGVSOut {
    float4 pos [[position]];
    float4 bg_rgba;
};

vertex BGVSOut bg_vs(const device BGVertex* vbuf [[buffer(0)]],
                     uint vid [[vertex_id]]) {
    BGVSOut o;
    BGVertex v = vbuf[vid];
    o.pos = float4(v.pos, 0.0, 1.0);
    o.bg_rgba = v.bg_rgba;
    return o;
}

fragment float4 bg_fs(BGVSOut in [[stage_in]]) {
    return in.bg_rgba;
}
