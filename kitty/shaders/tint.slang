#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// The uniform parameters of the program, shared by all its stages. See
// PUSH_CONSTANTS_MAX_SIZE in slang.py for why they are declared this way.
struct Params {
    float4 edges; // [ left, top, right, bottom ]
    float4 tint_color;
};
[[vk::push_constant]]
ConstantBuffer<Params> uniforms;

// Main Vertex Shader Entry Point
[shader("vertex")]
float4
vertex_main(uint vertex_id: SV_VertexID)
    : SV_Position {
    // Extract boundaries from the edges vector
    float left = uniforms.edges[0];
    float top = uniforms.edges[1];
    float right = uniforms.edges[2];
    float bottom = uniforms.edges[3];

    // Static mapping table for vertex positions
    const float2 pos_map[4] = { float2(left, top), float2(left, bottom), float2(right, bottom), float2(right, top) };

    // Calculate final position
    return float4(pos_map[vertex_id], 0.0, 1.0);
}

[shader("fragment")]
float4
fragment_main()
    : SV_Target {
    return uniforms.tint_color;
}
