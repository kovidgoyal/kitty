#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Tab-change reveal shader
// Plays a brief reveal animation whenever the active tab changes.
// The reveal direction for wipe-based modes is derived from d.central_area:
// the wipe starts at whichever edge of the content area is furthest from the
// viewport boundary — that edge is where the tab bar sits.
//
// ANIMATION_TYPE selects the effect:
//   0 = FADE   — uniform brightness fade-in over the whole screen
//   1 = WIPE   — a single swept edge travelling away from the tab bar
//   2 = BLINDS — sequential strip reveals sweeping away from the tab bar
//   3 = IRIS   — circular iris expanding from the centre of the content area

import kitty_custom_shader_types;

// 0=FADE, 1=WIPE, 2=BLINDS, 3=IRIS
extern static const int ANIMATION_TYPE = 1;

// Number of strips for ANIMATION_TYPE == 2 (BLINDS).
extern static const int NUM_BLINDS = 8;

// Soft-edge width in UV units used by WIPE and IRIS.
extern static const float EDGE_SOFTNESS = 0.04;

// Returns a value in [0, 1] for this pixel: 0 at the tab-bar edge of the
// content area, 1 at the opposite edge.  The wipe sweeps from 0 toward 1.
float wipe_pixel_pos(float2 uv, float4 ca) {
    float gap_left   = ca.x;
    float gap_right  = 1.0 - (ca.x + ca.z);
    float gap_bottom = ca.y;
    float gap_top    = 1.0 - (ca.y + ca.w);
    float max_gap    = max(max(gap_left, gap_right), max(gap_bottom, gap_top));

    float pos;
    if (max_gap == gap_top) {
        // Tab bar at top — sweep from top-of-content downward
        pos = (ca.y + ca.w - uv.y) / ca.w;
    } else if (max_gap == gap_bottom) {
        // Tab bar at bottom — sweep from bottom-of-content upward
        pos = (uv.y - ca.y) / ca.w;
    } else if (max_gap == gap_left) {
        // Tab bar at left — sweep from left-of-content rightward
        pos = (uv.x - ca.x) / ca.z;
    } else {
        // Tab bar at right — sweep from right-of-content leftward
        pos = (ca.x + ca.z - uv.x) / ca.z;
    }
    return clamp(pos, 0.0, 1.0);
}

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    float4 ca = d.central_area;
    if (ca.z <= 0.0 || ca.w <= 0.0) return color;

    float p = animation_progress;
    float brightness;

    if (ANIMATION_TYPE == 0) {
        // FADE: uniform ramp over the whole frame
        brightness = p;
    } else if (ANIMATION_TYPE == 1) {
        // WIPE: single swept edge with soft falloff
        float pixel_pos = wipe_pixel_pos(t.pos, ca);
        // 1.0 where revealed (pixel_pos < p), 0.0 where not yet reached
        brightness = 1.0 - smoothstep(p - EDGE_SOFTNESS, p + EDGE_SOFTNESS, pixel_pos);
    } else if (ANIMATION_TYPE == 2) {
        // BLINDS: strips opening in sequence from the tab-bar side
        float pixel_pos = wipe_pixel_pos(t.pos, ca);
        float inv_n     = 1.0 / float(NUM_BLINDS);
        float strip_idx = floor(pixel_pos * float(NUM_BLINDS));
        float strip_start = strip_idx * inv_n;
        // Progress local to this strip: 0 when it starts opening, 1 when fully open
        float strip_p   = clamp((p - strip_start) / inv_n, 0.0, 1.0);
        // Position within the strip (0 at tab-bar side, 1 at far side)
        float local     = fract(pixel_pos * float(NUM_BLINDS));
        float soft      = 0.1;
        brightness = 1.0 - smoothstep(strip_p - soft, strip_p + soft, local);
    } else {
        // IRIS: circular reveal expanding from the centre of the content area
        float2 ca_center = ca.xy + ca.zw * 0.5;
        float half_diag  = length(ca.zw * 0.5);
        float dist       = length(t.pos - ca_center) / max(half_diag, 0.001);
        brightness = 1.0 - smoothstep(p - EDGE_SOFTNESS, p + EDGE_SOFTNESS, dist);
    }

    return float4(color.rgb * brightness, color.a);
}
