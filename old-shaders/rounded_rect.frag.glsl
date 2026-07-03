#version 140



#line 0 7893003
vec4 alpha_blend(vec4 over, vec4 under) {
    // Alpha blend two colors returning the resulting color pre-multiplied by its alpha
    // and its alpha.
    // See https://en.wikipedia.org/wiki/Alpha_compositing
    float alpha = mix(under.a, 1.0f, over.a);
    vec3 combined_color = mix(under.rgb * under.a, over.rgb, over.a);
    return vec4(combined_color, alpha);
}

vec4 alpha_blend_premul(vec4 over, vec4 under) {
    // Same as alpha_blend() except that it assumes over and under are both premultiplied.
    float inv_over_alpha = 1.0f - over.a;
    float alpha = over.a + under.a * inv_over_alpha;
    return vec4(over.rgb + under.rgb * inv_over_alpha, alpha);
}

vec4 alpha_blend_premul(vec4 over, vec3 under) {
    // same as alpha_blend_premul with under_alpha = 1 outputs a blended color
    // with alpha 1 which is effectively pre-multiplied since alpha is 1
    float inv_over_alpha = 1.0f - over.a;
    return vec4(over.rgb + under.rgb * inv_over_alpha, 1.0);
}



#line 0 7893002




#line 0 7893004
// Return 0 if x < 1 otherwise 1
#define zero_or_one(x) step(1.f, x)
// condition must be zero or one. When 1 thenval is returned otherwise elseval
#define if_one_then(condition, thenval, elseval) mix(elseval, thenval, condition)
// a < b ? thenval : elseval
#define if_less_than(a, b, thenval, elseval) mix(thenval, elseval, step(b, a))

vec4 vec4_premul(vec3 rgb, float a) {
    return vec4(rgb * a, a);
}

vec4 vec4_premul(vec4 rgba) {
    return vec4(rgba.rgb * rgba.a, rgba.a);
}



#line 1 7893002


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
