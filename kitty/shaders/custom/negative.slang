#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.
//
// Color-inversion (negative) effect.

import kitty_custom_shader_types;

public float4 fragment_main(
    float4 color,
    KittyTextures t,
    KittyCustomShaderData d,
    float4 viewport,
    float animation_progress
) {
    return float4(1.0 - color.r, 1.0 - color.g, 1.0 - color.b, color.a);
}
