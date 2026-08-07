#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Underwater light ray effect.
// Adapted from https://www.shadertoy.com/view/lljGDt

import kitty_custom_shader_types;

// Luminance threshold: pixels darker than this receive the ray overlay
extern static const float BLACK_BLEND_THRESHOLD = 0.4;

// Ray 1 source position (as fractions of viewport dimensions)
extern static const float RAY1_SRC_X  = 0.7;
extern static const float RAY1_SRC_Y  = 1.1;
// Y component of ray 1 reference direction (X component is always 1.0)
extern static const float RAY1_DIR_Y  = 0.116;
extern static const float RAY1_SEED_A = 36.2214;
extern static const float RAY1_SEED_B = 21.11349;
extern static const float RAY1_SPEED  = 1.1;
extern static const float RAY1_WEIGHT = 0.5;   // contribution weight in final blend

// Ray 2 source position (as fractions of viewport dimensions)
extern static const float RAY2_SRC_X  = 0.8;
extern static const float RAY2_SRC_Y  = 1.2;
extern static const float RAY2_DIR_Y  = -0.241;
extern static const float RAY2_SEED_A = 22.39910;
extern static const float RAY2_SEED_B = 18.0234;
extern static const float RAY2_SPEED  = 0.9;
extern static const float RAY2_WEIGHT = 0.4;

// Per-channel depth-attenuation: channel *= BASE + brightness * SCALE
extern static const float DEPTH_R_BASE  = 0.05;
extern static const float DEPTH_R_SCALE = 0.8;
extern static const float DEPTH_G_BASE  = 0.15;
extern static const float DEPTH_G_SCALE = 0.6;
extern static const float DEPTH_B_BASE  = 0.3;
extern static const float DEPTH_B_SCALE = 0.5;

// Overall strength of the ray overlay on dark terminal content
extern static const float OVERLAY_STRENGTH = 0.3;

float hash21(float2 p) {
    p = frac(p * float2(233.34, 851.73));
    p += dot(p, p + 23.45);
    return frac(p.x * p.y);
}

float rayStrength(
    float2 raySource, float2 rayRefDir, float2 coord,
    float seedA, float seedB, float speed,
    float iTime, float resX
) {
    float2 sourceToCoord = coord - raySource;
    float  cosAngle      = dot(normalize(sourceToCoord), rayRefDir);
    float  dither        = hash21(coord) * 0.015 - 0.0075;
    float  ray           = clamp(
        (0.45 + 0.15 * sin( cosAngle * seedA + iTime * speed)) +
        (0.30 + 0.20 * cos(-cosAngle * seedB + iTime * speed)) + dither,
        0.0, 1.0);
    float distFade = smoothstep(0.0, resX, resX - length(sourceToCoord));
    return ray * lerp(0.5, 1.0, distFade);
}

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    float2 iResolution = float2(d.viewport_size_pixels) * viewport.zw;
    float  iTime       = d.timestamp;

    // Convert kitty UV (y=0 at bottom) to a top-left-origin pixel coordinate,
    // matching the original shader's internal coordinate system.
    float2 coord = float2(t.pos.x, 1.0 - t.pos.y) * iResolution;

    float2 rayPos1    = float2(iResolution.x * RAY1_SRC_X, iResolution.y * RAY1_SRC_Y);
    float2 rayRefDir1 = normalize(float2(1.0, RAY1_DIR_Y));

    float2 rayPos2    = float2(iResolution.x * RAY2_SRC_X, iResolution.y * RAY2_SRC_Y);
    float2 rayRefDir2 = normalize(float2(1.0, RAY2_DIR_Y));

    float4 rays1 = float4(1.0, 1.0, 1.0, 0.0) *
        rayStrength(rayPos1, rayRefDir1, coord,
                    RAY1_SEED_A, RAY1_SEED_B, RAY1_SPEED, iTime, iResolution.x);

    float4 rays2 = float4(1.0, 1.0, 1.0, 0.0) *
        rayStrength(rayPos2, rayRefDir2, coord,
                    RAY2_SEED_A, RAY2_SEED_B, RAY2_SPEED, iTime, iResolution.x);

    float4 col = rays1 * RAY1_WEIGHT + rays2 * RAY2_WEIGHT;

    // Attenuate toward the bottom (depth) with a blue-green tint
    float brightness = t.pos.y;  // 0 at screen bottom (deep), 1 at top (surface)
    col.r *= DEPTH_R_BASE + brightness * DEPTH_R_SCALE;
    col.g *= DEPTH_G_BASE + brightness * DEPTH_G_SCALE;
    col.b *= DEPTH_B_BASE + brightness * DEPTH_B_SCALE;

    float4 terminalColor = t.backbuffer.Sample(t.pos);

    // Overlay rays onto dark (near-black) terminal pixels; preserve bright content
    float  alpha        = step(length(terminalColor.rgb), BLACK_BLEND_THRESHOLD);
    float3 blendedColor = lerp(terminalColor.rgb, col.rgb * OVERLAY_STRENGTH, alpha);

    return float4(blendedColor, terminalColor.a);
}
