#pragma kitty_include_shader <utils.glsl>

#define DEFAULT_BG 0
#define ACTIVE_BORDER_COLOR 1
#define INACTIVE_BORDER_COLOR 2
#define WINDOW_BACKGROUND_PLACEHOLDER 3
#define BELL_BORDER_COLOR 4
#define TAB_BAR_BG_COLOR 5
#define TAB_BAR_MARGIN_COLOR 6
#define TAB_BAR_EDGE_LEFT_COLOR 7
#define TAB_BAR_EDGE_RIGHT_COLOR 8
uniform uint colors[9];
uniform float background_opacity;
uniform float gamma_lut[256];

in vec4 rect;  // left, top, right, bottom
in uint rect_color;
out vec4 color_premul;

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

float is_integer_value(uint c, int x) {
    return 1. - step(0.5, abs(float(c) - float(x)));
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
    float is_window_bg = is_integer_value(rc, WINDOW_BACKGROUND_PLACEHOLDER); // used by window padding areas
    float is_default_bg = is_integer_value(rc, DEFAULT_BG);
    color3 = if_one_then(is_window_bg, window_bg, color3);
    // Actual border quads must be always drawn opaque
    float is_not_a_border = zero_or_one(abs(
        (float(rc) - ACTIVE_BORDER_COLOR) * (float(rc) - INACTIVE_BORDER_COLOR) * (float(rc) - BELL_BORDER_COLOR)
    ));
    float final_opacity = if_one_then(is_not_a_border, background_opacity, 1.);
    color_premul = vec4_premul(color3, final_opacity);
}
