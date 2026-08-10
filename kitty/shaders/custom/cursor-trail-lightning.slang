#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Lightning cursor trail — port of cursor_lightning.glsl to slang for kitty
// Draws a brief jagged bolt from the previous cursor position to the current one.

import kitty_custom_shader_types;

static const float3 BOLT_COLOR = float3(1.00, 0.82, 0.72);
static const float3 GLOW_COLOR = float3(0.74, 0.00, 0.00);
// Bolt lifetime in seconds.
static const float DURATION = 0.14;
// Sideways displacement relative to bolt length.
static const float JAGGEDNESS = 0.085;
// Core stroke width in pixels.
static const float CORE_WIDTH = 1.15;
// Glow radius in pixels.
static const float GLOW_WIDTH = 5.5;
// Number of linear segments that make up the main bolt.
static const int BOLT_SEGMENTS = 12;

static float
hash11(float p) {
    p = frac(p * 0.1031);
    p *= p + 33.33;
    p *= p + p;
    return frac(p);
}

static float
segDist(float2 p, float2 a, float2 b) {
    float2 ab = b - a;
    float t = clamp(dot(p - a, ab) / max(dot(ab, ab), 1e-7), 0.0, 1.0);
    return length(p - (a + ab * t));
}

// A point on the piecewise-linear bolt.  Endpoints stay fixed; interior nodes
// are displaced perpendicular to the travel direction.
static float2
boltPoint(float2 a, float2 b, float t, float seed) {
    float2 delta = b - a;
    float boltLength = length(delta);
    float2 perp = float2(-delta.y, delta.x) / max(boltLength, 1e-5);
    float node = floor(t * float(BOLT_SEGMENTS) + 0.5);
    float rnd = hash11(node * 17.17 + seed) * 2.0 - 1.0;
    float fade = sin(3.14159265 * t);
    return lerp(a, b, t) + perp * rnd * boltLength * JAGGEDNESS * fade;
}

// Minimum distance from p to the main bolt's piecewise-linear path.
static float
mainBoltDist(float2 p, float2 a, float2 b, float seed) {
    float minD = 1e5;
    float2 prev = a;
    [ForceUnroll]
    for (int i = 1; i <= BOLT_SEGMENTS; i++) {
        float t = float(i) / float(BOLT_SEGMENTS);
        float2 cur = boltPoint(a, b, t, seed);
        minD = min(minD, segDist(p, prev, cur));
        prev = cur;
    }
    return minD;
}

// Three small forks growing out of alternating points on the main bolt.
static float
forkDist(float2 p, float2 a, float2 b, float seed) {
    float minD = 1e5;
    float2 delta = b - a;
    float boltLength = length(delta);
    float2 perp = float2(-delta.y, delta.x) / max(boltLength, 1e-5);
    float2 dir = normalize(delta);

    [ForceUnroll]
    for (int i = 0; i < 3; i++) {
        float fi = float(i);
        float t = 0.28 + fi * 0.22;
        float2 root = boltPoint(a, b, t, seed);
        float side = lerp(-1.0, 1.0, step(0.5, hash11(seed + fi * 41.0)));
        float reach = boltLength * (0.055 + 0.035 * hash11(seed + fi * 53.0));
        float2 along = dir * reach * (hash11(seed + fi * 67.0) - 0.35);
        float2 tip = root + perp * side * reach + along;
        float2 elbow = lerp(root, tip, 0.52) - perp * side * reach * (0.12 + 0.18 * hash11(seed + fi * 79.0));
        minD = min(minD, segDist(p, root, elbow));
        minD = min(minD, segDist(p, elbow, tip));
    }
    return minD;
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float age = clamp((d.timestamp - d.cursor_trail_change_time) / DURATION, 0.0, 1.0);
    if (age >= 1.0) return color;

    float2 pixelDims = float2(d.viewport_size_pixels) * t.viewport.zw;

    // Cursor centres in pixel space (edge: .x=left .y=right .z=top .w=bottom, y-up).
    float2 curCenter = float2((d.cursor_trail_edge.x + d.cursor_trail_edge.y) * 0.5, (d.cursor_trail_edge.z + d.cursor_trail_edge.w) * 0.5) * pixelDims;
    float2 prevCenter =
        float2((d.cursor_trail_prev_edge.x + d.cursor_trail_prev_edge.y) * 0.5, (d.cursor_trail_prev_edge.z + d.cursor_trail_prev_edge.w) * 0.5) * pixelDims;

    float cursorWidth = (d.cursor_trail_edge.y - d.cursor_trail_edge.x) * pixelDims.x;

    float2 px = t.pos * pixelDims;

    // Quantise the event time for a stable bolt shape across the bolt's lifetime.
    float seed = floor(d.cursor_trail_change_time * 1000.0) * 0.013;

    float mainD = mainBoltDist(px, prevCenter, curCenter, seed);
    float forkD = forkDist(px, prevCenter, curCenter, seed);

    float pixel = max(fwidth(mainD), 0.65);
    float core = 1.0 - smoothstep(CORE_WIDTH, CORE_WIDTH + pixel, mainD);
    float forkCore = 1.0 - smoothstep(CORE_WIDTH * 0.72, CORE_WIDTH * 0.72 + pixel, forkD);
    float glow = exp(-mainD * mainD / (GLOW_WIDTH * GLOW_WIDTH));
    float forkGlow = exp(-forkD * forkD / (GLOW_WIDTH * GLOW_WIDTH * 0.55));

    // Flash hard, then rapidly lose the core, leaving only glow.
    float flash = 1.0 - smoothstep(0.0, 1.0, age);
    flash *= flash;
    float flicker = 0.82 + 0.18 * sin(age * 95.0 + seed);
    float glowAmt = max(glow, forkGlow * 0.55) * flash * flicker * 0.72;
    float coreAmt = max(core, forkCore * 0.82) * flash * flicker;

    float3 rgb = lerp(color.rgb, GLOW_COLOR, clamp(glowAmt, 0.0, 1.0));
    rgb = lerp(rgb, BOLT_COLOR, clamp(coreAmt, 0.0, 1.0));

    // Keep the cursor crisp above the effect.
    float insideCursor = step(d.cursor_trail_edge.x, t.pos.x) * step(t.pos.x, d.cursor_trail_edge.y) * step(d.cursor_trail_edge.w, t.pos.y) *
                         step(t.pos.y, d.cursor_trail_edge.z);
    rgb = lerp(rgb, color.rgb, insideCursor);

    return float4(rgb, color.a);
}
