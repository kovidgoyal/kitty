#version GLSL_VERSION
#define ALPHA_TYPE

uniform sampler2D image;
#ifdef ALPHA_MASK
uniform uint fg;
uniform float alpha_mask_premult;
#else
uniform float inactive_text_alpha;
#endif

in vec2 texcoord;
out vec4 color;

#ifdef ALPHA_MASK
const uint BYTE_MASK = uint(0xFF);

vec3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return vec3(float(r) / 255.0, float(g) / 255.0, float(b) / 255.0);
}
#endif


void main() {
    color = texture(image, texcoord);
#ifdef ALPHA_MASK
    color = vec4(color_to_vec(fg), color.r);
    color = mix(color, vec4(color.rgb * color.a, color.a), alpha_mask_premult);
#else
    color.a *= inactive_text_alpha;
#ifdef PREMULT
    color = vec4(color.rgb * color.a, color.a);
#endif
#endif
}
