#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Gives a pixelated appearance similar to early Thin Film Transistor LCD displays

import kitty_custom_shader_types;

// size of the simulated pixels
extern static const float resolution = 4.0;

// strength of the effect
extern static const float strength = 0.5;

void scanline(inout float3 color, float2 pixel_pos) {
    float scanline = step(1.2, fmod(pixel_pos.y, resolution));
    float grille   = step(1.2, fmod(pixel_pos.x, resolution));
    color *= max(1.0 - strength, scanline * grille);
}

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport
) {
    float2 pixel_pos = t.pos * float2(d.viewport_size_pixels);
    float3 c = color.rgb;
    scanline(c, pixel_pos);
    return float4(c, 1.0);
}
