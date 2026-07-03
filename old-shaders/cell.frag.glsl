#version 140



#line 0 7893006
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



#line 0 7893005




#line 0 7893007
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



#line 1 7893005




#line 0 7893008
#define FG_OVERRIDE_ALGO 0
#define TEXT_NEW_GAMMA 1

#define DECORATION_SHIFT 0
#define REVERSE_SHIFT 5
#define STRIKE_SHIFT 6
#define DIM_SHIFT 7
#define BLINK_SHIFT 8
#define MARK_SHIFT 9
#define MARK_MASK 3
#define USE_SELECTION_FG
#define NUM_COLORS 256
#define COLOR_NOT_SET 0
#define COLOR_IS_SPECIAL 1
#define COLOR_IS_RGB 3
#define COLOR_IS_INDEX 2

#if 1 == 1
#define ONLY_BACKGROUND
#endif

#if 0 == 1
#define ONLY_FOREGROUND
#endif

#if FG_OVERRIDE_ALGO == 0
#define DO_FG_OVERRIDE 0
#else
#define DO_FG_OVERRIDE 1
#endif

// Linear space luminance values
const vec3 Y = vec3(0.2126, 0.7152, 0.0722);



#line 2 7893005




#line 0 7893009
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



#line 3 7893005


uniform float text_contrast;
uniform float text_gamma_adjustment;
uniform sampler2DArray sprites;

in vec3 background;
in vec4 effective_background_premul;
#ifndef ONLY_BACKGROUND
in float effective_text_alpha;
in vec3 sprite_pos;
in vec3 underline_pos;
in vec3 cursor_pos;
in vec3 strike_pos;
flat in uint underline_exclusion_pos;
in vec3 cell_foreground;
in vec4 cursor_color_premult;
in vec3 decoration_fg;
in float colored_sprite;
#endif

out vec4 output_color;

// Scaling factor for the extra text-alpha adjustment for luminance-difference.
const float text_gamma_scaling = 0.5;

float clamp_to_unit_float(float x) {
    // Clamp value to suitable output range
    return clamp(x, 0.0f, 1.0f);
}

#ifndef ONLY_BACKGROUND
#if TEXT_NEW_GAMMA == 1
vec4 foreground_contrast(vec4 over, vec3 under) {
    float under_luminance = dot(under, Y);
    float over_lumininace = dot(over.rgb, Y);
    // Apply additional gamma-adjustment scaled by the luminance difference, the darker the foreground the more adjustment we apply.
    // A multiplicative contrast is also available to increase saturation.
    over.a = clamp_to_unit_float(mix(over.a, pow(over.a, text_gamma_adjustment), (1 - over_lumininace + under_luminance) * text_gamma_scaling) * text_contrast);
    return over;
}

#else

vec4 foreground_contrast(vec4 over, vec3 under) {
    // Simulation of gamma-incorrect blending
    float under_luminance = dot(under, Y);
    float over_lumininace = dot(over.rgb, Y);
    // This is the original gamma-incorrect rendering, it is the solution of the following equation:
    //
    // linear2srgb(over * overA2 + under * (1 - overA2)) = linear2srgb(over) * over.a + linear2srgb(under) * (1 - over.a)
    // ^ gamma correct blending with new alpha             ^ gamma incorrect blending with old alpha
    over.a = clamp_to_unit_float((srgb2linear(linear2srgb(over_lumininace) * over.a + linear2srgb(under_luminance) * (1.0f - over.a)) - under_luminance) / (over_lumininace - under_luminance));
    return over;
}
#endif

vec4 load_text_foreground_color() {
    // For colored sprites use the color from the sprite rather than the text foreground
    // Return non-premultiplied foreground color
    vec4 text_fg = texture(sprites, sprite_pos);
    return vec4(mix(cell_foreground, text_fg.rgb, colored_sprite), text_fg.a);
}

vec4 calculate_premul_foreground_from_sprites(vec4 text_fg) {
    // Return premul foreground color from decorations (cursor, underline, strikethrough)
    ivec3 sz = textureSize(sprites, 0);
    float underline_alpha = texture(sprites, underline_pos).a;
    float underline_exclusion = texelFetch(sprites, ivec3(int(
        sprite_pos.x * float(sz.x)), int(underline_exclusion_pos), int(sprite_pos.z)), 0).a;
    underline_alpha *= 1.0f - underline_exclusion;
    float strike_alpha = texture(sprites, strike_pos).a;
    float cursor_alpha = texture(sprites, cursor_pos).a;
    // Since strike and text are the same color, we simply add the alpha values
    float combined_alpha = min(text_fg.a + strike_alpha, 1.0f);
    // Underline color might be different, so alpha blend
    vec4 ans = alpha_blend(vec4(text_fg.rgb, combined_alpha * effective_text_alpha), vec4(decoration_fg, underline_alpha * effective_text_alpha));
    return mix(ans, cursor_color_premult, cursor_alpha * cursor_color_premult.a);
}

vec4 adjust_foreground_contrast_with_background(vec4 text_fg, vec3 bg) {
    // When rendering on a background we can adjust the alpha channel contrast
    // to improve legibility based on the source and destination colors
    return foreground_contrast(text_fg, bg);
}
#endif  // ifndef ONLY_BACKGROUND


void main() {
#ifdef ONLY_FOREGROUND
    vec4 ans_premul;
#else
    vec4 ans_premul = effective_background_premul;
#endif

#ifndef ONLY_BACKGROUND
    // blend in the foreground color
    vec4 text_fg = load_text_foreground_color();
    text_fg = adjust_foreground_contrast_with_background(text_fg, background);
    vec4 text_fg_premul = calculate_premul_foreground_from_sprites(text_fg);
#ifdef ONLY_FOREGROUND
    ans_premul = text_fg_premul;
#else
    ans_premul = alpha_blend_premul(text_fg_premul, ans_premul);
#endif
#endif  // ifndef ONLY_BACKGROUND
    output_color = ans_premul;
}
