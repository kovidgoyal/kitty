#version GLSL_VERSION
uniform float background_opacity;
in vec3 color;
out vec4 final_color;

void main() {
    final_color = vec4(color * background_opacity, background_opacity);
}
