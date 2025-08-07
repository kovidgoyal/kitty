
uniform sampler2D image;
in vec2 texcoord;
out vec4 premult_color;

void main() {
    vec4 color = texture(image, texcoord);
    premult_color = vec4(color.rgb * color.a, color.a);
}
