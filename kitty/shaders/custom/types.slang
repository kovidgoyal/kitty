#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.


// Internals, not part of the documented API
// Must match CUSTOM_SHADER_WINDOW_TEXELS and CUSTOM_SHADER_WINDOWS_PER_ROW in state.h
static const uint KITTY_WINDOW_TEXELS = 16;
static const uint KITTY_WINDOWS_PER_ROW = 64;

// Reads a texel of a combined texture sampler, see texel_fetch() in
// kitty/shaders/utils.slang for why this is needed.
uint
kitty_fetch_texel(Sampler2D<uint> s, int2 pos) {
    __target_switch {
    case metal: __intrinsic_asm "$0.read(uint2($2))$z";
    default: return s[pos];
    }
}

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

    // State of the active window in the active tab. All are zero when there is no active window.
    // 1.0 when the active window is showing the alternate screen, as used by
    // full screen programs such as editors and pagers, 0.0 otherwise.
    public float active_window_alternate_screen;
    // 1.0 while a command is running in the active window, 0.0 otherwise.
    // Requires shell integration, see https://sw.kovidgoyal.net/kitty/shell-integration/
    // A command starts when its output starts (OSC 133;C) and finishes when the
    // shell reports it finished (OSC 133;D) or draws the next prompt.
    public float active_window_command_running;
    // Seconds since the active window last entered or left the alternate screen,
    // negative if it never has. Use with the alternate-screen-enter and
    // alternate-screen-exit events to fade effects in and out.
    public float active_window_alternate_screen_age;
    // Seconds since a command last started or finished in the active window,
    // negative if none has. Use with the command-start and command-finish events.
    public float active_window_command_state_age;
    // The number of visible windows in the active tab, available via
    // KittyTextures.windows. Zero in shaders that do not use KittyTextures.windows.
    public uint num_windows;

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
// occupy only the top-left corner of the texture after the window is made
// smaller. Also, texture co-ordinates have their origin at the top-left,
// unlike UV co-ordinates. Sampling via the Sample() method below hides these
// details, so shaders never need to know about the underlying texture.
public struct KittyTexture {
    // The underlying texture. Use this only if you need raw texture
    // co-ordinates, which have their origin at the top-left, remember to
    // multiply your co-ordinates by scale below when you do.
    public Sampler2D tex;
    // The fraction of tex occupied by the OS Window viewport. Always in (0, 1].
    public float2 scale;
    // The largest usable texture co-ordinate, before multiplying by scale,
    // for Sample() below. Half a texel less than one, so that sampling the
    // right/bottom edge does not blend in texels from outside the viewport.
    public float2 max_pos;

    // Sample this texture at pos, which is in the same UV co-ordinate space as
    // KittyTextures.pos, that is, [0, 1] with the origin at the bottom-left.
    // Co-ordinates outside that range are clamped to the edge of the viewport.
    public float4
    Sample(float2 pos) {
        return tex.Sample(clamp(float2(pos.x, 1.f - pos.y), float2(0.f), max_pos) * scale);
    }
}

// The values of KittyWindow.progress_state
public static const uint KITTY_PROGRESS_UNSET = 0;
public static const uint KITTY_PROGRESS_SET = 1;
public static const uint KITTY_PROGRESS_ERROR = 2;
public static const uint KITTY_PROGRESS_INDETERMINATE = 3;
public static const uint KITTY_PROGRESS_PAUSED = 4;

// A visible window in the active tab
public struct KittyWindow {
    // Geometry of the window contents in UV co-ordinates (origin bottom-left).
    // .xy = lower-left corner, .zw = width and height. Same as
    // KittyCustomShaderData.active_window_geometry for the active window.
    public float4 geometry;
    // Extents beyond the contents, including a visible title bar, margin,
    // border, padding and cell-size compensation.
    // .xy = left/bottom, .zw = right/top, in viewport UV units. Same as
    // KittyCustomShaderData.active_window_padding for the active window.
    public float4 padding;
    // The state of the progress bar set by the program running in the window
    // with OSC 9;4, one of the KITTY_PROGRESS_* constants above.
    public uint progress_state;
    // The progress in [0, 1]. Meaningful only for KITTY_PROGRESS_SET and
    // KITTY_PROGRESS_PAUSED, zero otherwise.
    public float progress;
    // The values of progress_state and progress before they last changed, so
    // that shaders can animate from them to the current values, using progress_age.
    public uint previous_progress_state;
    public float previous_progress;
    // Seconds since progress_state or progress last changed, negative if they never have.
    public float progress_age;
    public bool is_active;           // true for the active window
    public bool is_alternate_screen; // true if the window is showing the alternate screen
    public bool is_command_running;  // true while a command is running, requires shell integration
    public bool is_last_bell_window; // true if the most recent bell was in this window

    // Whether pos (UV co-ordinates) is inside the contents of this window, or,
    // if include_padding is true, inside the area including the padding.
    public bool
    contains(float2 pos, bool include_padding = false) {
        float2 lo = geometry.xy, hi = geometry.xy + geometry.zw;
        if (include_padding) {
            lo -= padding.xy;
            hi += padding.zw;
        }
        return all(pos >= lo) && all(pos < hi);
    }
}

// The visible windows in the active tab. Loop over them with:
//   for (uint i = 0; i < t.windows.count; i++) { KittyWindow w = t.windows.get(i); ... }
// or use window_at() to find the window at a position.
public struct KittyWindows {
    // The number of windows, the same as KittyCustomShaderData.num_windows
    public uint count;
    // The texture describing the windows. Use get() rather than reading it directly.
    public Sampler2D<uint> data;
    // Copies of KittyCustomShaderData.viewport_size_pixels, timestamp_seconds and timestamp_fraction
    public uint2 viewport_size_pixels;
    public uint timestamp_seconds;
    public float timestamp_fraction;

    uint
    texel(uint idx, uint offset) {
        uint x = (idx % KITTY_WINDOWS_PER_ROW) * KITTY_WINDOW_TEXELS + offset;
        return kitty_fetch_texel(data, int2(int(x), int(idx / KITTY_WINDOWS_PER_ROW)));
    }

    // The geometry of window idx, as KittyWindow.geometry. Cheaper than get()
    // when only the geometry is needed, for example, when searching for a window.
    public float4
    geometry(uint idx) {
        // left, top, right, bottom in pixels, with the origin at the top left
        float4 edges = float4(texel(idx, 0), texel(idx, 1), texel(idx, 2), texel(idx, 3));
        float2 size = max(float2(viewport_size_pixels), float2(1.f));
        return float4(edges.x / size.x, 1.f - edges.w / size.y, (edges.z - edges.x) / size.x, (edges.w - edges.y) / size.y);
    }

    // The padding of window idx, as KittyWindow.padding
    public float4
    padding(uint idx) {
        float2 size = max(float2(viewport_size_pixels), float2(1.f));
        return float4(texel(idx, 4), texel(idx, 5), texel(idx, 6), texel(idx, 7)) / float4(size, size);
    }

    // The window at index idx, which must be less than count
    public KittyWindow
    get(uint idx) {
        KittyWindow w;
        w.geometry = geometry(idx);
        w.padding = padding(idx);
        uint flags = texel(idx, 8);
        w.progress_state = flags & 7u;
        w.previous_progress_state = (flags >> 7) & 7u;
        w.is_active = (flags & (1u << 3)) != 0u;
        w.is_alternate_screen = (flags & (1u << 4)) != 0u;
        w.is_command_running = (flags & (1u << 5)) != 0u;
        w.is_last_bell_window = (flags & (1u << 6)) != 0u;
        uint percents = texel(idx, 9);
        w.progress = float(percents & 0xffu) / 100.f;
        w.previous_progress = float((percents >> 8) & 0xffu) / 100.f;
        uint changed_seconds = texel(idx, 10);
        if (changed_seconds == 0xffffffffu) w.progress_age = -1.f;
        // Subtract as integers first to stay exact however long kitty runs
        else w.progress_age = max(0.f, float(int(timestamp_seconds - changed_seconds)) + (timestamp_fraction - float(texel(idx, 11)) * 1e-9f));
        return w;
    }

    // The index of the window containing pos (UV co-ordinates), or -1 if there
    // is none. With include_padding, the area around the window contents, as
    // described by KittyWindow.padding, counts too. This checks every window,
    // so it is best called once per pixel, using get() on the result.
    public int
    window_at(float2 pos, bool include_padding = false) {
        for (uint i = 0; i < count; i++) {
            float4 g = geometry(i);
            float2 lo = g.xy, hi = g.xy + g.zw;
            if (include_padding) {
                float4 p = padding(i);
                lo -= p.xy;
                hi += p.zw;
            }
            if (all(pos >= lo) && all(pos < hi)) return int(i);
        }
        return -1;
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
    // The visible windows in the active tab
    public KittyWindows windows;

    public float2 pos; // the position of this pixel in the viewport (UV coordinates, [0,1] range, origin at bottom-left)

    // Some group related uniforms. These are here rather than in
    // KittyCustomShaderData as that is shared by all groups, while these can
    // differ from group to group.

    // The viewport for this group in the form (x, y, width, height) where (x, y) is the
    // bottom-left corner, with (0, 0) at the bottom-left of the screen and y increasing upwards
    // (UV coordinates). Defaults to (0, 0, 1, 1) when no viewport is defined for the group.
    public float4 viewport;
    // Goes from zero to one over animation_duration after the group's
    // animation starts, with the animation_curve applied, then stays at one.
    // If animation_reverse is set, it goes back down to zero after the
    // animation stops, going up and down again animation_loops - 1 more
    // times. Always zero for groups that run on every frame and for
    // groups that have neither animation_duration nor a stop duration.
    public float animation_progress;
    // The index of the current group in the pipeline.
    public int group;
}
// END_TYPES_DEFINITION
