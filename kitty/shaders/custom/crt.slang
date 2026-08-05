#language slang 2026
// Original shader: https://www.shadertoy.com/view/WsVSzV (CC BY NC SA 3.0)
// Ported to slang for kitty

import kitty_custom_shader_types;

extern static const float warp = 0.25f;  // simulates curvature of CRT monitor
extern static const float scan = 0.50f;  // simulates darkness between scanlines

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport
) {
    // UV within the current viewport (0..1)
    float2 uv = t.pos;

    // Squared distance from center (drives curvature)
    float2 dc = abs(0.5f - uv);
    dc *= dc;

    // Warp UV to simulate CRT screen curvature
    uv.x -= 0.5f; uv.x *= 1.0f + (dc.y * (0.3f * warp)); uv.x += 0.5f;
    uv.y -= 0.5f; uv.y *= 1.0f + (dc.x * (0.4f * warp)); uv.y += 0.5f;

    // Original Y pixel coordinate within the viewport (for scanline phase)
    float fragCoordY = (t.pos.y - viewport.y) * float(d.viewport_size_pixels.y);

    // Scanline darkness at this pixel row
    float apply = abs(sin(fragCoordY) * 0.25f * scan);

    // Sample the backbuffer at the warped viewport UV
    float2 sample_uv = viewport.xy + uv * viewport.zw;
    float3 col = t.backbuffer.Sample(sample_uv).rgb;

    return float4(lerp(col, float3(0.0f), apply), 1.0f);
}
