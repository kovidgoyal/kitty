uniform uvec2 viewport;
uniform uint colors[9];
uniform float background_opacity;
uniform float tint_opacity, tint_premult;
uniform float gamma_lut[256];
in vec4 rect;  // left, top, right, bottom
in uint rect_color;
out vec4 color;

// indices into the rect vector
const int LEFT = 0;
const int TOP = 1;
const int RIGHT = 2;
const int BOTTOM = 3;
const uint FF = uint(0xff);

const uvec2 pos_map[] = uvec2[4](
    uvec2(RIGHT, TOP),
    uvec2(RIGHT, BOTTOM),
    uvec2(LEFT, BOTTOM),
    uvec2(LEFT, TOP)
);

float to_color(uint c) {
    return gamma_lut[c & FF];
}

float is_integer_value(uint c, float x) {
    return 1. - step(0.5, abs(float(c) - x));
}

vec3 as_color_vector(uint c, int shift) {
    return vec3(to_color(c >> shift), to_color(c >> (shift - 8)), to_color(c >> (shift - 16)));
}

void main() {
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(rect[pos.x], rect[pos.y], 0, 1);
    vec3 window_bg = as_color_vector(rect_color, 24);
    uint rc = rect_color & FF;
    vec3 color3 = as_color_vector(colors[rc], 16);
    float is_window_bg = is_integer_value(rc, 3.);
    float is_default_bg = is_integer_value(rc, 0.);
    color3 = is_window_bg * window_bg + (1. - is_window_bg) * color3;
    // Border must be always drawn opaque
    float is_border_bg = 1. - step(0.5, abs((float(rc) - 2.) * (float(rc) - 1.) * (float(rc) - 4.))); // 1 if rc in (1, 2, 4) else 0
    float final_opacity = is_default_bg * tint_opacity + (1. - is_default_bg) * background_opacity;
    final_opacity = is_border_bg + (1. - is_border_bg) * final_opacity;
    float final_premult_opacity = is_default_bg * tint_premult + (1. - is_default_bg) * background_opacity;
    final_premult_opacity = is_border_bg + (1. - is_border_bg) * final_premult_opacity;
    color = vec4(color3 * final_premult_opacity, final_opacity);
}
