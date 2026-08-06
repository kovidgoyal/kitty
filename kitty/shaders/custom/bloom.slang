#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Original shader: https://gist.github.com/qwerasd205/c3da6c610c8ffe17d6d2d3cc7068f17f
// Credits: https://github.com/qwerasd205
// Bloom effect using golden spiral sample pattern.

import kitty_custom_shader_types;

// Golden spiral samples [x, y, weight] — weight is inverse of distance
static const float3 samples[24] = {
    float3(0.1693761725038636,  0.9855514761735895,  1.0),
    float3(-1.333070830962943,  0.4721463328627773,  0.7071067811865475),
    float3(-0.8464394909806497, -1.51113870578065,   0.5773502691896258),
    float3(1.554155680728463,   -1.2588090085709776, 0.5),
    float3(1.681364377589461,   1.4741145918052656,  0.4472135954999579),
    float3(-1.2795157692199817, 2.088741103228784,   0.4082482904638631),
    float3(-2.4575847530631187, -0.9799373355024756, 0.3779644730092272),
    float3(0.5874641440200847,  -2.7667464429345077, 0.35355339059327373),
    float3(2.997715703369726,   0.11704939884745152, 0.3333333333333333),
    float3(0.41360842451688395, 3.1351121305574803,  0.31622776601683794),
    float3(-3.167149933769243,  0.9844599011770256,  0.30151134457776363),
    float3(-1.5736713846521535, -3.0860263079123245, 0.2886751345948129),
    float3(2.888202648340422,   -2.1583061557896213, 0.2773500981126146),
    float3(2.7150778983300325,  2.5745586041105715,  0.2672612419124244),
    float3(-2.1504069972377464, 3.2211410627650165,  0.2581988897471611),
    float3(-3.6548858794907493, -1.6253643308191343, 0.25),
    float3(1.0130775986052671,  -3.9967078676335834, 0.24253562503633297),
    float3(4.229723673607257,   0.33081361055181563, 0.23570226039551587),
    float3(0.40107790291173834, 4.340407413572593,   0.22941573387056174),
    float3(-4.319124570236028,  1.159811599693438,   0.22360679774997896),
    float3(-1.9209044802827355, -4.160543952132907,  0.2182178902359924),
    float3(3.8639122286635708,  -2.6589814382925123, 0.21320071635561041),
    float3(3.3486228404946234,  3.4331800232609,     0.20851441405707477),
    float3(-2.8769733643574344, 3.9652268864187157,  0.20412414523193154)
};

// minimum luminance for a pixel to contribute bloom
extern static const float bloom_threshold = 0.2f;
// strength of the bloom contribution
extern static const float bloom_strength = 0.2f;

float lum(float4 c) {
    return 0.299f * c.r + 0.587f * c.g + 0.114f * c.b;
}

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    float2 uv = t.pos;

    // One pixel in backbuffer UV space; scale by sqrt(2) to match original step
    float2 step = float2(1.414f) / float2(d.viewport_size_pixels);

    float4 result = color;

    [ForceUnroll]
    for (int i = 0; i < 24; i++) {
        float3 s = samples[i];
        float4 sc = t.backbuffer.Sample(uv + s.xy * step);
        float l = lum(sc);
        result += (float4)(l * s.z * sc * bloom_strength) * ::step(bloom_threshold, l);
    }

    return result;
}
