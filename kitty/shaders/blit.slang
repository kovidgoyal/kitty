#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import blit_common;
import alpha_blend;
import utils;
import linear2srgb;

// The uniform parameters of the program, shared by all its stages. See
// PUSH_CONSTANTS_MAX_SIZE in slang.py for why they are declared this way.
struct Params {
    float4 src_rect;
    float4 dest_rect;
};
[[vk::push_constant]]
ConstantBuffer<Params> uniforms;

struct VSOutput {
    float2 texcoord : TEXCOORD;
    float4 position : SV_Position;
};


[shader("vertex")]
VSOutput
vertex_main(uint vertex_id: SV_VertexID) {
    BlitOutput ans = get_coords_for_blit(vertex_id, uniforms.src_rect, uniforms.dest_rect);
    return { ans.texcoord, float4(ans.position[0], ans.position[1], 0.0, 1.0) };
}

[[vk::binding(1)]]
uniform Sampler2D image; // binding slots: see SHADER_BINDING_SLOTS in slang.py

[shader("fragment")]
float4
fragment_main(float2 texcoord: TEXCOORD)
    : SV_Target {
    float4 color_premul = image.Sample(texcoord);
    return vec4_premul(linear2srgb(color_premul.rgb / color_premul.a), color_premul.a);
}
