#version GLSL_VERSION

in vec4 src;
out vec2 texcoord;

void main() {
    texcoord = vec2(src[0], src[1]);
    gl_Position = vec4(src[2], src[3], 0, 1);
}
