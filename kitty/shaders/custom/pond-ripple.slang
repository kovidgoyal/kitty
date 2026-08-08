#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Pond ripple effect — concentric expanding rings centered on pointer-left-button-press.
// animation_progress (0 → 1) drives the wavefront expansion over the pipeline duration.

import kitty_custom_shader_types;

// Maximum wavefront radius at animation_progress=1 (aspect-corrected UV units).
extern static const float WAVE_SPEED     = 0.45;
// Spatial frequency of the rings (cycles per aspect-corrected UV unit).
extern static const float WAVE_FREQUENCY = 14.0;
// Starting half-width of the Gaussian envelope (expands as animation_progress increases).
extern static const float WAVE_WIDTH     = 0.055;
// Peak radial UV displacement at the wavecrest.
extern static const float AMPLITUDE      = 0.010;
// Multiplicative brightness modulation at the wave crests (water-surface sheen).
extern static const float CREST_BRIGHT   = 0.12;

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    float2 pixelDims = float2(d.viewport_size_pixels) * viewport.zw;
    float  aspect    = pixelDims.x / pixelDims.y;

    // d.mouse_pos.zw is the UV position of the last left-button press (y=0 at bottom).
    float2 center = d.mouse_pos.zw;

    // Aspect-corrected vector from the click center to this pixel.
    float2 delta = (t.pos - center) * float2(aspect, 1.0);
    float  dist  = length(delta);
    float2 dir   = delta / max(dist, 1e-5);

    // Wavefront radius advances linearly with animation_progress.
    float front = WAVE_SPEED * animation_progress;

    // Signed distance from the wavefront (negative = wave has passed, positive = not yet reached).
    float behind = dist - front;

    // Gaussian spatial envelope centered at the wavefront; grows in width over time.
    float sigma = WAVE_WIDTH * (1.0 + animation_progress);
    float env   = exp(-behind * behind / (2.0 * sigma * sigma));

    // Causality: suppress any energy ahead of the wavefront.
    env *= 1.0 - smoothstep(-0.01, 0.02, behind);

    // Temporal amplitude decay as the wave expands outward.
    float decay = pow(1.0 - animation_progress, 0.7);

    // Traveling sinusoidal wave: phase = k * (dist − front).
    float wave = sin(behind * WAVE_FREQUENCY * 6.28318530718);

    // Radial UV displacement: push pixels away from center at crests, pull inward at troughs.
    float2 warpedUV = clamp(
        t.pos + dir * (wave * env * decay * AMPLITUDE),
        float2(0.0), float2(1.0)
    );

    // Sample the terminal backbuffer at the displaced position.
    float4 result = t.backbuffer.Sample(warpedUV);

    // Multiplicative brightness sheen at the wave crests (simulates reflected surface light).
    result.rgb *= 1.0 + abs(wave) * env * decay * CREST_BRIGHT;

    return result;
}
