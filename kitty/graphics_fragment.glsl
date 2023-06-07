#version GLSL_VERSION
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

#ifdef ALPHA_MASK
vec4 alpha_blend_premul(vec4 over, vec4 under) {
    // Same as alpha_blend() except that it assumes over and under are both premultiplied.
    float inv_over_alpha = 1.0f - over.a;
    float alpha = over.a + under.a * inv_over_alpha;
    return vec4(over.rgb + under.rgb * inv_over_alpha, alpha);
}
#endif

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
