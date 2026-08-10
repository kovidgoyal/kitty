#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Water caustics effect.

import kitty_custom_shader_types;

static const float  TAU             = 6.28318530718;
static const int    MAX_ITER        = 6;
static const float3 WATER_COLOR     = float3(0.5, 0.5, 0.5);  // water overlay tint
static const float  CAUSTIC_INTEN   = 0.005;                  // caustic ripple intensity
static const float  UV_DISPLACEMENT = 0.04;                   // UV warp magnitude from caustics

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d
) {
    float  wtime = d.timestamp * 0.5 + 23.0;
    float2 uv    = t.pos;

    float2 p = fmod(uv * TAU, TAU) - 250.0;
    float2 i = p;
    float  c = 1.0;

    [ForceUnroll]
    for (int n = 0; n < MAX_ITER; n++) {
        float tval = wtime * (1.0 - (3.5 / float(n + 1)));
        i = p + float2(cos(tval - i.x) + sin(tval + i.y),
                       sin(tval - i.y) + cos(tval + i.x));
        c += 1.0 / length(float2(p.x / (sin(i.x + tval) / CAUSTIC_INTEN),
                                 p.y / (cos(i.y + tval) / CAUSTIC_INTEN)));
    }
    c /= float(MAX_ITER);
    c = 1.17 - pow(c, 1.4);
    float3 col = float3(pow(abs(c), 15.0));
    col = clamp((col + WATER_COLOR) * 1.2, 0.0, 1.0);

    // Perturb UV based on caustic value and resample
    float2 tc = float2(cos(c) - 0.75, sin(c) - 0.75) * UV_DISPLACEMENT;
    uv = clamp(uv + tc, 0.0, 1.0);

    float4 result = t.backbuffer.Sample(uv);
    // Branchless: give fully-transparent pixels an opaque white base
    float transparent = 1.0 - step(1e-6, result.a);
    result = lerp(result, float4(1.0, 1.0, 1.0, 1.0), transparent);
    return result * float4(col, 1.0);
}
