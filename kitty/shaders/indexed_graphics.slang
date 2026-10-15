#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// Renders images whose pixels are indices into the terminal color palette, so
// that they change automatically when the terminal colors change. This is a
// separate program from graphics.slang so that rendering of normal images has
// no overhead because of it.

import blit_common;
import background;

struct VSOutput {
    float2 texcoord : TEXCOORD;
    float4 position : SV_Position;
};

[shader("vertex")]
VSOutput
vertex_main(uint vertex_id: SV_VertexID, uniform float4 src_rect, uniform float4 dest_rect, ) {
    BlitOutput ans = get_coords_for_blit(vertex_id, src_rect, dest_rect);
    return { ans.texcoord, float4(ans.position[0], ans.position[1], 0.0, 1.0) };
}

// The red channel is the palette index and, when has_alpha is non-zero, the
// green channel is the straight alpha.
uniform Sampler2D<uint4> image;

float4
premult_color_at(int2 pos, uint has_alpha) {
    uint4 px = image[pos];
    float alpha = has_alpha != 0 ? float(px.g) / 255.0 : 1.0;
    return float4(indexed_image_color(px.r) * alpha, alpha);
}

[shader("fragment")]
float4
fragment_main(float2 texcoord: TEXCOORD, uniform uint has_alpha, uniform float extra_alpha)
    : SV_Target {
    // Integer textures cannot be filtered and anyway the palette lookup must
    // happen before interpolation, so do bilinear filtering here. When the
    // image is not scaled this reduces to reading a single pixel.
    int width, height;
    image.GetDimensions(width, height);
    const int2 limit = int2(width - 1, height - 1);
    const float2 pos = texcoord * float2(width, height) - 0.5;
    const float2 base = floor(pos);
    const float2 frac = pos - base;
    const int2 p0 = clamp(int2(base), int2(0, 0), limit);
    const int2 p1 = clamp(int2(base) + int2(1, 1), int2(0, 0), limit);
    const float4 top = lerp(premult_color_at(p0, has_alpha), premult_color_at(int2(p1.x, p0.y), has_alpha), frac.x);
    const float4 bottom = lerp(premult_color_at(int2(p0.x, p1.y), has_alpha), premult_color_at(p1, has_alpha), frac.x);
    return lerp(top, bottom, frac.y) * extra_alpha;
}
