#version GLSL_VERSION
#define LAYOUT_TYPE

uniform sampler2D image;
uniform float bgimage_opacity;
#ifdef TILED
uniform float bgimage_scale;

uniform float window_width;
uniform float window_height;
#endif
in vec2 texcoord;
out vec4 color;

void main() {
#ifdef TILED
    ivec2 image_size = textureSize(image, 0);
    vec2 txsz = vec2(window_width / (float(image_size[0]) * bgimage_scale), window_height / (float(image_size[1]) * bgimage_scale));
    color = texture(image, texcoord * txsz);
#endif
#ifdef SIMPLE
    color = texture(image, texcoord);
#endif
    color = vec4(color.rgb, color.a * bgimage_opacity);
}
