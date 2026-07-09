#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

// https://github.com/shader-slang/slang/issues/11874
// warnings-disable: 41012

import utils;
import background;

// This shader colors the compensatory window padding (the thin strips that
// appear when the window size is not an exact multiple of the cell size) so
// that each strip matches the background of its neighboring cell. It re-uses
// the cell VAO (colors/sprite_idx/is_selected instanced attributes) and the
// background module's padding_background_premul() to compute the color.
//
// It is invoked once per edge (a "strip") with the cell VAO attributes
// re-pointed so that instance i corresponds to the i'th cell along that strip.
// The geometry of the quad is computed entirely from uniforms in
// framebuffer-NDC, since the padding lies outside the per-window cell viewport
// and is therefore drawn with the full framebuffer viewport.

// Corner indicator per quad vertex, matching cell_pos_map in background.slang.
// .x: 0 -> left, 1 -> right ; .y: 0 -> top, 1 -> bottom
static const uint2 pad_pos_map[4] = {
    uint2(1u, 0u),  // right, top
    uint2(1u, 1u),  // right, bottom
    uint2(0u, 1u),  // left, bottom
    uint2(0u, 0u)   // left, top
};

struct VertexOutput {
    float4 color_premul : COLOR_PREMUL;
    float4 position : SV_Position;
};

[shader("vertex")]
VertexOutput vertex_main(
    [[vk::location(0)]] uint3 colors,
    [[vk::location(1)]] uint2 sprite_idx,
    [[vk::location(2)]] uint  is_selected,
    uint vertex_id : SV_VertexID,
    uint instance_id : SV_InstanceID,
    // The true cell index (into the cell grid) of this strip cell, used only to
    // reconstruct the row/column for the shared background computation. It is
    // base_instance + instance_id * instance_step and matches the offset/stride
    // used to re-point the VAO attributes on the C side.
    uniform uint base_instance,
    uniform uint instance_step,
    // 1 for the top/bottom strips (the strip runs along x), 0 for left/right.
    uniform uint is_horizontal,
    // Number of cells along the strip (== instance count).
    uniform uint along_count,
    // The two NDC values of the thin (across) dimension of the strip, selected
    // by the quad corner: .x for the near-content corner mapping, .y for the
    // other. The C side assigns these per edge.
    uniform float2 across,
    // NDC of the along dimension for the first cell's near corner, and the step
    // per cell (signed; negative for the vertical strips as NDC y decreases
    // downwards).
    uniform float along_start,
    uniform float along_step,
    // NDC bounds used to extend the first/last cell so the strip fills the
    // corners (a no-op when set to the natural strip extent).
    uniform float2 along_clamp,
) {
    VertexOutput vo;
    uint real_id = base_instance + instance_id * instance_step;
    vo.color_premul = padding_background_premul(colors, sprite_idx, is_selected, real_id);

    uint2 p = pad_pos_map[vertex_id];
    float along_lo = along_start + float(instance_id) * along_step;
    float along_hi = along_lo + along_step;

    // Branch-free selection via lerp(). h selects the strip orientation, s is the
    // corner component along the strip axis and a the component across it.
    float h = float(is_horizontal);
    float s = lerp(float(p.y), float(p.x), h);
    float a = lerp(float(p.x), float(p.y), h);
    // 1 when this is the first/last cell along the strip, else 0.
    float is_first = 1.0 - min(float(instance_id), 1.0);
    float is_last = 1.0 - min(float(along_count - 1u - instance_id), 1.0);

    float along = lerp(along_lo, along_hi, s);
    // Extend the first cell's near corner and the last cell's far corner out to
    // along_clamp so the strip fills the corners.
    along = lerp(along, along_clamp.x, is_first * (1.0 - s));
    along = lerp(along, along_clamp.y, is_last * s);
    float across_v = lerp(across.x, across.y, a);

    // Horizontal strip -> position is (along, across); vertical -> (across, along).
    vo.position = float4(lerp(across_v, along, h), lerp(along, across_v, h), 0.0, 1.0);
    return vo;
}

[shader("fragment")]
float4 fragment_main(float4 color_premul : COLOR_PREMUL) : SV_Target {
    return color_premul;
}
