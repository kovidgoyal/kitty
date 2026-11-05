#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Screen shake effect
// Shakes the window in which a bell (BEL character) occurred, leaving all
// other windows in the tab untouched. Uses d.bell_window_geometry to locate the
// window. If that window is no longer visible, the whole tab area is shaken.
// The shake decays to nothing over the animation, which should use a linear
// animation_curve, as the decay is computed here.
//
// A handy use for this is to shake the window when a shell command fails, by
// having the shell print a BEL character when that happens. Set
// visual_bell_duration to zero in kitty.conf to disable the builtin visual
// bell flash, the shake is triggered regardless.

import kitty_custom_shader_types;

// 0 = HORIZONTAL — a side to side shake, like a head shaking "no"
// 1 = RANDOM     — a jittery shake in random directions, both horizontally and vertically
static const int SHAKE_MODE = 0;
// Maximum displacement of the window contents in pixels, at the start of the shake.
static const float AMPLITUDE_PIXELS = 12.0;
// Number of back and forth movements over the duration of the animation. Keep
// this low enough that each movement lasts at least a few frames, otherwise
// the shake becomes a flicker.
static const float SHAKES = 4.0;
// How quickly the shake dies down, higher values die down faster. 1 is linear.
static const float DECAY_POWER = 2.0;
// What to show in the strip uncovered at the edge of the window as its contents move:
// false = the window background color
// true  = repeat the pixels at the edge of the window
static const bool REPEAT_EDGE = false;
// Shake the whole tab area rather than just the window that belled.
static const bool SHAKE_ENTIRE_TAB = false;

static const float TAU = 6.28318530718;

// Pseudo-random value in [0, 1) for each integer n
float
hash(float n) {
    return fract(sin(n * 12.9898 + 78.233) * 43758.5453);
}

// Smooth noise in [-1, 1]
float
noise(float x) {
    float i = floor(x);
    float f = fract(x);
    float u = f * f * (3.0 - 2.0 * f);
    return lerp(hash(i), hash(i + 1.0), u) * 2.0 - 1.0;
}

// Two octaves of noise in [-1, 1]
float
fractal_noise(float x) {
    return (noise(x) + 0.5 * noise(2.0 * x + 31.7)) / 1.5;
}

// Displacement of the window contents as a fraction of the amplitude, for animation progress p
float2
shake_offset(float p) {
    float strength = pow(1.0 - p, DECAY_POWER);
    if (SHAKE_MODE == 1) {
        // Each noise lattice point is a new random target position, so use
        // two of them per shake
        float x = p * SHAKES * 2.0;
        return strength * float2(fractal_noise(x), fractal_noise(x + 113.0));
    }
    return float2(strength * sin(TAU * SHAKES * p), 0.0);
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    float4 g = SHAKE_ENTIRE_TAB ? d.central_area : d.bell_window_geometry;
    // Nothing to shake before the first bell
    if (g.z <= 0.0 || g.w <= 0.0) return color;
    float2 win_min = g.xy;
    float2 win_max = g.xy + g.zw;
    if (any(t.pos < win_min) || any(t.pos > win_max)) return color;

    float2 px = float2(d.viewport_size_pixels) * t.viewport.zw;
    if (px.x <= 0.0 || px.y <= 0.0) return color;
    float2 offset = shake_offset(t.animation_progress) * AMPLITUDE_PIXELS / px;
    float2 src = t.pos - offset;

    if (REPEAT_EDGE) {
        float2 half_pixel = 0.5 / px;
        return t.backbuffer.Sample(clamp(src, win_min + half_pixel, win_max - half_pixel));
    }
    if (all(src >= win_min) && all(src <= win_max)) return t.backbuffer.Sample(src);
    // The pixel is uncovered, fill it with the window background. The
    // background of the active window is known, for other windows use the
    // global background.
    bool is_active = all(abs(g - d.active_window_geometry) < 0.5 / float4(px, px));
    float3 bg = is_active ? d.active_window_background.rgb : d.background.rgb;
    return float4(bg, color.a);
}
