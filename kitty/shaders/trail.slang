#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

struct VertexOutput
{
    float2 frag_pos : TEXCOORD;
    float4 position : SV_Position;
};

// Main Vertex Shader Entry Point
[shader("vertex")]
VertexOutput vertex_main(uint vertex_id : SV_VertexID, uniform float4 x_coords, uniform float4 y_coords) {
    VertexOutput output;
    float2 pos = float2(x_coords[vertex_id], y_coords[vertex_id]);
    output.position = float4(pos, 1.0, 1.0);
    output.frag_pos = pos;
    return output;
}


// Main Fragment Shader Entry Point
[shader("fragment")]
float4 fragment_main(
    float2 frag_pos : TEXCOORD,
    uniform float2 cursor_edge_x,
    uniform float2 cursor_edge_y,
    uniform float3 trail_color,
    uniform float trail_opacity
) : SV_Target {
    float opacity = trail_opacity;
    // Evaluate if the fragment falls inside the bounding box of the cursor
    float in_x = step(cursor_edge_x[0], frag_pos.x) * step(frag_pos.x, cursor_edge_x[1]);
    float in_y = step(cursor_edge_y[1], frag_pos.y) * step(frag_pos.y, cursor_edge_y[0]);

    // Mask out opacity inside the active cursor area
    opacity *= 1.0f - (in_x * in_y);

    // Output color with premultiplied alpha formatting
    return float4(trail_color * opacity, opacity);
}
