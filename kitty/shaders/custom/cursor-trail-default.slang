#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// The default custom cursor trail. Set custom_shaders cursor-trail-default
// to use this shader instead of kitty's built-in cursor trail renderer.
//
// The options below are compile-time shader options. They can be changed
// here, or overridden from cursor-trail-default.pipeline with `var` lines.
// For example:
//     var bool MOTION_BLUR true
//     var int MOTION_BLUR_SAMPLES 64
//
// MOTION_BLUR integrates the moving trail over time. ANTIALIASING integrates
// coverage over a regular subpixel grid. Both are enabled by default here;
// set either to false to disable that part of the effect. The sample counts
// are capped at 256 to keep accidental settings from producing an unusable
// shader. CONNECTED makes the blur terminate at the target cursor; when false
// it preserves kitty's original disconnected, lagging-cursor appearance.

import kitty_custom_shader_types;

// Integrate the trail between the previous and current animated positions.
static const bool MOTION_BLUR = true;
// Estimate pixel coverage using a regular grid of subpixel samples.
static const bool ANTIALIASING = true;
// Number of positions integrated per frame. Valid range is 1..256.
static const int MOTION_BLUR_SAMPLES = 64;
// Number of subpixel samples per frame. Valid range is 1..256.
static const int ANTIALIASING_SAMPLES = 16;
// If true, integrate to the target cursor rectangle; otherwise preserve the
// original disconnected, lagging-cursor shape.
static const bool CONNECTED = false;
// Opacity floor for the motion-blurred trail, in the range 0..1.
static const float MIN_OPACITY = 0.2;
// Fractions of the distance from the target over which the trail becomes
// white. The blend uses a smooth radial S-curve and reaches white at the end.
static const float TARGET_BLEND_START = 0.1;
static const float TARGET_BLEND_END = 0.02;

// Corner order: top-right, bottom-right, bottom-left, top-left.
static bool
inside_triangle(float2 p, float2 a, float2 b, float2 c) {
    float ab = (b.x - a.x) * (p.y - a.y) - (b.y - a.y) * (p.x - a.x);
    float bc = (c.x - b.x) * (p.y - b.y) - (c.y - b.y) * (p.x - b.x);
    float ca = (a.x - c.x) * (p.y - c.y) - (a.y - c.y) * (p.x - c.x);
    return ab <= 0.0 && bc <= 0.0 && ca <= 0.0;
}

static float
trail_coverage(float2 p, float4 xs, float4 ys) {
    float2 c0 = float2(xs.x, ys.x);
    float2 c1 = float2(xs.y, ys.y);
    float2 c2 = float2(xs.z, ys.z);
    float2 c3 = float2(xs.w, ys.w);
    // Match the GL_TRIANGLE_FAN used by kitty's original trail exactly.
    return (inside_triangle(p, c0, c1, c2) || inside_triangle(p, c0, c2, c3)) ? 1.0 : 0.0;
}

static bool
inside_rect(float2 p, float4 edge) {
    return p.x >= edge.x && p.x <= edge.y && p.y >= edge.w && p.y <= edge.z;
}

static float
distance_to_rect_pixels(float2 p, float4 edge, float2 pixel_dims) {
    float2 lo = float2(edge.x, edge.w) * pixel_dims;
    float2 hi = float2(edge.y, edge.z) * pixel_dims;
    float2 px = p * pixel_dims;
    float2 delta = max(max(lo - px, px - hi), float2(0.0));
    return length(delta);
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    if (d.cursor_trail_color.a <= 0.0 || d.cursor_trail_state <= 0.0) return color;

    float2 pixel_dims = float2(d.viewport_size_pixels) * t.viewport.zw;
    pixel_dims = max(pixel_dims, float2(1.0));
    float2 pixel_size = 1.0 / pixel_dims;

    const int temporal_samples = MOTION_BLUR ? min(max(MOTION_BLUR_SAMPLES, 1), 256) : 1;
    const int spatial_samples = ANTIALIASING ? min(max(ANTIALIASING_SAMPLES, 1), 256) : 1;
    const int grid_size = ANTIALIASING ? int(ceil(sqrt(float(spatial_samples)))) : 1;

    float4 end_x = d.cursor_trail_corners_x;
    float4 end_y = d.cursor_trail_corners_y;
    if (MOTION_BLUR && CONNECTED) {
        // Connected mode ends at the target cursor rectangle.
        end_x = float4(d.cursor_trail_edge.y, d.cursor_trail_edge.y, d.cursor_trail_edge.x, d.cursor_trail_edge.x);
        end_y = float4(d.cursor_trail_edge.z, d.cursor_trail_edge.w, d.cursor_trail_edge.w, d.cursor_trail_edge.z);
    }

    float4 start_x = MOTION_BLUR ? d.cursor_trail_prev_corners_x : end_x;
    float4 start_y = MOTION_BLUR ? d.cursor_trail_prev_corners_y : end_y;

    // Custom end shaders run over the whole viewport. Reject pixels outside
    // the swept trail before entering the expensive temporal/spatial loops.
    float2 swept_min = float2(1.0, 1.0);
    float2 swept_max = float2(0.0, 0.0);
    for (int i = 0; i < 4; i++) {
        float2 start = float2(start_x[i], start_y[i]);
        float2 end = float2(end_x[i], end_y[i]);
        swept_min = min(swept_min, min(start, end));
        swept_max = max(swept_max, max(start, end));
    }
    swept_min -= pixel_size * 0.5;
    swept_max += pixel_size * 0.5;
    if (t.pos.x < swept_min.x || t.pos.x > swept_max.x || t.pos.y < swept_min.y || t.pos.y > swept_max.y) return color;

    float2 start_center = float2((start_x.x + start_x.y + start_x.z + start_x.w) * 0.25, (start_y.x + start_y.y + start_y.z + start_y.w) * 0.25);
    float2 end_center = float2((end_x.x + end_x.y + end_x.z + end_x.w) * 0.25, (end_y.x + end_y.y + end_y.z + end_y.w) * 0.25);
    float motion_distance = length((end_center - start_center) * pixel_dims);

    float blend_start = max(clamp(TARGET_BLEND_START, 0.0, 1.0), clamp(TARGET_BLEND_END, 0.0, 1.0));
    float blend_end = min(clamp(TARGET_BLEND_START, 0.0, 1.0), clamp(TARGET_BLEND_END, 0.0, 1.0));
    float start_radius = motion_distance * blend_start;
    float end_radius = motion_distance * blend_end;
    float target_blend = 0.0;
    if (MOTION_BLUR && start_radius > end_radius && motion_distance > 0.0) {
        float distance = distance_to_rect_pixels(t.pos, d.cursor_trail_edge, pixel_dims);
        // Apply the radial blend before coverage so antialiased edges never
        // become opaque merely because they are close to the target.
        target_blend = 1.0 - smoothstep(end_radius, start_radius, distance);
    }

    float coverage_sum = 0.0;
    for (int ti = 0; ti < temporal_samples; ti++) {
        float time = MOTION_BLUR ? (float(ti) + 0.5) / float(temporal_samples) : 1.0;
        float4 xs = lerp(start_x, end_x, time);
        float4 ys = lerp(start_y, end_y, time);
        float2 sample_min = float2(1.0, 1.0);
        float2 sample_max = float2(0.0, 0.0);
        for (int ci = 0; ci < 4; ci++) {
            float2 corner = float2(xs[ci], ys[ci]);
            sample_min = min(sample_min, corner);
            sample_max = max(sample_max, corner);
        }
        sample_min -= pixel_size * 0.5;
        sample_max += pixel_size * 0.5;
        if (t.pos.x < sample_min.x || t.pos.x > sample_max.x || t.pos.y < sample_min.y || t.pos.y > sample_max.y) continue;

        float sample_coverage = 0.0;
        for (int si = 0; si < spatial_samples; si++) {
            float2 sample_pos = t.pos;
            if (ANTIALIASING) {
                int sx = si % grid_size;
                int sy = si / grid_size;
                sample_pos += (float2(float(sx) + 0.5, float(sy) + 0.5) / float(grid_size) - 0.5) * pixel_size;
            }
            // Preserve the terminal-rendered cursor, including hollow and
            // blinking cursor states. The trail never paints its rectangle.
            if (d.cursor_color.a > 0.0 && inside_rect(sample_pos, d.cursor_trail_edge)) continue;
            sample_coverage += trail_coverage(sample_pos, xs, ys);
        }
        coverage_sum += sample_coverage / float(spatial_samples);
    }
    float coverage = coverage_sum / float(temporal_samples);
    if (coverage <= 0.0) return color;

    float opacity = d.cursor_trail_color.a;
    if (MOTION_BLUR) {
        float min_opacity = clamp(MIN_OPACITY, 0.0, 1.0);
        opacity = min_opacity + (1.0 - min_opacity) * max(opacity, d.cursor_color.a);
        opacity = lerp(opacity, 1.0, target_blend);
    }
    opacity = clamp(opacity * coverage, 0.0, 1.0);
    return float4(lerp(color.rgb, d.cursor_trail_color.rgb, opacity), color.a);
}
