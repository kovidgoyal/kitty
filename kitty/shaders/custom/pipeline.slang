#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// IMPORTS

static const int LEFT = 0;
static const int TOP = 1;
static const int RIGHT = 2;
static const int BOTTOM = 3;
static const uint FF = 0xff;

static const uint2 pos_map[4] = {
    uint2(RIGHT, TOP),
    uint2(RIGHT, BOTTOM),
    uint2(LEFT, BOTTOM),
    uint2(LEFT, TOP)
};

struct VertexOutput {
    float4 position : SV_Position;
    KittyCustomShaderData d;
};


[shader("vertex")]
VertexOutput vertex_main(float4 rect, uint vertex_id : SV_VertexID) {
    uint2 pos = pos_map[vertex_id];
    VertexOutput vo;
    vo.position = float4(rect[pos.x], rect[pos.y], 0, 1);
    return vo;
}

[shader("fragment")]
float4 pipeline_fragment_main(VertexOutput vo) : SV_Target {
    vo.d.pos = vo.position;
    float4 color = float4(1, 1, 1, 1);  // TODO: load from framebuffer
    // PIPELINE
    return color;
}

