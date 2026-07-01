#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import blit_common;
import linear2srgb;

struct VSOutput {
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
    return {ans.texcoord, float4(ans.position[0], ans.position[1], 0.0, 1.0)};
}

uniform Sampler2D image;

float3 safe_unpremult_to_linear(float4 s) {
    // Avoid division by zero by replacing 0.0 alpha with 1.0.
    // If alpha is 0.0, the division is safe, and lerp masks the result to 0.0 anyway.
    float safe_alpha = lerp(1.0f, s.a, step(0.00001f, s.a));
    float3 unpremult = s.rgb / safe_alpha;
    // Select between the computed linear color and float3(0.0) based on alpha presence
    return lerp(float3(0.0f), srgb2linear(unpremult), step(0.00001f, s.a));
}

[shader("fragment")]
float4 fragment_main(float2 texcoord : TEXCOORD, uniform float2 src_size) : SV_Target {
    float4 s00, s10, s01, s11;
    float2 texel_size = 1.0 / src_size;

    // Use Slang target switches to dynamically compile for specific backend features
    __target_switch
    {
        // Modern backends with full texture gathering capabilities
        case spirv: case hlsl: case metal: {
            float2 gather_coord = texcoord - (0.5 * texel_size);

            float4 r_gather = image.GatherRed(gather_coord);
            float4 g_gather = image.GatherGreen(gather_coord);
            float4 b_gather = image.GatherBlue(gather_coord);
            float4 a_gather = image.GatherAlpha(gather_coord);

            s00 = float4(r_gather.w, g_gather.w, b_gather.w, a_gather.w); // Bottom-Left
            s10 = float4(r_gather.z, g_gather.z, b_gather.z, a_gather.z); // Bottom-Right
            s01 = float4(r_gather.x, g_gather.x, b_gather.x, a_gather.x); // Top-Left
            s11 = float4(r_gather.y, g_gather.y, b_gather.y, a_gather.y); // Top-Right
        }
        // Fallback for older targets or legacy GLSL versions
        default: {
            s00 = image.Sample(texcoord + float2(-0.25, -0.25) * texel_size);
            s10 = image.Sample(texcoord + float2( 0.25, -0.25) * texel_size);
            s01 = image.Sample(texcoord + float2(-0.25,  0.25) * texel_size);
            s11 = image.Sample(texcoord + float2( 0.25,  0.25) * texel_size);
        }
    }

    // Unpremultiply and convert to linear for each sample
    float3 linear00 = safe_unpremult_to_linear(s00);
    float3 linear10 = safe_unpremult_to_linear(s10);
    float3 linear01 = safe_unpremult_to_linear(s01);
    float3 linear11 = safe_unpremult_to_linear(s11);

    // Average the alpha values
    float avg_alpha = (s00.a + s10.a + s01.a + s11.a) * 0.25;

    // For proper downsampling with transparency, weight colors by their alpha
    float3 weighted_sum = linear00 * s00.a + linear10 * s10.a + linear01 * s01.a + linear11 * s11.a;
    float total_weight = s00.a + s10.a + s01.a + s11.a;

    // Calculate the weighted average color in linear space
    float safe_total_weight = lerp(1.0f, total_weight, step(0.00001f, total_weight));
    float3 avg_linear = lerp(float3(0.0f), weighted_sum / safe_total_weight, step(0.00001f, total_weight));

    // Convert back to sRGB
    float3 srgb_color = linear2srgb(avg_linear);

    // Output unpremultiplied sRGB color
    return float4(srgb_color, avg_alpha);
}
