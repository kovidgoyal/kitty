#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import blit_common;
import alpha_blend;
import utils;

extern static const bool is_alpha_mask = false;
extern static const bool texture_is_not_premultiplied = true;


// The uniform parameters of the program, shared by all its stages. See
// PUSH_CONSTANTS_MAX_SIZE in slang.py for why they are declared this way.
struct Params {
    float4 src_rect;
    float4 dest_rect;
    float3 amask_fg;
    float4 amask_bg_premult;
    float extra_alpha;
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
    float4 color = image.Sample(texcoord);
    if (is_alpha_mask) {
        color = float4(uniforms.amask_fg, color.r);
        color = vec4_premul(color);
        color = alpha_blend_premul(color, uniforms.amask_bg_premult);
    } else color.a *= uniforms.extra_alpha;

    if (texture_is_not_premultiplied) color = vec4_premul(color);

    return color;
}
