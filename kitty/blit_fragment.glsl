#version GLSL_VERSION

uniform sampler2D image;

in vec2 texcoord;
out vec4 color;

float linear2srgb(float x) {
    // Linear to sRGB conversion.
    float lower = 12.92 * x;
    float upper = 1.055 * pow(x, 1.0f / 2.4f) - 0.055f;

    return mix(lower, upper, step(0.0031308f, x));
}


void main() {
    color = texture(image, texcoord);
    color.a = linear2srgb(color.a);
}
