#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// A smoother cursor trail, using motion blur.
//
// When the cursor jumps to a new place, kitty draws a trail that stretches
// from where the cursor was towards where it is now, and then quickly shrinks
// into the cursor. The screen is redrawn many times a second and each redraw
// shows the trail in a new position. When the cursor moves fast, those
// positions are far apart, so the trail can look like it is hopping from place
// to place instead of gliding.
//
// This shader smooths that out the same way a camera does. A photo of
// something moving fast comes out streaked, because the object kept moving
// while the shutter was open. Similarly, every time the screen is redrawn,
// this shader draws the trail at many in-between positions, from where it was
// in the previous redraw to where it is now, and blends them together. The
// result is a soft streak that looks like continuous motion. It also smooths
// the slanted edges of the trail, so they look clean rather than jagged
// (antialiasing).
//
// To use it, add the following to kitty.conf:
//     cursor_trail 1
//     custom_shaders cursor-trail-motion-blur
//
// You can tune the options below without editing this file. Save a pipeline
// file such as shaders/my-trail.pipeline in your kitty config directory,
// containing, for example:
//     startgroup
//         animation_start cursor-trail-move
//         animation_stop cursor-trail-stop
//         var bool CONNECTED true
//         var int MOTION_BLUR_SAMPLES 32
//         shaders cursor-trail-motion-blur
//     endgroup
// and then use custom_shaders my-trail in kitty.conf.

import kitty_custom_shader_types;

// Turn motion blur on or off. When off, only antialiasing is applied.
static const bool MOTION_BLUR = true;
// Number of in-between positions blended per redraw. More is smoother but
// slower. Values are limited to the range 1..64.
static const int MOTION_BLUR_SAMPLES = 16;
// Smooth the edges of the trail.
static const bool ANTIALIASING = true;
// When true, the blur reaches all the way into the cursor, so the trail looks
// like one continuous streak. When false, the trail keeps kitty's usual look,
// where its tail lags slightly behind the cursor.
static const bool CONNECTED = false;

// All positions below are in pixels.

// How much of the pixel centered at p lies outside the edge a→b, from 0 (none
// of it) to 1 (all of it). orientation is +1 for triangles whose corners are
// in counter-clockwise order and -1 for clockwise.
static float
outside_edge(float2 p, float2 a, float2 b, float orientation) {
    float2 e = b - a;
    // Signed distance from the edge, positive on the inner side
    float dist = orientation * (e.x * (p.y - a.y) - e.y * (p.x - a.x)) / length(e);
    if (!ANTIALIASING) return dist < 0.0 ? 1.0 : 0.0;
    return 1.0 - saturate(0.5 + dist);
}

// The fraction of the pixel centered at p that is covered by the triangle abc.
// Subtracting the part of the pixel outside each edge is exact for straight
// edges and also stays correct for slivers thinner than a pixel.
static float
triangle_coverage(float2 p, float2 a, float2 b, float2 c) {
    float area = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
    // A triangle that has collapsed to a line or point covers nothing
    if (abs(area) < 1e-6) return 0.0;
    float orientation = area > 0.0 ? 1.0 : -1.0;
    return saturate(1.0 - outside_edge(p, a, b, orientation) - outside_edge(p, b, c, orientation) - outside_edge(p, c, a, orientation));
}

// The fraction of the pixel centered at p covered by the trail. Corner order
// is top-right, bottom-right, bottom-left, top-left. The quad is split into
// the same two triangles as kitty's built-in trail renderer.
static float
trail_coverage(float2 p, float4 xs, float4 ys) {
    float2 c0 = float2(xs.x, ys.x);
    float2 c1 = float2(xs.y, ys.y);
    float2 c2 = float2(xs.z, ys.z);
    float2 c3 = float2(xs.w, ys.w);
    return min(triangle_coverage(p, c0, c1, c2) + triangle_coverage(p, c0, c2, c3), 1.0);
}

// The fraction of the pixel centered at p covered by the axis aligned
// rectangle from lo to hi.
static float
rect_coverage(float2 p, float2 lo, float2 hi) {
    if (!ANTIALIASING) return (p.x >= lo.x && p.x <= hi.x && p.y >= lo.y && p.y <= hi.y) ? 1.0 : 0.0;
    float2 overlap = saturate(min(p + 0.5, hi) - max(p - 0.5, lo));
    return overlap.x * overlap.y;
}

static float
min4(float4 v) {
    return min(min(v.x, v.y), min(v.z, v.w));
}

static float
max4(float4 v) {
    return max(max(v.x, v.y), max(v.z, v.w));
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float opacity = d.cursor_trail_color.a;
    if (opacity <= 0.0 || d.cursor_trail_state <= 0.0) return color;

    float2 pixel_dims = max(float2(d.viewport_size_pixels) * t.viewport.zw, float2(1.0));
    float2 p = t.pos * pixel_dims;
    // cursor_trail_edge: .x=left, .y=right, .z=top, .w=bottom
    float2 cursor_lo = float2(d.cursor_trail_edge.x, d.cursor_trail_edge.w) * pixel_dims;
    float2 cursor_hi = float2(d.cursor_trail_edge.y, d.cursor_trail_edge.z) * pixel_dims;

    float4 end_x = d.cursor_trail_corners_x * pixel_dims.x;
    float4 end_y = d.cursor_trail_corners_y * pixel_dims.y;
    if (MOTION_BLUR && CONNECTED) {
        end_x = float4(cursor_hi.x, cursor_hi.x, cursor_lo.x, cursor_lo.x);
        end_y = float4(cursor_hi.y, cursor_lo.y, cursor_lo.y, cursor_hi.y);
    }
    float4 start_x = MOTION_BLUR ? d.cursor_trail_prev_corners_x * pixel_dims.x : end_x;
    float4 start_y = MOTION_BLUR ? d.cursor_trail_prev_corners_y * pixel_dims.y : end_y;

    // This runs for every pixel on screen, so skip pixels that are outside
    // the area swept by the trail in this redraw.
    float2 swept_lo = float2(min(min4(start_x), min4(end_x)), min(min4(start_y), min4(end_y))) - 1.0;
    float2 swept_hi = float2(max(max4(start_x), max4(end_x)), max(max4(start_y), max4(end_y))) + 1.0;
    if (p.x < swept_lo.x || p.x > swept_hi.x || p.y < swept_lo.y || p.y > swept_hi.y) return color;

    const int samples = MOTION_BLUR ? clamp(MOTION_BLUR_SAMPLES, 1, 64) : 1;
    float coverage = 0.0;
    for (int i = 0; i < samples; i++) {
        float time = MOTION_BLUR ? (float(i) + 0.5) / float(samples) : 1.0;
        coverage += trail_coverage(p, lerp(start_x, end_x, time), lerp(start_y, end_y, time));
    }
    coverage /= float(samples);
    // Never paint over the cursor itself, so that it renders cleanly on top.
    coverage *= 1.0 - rect_coverage(p, cursor_lo, cursor_hi);
    if (coverage <= 0.0) return color;

    return float4(lerp(color.rgb, d.cursor_trail_color.rgb, saturate(opacity * coverage)), color.a);
}
