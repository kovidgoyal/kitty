float srgb2linear(float x) {
    // sRGB to linear conversion
    float lower = x / 12.92;
    float upper = pow((x + 0.055f) / 1.055f, 2.4f);

    return mix(lower, upper, step(0.04045f, x));
}

float linear2srgb(float x) {
    // Linear to sRGB conversion.
    float lower = 12.92 * x;
    float upper = 1.055 * pow(x, 1.0f / 2.4f) - 0.055f;

    return mix(lower, upper, step(0.0031308f, x));
}

vec3 linear2srgb(vec3 x) {
    vec3 lower = 12.92 * x;
    vec3 upper = 1.055 * pow(x, vec3(1.0f / 2.4f)) - 0.055f;
    return mix(lower, upper, step(0.0031308f, x));
}

vec3 srgb2linear(vec3 c) {
    return vec3(srgb2linear(c.r), srgb2linear(c.g), srgb2linear(c.b));
}
