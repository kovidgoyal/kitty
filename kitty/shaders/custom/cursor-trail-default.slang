#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Custom cursor trail shader — replicates the built-in trail using the
// cursor_trail_* uniforms. Use as a starting point for custom effects.
//
// Suggested pipeline config:
//   startgroup
//       animation_start cursor-trail-move
//       animation_stop  cursor-trail-stop
//       shaders cursor-trail
//   endgroup
//
// Note: animation_progress is not tied to the trail duration (which is
// an exponential decay of variable length). Use cursor_trail_color.a
// for opacity and the corner positions for geometry instead.

import kitty_custom_shader_types;

// Returns true when uv is inside the convex quad c0→c1→c2→c3 (clockwise, y-up).
// Corner order from cursor_trail_corners_*: 0=top-right, 1=bottom-right, 2=bottom-left, 3=top-left.
bool inside_trail_quad(float2 uv, float2 c0, float2 c1, float2 c2, float2 c3) {
    float2 e0 = c1 - c0; float2 e1 = c2 - c1; float2 e2 = c3 - c2; float2 e3 = c0 - c3;
    float s0 = e0.x * (uv.y - c0.y) - e0.y * (uv.x - c0.x);
    float s1 = e1.x * (uv.y - c1.y) - e1.y * (uv.x - c1.x);
    float s2 = e2.x * (uv.y - c2.y) - e2.y * (uv.x - c2.x);
    float s3 = e3.x * (uv.y - c3.y) - e3.y * (uv.x - c3.x);
    return s0 <= 0.0 && s1 <= 0.0 && s2 <= 0.0 && s3 <= 0.0;
}

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    float opacity = d.cursor_trail_color.a;
    if (opacity <= 0.0) return color;

    float2 uv = t.pos;

    float2 c0 = float2(d.cursor_trail_corners_x.x, d.cursor_trail_corners_y.x);  // top-right
    float2 c1 = float2(d.cursor_trail_corners_x.y, d.cursor_trail_corners_y.y);  // bottom-right
    float2 c2 = float2(d.cursor_trail_corners_x.z, d.cursor_trail_corners_y.z);  // bottom-left
    float2 c3 = float2(d.cursor_trail_corners_x.w, d.cursor_trail_corners_y.w);  // top-left

    if (!inside_trail_quad(uv, c0, c1, c2, c3)) return color;

    // Mask out the cursor's current rectangle so the real cursor renders cleanly on top.
    // cursor_trail_edge: .x=left, .y=right, .z=top, .w=bottom (UV, y-up)
    float inside_cursor = step(d.cursor_trail_edge.x, uv.x) * step(uv.x, d.cursor_trail_edge.y)
                        * step(d.cursor_trail_edge.w, uv.y) * step(uv.y, d.cursor_trail_edge.z);
    opacity *= 1.0 - inside_cursor;
    if (opacity <= 0.0) return color;

    return float4(lerp(color.rgb, d.cursor_trail_color.rgb, opacity), color.a);
}
