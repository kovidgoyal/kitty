#version 330

layout(location=0) in vec4 src;
layout(location=1) in vec4 position;
out vec2 texcoord;

const uint LEFT = uint(0), TOP = uint(1), RIGHT = uint(2), BOTTOM = uint(3);

const uvec2 pos_map[] = uvec2[4](
    uvec2(RIGHT, TOP),  
    uvec2(RIGHT, BOTTOM),  
    uvec2(LEFT, BOTTOM),  
    uvec2(LEFT, TOP)   
);


void main() {
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(position[pos.x], position[pos.y], 0, 1);
    texcoord = vec2(src[pos.x], src[pos.y]);
}
