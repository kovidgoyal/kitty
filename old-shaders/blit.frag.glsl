#version 140



#line 0 7893004
vec4 alpha_blend(vec4 over, vec4 under) {
    // Alpha blend two colors returning the resulting color pre-multiplied by its alpha
    // and its alpha.
    // See https://en.wikipedia.org/wiki/Alpha_compositing
    float alpha = mix(under.a, 1.0f, over.a);
    vec3 combined_color = mix(under.rgb * under.a, over.rgb, over.a);
    return vec4(combined_color, alpha);
}

vec4 alpha_blend_premul(vec4 over, vec4 under) {
    // Same as alpha_blend() except that it assumes over and under are both premultiplied.
    float inv_over_alpha = 1.0f - over.a;
    float alpha = over.a + under.a * inv_over_alpha;
    return vec4(over.rgb + under.rgb * inv_over_alpha, alpha);
}

vec4 alpha_blend_premul(vec4 over, vec3 under) {
    // same as alpha_blend_premul with under_alpha = 1 outputs a blended color
    // with alpha 1 which is effectively pre-multiplied since alpha is 1
    float inv_over_alpha = 1.0f - over.a;
    return vec4(over.rgb + under.rgb * inv_over_alpha, 1.0);
}



#line 0 7893003




#line 0 7893005
// Return 0 if x < 1 otherwise 1
#define zero_or_one(x) step(1.f, x)
// condition must be zero or one. When 1 thenval is returned otherwise elseval
#define if_one_then(condition, thenval, elseval) mix(elseval, thenval, condition)
// a < b ? thenval : elseval
#define if_less_than(a, b, thenval, elseval) mix(thenval, elseval, step(b, a))

vec4 vec4_premul(vec3 rgb, float a) {
    return vec4(rgb * a, a);
}

vec4 vec4_premul(vec4 rgba) {
    return vec4(rgba.rgb * rgba.a, rgba.a);
}



#line 1 7893003




#line 0 7893006
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



#line 2 7893003


uniform sampler2D image;

in vec2 texcoord;
out vec4 output_color;

void main() {
    vec4 color_premul = texture(image, texcoord);
    output_color = vec4_premul(linear2srgb(color_premul.rgb / color_premul.a), color_premul.a);
}
