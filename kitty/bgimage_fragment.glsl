#pragma kitty_include_shader <alpha_blend.glsl>

uniform sampler2D image;
uniform vec4 background;
in vec2 texcoord;
out vec4 premult_color;

void main() {
    vec4 color = texture(image, texcoord);
    premult_color = alpha_blend(color, background);
}
