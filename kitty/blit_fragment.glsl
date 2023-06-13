#pragma kitty_include_shader <linear2srgb.glsl>

uniform sampler2D image;

in vec2 texcoord;
out vec4 color;


void main() {
    color = texture(image, texcoord);
    color.a = linear2srgb(color.a);
}
