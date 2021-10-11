#version GLSL_VERSION
uniform vec4 area_bounds;
uniform vec4 digit_color;
uniform int digit;
layout(origin_upper_left) in vec4 gl_FragCoord;

const float PI = 3.1415926535897932384626433832795;
const int s_map[] = int[10](182, 150, 78, 47, 104, 85, 16, 212, 15, 142);

mat2 rotate2D(in float a) {
    return mat2(cos(a), sin(a), -sin(a), cos(a));
}

float draw_number(int num, vec2 p) {
    // return 1 if this position should be colored and 0 if not
    int s = s_map[max(0, min(num, 9))];
    float scale = 0.3;
    float n = fract(sin(dot(ceil(p * rotate2D(PI / 4.) / sqrt(2.) / scale + 0.5 + float(s)), vec2(3., 5.))) * 50.);

    p.y = abs(p.y);
    p.y -= scale;
    p = abs(p);
    p = vec2(max(p.x, p.y), min(p.x, p.y));
    p.x -= scale;
    p.x = abs(p.x);
    float d = max(p.x + p.y - scale * 0.667, p.x);
    return step(d, scale * 0.267) * step(n, 0.5);
}

out vec4 color;

void main() {
    float left = area_bounds[0], top = area_bounds[1];
    vec2 resolution = vec2(area_bounds[2], area_bounds[3]);
    vec2 shifted_frag_pos = vec2(gl_FragCoord.x - left, gl_FragCoord.y - top);
    vec2 pos = (shifted_frag_pos * 2 - resolution) / min(resolution.x, resolution.y);
    pos.y *= -1;
    color = digit_color * draw_number(digit, pos);
}
