#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// https://github.com/shader-slang/slang/issues/11874
// warnings-disable: 41012

#define NUM_COLORS 256

extern static const bool DO_FG_OVERRIDE;
extern static const uint FG_OVERRIDE_ALGO;
extern static const float FG_OVERRIDE_THRESHOLD;
extern static const bool TEXT_NEW_GAMMA;
extern static const bool ONLY_FOREGROUND;
extern static const bool ONLY_BACKGROUND;

// Inputs {{{
struct CellRenderDataStruct
{
    float use_cell_bg_for_selection_fg, use_cell_fg_for_selection_fg, use_cell_for_selection_bg;

    uint default_fg, highlight_fg, highlight_bg, main_cursor_fg, main_cursor_bg, url_color, url_style, inverted, extra_cursor_fg, extra_cursor_bg;

    uint columns, lines, sprites_xnum, sprites_ynum, cursor_shape, cell_width, cell_height;
    uint cursor_x1, cursor_x2, cursor_y1, cursor_y2;
    float cursor_opacity, inactive_text_alpha, dim_opacity, blink_opacity;

    // must have unique entries with 0 being default_bg and unset being UINT32_MAX
    uint bg_colors0, bg_colors1, bg_colors2, bg_colors3, bg_colors4, bg_colors5, bg_colors6, bg_colors7;
    float bg_opacities0, bg_opacities1, bg_opacities2, bg_opacities3, bg_opacities4, bg_opacities5, bg_opacities6, bg_opacities7;
};

// Uniform Blocks (adjust binding slots as needed for your pipeline layout)
ConstantBuffer<CellRenderDataStruct> CellRenderData;

struct ColorTableStruct
{
    uint color_table[NUM_COLORS + MARK_MASK + MARK_MASK + 2];
};

ConstantBuffer<ColorTableStruct> ColorTable;

uniform float gamma_lut[256];
uniform Sampler2D<uint4> sprite_decorations_map;
//

static const int fg_index_map[3] = {0, 1, 0};
static const uint2 cell_pos_map[4] = {
    uint2(1u, 0u),  // right, top
    uint2(1u, 1u),  // right, bottom
    uint2(0u, 1u),  // left, bottom
    uint2(0u, 0u)   // left, top
};
static const uint cursor_shape_map[] = {  // maps cursor shape to foreground sprite index
   0u,  // NO_CURSOR
   0u,  // BLOCK  (this is rendered as background)
   2u,  // BEAM
   3u,  // UNDERLINE
   4u   // UNFOCUSED
};

// Vertex Input Attributes with explicit fixed locations
struct VertexInput
{
    [[vk::location(0)]] uint3 colors       : COLORS;
    [[vk::location(1)]] uint2 sprite_idx   : SPRITE_IDX;
    [[vk::location(2)]] uint  is_selected  : IS_SELECTED;
};

struct VSOutput {
    float4 position : SV_Position;

    float3 background;
    float4 effective_background_premul;
    float  effective_text_alpha;
    float3 sprite_pos;
    float3 underline_pos;
    float3 cursor_pos;
    float3 strike_pos;
    nointerpolation uint underline_exclusion_pos;
    float3 cell_foreground;
    float4 cursor_color_premult;
    float3 decoration_fg;
    float  colored_sprite;
};


[shader("vertex")]
VSOutput vertex_main(
    VertexInput vi,
    uint vertex_id : SV_VertexID,
    uniform uint draw_bg_bitfield,
    uniform float row_offset,
) {
    int width, height;
    sprite_decorations_map.GetDimensions(width, height);
    uint4 data = sprite_decorations_map.Load(int3(1,2,0));
    VSOutput r;
    r.position = float4(vertex_id + draw_bg_bitfield, data[0] / width * height, row_offset, CellRenderData.cursor_opacity);
    r.background = float3(ColorTable.color_table[vertex_id], vi.is_selected, 2);
    return r;
}


