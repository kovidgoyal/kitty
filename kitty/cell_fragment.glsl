#pragma kitty_include_shader <alpha_blend.glsl>
#pragma kitty_include_shader <linear2srgb.glsl>
#pragma kitty_include_shader <cell_defines.glsl>
#pragma kitty_include_shader <utils.glsl>

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
in vec3 foreground;
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
    return vec4(mix(foreground, text_fg.rgb, colored_sprite), text_fg.a);
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
