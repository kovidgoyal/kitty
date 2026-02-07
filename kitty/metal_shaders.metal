#include <metal_stdlib>
using namespace metal;

// ----------- Shared structs ------------
struct CellVertex {
    float2 pos;            // clip-space
    float2 uv;             // glyph UV
    float2 underline_uv;
    float2 strike_uv;
    float2 cursor_uv;
    uint   layer;          // sprite layer
    float4 fg_rgba;        // premul fg
    float4 bg_rgba;        // premul bg
    float4 deco_rgba;      // decoration color (premul)
    float  text_alpha;     // per-vertex text alpha
    float  colored_sprite; // mix factor
    float  cursor_alpha;   // explicit cursor mask
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

struct Uniforms {
    float4 bg_clear;
};

// ----------- Pipelines ------------
vertex CellVSOut cell_vs(const device CellVertex* vbuf [[buffer(0)]],
                        uint vid [[vertex_id]]) {
    CellVSOut o;
    CellVertex v = vbuf[vid];
    o.pos = float4(v.pos, 0, 1);
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

fragment float4 cell_fs(CellVSOut in [[stage_in]],
                        texture2d_array<float> sprites [[texture(0)]],
                        texture2d<uint> decor [[texture(1)]],
                        sampler samp [[sampler(0)]]) {
    float4 glyph = sprites.sample(samp, float3(in.uv, float(in.layer)));
    float text_alpha = glyph.a * in.text_alpha;
    float3 fg = mix(in.fg_rgba.rgb, glyph.rgb, in.colored_sprite);
    float4 premul_fg = float4(fg * text_alpha, text_alpha);

    float underline = sprites.sample(samp, float3(in.underline_uv, float(in.layer))).a;
    float strike = sprites.sample(samp, float3(in.strike_uv, float(in.layer))).a;
    float cursor_tex = sprites.sample(samp, float3(in.cursor_uv, float(in.layer))).a;
    float cursor = clamp(cursor_tex * in.cursor_alpha, 0.0, 1.0);

    float4 outp = premul_fg;
    // underline blends decoration color
    outp = mix(outp, float4(outp.rgb + in.deco_rgba.rgb * underline, outp.a + in.deco_rgba.a * underline), underline);
    // strike simply adds alpha to avoid extra texture fetch complexity
    outp = float4(outp.rgb + outp.a * strike, clamp(outp.a + strike, 0.0, 1.0));
    // cursor overrides with deco color
    outp = mix(outp, in.deco_rgba, cursor);
    // composite over cell background (premultiplied)
    float one_minus_a = 1.0 - outp.a;
    return float4(outp.rgb + in.bg_rgba.rgb * one_minus_a, outp.a + in.bg_rgba.a * one_minus_a);
}

// Simple solid quad used for clears/blits
struct QuadVSOut { float4 pos [[position]]; };
vertex QuadVSOut quad_vs(uint vid [[vertex_id]]) {
    float2 pts[4] = { {-1,-1}, {1,-1}, { -1,1 }, {1,1} };
    QuadVSOut o; o.pos = float4(pts[vid], 0,1); return o; }
fragment float4 quad_fs(QuadVSOut in [[stage_in]], constant Uniforms &u [[buffer(0)]]) {
    return u.bg_clear;
}
