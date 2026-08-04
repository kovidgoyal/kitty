#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

import kitty_custom_shader_types;

public float4 fragment_main(float4 color, KittyTextures t, KittyCustomShaderData d, float4 viewport) {
    return float4(color.r, min(max(0.1, color.g) * 2, 1), color.b, color.a);
}
