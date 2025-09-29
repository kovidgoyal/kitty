#pragma kitty_include_shader <alpha_blend.glsl>
#pragma kitty_include_shader <utils.glsl>

uniform sampler2D image;
uniform vec4 background;
in vec2 texcoord;
out vec4 color;

void main() {
    color = texture(image, texcoord);
    float alpha = color.a * background.a;
    vec4 premult_color = vec4_premul(color.rgb, alpha);
    color = vec4(color.rgb, alpha);
    color = alpha_blend(color, premult_color);
}
