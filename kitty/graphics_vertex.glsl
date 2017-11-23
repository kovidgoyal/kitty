#version GLSL_VERSION

// Have to use fixed locations here as all variants of the program share the same VAO
layout(location=0) in vec4 src;
out vec2 texcoord;

void main() {
    texcoord = vec2(src[0], src[1]);
    gl_Position = vec4(src[2], src[3], 0, 1);
}
