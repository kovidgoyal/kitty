#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import alpha_blend;

// Constants and Macros
#define left 0
#define top 1
#define right 2
#define bottom 3
#define tex_left 0.0
#define tex_top 0.0
#define tex_right 1.0
#define tex_bottom 1.0

#define x_axis 0
#define y_axis 1

static const float2 tex_map[4] = { float2(tex_left, tex_top), float2(tex_left, tex_bottom), float2(tex_right, tex_bottom), float2(tex_right, tex_top) };


// The uniform parameters of the program, shared by all its stages. See
// PUSH_CONSTANTS_MAX_SIZE in slang.py for why they are declared this way.
struct Params {
    float tiled;
    float4 sizes;
    float4 positions;
    float4 background;
};
[[vk::push_constant]]
ConstantBuffer<Params> uniforms;

struct VertexOutput {
    float2 texcoord : TEXCOORD;
    float4 position : SV_Position;
};

// Helper Functions
float
scale_factor(float window_size, float image_size) {
    return window_size / image_size;
}

float
tiling_factor(int i, float4 sizes, float tiled) {
    int window = i;
    int image = i + 2;
    return tiled * scale_factor(sizes[window], sizes[image]) + (1.0 - tiled);
}

// Main Vertex Shader Entry Point
[shader("vertex")]
VertexOutput
vertex_main(uint vertex_id: SV_VertexID) {
    const float2 pos_map[4] = {
        float2(uniforms.positions[left], uniforms.positions[top]),
        float2(uniforms.positions[left], uniforms.positions[bottom]),
        float2(uniforms.positions[right], uniforms.positions[bottom]),
        float2(uniforms.positions[right], uniforms.positions[top])
    };


    VertexOutput output;
    // Calculate outputs
    float2 tex_coords = tex_map[vertex_id];
    output.texcoord = float2(
        tex_coords[x_axis] * tiling_factor(x_axis, uniforms.sizes, uniforms.tiled), tex_coords[y_axis] * tiling_factor(y_axis, uniforms.sizes, uniforms.tiled));
    output.position = float4(pos_map[vertex_id], 0.0, 1.0);
    return output;
}

// Global Texture Bindings
[[vk::binding(1)]]
uniform Sampler2D image; // binding slots: see SHADER_BINDING_SLOTS in slang.py

// Main Fragment Shader Entry Point
[shader("fragment")]
float4
fragment_main(float2 texcoord: TEXCOORD)
    : SV_Target {
    // Sample the texture using Slang's intrinsic texture object syntax
    float4 color = image.Sample(texcoord);
    // Compute final color with alpha blending
    float4 premult_color = alpha_blend(color, uniforms.background);
    return premult_color;
}
