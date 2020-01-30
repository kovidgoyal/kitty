#version GLSL_VERSION

layout(location=0) in vec4 src;
out vec2 texcoord;

void main() {
    texcoord = clamp(vec2(src[0], src[1]*-1), 0, 1);
    gl_Position = src;
}
