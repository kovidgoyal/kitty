#version GLSL_VERSION
uniform vec3 color;
out vec4 final_color;

void main() {
    final_color = vec4(color, 1);
}
