#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// IMPORTS

public struct BlitOutput {
    public float2 texcoord;
    public float2 position;
};

#define left 0
#define top 1
#define right 2
#define bottom 3

// Static constant array mapping vertex IDs
static const int2 vertex_pos_map[4] = {
    {right, top},
    {right, bottom},
    {left, bottom},
    {left, top}
};

public BlitOutput get_coords_for_blit(uint vertex_id, float4 src_rect, float4 dest_rect) {
    int2 pos = vertex_pos_map[vertex_id];
    BlitOutput output;
    output.texcoord = float2(src_rect[pos.x], src_rect[pos.y]);
    output.position = float2(dest_rect[pos.x], dest_rect[pos.y]);
    return output;
}

struct VertexOutput {
    float2 texcoord : TEXCOORD;
    float4 position : SV_Position;
};


[shader("vertex")]
VertexOutput vertex_main(float4 src_rect, float4 dest_rect, uint vertex_id : SV_VertexID) {
    BlitOutput ans = get_coords_for_blit(vertex_id, src_rect, dest_rect);
    return {ans.texcoord, float4(ans.position[0], ans.position[1], 0.0, 1.0)};
}

uniform Sampler2D backbuffer;

[shader("fragment")]
float4 pipeline_fragment_main(float2 texcoord : TEXCOORD) : SV_Target {
    KittyCustomShaderData d;
    d.backbuffer = backbuffer;
    d.texcoord = texcoord;
    d.backbuffer = backbuffer;
    float4 color = backbuffer.Sample(texcoord);
    // PIPELINE
    return color;
}

