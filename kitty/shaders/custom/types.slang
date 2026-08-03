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
    // be updated with the output color only after all custom shaders in this group have run
    public Sampler2D backbuffer;
    // The following are named textures that can be sampled from in custom
    // shaders. The persist texture will persist across frames, anything
    // written to it in render number N can be read from it in subsequent
    // renders.
    public Sampler2D a;
    public Sampler2D b;
    public Sampler2D persist;

    public float2 pos;  // the position of this pixel in the textures
}
