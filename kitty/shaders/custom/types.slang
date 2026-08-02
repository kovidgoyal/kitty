#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.


public struct KittyCustomShaderData {
    public float4 src_rect, dest_rect;  // used by the vertex shader internally

    public uint2 viewport_size_pixels;  // the size in pixels of the viewport we are rendering too

    public float timestamp;  // time in seconds since kitty was started
}

public struct KittyTextures {
    // the buffer containing the original rendered pixels from kitty's own rendering. This will
    // be updated with the output color only after all custom shaders in the chain have run
    public Sampler2D backbuffer;

    public float2 pos;  // the position of this pixel in the textures
}
