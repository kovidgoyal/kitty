#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import utils;

// Macro definitions
#define DEFAULT_BG 0
#define ACTIVE_BORDER_COLOR 1
#define INACTIVE_BORDER_COLOR 2
#define WINDOW_BACKGROUND_PLACEHOLDER 3
#define BELL_BORDER_COLOR 4
#define TAB_BAR_BG_COLOR 5
#define TAB_BAR_MARGIN_COLOR 6
#define TAB_BAR_EDGE_LEFT_COLOR 7
#define TAB_BAR_EDGE_RIGHT_COLOR 8

uniform float gamma_lut[256];
uniform uint colors[9];

// Vertex attributes matching GLSL input locations
struct VertexInput {
    float4 rect; // left, top, right, bottom
    uint rect_color;
};

// Vertex shader output structure
struct VertexOutput
{
    float4 color_premul : COLOR_PREMUL;
    float4 position : SV_Position;
};

// Indices into the rect vector
static const int LEFT = 0;
static const int TOP = 1;
static const int RIGHT = 2;
static const int BOTTOM = 3;
static const uint FF = 0xff;

static const uint2 pos_map[4] = {
    uint2(RIGHT, TOP),
    uint2(RIGHT, BOTTOM),
    uint2(LEFT, BOTTOM),
    uint2(LEFT, TOP)
};

float to_color(uint c) {
    return gamma_lut[c & FF];
}

float is_integer_value(uint c, int x) {
    return 1. - step(0.5, abs(float(c) - float(x)));
}

float3 as_color_vector(uint c, int shift) {
    return float3(to_color(c >> shift), to_color(c >> (shift - 8)), to_color(c >> (shift - 16)));
}

[shader("vertex")]
VertexOutput vertex_main(float4 rect, uint rect_color, uniform float background_opacity, uint vertex_id : SV_VertexID)
{
    VertexOutput output;

    uint2 pos = pos_map[vertex_id];
    output.position = float4(rect[pos.x], rect[pos.y], 0, 1);

    float3 window_bg = as_color_vector(rect_color, 24);
    uint rc = rect_color & FF;
    float3 color3 = as_color_vector(colors[rc], 16);

    float is_window_bg = is_integer_value(rc, WINDOW_BACKGROUND_PLACEHOLDER); // used by window padding areas
    float is_default_bg = is_integer_value(rc, DEFAULT_BG);
    color3 = if_one_then(is_window_bg, window_bg, color3);

    // Actual border quads and tab bar edge strips must be always drawn opaque
    float is_not_a_border = zero_or_one(abs(
        (float(rc) - ACTIVE_BORDER_COLOR) * (float(rc) - INACTIVE_BORDER_COLOR) * (float(rc) - BELL_BORDER_COLOR) *
        (float(rc) - TAB_BAR_EDGE_LEFT_COLOR) * (float(rc) - TAB_BAR_EDGE_RIGHT_COLOR)
    ));

    float final_opacity = if_one_then(is_not_a_border, background_opacity, 1.);
    output.color_premul = vec4_premul(color3, final_opacity);

    return output;
}

[shader("fragment")]
float4 fragment_main(float4 color_premul : COLOR_PREMUL) : SV_Target {
    return color_premul;
}
