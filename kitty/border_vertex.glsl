#version GLSL_VERSION
uniform uvec2 viewport;
uniform vec3 default_bg;
uniform vec3 active_border_color;
uniform vec3 inactive_border_color;
uniform vec3 bell_border_color;
in uvec4 rect;  // left, top, right, bottom
in uint rect_color;
out vec3 color;

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

vec2 to_opengl(uint x, uint y) {
    return vec2(
        -1.0 + 2.0 * (float(x) / float(viewport.x)),
        1.0 - 2.0 * (float(y) / float(viewport.y))
    );
}

float to_color(uint c) {
    return float(c & FF) / 255.0;
}

void main() {
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(to_opengl(rect[pos.x], rect[pos.y]), 0, 1);
    int rc = int(rect_color);
    vec3 window_bg = vec3(to_color(rect_color >> 24), to_color(rect_color >> 16), to_color(rect_color >> 8));
    color = float(1 & rc) * default_bg + float((2 & rc) >> 1) * active_border_color + float((4 & rc) >> 2) * inactive_border_color + float((8 & rc) >> 3) * window_bg + float((16 & rc) >> 4) * bell_border_color;
}
