#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Original shader: https://www.shadertoy.com/view/WsVSzV (CC BY NC SA 3.0)
// Ported to slang and modified for kitty
//
// Note that this shader does not work with background_opacity < 1

import kitty_custom_shader_types;

static const float WARP = 0.25f;                   // simulates curvature of CRT monitor
static const float SCAN = 0.50f;                   // simulates darkness between scanlines
static const float4 TINT = float4(0, 0.8, 0.6, 0); // tint color set the fourth component to 1 to apply it fully

// Warp UV to simulate CRT screen curvature
float2
warp(float2 uv) {
    // Squared distance from center (drives curvature)
    float2 dc = abs(0.5f - uv);
    dc *= dc;
    uv.x -= 0.5f;
    uv.x *= 1.0f + (dc.y * (0.3f * WARP));
    uv.x += 0.5f;
    uv.y -= 0.5f;
    uv.y *= 1.0f + (dc.x * (0.4f * WARP));
    uv.y += 0.5f;
    return uv;
}

// Make clicks land on the text that is shown under the pointer
public float2
pointer_map(float2 pos, KittyCustomShaderData d) {
    return warp(pos);
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    // UV within the current viewport (0..1)
    float2 uv = warp(t.pos);

    // Original Y pixel coordinate within the viewport (for scanline phase)
    float fragCoordY = t.pos.y * float(d.viewport_size_pixels.y) * t.viewport.w;

    // Scanline darkness at this pixel row
    float apply = abs(sin(fragCoordY) * 0.25f * SCAN);

    // Sample the backbuffer at the warped viewport UV
    float3 col = t.backbuffer.Sample(uv).rgb;
    // apply the tint
    col = lerp(col, col * TINT.rgb, TINT.a);

    // since this shaders moves pixels around it cannot work with alpha < 1
    return float4(lerp(col, float3(0.0f), apply), 1);
}
