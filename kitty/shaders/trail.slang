#language slang 2026
// Copyright (C) 2026 Kovid Goyal <kovid at kovidgoyal.net>
// Distributed under terms of the GPLv3 license.

struct VertexOutput {
    float2 frag_pos : TEXCOORD;
    float4 position : SV_Position;
};

[shader("vertex")]
VertexOutput
vertex_main(
    uint vertex_id: SV_VertexID,
    uniform float4 x_coords,
    uniform float4 y_coords,
    uniform float2 pixel_size,
    uniform bool antialiasing_enabled_vertex
) {
    VertexOutput output;
    float2 pos = float2(x_coords[vertex_id], y_coords[vertex_id]);
    output.frag_pos = pos;
    if (antialiasing_enabled_vertex) {
        if (vertex_id == 0 || vertex_id == 3) pos.y += pixel_size.y;
        else pos.y -= pixel_size.y;
        if (vertex_id == 0 || vertex_id == 1) pos.x += pixel_size.x;
        else pos.x -= pixel_size.x;
    }
    output.position = float4(pos, 1.0, 1.0);
    return output;
}

float
edge_distance(float2 a, float2 b, float2 p) {
    float2 edge = b - a;
    return -((edge.x * (p.y - a.y)) - (edge.y * (p.x - a.x))) / max(length(edge), 1e-8);
}

float
triangle_coverage(float2 p, float2 a, float2 b, float2 c) {
    return step(0.0, min(edge_distance(a, b, p), min(edge_distance(b, c, p), edge_distance(c, a, p))));
}

float
trail_coverage(float2 p, uniform float4 trail_x_coords, uniform float4 trail_y_coords) {
    float2 corners[4] = {
        float2(trail_x_coords[0], trail_y_coords[0]),
        float2(trail_x_coords[1], trail_y_coords[1]),
        float2(trail_x_coords[2], trail_y_coords[2]),
        float2(trail_x_coords[3], trail_y_coords[3])
    };
    // The vertex shader draws a GL_TRIANGLE_FAN, not an arbitrary convex
    // polygon. The two triangles are the exact rasterized primitive and also
    // handle the concave/degenerate quads produced by disconnected trails.
    return max(triangle_coverage(p, corners[0], corners[1], corners[2]),
               triangle_coverage(p, corners[0], corners[2], corners[3]));
}

float
distance_to_target_cursor(float2 p, uniform float2 cursor_edge_x, uniform float2 cursor_edge_y, uniform float2 trail_pixel_size) {
    float2 target_min = float2(cursor_edge_x[0], cursor_edge_y[1]);
    float2 target_max = float2(cursor_edge_x[1], cursor_edge_y[0]);
    float2 delta = max(max(target_min - p, p - target_max), float2(0.0, 0.0));
    return length(delta / trail_pixel_size);
}

[shader("fragment")]
float4
fragment_main(
    float2 frag_pos: TEXCOORD,
    uniform float4 trail_x_coords,
    uniform float4 trail_y_coords,
    uniform float2 cursor_edge_x,
    uniform float2 cursor_edge_y,
    uniform float3 trail_color,
    uniform float trail_opacity,
    uniform bool motion_blur_enabled_fragment,
    uniform bool antialiasing_enabled_fragment,
    uniform float target_blend_exposure,
    uniform float target_blend_start_radius,
    uniform float target_blend_end_radius,
    uniform float target_cursor_opacity,
    uniform int subpixel_samples,
    uniform float2 trail_pixel_size,
    float4 frag_coord: SV_Position
): SV_Target {
    // The vertex shader expands the rasterized quad by one pixel when AA is
    // enabled. Use the actual fragment coordinate rather than the interpolated
    // unexpanded position so subpixel samples remain in screen space at the
    // expanded boundary.
    float2 screen_frag_pos = float2(frag_coord.x * trail_pixel_size.x - 1.0,
                                    frag_coord.y * trail_pixel_size.y - 1.0);
    if (!motion_blur_enabled_fragment && !antialiasing_enabled_fragment) {
        float opacity = trail_opacity;
        float in_x = step(cursor_edge_x[0], frag_pos.x) * step(frag_pos.x, cursor_edge_x[1]);
        float in_y = step(cursor_edge_y[1], frag_pos.y) * step(frag_pos.y, cursor_edge_y[0]);
        opacity *= 1.0 - in_x * in_y;
        return float4(trail_color * opacity, opacity);
    }

    float coverage = 0.0;
    if (antialiasing_enabled_fragment) {
        int grid_size = int(ceil(sqrt(float(subpixel_samples))));
        for (int i = 0; i < 256; i++) {
            if (i >= subpixel_samples) break;
            int grid_x = i % grid_size;
            int grid_y = i / grid_size;
            float2 offset = (float2(float(grid_x) + 0.5, float(grid_y) + 0.5) / float(grid_size) - 0.5) * trail_pixel_size;
            float2 sample_pos = screen_frag_pos + offset;
            if (target_cursor_opacity > 0.0) {
                float in_target_x = step(cursor_edge_x[0], sample_pos.x) * step(sample_pos.x, cursor_edge_x[1]);
                float in_target_y = step(cursor_edge_y[1], sample_pos.y) * step(sample_pos.y, cursor_edge_y[0]);
                if (in_target_x * in_target_y > 0.5) continue;
            }
            // Each sample is a point sample inside this pixel. Accumulating
            // the binary coverage gives actual supersampling; using smoothstep
            // here would blur every sample again and make the result dependent
            // on the rasterizer's quad derivatives.
            coverage += trail_coverage(sample_pos, trail_x_coords, trail_y_coords);
        }
        coverage /= float(subpixel_samples);
    } else {
        float in_target = 0.0;
        if (target_cursor_opacity > 0.0) {
            float in_x = step(cursor_edge_x[0], frag_pos.x) * step(frag_pos.x, cursor_edge_x[1]);
            float in_y = step(cursor_edge_y[1], frag_pos.y) * step(frag_pos.y, cursor_edge_y[0]);
            in_target = in_x * in_y;
        }
        coverage = 1.0 - in_target;
    }

    float target_blend = 0.0;
    if (target_blend_start_radius > target_blend_end_radius) {
        float radial_distance = distance_to_target_cursor(screen_frag_pos, cursor_edge_x, cursor_edge_y, trail_pixel_size);
        target_blend = 1.0 - smoothstep(target_blend_end_radius, target_blend_start_radius, radial_distance);
    }
    float opacity = trail_opacity * (1.0 + target_blend * target_blend_exposure) * coverage;
    return float4(trail_color * opacity, opacity);
}
