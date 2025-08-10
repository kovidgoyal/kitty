#pragma kitty_include_shader <alpha_blend.glsl>
#pragma kitty_include_shader <utils.glsl>
#pragma kitty_include_shader <linear2srgb.glsl>

uniform sampler2D image;

in vec2 texcoord;
out vec4 output_color;

void main() {
    vec4 color_premul = texture(image, texcoord);
    output_color = vec4_premul(linear2srgb(color_premul.rgb / color_premul.a), color_premul.a);
}
