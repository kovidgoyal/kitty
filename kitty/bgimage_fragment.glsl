
uniform sampler2D image;
uniform float opacity;
uniform float premult;
in vec2 texcoord;
out vec4 color;

void main() {
    color = texture(image, texcoord);
    float alpha = color.a * opacity;
    vec4 premult_color = vec4(color.rgb * alpha, alpha);
    color = vec4(color.rgb, alpha);
    color = premult * premult_color + (1 - premult) * color;
}
