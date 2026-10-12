#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.


public struct KittyCustomShaderData {
    public float4 src_rect, dest_rect; // used by the vertex shader internally

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
    // Geometry of the currently active window in UV co-ordinates (origin bottom-left).
    // .xy = lower-left corner of the window, .zw = width and height.
    // All components are zero when no active window was rendered this frame.
    public float4 active_window_geometry;
    // Extents beyond the active content, including a visible title bar, margin,
    // border, padding and cell-size compensation.
    // .xy = left/bottom, .zw = right/top, in viewport UV units.
    public float4 active_window_padding;
    // Geometry of the most recently belled window in UV co-ordinates (origin bottom-left).
    // .xy = lower-left corner of the window, .zw = width and height.
    // If the belled window is not currently visible in the active tab/layout, equals central_area.
    // All components are zero until the first bell-in-window event occurs.
    public float4 bell_window_geometry;
    // Geometry of the central content area of the OS window (the tab area, excluding any tab bar)
    // in UV co-ordinates (origin bottom-left).
    // .xy = lower-left corner, .zw = width and height.
    // Equals the full viewport when no tab bar is visible.
    public float4 central_area;

    // Cursor trail state (UV coordinates, origin bottom-left, (1,1) top-right).
    // All fields are zero when the cursor_trail kitty option is disabled or the trail is inactive.
    // The trail is a morphing quadrilateral whose four corners animate toward the cursor position.
    // Corner order: 0=top-right, 1=bottom-right, 2=bottom-left, 3=top-left.
    // Use animation_start cursor-trail-move / animation_stop cursor-trail-stop to activate.
    // animation_progress is NOT tied to trail duration; use cursor_trail_state.x for opacity instead.
    public float4 cursor_trail_corners_x; // UV x-coordinates of the 4 animated trail quad corners
    public float4 cursor_trail_corners_y; // UV y-coordinates of the 4 animated trail quad corners
    // Previous-frame animated trail quad corners. These are available for
    // custom shaders that perform temporal effects.
    public float4 cursor_trail_prev_corners_x;
    public float4 cursor_trail_prev_corners_y;
    // .x=left, .y=right, .z=top, .w=bottom UV edges of the current cursor rectangle
    public float4 cursor_trail_edge;
    // .x=left, .y=right, .z=top, .w=bottom UV edges of the cursor rectangle before the most recent move.
    // All zeros until the cursor has moved at least twice (first move establishes current; second move sets this).
    public float4 cursor_trail_prev_edge;
    // Effective cursor color (linear RGB) and opacity for the active window.
    // .rgb = cursor background color, .a = cursor opacity (0..1).
    // Both are zero when no active window was rendered this frame.
    public float4 cursor_color;
    // Effective cursor trail color (linear RGB) and opacity.
    // .rgb = trail color (falls back to cursor_color.rgb when cursor_trail_color option is "none").
    // .a = trail opacity (0..1); zero when the trail is inactive.
    public float4 cursor_trail_color;
    // The most recent cursor moves that started a cursor trail, most recent
    // first. Unlike the other cursor_trail_* fields these remain valid after
    // the trail has finished, so effects started by a move can outlive the
    // trail and effects from several moves can overlap.
    // .x=left, .y=right, .z=top, .w=bottom UV edges of the cursor rectangle
    // before (from) and after (to) the move.
    public float4 cursor_trail_history_from[8];
    public float4 cursor_trail_history_to[8];
    // Seconds since each move, move i is in cursor_trail_history_age[i / 4][i % 4].
    // Negative for unused entries.
    public float4 cursor_trail_history_age[2];
    // the size in pixels of the full underlying viewport we are rendering too,
    // before applying any viewport transforms from the current group.
    // You can use t.viewport to derive the actual size and position of the
    // viewport currently being rendered too.
    public uint2 viewport_size_pixels;

    public float mouse_pointer_hidden; // 1.0 if the mouse pointer is currently hidden, 0.0 if visible
    public float cursor_trail_state;   // 1.0 if the cursor trail is actively animating, 0.0 otherwise

    // Time in seconds since kitty was started. Note that this loses precision
    // the longer kitty runs: it is accurate to 1ms only for the first ~4.7 hours
    // and to ~64ms after a week. So for animations use wrapped_time() below,
    // and for the time elapsed since an event, use the various *_age fields.
    public float timestamp;
    public float last_rendered_at; // time of previous render, same epoch and precision as timestamp
    public uint frame_counter;     // cumulative frame counter increments by one every time a frame is fully rendered, first frame is zero
    // Time (same epoch and precision as `timestamp`) of the most recent cursor position change that triggered a trail.
    // Zero until the cursor has moved at least twice. Pair with cursor_trail_prev_edge.
    // Use cursor_trail_age instead to find how long ago this was.
    public float cursor_trail_change_time;

    // timestamp split into whole seconds and the fraction of the current
    // second, which together are exact however long kitty runs. Usually you
    // want to use wrapped_time() below instead of these.
    public uint timestamp_seconds;
    public float timestamp_fraction; // in [0, 1)
    // Seconds between the previous render and this one, zero for the first render.
    public float time_since_last_render;
    // Seconds since cursor_trail_change_time, negative when cursor_trail_change_time is zero.
    public float cursor_trail_age;

    // Seconds since kitty was started, wrapped to [0, period_seconds). Unlike
    // timestamp, this keeps sub-millisecond precision however long kitty runs,
    // as long as period_seconds is at most an hour or so. The value jumps back
    // to zero once every period, so either use a period over which your
    // animation repeats seamlessly, or a long one so that the jump is rare.
    public float
    wrapped_time(uint period_seconds) {
        return float(timestamp_seconds % period_seconds) + timestamp_fraction;
    }
}

// A texture kitty renders into, addressed in the same UV co-ordinate space as
// KittyTextures.pos. kitty renders into textures that are at least as large as
// the largest OS Window viewport, so the pixels for the current OS Window
// occupy only the lower-left corner of the texture after the window is made
// smaller. Sampling via the Sample() method below hides that detail, so
// shaders never need to know the size of the underlying texture.
public struct KittyTexture {
    // The underlying texture. Use this only if you need raw texture UV,
    // remember to multiply your co-ordinates by scale below when you do.
    public Sampler2D tex;
    // The fraction of tex occupied by the OS Window viewport. Always in (0, 1].
    public float2 scale;
    // The largest usable co-ordinate for Sample() below. Half a texel less than
    // one, so that sampling the top/right edge does not blend in texels from
    // outside the viewport.
    public float2 max_pos;

    // Sample this texture at pos, which is in the same UV co-ordinate space as
    // KittyTextures.pos, that is, [0, 1] with the origin at the bottom-left.
    // Co-ordinates outside that range are clamped to the edge of the viewport.
    public float4
    Sample(float2 pos) {
        return tex.Sample(clamp(pos, float2(0.f), max_pos) * scale);
    }
}

public struct KittyTextures {
    // the buffer containing the original rendered pixels from kitty's own rendering. This will
    // be updated with the output color only after all custom shaders in this group have run
    public KittyTexture backbuffer;
    // The following are named textures that can be sampled from in custom
    // shaders. The persist texture will persist across frames, anything
    // written to it in render number N can be read from it in subsequent
    // renders.
    public KittyTexture a;
    public KittyTexture b;
    public KittyTexture persist;

    public float2 pos; // the position of this pixel in the viewport (UV coordinates, [0,1] range, origin at bottom-left)

    // Some group related uniforms

    // The viewport for this group in the form (x, y, width, height) where (x, y) is the
    // bottom-left corner, with (0, 0) at the bottom-left of the screen and y increasing upwards
    // (UV coordinates). Defaults to (0, 0, 1, 1) when no viewport is defined for the group.
    public float4 viewport;
    // The value after applying the animation easing curve to time since animation start.
    // Zero when no animation is active.
    public float animation_progress;
    // The index of the current group in the pipeline.
    public int group;
}
// END_TYPES_DEFINITION
