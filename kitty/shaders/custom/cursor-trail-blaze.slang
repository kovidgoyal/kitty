#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Blaze cursor trail — port of https://gist.github.com/chardskarth/95874c54e29da6b5a36ab7b50ae2d088
// by chardskarth. Draws a fading parallelogram trail from the previous cursor
// position to the current one, coloured with an amber fill and red-orange border.
// Ported to slang for kitty

import kitty_custom_shader_types;

extern static const float4 TRAIL_COLOR        = float4(1.0, 0.725, 0.161, 1.0);
extern static const float4 TRAIL_COLOR_ACCENT = float4(1.0, 0.0,   0.0,   1.0);
// Trail lifetime in seconds.
extern static const float  DURATION           = 0.5;

// pow(1 - x, 10) via repeated squaring — branchless ease-out.
static float ease_out10(float x) {
    float y  = 1.0 - x;
    float y2 = y * y;
    float y4 = y2 * y2;
    return y4 * y4 * y2;
}

// Smooth blend curve for the progress value.
static float blend_smooth(float t) {
    float s = t * t;
    return s / (2.0 * (s - t) + 1.0);
}

// SDF of an axis-aligned box.  p = query point, center = box centre, hext = half-extents.
static float sdBox(float2 p, float2 center, float2 hext) {
    float2 d = abs(p - center) - hext;
    return length(max(d, float2(0.0))) + min(max(d.x, d.y), 0.0);
}

// Single edge contribution for the quadrilateral SDF (signed winding accumulation).
static float seg(float2 p, float2 a, float2 b, inout float s, float d) {
    float2 e    = b - a;
    float2 w    = p - a;
    float2 proj = a + e * clamp(dot(w, e) / dot(e, e), 0.0, 1.0);
    d = min(d, dot(p - proj, p - proj));

    float c0 = step(0.0, p.y - a.y);
    float c1 = 1.0 - step(0.0, p.y - b.y);
    float c2 = 1.0 - step(0.0, e.x * w.y - e.y * w.x);
    float allCond  = c0 * c1 * c2;
    float noneCond = (1.0 - c0) * (1.0 - c1) * (1.0 - c2);
    s *= lerp(1.0, -1.0, step(0.5, allCond + noneCond));
    return d;
}

// SDF of an arbitrary quadrilateral (uses winding number via four edge contributions).
static float sdQuad(float2 p, float2 v0, float2 v1, float2 v2, float2 v3) {
    float s = 1.0;
    float d = dot(p - v0, p - v0);
    d = seg(p, v0, v3, s, d);
    d = seg(p, v1, v0, s, d);
    d = seg(p, v2, v1, s, d);
    d = seg(p, v3, v2, s, d);
    return s * sqrt(d);
}

// Returns 0 for diagonal movement (up-left / down-right), 1 otherwise.
// Selects which corner of the parallelogram aligns with the movement direction.
static float movementVertexFactor(float2 a, float2 b) {
    float c1 = step(b.x, a.x) * step(a.y, b.y);
    float c2 = step(a.x, b.x) * step(b.y, a.y);
    return 1.0 - max(c1, c2);
}

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    if (d.cursor_trail_color.a <= 0.0) return color;

    float age = clamp((d.timestamp - d.cursor_trail_change_time) / DURATION, 0.0, 1.0);
    if (age >= 1.0) return color;

    float easedProgress = ease_out10(blend_smooth(age));
    if (easedProgress <= 0.0) return color;

    // Work in pixel space for correct aspect-ratio distance measurements.
    float2 pixelDims = float2(d.viewport_size_pixels) * viewport.zw;
    float2 px        = t.pos * pixelDims;

    // Current cursor rect in pixel space (edge: .x=left .y=right .z=top .w=bottom, y-up).
    float curLeft   = d.cursor_trail_edge.x * pixelDims.x;
    float curRight  = d.cursor_trail_edge.y * pixelDims.x;
    float curTop    = d.cursor_trail_edge.z * pixelDims.y;
    float curBottom = d.cursor_trail_edge.w * pixelDims.y;
    float curWidth  = curRight - curLeft;
    float curHeight = curTop   - curBottom;
    float2 curCenter = float2((curLeft + curRight) * 0.5, (curTop + curBottom) * 0.5);

    float prevLeft   = d.cursor_trail_prev_edge.x * pixelDims.x;
    float prevTop    = d.cursor_trail_prev_edge.z * pixelDims.y;
    float prevBottom = d.cursor_trail_prev_edge.w * pixelDims.y;
    float2 prevCenter = float2(
        (d.cursor_trail_prev_edge.x + d.cursor_trail_prev_edge.y) * 0.5 * pixelDims.x,
        (d.cursor_trail_prev_edge.z + d.cursor_trail_prev_edge.w) * 0.5 * pixelDims.y
    );

    float lineLength = length(curCenter - prevCenter);
    // Alpha fades to 0 at the previous-cursor end, reaching full effect at the current cursor.
    float alphaModifier = min(length(px - curCenter) / (lineLength * easedProgress), 1.0);

    // Build parallelogram vertices in pixel space.
    float vf  = movementVertexFactor(curCenter, prevCenter);
    float ivf = 1.0 - vf;
    float2 v0 = float2(lerp(curLeft, curRight, vf),  curBottom);
    float2 v1 = float2(lerp(curLeft, curRight, ivf), curTop);
    float2 v2 = float2(prevLeft + curWidth * ivf,    prevTop);
    float2 v3 = float2(prevLeft + curWidth * vf,     prevBottom);

    float sdfCursor = sdBox(px, curCenter, float2(curWidth, curHeight) * 0.5);
    float sdfTrail  = sdQuad(px, v0, v1, v2, v3);

    // ~2-pixel anti-aliasing range in pixel space.
    float aaRange = 2.0;
    float4 newColor = color;
    // Inner border accent (red-orange inside the trail edges).
    newColor = lerp(newColor, TRAIL_COLOR_ACCENT, 1.0 - smoothstep(sdfTrail, -aaRange, aaRange * 0.05));
    // Main amber fill.
    newColor = lerp(newColor, TRAIL_COLOR, 1.0 - smoothstep(0.0, aaRange, sdfTrail));
    // Fade: effect is weakest toward the previous cursor end.
    newColor = lerp(color, newColor, 1.0 - alphaModifier);
    // Restore original pixels inside the cursor rectangle.
    return lerp(newColor, color, step(sdfCursor, 0.0));
}
