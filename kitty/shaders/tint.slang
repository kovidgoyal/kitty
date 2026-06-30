#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// Main Vertex Shader Entry Point
[shader("vertex")]
float4 vertex_main(
    uint vertex_id : SV_VertexID,
    uniform float4 edges, // [ left, top, right, bottom ]
) : SV_Position {
    // Extract boundaries from the edges vector
    float left   = edges[0];
    float top    = edges[1];
    float right  = edges[2];
    float bottom = edges[3];

    // Static mapping table for vertex positions
    const float2 pos_map[4] = {
        float2(left, top),
        float2(left, bottom),
        float2(right, bottom),
        float2(right, top)
    };

    // Calculate final position
    return float4(pos_map[vertex_id], 0.0, 1.0);
}

[shader("fragment")]
float4 fragment_main(uniform float4 tint_color) : SV_Target {
    return tint_color;
}
