#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import blit;
import alpha_blend;
import utils;

extern static const bool is_alpha_mask = false;
extern static const bool texture_is_not_premultiplied = false;
// specialize: alpha_mask: is_alpha_mask=true
// specialize: premult: texture_is_not_premultiplied=true


struct VSOutput
{
    float2 texcoord : TEXCOORD;
    float4 position : SV_Position;
};


[shader("vertex")]
VSOutput vertex_main(
    uint vertex_id : SV_VertexID,
    uniform float4 src_rect,
    uniform float4 dest_rect,
) {
    BlitOutput ans = get_coords_for_blit(vertex_id, src_rect, dest_rect);
    VSOutput output;
    output.texcoord = ans.texcoord;
    output.position = float4(ans.position[0], ans.position[1], 0.0, 1.0);
    return output;
}

uniform Sampler2D image;

[shader("fragment")]
float4 fragment_main(
    float2 texcoord : TEXCOORD,
    uniform float3 amask_fg,
    uniform float4 amask_bg_premult,
    uniform float extra_alpha
) : SV_Target {
    float4 color = image.Sample(texcoord);
    if (is_alpha_mask) {
        color = float4(amask_fg, color.r);
        color = vec4_premul(color);
        color = alpha_blend_premul(color, amask_bg_premult);
    } else color.a *= extra_alpha;

    if (texture_is_not_premultiplied) color = vec4_premul(color);

    return color;
}
