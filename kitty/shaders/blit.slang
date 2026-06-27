#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// Maps a vertex id to src and destination co-ordinates
module blit;

public struct BlitOutput {
    public float2 texcoord;
    public float2 position;
};

#define left 0
#define top 1
#define right 2
#define bottom 3

// Static constant array mapping vertex IDs
static const int2 vertex_pos_map[4] =
{
    int2(right, top),
    int2(right, bottom),
    int2(left, bottom),
    int2(left, top)
};

public BlitOutput get_coords_for_blit(uint vertex_id, float4 src_rect, float4 dest_rect) {
    BlitOutput output;
    int2 pos = vertex_pos_map[vertex_id];
    // Indexing into the float4 vectors using pos.x and pos.y
    output.texcoord = float2(src_rect[pos.x], src_rect[pos.y]);
    output.position = float2(dest_rect[pos.x], dest_rect[pos.y]);
    return output;
}

