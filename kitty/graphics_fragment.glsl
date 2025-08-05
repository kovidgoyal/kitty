#pragma kitty_include_shader <alpha_blend.glsl>
#pragma kitty_include_shader <utils.glsl>
#define ALPHA_TYPE

uniform sampler2D image;
#ifdef ALPHA_MASK
uniform vec3 amask_fg;
uniform vec4 amask_bg_premult;
#else
uniform float inactive_text_alpha;
#endif

in vec2 texcoord;
out vec4 output_color;

void main() {
    vec4 color = texture(image, texcoord);
#ifdef ALPHA_MASK
    color = vec4(amask_fg, color.r);
    color = vec4_premul(color);
    color = alpha_blend_premul(color, amask_bg_premult);
#else
    color.a *= inactive_text_alpha;
    color = vec4_premul(color);
#endif
    output_color = color;
}
