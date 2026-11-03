#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// The uniform parameters of the program, shared by all its stages. See
// PUSH_CONSTANTS_MAX_SIZE in slang.py for why they are declared this way.
struct Params {
    float4 x_coords;
    float4 y_coords;
    float2 cursor_edge_x;
    float2 cursor_edge_y;
    float3 trail_color;
    float trail_opacity;
};
[[vk::push_constant]]
ConstantBuffer<Params> uniforms;

struct VertexOutput {
    float2 frag_pos : TEXCOORD;
    float4 position : SV_Position;
};

// Main Vertex Shader Entry Point
[shader("vertex")]
VertexOutput
vertex_main(uint vertex_id: SV_VertexID) {
    VertexOutput output;
    float2 pos = float2(uniforms.x_coords[vertex_id], uniforms.y_coords[vertex_id]);
    output.position = float4(pos, 1.0, 1.0);
    output.frag_pos = pos;
    return output;
}


// Main Fragment Shader Entry Point
[shader("fragment")]
float4
fragment_main(float2 frag_pos: TEXCOORD)
    : SV_Target {
    float opacity = uniforms.trail_opacity;
    // Evaluate if the fragment falls inside the bounding box of the cursor
    float in_x = step(uniforms.cursor_edge_x[0], frag_pos.x) * step(frag_pos.x, uniforms.cursor_edge_x[1]);
    float in_y = step(uniforms.cursor_edge_y[1], frag_pos.y) * step(frag_pos.y, uniforms.cursor_edge_y[0]);

    // Mask out opacity inside the active cursor area
    opacity *= 1.0f - (in_x * in_y);

    // Output color with premultiplied alpha formatting
    return float4(uniforms.trail_color * opacity, opacity);
}
