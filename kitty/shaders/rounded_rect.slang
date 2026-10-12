#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import alpha_blend;

// The four corners of the full viewport quad in NDC, in triangle fan order:
// top-right, bottom-right, bottom-left, top-left.
// Note: deliberately a table of ready made positions rather than a dynamic
// index into a rect vector. slangc inlines a static const vector into the
// generated GLSL as an anonymous vec4() constructor, and on the macOS AMD
// driver (GL_RENDERER 4.1 ATI-5.5.20) dynamically indexing that temporary
// produced 0 for the right and bottom components, collapsing this quad to its
// top left quadrant so only half of each rounded border/scrollbar was drawn.
// Indexing a *named* vector dynamically is fine there, borders.slang does it.
// See https://github.com/kovidgoyal/kitty/issues/10549
static const float2 vertex_pos_map[4] = { float2(1, 1), float2(1, -1), float2(-1, -1), float2(-1, 1) };

[shader("vertex")]
float4
vertex_main(uint vertex_id: SV_VertexID)
    : SV_Position {
    return float4(vertex_pos_map[vertex_id], 0, 1);
}

// Signed distance function for a rounded rectangle
float
rounded_rectangle_sdf(float2 p, float2 b, float r) {
    // signed distance field
    // first term is used for points outside the rectangle
    float2 q = abs(p) - b;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

[shader("fragment")]
float4
fragment_main(
    uniform float4 rect,
    uniform float2 params,
    uniform float4 color,
    uniform float4 background_color,
    uniform float4 outer_color,
    float4 frag_coord: SV_Position // SV_Position provides gl_FragCoord equivalent in Slang
    )
    : SV_Target {
    float2 size = rect.zw; // GLSL .ba maps to .zw or .ba in Slang (using .zw is typical)
    float2 origin = rect.xy;
    float thickness = params[0];
    float corner_radius = params[1];

    // Position must be relative to the center of the rectangle of (size) located at (origin)
    // frag_coord.xy maps directly to gl_FragCoord.xy
    float2 position = frag_coord.xy - size / 2.0 - origin;

    // Calculate distance to rounded rectangle
    float dist = rounded_rectangle_sdf(position, size * 0.5 - corner_radius, corner_radius);

    // The border is outer - inner rects
    float outer_edge = -dist;
    float inner_edge = outer_edge - thickness;

    // Smooth borders (anti-alias)
    static const float step_size = 1.0;
    float outer_coverage = smoothstep(-step_size, step_size, outer_edge);
    float alpha = outer_coverage - smoothstep(-step_size, step_size, inner_edge);

    float4 ans = color;
    ans.a *= alpha;

    // background_color shows under and inside the border, outer_color fills
    // the corner regions between the rounded outline and the bounding rect
    float4 under = lerp(outer_color, background_color, outer_coverage);
    // pre-multiplied output
    return alpha_blend(ans, under);
}
