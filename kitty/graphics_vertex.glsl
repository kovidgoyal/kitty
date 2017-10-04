#version 330

layout(location=8) in vec4 src;
layout(location=9) in vec4 position;
out vec2 texcoord;

const uvec2 pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);


void main() {
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(position[pos.x], position[pos.y + uint(2)], 0, 1);
    texcoord = vec2(src[pos.x], src[pos.y + uint(2)]);
}
