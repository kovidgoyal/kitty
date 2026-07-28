#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// IMPORTS

public struct BlitOutput {
    float2 texcoord;
    float2 position;
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

BlitOutput get_coords_for_blit(uint vertex_id, float4 src_rect, float4 dest_rect) {
    int2 pos = vertex_pos_map[vertex_id];
    BlitOutput output;
    output.texcoord = float2(src_rect[pos.x], src_rect[pos.y]);
    output.position = float2(dest_rect[pos.x], dest_rect[pos.y]);
    return output;
}

public float4 pipeline_vertex_main(float4 src_rect, float4 dest_rect, uint vertex_id) {
    BlitOutput ans = get_coords_for_blit(vertex_id, src_rect, dest_rect);
    return float4(ans.texcoord[0], ans.texcoord[1], ans.position[0], ans.position[1]);
}

uniform Sampler2D backbuffer;

public float4 pipeline_fragment_main(float2 texcoord) {
    KittyCustomShaderData d;
    d.backbuffer = backbuffer;
    d.texcoord = texcoord;
    d.backbuffer = backbuffer;
    float4 color = backbuffer.Sample(texcoord);
    // PIPELINE
    return color;
}

