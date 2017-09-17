#version GLSL_VERSION
uniform vec4 pos;

const uvec2 pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);

void main() {
    vec2 xpos = vec2(pos[0], pos[2]);
    vec2 ypos = vec2(pos[1], pos[3]);
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(xpos[pos[0]], ypos[pos[1]], 0, 1);
}


