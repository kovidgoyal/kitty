#pragma kitty_include_shader <alpha_blend.glsl>
#define ALPHA_TYPE

uniform sampler2D image;
#ifdef ALPHA_MASK
uniform vec3 amask_fg;
uniform vec4 amask_bg_premult;
#else
uniform float inactive_text_alpha;
#endif

in vec2 texcoord;
out vec4 color;

void main() {
    color = texture(image, texcoord);
#ifdef ALPHA_MASK
    color = vec4(amask_fg, color.r);
    color = vec4(color.rgb * color.a, color.a);
    color = alpha_blend_premul(color, amask_bg_premult);
#else
    color.a *= inactive_text_alpha;
#ifdef PREMULT
    color = vec4(color.rgb * color.a, color.a);
#endif
#endif
}
