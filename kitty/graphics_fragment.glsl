#version GLSL_VERSION
#define ALPHA_TYPE

uniform sampler2D image;
uniform float inactive_text_alpha;

in vec2 texcoord;
out vec4 color;

void main() {
    color = texture(image, texcoord);
    color.a *= inactive_text_alpha;
#ifdef PREMULT
    color = vec4(color.rgb * color.a, color.a);
#endif
}
