#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import kitty_custom_shader_types;

static const float FACTOR = 2;

// START_FUNCTION_SIGNATURE
public float4
fragment_main(
    // The color from the previous custom shader in this group or from the
    // backbuffer if this is the first shader in the group
    float4 color,

    // See types.slang for details on the data in this structure
    KittyTextures t,

    // See types.slang for details on the data in this structure
    KittyCustomShaderData d) {
    // END_FUNCTION_SIGNATURE
    return float4(color.r, min(max(0.1, color.g) * FACTOR, 1), color.b, color.a);
}
