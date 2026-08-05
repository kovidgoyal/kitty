#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.


public struct KittyCustomShaderData {
    public float4 src_rect, dest_rect;  // used by the vertex shader internally

    // global background/foreground colors from kitty options (linear RGB, alpha=1)
    public float4 background, foreground;
    // background color of the active window in the active tab (linear RGB, alpha=1)
    public float4 active_window_background;

    // the size in pixels of the full underlying viewport we are rendering too,
    // before applying any viewport transforms from the current group.
    // You can use the viewport vector passed to fragment_main to derive the
    // actual size and position of the viewport currently being rendered too.
    // That vector contains the viewport_pos and viewport_size fields from the
    // pipeline definition in the format (x, y, width, height) (as unit floats
    // with origin at top left)
    public uint2 viewport_size_pixels;

    public float timestamp;  // time in seconds since kitty was started (millisecond precision)
    public float last_rendered_at;  // time of previous render in seconds since kitty was started (millisecond precision)
    public uint frame_counter;  // cumulative frame counter increments by one every time a frame is fully rendered, first frame is zero
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

    public float2 pos;  // the position of this pixel in the textures (UV coordinates)
}
