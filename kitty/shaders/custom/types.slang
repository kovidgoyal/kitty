#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.


public struct KittyCustomShaderData {
    public float4 src_rect, dest_rect;  // used by the vertex shader internally

    // global background/foreground colors from kitty options (linear RGB, alpha=1)
    public float4 background, foreground;
    // background color of the active window in the active tab (linear RGB, alpha=1)
    public float4 active_window_background;
    // Mouse position in UV coordinates (origin at lower-left).
    // Values outside [0, 1] indicate the mouse is outside the OS window.
    // The first two co-ordinates are current position, the last two the
    // position of the last left mouse press.
    public float4 mouse_pos;
    // Press state of the first four mouse buttons (left, right, middle, button4).
    // Each component is 1.0 if the button is currently held, 0.0 otherwise.
    public float4 mouse_button_pressed;

    // Cursor trail state (UV coordinates, origin bottom-left, (1,1) top-right).
    // All fields are zero when the cursor_trail kitty option is disabled or the trail is inactive.
    // The trail is a morphing quadrilateral whose four corners animate toward the cursor position.
    // Corner order: 0=top-right, 1=bottom-right, 2=bottom-left, 3=top-left.
    // Use animation_start cursor-trail-move / animation_stop cursor-trail-stop to activate.
    // animation_progress is NOT tied to trail duration; use cursor_trail_state.x for opacity instead.
    public float4 cursor_trail_corners_x;  // UV x-coordinates of the 4 animated trail quad corners
    public float4 cursor_trail_corners_y;  // UV y-coordinates of the 4 animated trail quad corners
    // .x=left, .y=right, .z=top, .w=bottom UV edges of the current cursor rectangle
    public float4 cursor_trail_edge;
    // Effective cursor color (linear RGB) and opacity for the active window.
    // .rgb = cursor background color, .a = cursor opacity (0..1).
    // Both are zero when no active window was rendered this frame.
    public float4 cursor_color;
    // Effective cursor trail color (linear RGB) and opacity.
    // .rgb = trail color (falls back to cursor_color.rgb when cursor_trail_color option is "none").
    // .a = trail opacity (0..1); zero when the trail is inactive.
    public float4 cursor_trail_color;

    // the size in pixels of the full underlying viewport we are rendering too,
    // before applying any viewport transforms from the current group.
    // You can use the viewport vector passed to fragment_main to derive the
    // actual size and position of the viewport currently being rendered too.
    public uint2 viewport_size_pixels;

    public float mouse_pointer_hidden;  // 1.0 if the mouse pointer is currently hidden, 0.0 if visible
    public float cursor_trail_state;    // 1.0 if the cursor trail is actively animating, 0.0 otherwise

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
