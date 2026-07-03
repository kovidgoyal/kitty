#version 140



#line 0 7893004
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



#line 0 7893003


uniform sampler2D image;
uniform vec2 src_size;  // Source texture size in pixels

in vec2 texcoord;
out vec4 output_color;

void main() {
    // The input texture contains sRGB colors with premultiplied alpha.
    // We need to output unpremultiplied sRGB colors with proper downscaling.

    // For proper downscaling, we need to:
    // 1. Sample neighboring pixels
    // 2. Convert from sRGB to linear (unpremultiplying first)
    // 3. Average in linear space
    // 4. Convert back to sRGB
    // 5. Output unpremultiplied

    // Calculate the texel size
    vec2 texel_size = 1.0 / src_size;

    // Sample a 2x2 grid for better quality downscaling
    // This provides basic bilinear-like filtering in linear space
    vec2 tc = texcoord;

    vec4 s00 = texture(image, tc + vec2(-0.25, -0.25) * texel_size);
    vec4 s10 = texture(image, tc + vec2( 0.25, -0.25) * texel_size);
    vec4 s01 = texture(image, tc + vec2(-0.25,  0.25) * texel_size);
    vec4 s11 = texture(image, tc + vec2( 0.25,  0.25) * texel_size);

    // Unpremultiply and convert to linear for each sample
    vec3 linear00 = s00.a > 0.0 ? srgb2linear(s00.rgb / s00.a) : vec3(0.0);
    vec3 linear10 = s10.a > 0.0 ? srgb2linear(s10.rgb / s10.a) : vec3(0.0);
    vec3 linear01 = s01.a > 0.0 ? srgb2linear(s01.rgb / s01.a) : vec3(0.0);
    vec3 linear11 = s11.a > 0.0 ? srgb2linear(s11.rgb / s11.a) : vec3(0.0);

    // Average the alpha values
    float avg_alpha = (s00.a + s10.a + s01.a + s11.a) * 0.25;

    // For proper downsampling with transparency, weight colors by their alpha
    // This ensures partially transparent pixels contribute proportionally
    vec3 weighted_sum = linear00 * s00.a + linear10 * s10.a + linear01 * s01.a + linear11 * s11.a;
    float total_weight = s00.a + s10.a + s01.a + s11.a;

    // Calculate the weighted average color in linear space
    vec3 avg_linear = total_weight > 0.0 ? weighted_sum / total_weight : vec3(0.0);

    // Convert back to sRGB
    vec3 srgb_color = linear2srgb(avg_linear);

    // Output unpremultiplied sRGB color
    output_color = vec4(srgb_color, avg_alpha);
}
