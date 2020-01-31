#version GLSL_VERSION
#define left  -1.0f
#define top  1.0f
#define right  1.0f
#define bottom  -1.0f

out vec2 texcoord;

const vec2 pos_map[] = vec2[4](
    vec2(left, top),
    vec2(left, bottom),
    vec2(right, bottom),
    vec2(right, top)
);


void main() {
    vec2 vertex = pos_map[gl_VertexID];
    texcoord = clamp(vec2(vertex[0], vertex[1]*-1), 0, 1);
    gl_Position = vec4(vertex, 0, 1);
}
