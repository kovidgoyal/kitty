#pragma kitty_include_shader <alpha_blend.glsl>
#pragma kitty_include_shader <utils.glsl>

in vec2 dimensions;
out vec4 output_color;

uniform vec4 resolution_and_params;
uniform vec4 color;
uniform vec4 background_color;
uniform vec2 origin;

float rounded_rectangle_sdf(vec2 position, vec2 size, float radius) {
    // signed distance field
    size *= 0.5;  // we work with a quadrant at a time
    radius = min(radius, min(size.x, size.y));  // radius must be no larger than size
    // Calculate distance vector from point to rectangle boundaries
    vec2 q = abs(position) - (size - vec2(radius));
    // Distance calculation
    // 1. For points outside the rectangle (including corners): Euclidean distance to corner circle
    // 2. For points along the edges: Perpendicular distance to the edge
    // 3. For points inside: Negative distance to nearest edge
    return length(max(q, 0.0)) + min(max(q.x, q.y), 0.0) - radius;
}

void main() {
    // Calculate normalized coordinates [-1, 1]
    vec2 position = 2.0 * gl_FragCoord.xy / resolution_and_params.xy;
    position = vec2(position.x - 1.0, 1.0 - position.y);
    position -= origin;  // shift origin
    vec2 size = vec2(2, 2);  // we are drawing in the full viewport

    float thickness = resolution_and_params[2];
    float corner_radius = resolution_and_params[3];

    // Adjust co-ordinates to account for the aspect ratio of the screen
    float aspect_ratio = resolution_and_params.x / resolution_and_params.y;
    size.x *= aspect_ratio; position.x *= aspect_ratio;

    // Calculate distance to rounded rectangle
    float dist = rounded_rectangle_sdf(position, size, corner_radius);

    // The border is outer - inner rects
    float outer_edge = -dist;
    float inner_edge = outer_edge - thickness;

    // Smooth borders (anti-alias)
    const float step_size = 0.005;
    float alpha = smoothstep(-step_size, step_size, outer_edge) - smoothstep(-step_size, step_size, inner_edge);
    vec4 ans = color;
    ans.a *= alpha;

    // pre-multiplied output
    output_color = alpha_blend(ans, background_color);
}
