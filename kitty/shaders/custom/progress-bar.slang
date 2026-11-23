#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Progress bar effect
// Draws the progress bars that programs report with OSC 9;4 as glowing bars
// along the top edge of every visible window, replacing kitty's builtin
// progress bars. Changes in progress animate smoothly, a bar for progress of
// unknown length sweeps back and forth and a finished bar fades away.
// Uses KittyTextures.windows to find the windows and their progress.

import kitty_custom_shader_types;

// Thickness of the bar in pixels
static const float BAR_HEIGHT_PIXELS = 3.0;
// Height in pixels of the glow below the bar, zero to disable it
static const float GLOW_PIXELS = 8.0;
// Strength of the glow below the bar
static const float GLOW_INTENSITY = 0.5;
// Opacity of the track behind the unfilled part of the bar
static const float TRACK_OPACITY = 0.15;
// Seconds over which a change in progress is animated
static const float CHANGE_SECONDS = 0.3;
// Seconds over which the bar fades out once the progress is cleared
static const float FADE_OUT_SECONDS = 0.6;
// Width of the sweeping part of a bar for progress of unknown length, as a fraction of the window width
static const float INDETERMINATE_WIDTH = 0.2;
// Seconds for the sweeping part to go from one side of the window to the other and back
static const float INDETERMINATE_PERIOD = 2.0;
// Draw the bar along the edge of the area including the window padding, title
// bar, etc. rather than along the edge of the window contents
static const bool INCLUDE_WINDOW_PADDING = true;
// Bar colors for the various states, in linear RGB
static const float3 COLOR = float3(0.05, 0.45, 1.0);
static const float3 PAUSED_COLOR = float3(1.0, 0.55, 0.0);
static const float3 ERROR_COLOR = float3(1.0, 0.05, 0.05);
// Brightness of a highlight that moves along a filled bar, zero to disable it.
// kitty renders frames only while progress is changing, so when enabling this
// also set animation_step in the pipeline, at the cost of continuous redraws.
static const float SHIMMER = 0.0;

// Coverage of the interval [lo, hi] at x, anti-aliased over aa
float
span(float x, float lo, float hi, float aa) {
    return saturate((x - lo) / aa + 0.5) * saturate((hi - x) / aa + 0.5);
}

public float4
fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d) {
    int idx = t.windows.window_at(t.pos, INCLUDE_WINDOW_PADDING);
    if (idx < 0) return color;
    KittyWindow w = t.windows.get(uint(idx));
    float opacity = 1.0;
    float fill = w.progress;
    uint state = w.progress_state;
    if (state == KITTY_PROGRESS_UNSET) {
        // Fade out the bar as it was before it was cleared
        if (w.progress_age < 0.0 || w.progress_age >= FADE_OUT_SECONDS || w.previous_progress_state == KITTY_PROGRESS_UNSET) return color;
        opacity = 1.0 - w.progress_age / FADE_OUT_SECONDS;
        fill = w.previous_progress;
        state = w.previous_progress_state;
    } else if (w.progress_age >= 0.0 && w.progress_age < CHANGE_SECONDS) {
        fill = lerp(w.previous_progress, w.progress, smoothstep(0.0, CHANGE_SECONDS, w.progress_age));
    }

    float2 px = 1.0 / float2(max(d.viewport_size_pixels, uint2(1u)));
    float4 g = w.geometry;
    if (INCLUDE_WINDOW_PADDING) {
        g.xy -= w.padding.xy;
        g.zw += w.padding.xy + w.padding.zw;
    }
    float top = g.y + g.w;
    float bar_bottom = top - BAR_HEIGHT_PIXELS * px.y;
    float glow_bottom = bar_bottom - GLOW_PIXELS * px.y;
    if (t.pos.y < glow_bottom) return color;
    // Position along the bar in [0, 1]
    float x = (t.pos.x - g.x) / max(g.z, 1e-6);
    float aa = px.x / max(g.z, 1e-6);

    float3 bar_color = COLOR;
    float coverage; // how much of this pixel the filled part of the bar covers
    float shimmer = 0.0;
    if (state == KITTY_PROGRESS_INDETERMINATE) {
        float phase = fract(d.wrapped_time(3600u) / INDETERMINATE_PERIOD);
        float tri = phase < 0.5 ? phase * 2.0 : 2.0 - phase * 2.0;
        float start = smoothstep(0.0, 1.0, tri) * (1.0 - INDETERMINATE_WIDTH);
        coverage = span(x, start, start + INDETERMINATE_WIDTH, aa);
    } else {
        if (state == KITTY_PROGRESS_ERROR) {
            bar_color = ERROR_COLOR;
            fill = 1.0;
        } else if (state == KITTY_PROGRESS_PAUSED) {
            bar_color = PAUSED_COLOR;
        } else if (SHIMMER > 0.0 && fill > 0.0) {
            // A highlight travelling along the filled part of the bar
            float head = fract(d.wrapped_time(60u) * 0.5) * 1.6 - 0.3;
            shimmer = SHIMMER * exp(-pow((x / max(fill, 1e-3) - head) * 6.0, 2.0));
        }
        coverage = span(x, 0.0, fill, aa);
    }
    bar_color = saturate(bar_color * (1.0 + shimmer) + shimmer * 0.5);

    float3 rgb = color.rgb;
    if (t.pos.y >= bar_bottom) {
        // The bar itself, over a faint track
        rgb = lerp(rgb, bar_color, TRACK_OPACITY * opacity);
        rgb = lerp(rgb, bar_color, coverage * opacity);
    } else if (GLOW_PIXELS > 0.0) {
        // The glow below the filled part, fading with distance from the bar
        float fall = (t.pos.y - glow_bottom) / (bar_bottom - glow_bottom);
        rgb += bar_color * GLOW_INTENSITY * coverage * opacity * fall * fall;
    }
    return float4(rgb, color.a);
}
