#version GLSL_VERSION
#define LAYOUT_TYPE

uniform sampler2D image;
uniform float bgimage_opacity;
#ifdef TILED
uniform float bgimage_scale;

// These are of the window, not the screen.
uniform float width;
uniform float height;
#endif
in vec2 texcoord;
out vec4 color;

void main() {
#ifdef TILED
    vec2 txsz = vec2(width,height) / textureSize(image,0);
    txsz /= bgimage_scale;
    color = texture(image, texcoord * txsz);
#endif
#ifdef SIMPLE
    color = texture(image, texcoord);
#endif
    color = vec4(color.rgb, color.a * bgimage_opacity);
}
