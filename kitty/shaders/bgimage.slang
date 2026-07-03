#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import alpha_blend;

// Constants and Macros
#define left  0
#define top  1
#define right  2
#define bottom  3
#define tex_left 0.0
#define tex_top 0.0
#define tex_right 1.0
#define tex_bottom 1.0

#define x_axis 0
#define y_axis 1

static const float2 tex_map[4] = {
    float2(tex_left, tex_top),
    float2(tex_left, tex_bottom),
    float2(tex_right, tex_bottom),
    float2(tex_right, tex_top)
};


struct VertexOutput {
    float2 texcoord : TEXCOORD;
    float4 position : SV_Position;
};

// Helper Functions
float scale_factor(float window_size, float image_size) {
    return window_size / image_size;
}

float tiling_factor(int i, float4 sizes, float tiled) {
    int window = i;
    int image = i + 2;
    return tiled * scale_factor(sizes[window], sizes[image]) + (1.0 - tiled);
}

// Main Vertex Shader Entry Point
[shader("vertex")]
VertexOutput vertex_main(
    uint vertex_id : SV_VertexID,
    uniform float tiled,
    uniform float4 sizes,
    uniform float4 positions,
) {
    const float2 pos_map[4] = {
        float2(positions[left], positions[top]),
        float2(positions[left], positions[bottom]),
        float2(positions[right], positions[bottom]),
        float2(positions[right], positions[top])
    };


    VertexOutput output;
    // Calculate outputs
    float2 tex_coords = tex_map[vertex_id];
    output.texcoord = float2(
        tex_coords[x_axis] * tiling_factor(x_axis, sizes, tiled),
        tex_coords[y_axis] * tiling_factor(y_axis, sizes, tiled)
    );
    output.position = float4(pos_map[vertex_id], 0.0, 1.0);
    return output;
}

// Global Texture Bindings
uniform Sampler2D image;

// Main Fragment Shader Entry Point
[shader("fragment")]
float4 fragment_main(float2 texcoord: TEXCOORD, uniform float4 background) : SV_Target {
    // Sample the texture using Slang's intrinsic texture object syntax
    float4 color = image.Sample(texcoord);
    // Compute final color with alpha blending
    float4 premult_color = alpha_blend(color, background);
    return premult_color;
}
