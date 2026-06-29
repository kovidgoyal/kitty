#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

module alpha_blend;

// Alpha blend two colors returning the resulting color pre-multiplied by its alpha
// and its alpha. See https://en.wikipedia.org/wiki/Alpha_compositing
public float4 alpha_blend(float4 over, float4 under) {
    float alpha = lerp(under.a, 1.0f, over.a);
    float3 combined_color = lerp(under.rgb * under.a, over.rgb, over.a);
    return float4(combined_color, alpha);
}

// Same as alpha_blend() except that it assumes over and under are both premultiplied.
public float4 alpha_blend_premul(float4 over, float4 under) {
    float inv_over_alpha = 1.0f - over.a;
    float alpha = over.a + under.a * inv_over_alpha;
    return float4(over.rgb + under.rgb * inv_over_alpha, alpha);
}

// Same as alpha_blend_premul with under_alpha = 1 outputs a blended color
// with alpha 1 which is effectively pre-multiplied since alpha is 1
public float4 alpha_blend_premul(float4 over, float3 under) {
    float inv_over_alpha = 1.0f - over.a;
    return float4(over.rgb + under.rgb * inv_over_alpha, 1.0f);
}

