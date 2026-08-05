#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import kitty_custom_shader_types;

public float4 fragment_main(
    // The color from the previous custom shader in this group or from the
    // backbuffer if this is the first shader in the group
    float4 color,
    // See types.slang for details on the data in this structure
    KittyTextures t,
    // See types.slang for details on the data in this structure
    KittyCustomShaderData d,
    // The viewport used for this group. In the form (x, y, width, height)
    // where (x, y) is (0, 0) at the top-left corner and y increases downwards.
    // All numbers are unit floats. If no viewport is defined for the group
    // defaults to (0, 0, 1, 1) that is, the full backbuffer.
    float4 viewport
) {
    return float4(color.r, min(max(0.1, color.g) * 2, 1), color.b, color.a);
}
