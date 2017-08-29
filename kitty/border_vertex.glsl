#version GLSL_VERSION
uniform vec3 colors[3];
in vec3 rect;
out vec3 color;

void main() {
    gl_Position = vec4(rect[0], rect[1], 0, 1);
    color = colors[uint(rect[2])];
}
