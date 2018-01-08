#version GLSL_VERSION
#define left  -1.0f
#define top  1.0f
#define right  1.0f
#define bottom  -1.0f

const vec2 pos_map[] = vec2[4](
    vec2(right, top),
    vec2(right, bottom),
    vec2(left, bottom),
    vec2(left, top)
);

out vec2 texcoord;

void main() {
    vec2 vertex = pos_map[gl_VertexID];
    gl_Position = vec4(vertex, 0, 1);
    texcoord = (vertex + 1.0) / 2.0;
}
