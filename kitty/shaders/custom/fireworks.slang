#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Fireworks shader — port of https://www.shadertoy.com/view/lscGRl
// "Fireworks" by Martijn Steinrucken aka BigWings - 2015
// License: Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported

import kitty_custom_shader_types;

static const int   NUM_EXPLOSIONS        = 3;
static const int   NUM_PARTICLES         = 42;
static const float BLACK_BLEND_THRESHOLD = 0.4f;
static const float TIME_SCALE            = 0.5f;
static const float PI                    = 3.14159265359f;

// Noise constant from Dave Hoskins — not user-tunable so kept as plain static const
static const float3 MOD3 = float3(0.1031f, 0.11369f, 0.13787f);

float3 hash31(float p) {
    float3 p3 = frac(float3(p) * MOD3);
    p3 += dot(p3, p3.yzx + 19.19f);
    return frac(float3((p3.x + p3.y) * p3.z,
                       (p3.x + p3.z) * p3.y,
                       (p3.y + p3.z) * p3.x));
}

float hash12(float2 p) {
    float3 p3 = frac(float3(p.xyx) * MOD3);
    p3 += dot(p3, p3.yzx + 19.19f);
    return frac((p3.x + p3.y) * p3.z);
}

float light(float2 uv, float2 pos, float size) {
    uv   -= pos;
    size *= size;
    return size / dot(uv, uv);
}

float3 explosion(float2 uv, float2 p, float seed, float t) {
    float3 col     = float3(0.0f);
    float3 en      = hash31(seed);
    float3 baseCol = en;

    // startP, pt, and b are loop-invariant; computed once outside
    float2 startP = p - float2(0.0f, t * t * 0.1f);
    float  pt     = 1.0f - pow(t - 1.0f, 2.0f);
    // B(en.x, en.y, en.z, t) macro expansion
    float  b      = smoothstep(en.x - en.z, en.x + en.z, t)
                  * smoothstep(en.y + en.z, en.y - en.z, t);
    float  sizeBase = lerp(0.01f, 0.005f, smoothstep(0.0f, 0.1f, pt))
                    * smoothstep(1.0f, 0.1f, pt);

    [ForceUnroll]
    for (int i = 0; i < NUM_PARTICLES; i++) {
        float3 n    = hash31(float(i)) - 0.5f;
        float2 endP = startP + normalize(n.xy) * n.z - float2(0.0f, t * 0.2f);
        float2 pos  = lerp(p, endP, pt);

        float sparkle = sin((pt + n.z) * 21.0f) * 0.5f + 0.5f;
        sparkle = pow(sparkle, pow(en.x, 3.0f) * 50.0f)
                * lerp(0.01f, 0.01f, en.y * n.y);

        col += baseCol * light(uv, pos, sizeBase + sparkle * b);
    }
    return col;
}

float3 rainbow(float3 c, float time) {
    float avg = (c.r + c.g + c.b) / 3.0f;
    c  = avg + (c - avg) * sin(float3(0.0f, 0.333f, 0.666f) + time);
    c += sin(float3(0.4f, 0.3f, 0.3f) * time
           + float3(1.1244f, 3.43215f, 6.435f))
       * float3(0.4f, 0.1f, 0.5f);
    return c;
}

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    float2 pixelDims = float2(d.viewport_size_pixels) * viewport.zw;
    float  aspect    = pixelDims.x / pixelDims.y;
    float  time      = fmod(d.timestamp, 3600.0f) * TIME_SCALE;

    // Aspect-corrected UV with y=0 at top so gravity points downward
    float2 uv = t.pos;
    uv.x -= 0.5f;
    uv.x *= aspect;
    uv.y  = -uv.y + 1.0f;

    float3 c = float3(0.0f);

    [ForceUnroll]
    for (int i = 0; i < NUM_EXPLOSIONS; i++) {
        float et = time + float(i) * 1234.45235f;
        float id = floor(et);
        et      -= id;

        float2 p = hash31(id).xy;
        p.x -= 0.5f;
        p.x *= 1.6f;
        c += explosion(uv, p, id, et);
    }
    c = rainbow(c, d.timestamp);

    float4 terminalColor = t.backbuffer.Sample(t.pos);
    float  alpha         = step(length(terminalColor.rgb), BLACK_BLEND_THRESHOLD);
    float3 blended       = lerp(terminalColor.rgb, c * 0.3f, alpha);

    return float4(blended, terminalColor.a);
}
