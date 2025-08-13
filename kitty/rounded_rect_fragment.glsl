#pragma kitty_include_shader <alpha_blend.glsl>
#pragma kitty_include_shader <utils.glsl>

in vec2 dimensions;
out vec4 output_color;

uniform vec4 rect;
uniform vec2 params;
uniform vec4 color;
uniform vec4 background_color;

// Signed distance function for a rounded rectangle
float rounded_rectangle_sdf(vec2 p, vec2 b, float r) {
    // signed distance field
    // first term is used for points outside the rectangle
    vec2 q = abs(p) - b;
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - r;
}

void main() {
    vec2 size = rect.ba, origin = rect.xy;
    float thickness = params[0], corner_radius = params[1];
    // Position must be relative to the center of the rectangle of (size) located at (origin)
    vec2 position = gl_FragCoord.xy - size / 2.0 - origin;
    // Calculate distance to rounded rectangle
    float dist = rounded_rectangle_sdf(position, size*0.5 - corner_radius, corner_radius);

    // The below is for a filled rounded rect
    // float alpha = 1.0 - smoothstep(0.0, 1.0, dist);
    // vec4 ans = color; ans.a *= alpha;
    // output_color = alpha_blend(ans, background_color);

    // The border is outer - inner rects
    float outer_edge = -dist, inner_edge = outer_edge - thickness;
    // Smooth borders (anti-alias)
    const float step_size = 1.0;  // controls how blurred the aliasing causes the rect to be
    float alpha = smoothstep(-step_size, step_size, outer_edge) - smoothstep(-step_size, step_size, inner_edge);
    vec4 ans = color; ans.a *= alpha;
    // pre-multiplied output
    output_color = alpha_blend(ans, background_color);
}
