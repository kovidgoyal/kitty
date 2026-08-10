#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Focus highlight effect
// Briefly illuminates the active window whenever it gains focus, then fades out.
// Uses d.active_window_geometry to locate the window bounds in UV space.
// animation_progress (0 → 1) drives the fade over the pipeline duration.

import kitty_custom_shader_types;

// Brightness multiplier boost applied to content inside the active window.
// 0.0 = no boost, 0.15 = 15% brighter.
static const float HIGHLIGHT_INTENSITY = 0.30;
// Width of the inner border glow in UV units.
static const float BORDER_WIDTH = 0.04;
// Peak additive brightness multiplier at the window border edge.
static const float BORDER_GLOW = 0.55;
// Dim factor applied to pixels outside the active window (1.0 = unchanged, 0.0 = black).
static const float INACTIVE_DIM = 0.3;

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    float4 g = d.active_window_geometry;
    // Pass through unchanged if no active window geometry is known.
    if (g.z <= 0.0 || g.w <= 0.0) return color;

    float2 uv     = t.pos;
    float2 winMin = g.xy;
    float2 winMax = g.xy + g.zw;

    // Effect strength decays from 1 at animation start to 0 at the end.
    float strength = 1.0 - animation_progress;

    bool inWindow = all(uv >= winMin) && all(uv <= winMax);

    if (inWindow) {
        // Minimum distance from this pixel to any edge of the active window.
        float2 edgeDists  = min(uv - winMin, winMax - uv);
        float  nearestEdge = min(edgeDists.x, edgeDists.y);

        // Additive border glow: strongest at the edge, falls off over BORDER_WIDTH.
        float borderGlow = smoothstep(BORDER_WIDTH, 0.0, nearestEdge) * BORDER_GLOW;

        float boost = (HIGHLIGHT_INTENSITY + borderGlow) * strength;
        return float4(color.rgb * (1.0 + boost), color.a);
    } else {
        // Slightly dim inactive areas to draw the eye to the focused window.
        float dim = lerp(1.0, INACTIVE_DIM, strength);
        return float4(color.rgb * dim, color.a);
    }
}
