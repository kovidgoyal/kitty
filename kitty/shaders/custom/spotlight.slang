#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Spotlight effect
// Original GLSL by Paul Robello, ported to Slang for kitty

import kitty_custom_shader_types;

extern static const float SPOTLIGHT_RADIUS   = 0.25;  // spotlight radius in UV units
extern static const float SPOTLIGHT_SOFTNESS = 20.0;  // edge sharpness; higher = sharper
extern static const float AMBIENT_LIGHT      = 0.5;   // minimum brightness outside the spotlight
extern static const float SPOTLIGHT_SPEED    = 1.0;   // oscillation speed in random-motion mode
// Set to 1 to follow the mouse, 0 to use random oscillation
extern static const int   USE_MOUSE          = 1;
// When USE_MOUSE=1 and the mouse leaves the window:
//   0 = fall back to random oscillation
//   1 = clamp spotlight to the nearest window edge
extern static const int   MOUSE_CLAMP_TO_EDGE = 0;
// Set to 1 to pass through unchanged pixels when the mouse pointer is hidden
extern static const int   HIDE_WHEN_POINTER_HIDDEN = 1;

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    if (HIDE_WHEN_POINTER_HIDDEN == 1.0 && d.mouse_pointer_hidden != 0.0) return color;
    float2 uv = t.pos;

    // Viewport pixel dimensions for aspect-ratio correction
    float2 pixelDims   = float2(d.viewport_size_pixels) * viewport.zw;
    float  aspectRatio = pixelDims.x / pixelDims.y;

    // Random oscillating center (different frequencies and phases on each axis)
    float  time         = d.timestamp * SPOTLIGHT_SPEED;
    float2 randomCenter = float2(
        0.5 + 0.4 * sin(time),
        0.5 + 0.4 * sin(time * 1.3 + 3.14159)
    );

    // Mouse is valid only when both coords are inside the OS window [0, 1]
    float2 mp            = d.mouse_pos.xy;
    float  mouseInWindow = float(all(mp >= float2(0.0)) && all(mp <= float2(1.0)));

    // When mouse leaves the window: clamp to nearest edge or fall back to random
    float2 outsideFallback = lerp(randomCenter, clamp(mp, float2(0.0), float2(1.0)), float(MOUSE_CLAMP_TO_EDGE));

    // Branchless center selection
    float2 mouseCenter     = lerp(outsideFallback, mp, mouseInWindow);
    float2 spotlightCenter = lerp(randomCenter, mouseCenter, float(USE_MOUSE));

    // Euclidean distance in aspect-ratio-corrected space (produces a circular spotlight)
    float distToCenter = length((uv - spotlightCenter) * float2(aspectRatio, 1.0));

    // Soft spotlight edge
    float spotlightIntensity = smoothstep(
        SPOTLIGHT_RADIUS,
        SPOTLIGHT_RADIUS - (1.0 / SPOTLIGHT_SOFTNESS),
        distToCenter
    );

    // Blend between ambient and full illumination
    float3 result = color.rgb * lerp(float3(AMBIENT_LIGHT), float3(1.0), spotlightIntensity);

    return float4(result, color.a);
}
