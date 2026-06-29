#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import blit;


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

[shader("fragment")]
float4 fragment_main(float2 texcoord : TEXCOORD, uniform Sampler2D image) : SV_Target
{
    float4 color = image.Sample(texcoord);
    return color;
}
