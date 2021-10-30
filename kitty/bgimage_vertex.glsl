#version GLSL_VERSION
#define left  -1.0f
#define top  1.0f
#define right  1.0f
#define bottom  -1.0f
#define tex_left 0
#define tex_top 0
#define tex_right 1
#define tex_bottom 1

uniform float adjust_scale;
uniform vec2 transform;  // [ pos_left_relative, pos_top_relative ]
uniform vec4 sizes;  // [ window_width, window_height, image_width, image_height ]

out vec2 texcoord;

const vec2 pos_map[] = vec2[4](
    vec2(left, top),
    vec2(left, bottom),
    vec2(right, bottom),
    vec2(right, top)
);
const vec2 tex_map[] = vec2[4](
    vec2(tex_left, tex_top),
    vec2(tex_left, tex_bottom),
    vec2(tex_right, tex_bottom),
    vec2(tex_right, tex_top)
);


float scaling_factor(int i) {
    return adjust_scale * (sizes[i] / sizes[i + 2]) + (1 - adjust_scale);
}

float position_divisor(int i) {
    return (sizes[i] - sizes[i + 2]) * transform[i] / sizes[i + 2];
}

void main() {
    vec2 tex_coords = tex_map[gl_VertexID];
    texcoord = vec2(tex_coords[0] * scaling_factor(0) - position_divisor(0), tex_coords[1] * scaling_factor(1) - position_divisor(1));
    gl_Position = vec4(pos_map[gl_VertexID], 0, 1);
}
