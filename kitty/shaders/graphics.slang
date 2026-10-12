#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import blit_common;
import alpha_blend;
import utils;
import background;

extern static const bool is_alpha_mask = false;
extern static const bool texture_is_not_premultiplied = true;


struct VSOutput {
    float2 texcoord : TEXCOORD;
    float4 position : SV_Position;
};

float4
transparent() {
    return float4(0.0);
}

float4
get_termscheme(uint i) {
    if(i == 0) {
        return float4(crd.default_bg_lin.rgb, 1.0);
    }
    if(i == 1) {
        return float4(crd.default_fg_lin.rgb, 1.0);
    }
    if(i == 2) {
        return float4(crd.highlight_bg_lin.rgb, 1.0);
    }
    if(i == 3) {
        return float4(crd.highlight_fg_lin.rgb, 1.0);
    }
    if(i == 4) {
        return float4(crd.main_cursor_bg_lin.rgb, 1.0);
    }
    if(i == 5) {
        return float4(crd.main_cursor_fg_lin.rgb, 1.0);
    }
    if(i < 22) {
        return float4(color_to_vec(ctb.color_table[i-5]), 1.0);
    }
    if(i == 22) {
        return transparent();
    }
    return transparent();
}

[shader("vertex")]
VSOutput
vertex_main(uint vertex_id: SV_VertexID, uniform float4 src_rect, uniform float4 dest_rect, ) {
    BlitOutput ans = get_coords_for_blit(vertex_id, src_rect, dest_rect);
    return { ans.texcoord, float4(ans.position[0], ans.position[1], 0.0, 1.0) };
}

uniform Sampler2D image;
uniform Sampler2D<uint> paletted_image;

[shader("fragment")]
float4
fragment_main(float2 texcoord: TEXCOORD, uniform float3 amask_fg, uniform float4 amask_bg_premult, uniform float extra_alpha, uniform bool is_colorscheme)
    : SV_Target {
    float4 color;

    if(is_colorscheme) {
        uint color_index = paletted_image.Sample(texcoord);
        color = get_termscheme(color_index);
    } else {
        color = image.Sample(texcoord);
    }

    if (is_alpha_mask) {
        color = float4(amask_fg, color.r);
        color = vec4_premul(color);
        color = alpha_blend_premul(color, amask_bg_premult);
    } else color.a *= extra_alpha;

    if (texture_is_not_premultiplied) color = vec4_premul(color);

    return color;
}
