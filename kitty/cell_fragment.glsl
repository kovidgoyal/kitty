#pragma kitty_include_shader <alpha_blend.glsl>
#pragma kitty_include_shader <linear2srgb.glsl>
#pragma kitty_include_shader <cell_defines.glsl>

uniform sampler2DArray sprites;
uniform float text_contrast;
uniform float text_gamma_adjustment;

in vec3 background;
in float bg_alpha;
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

out vec4 output_color;

// Util functions {{{
vec4 vec4_premul(vec3 rgb, float a) {
    return vec4(rgb * a, a);
}

vec4 vec4_premul(vec4 rgba) {
    return vec4(rgba.rgb * rgba.a, rgba.a);
}
// }}}


// Scaling factor for the extra text-alpha adjustment for luminance-difference.
const float text_gamma_scaling = 0.5;

float clamp_to_unit_float(float x) {
    // Clamp value to suitable output range
    return clamp(x, 0.0f, 1.0f);
}

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


float adjust_alpha_for_incorrect_blending_by_compositor(float text_fg_alpha, float final_alpha) {
    // Adjust the transparent alpha-channel to account for incorrect
    // gamma-blending performed by the compositor (true for at least wlroots, picom)
    // We have a linear alpha channel apply the sRGB curve to it once again to compensate
    // for the incorrect blending in the compositor.
    // We apply the correction only if there was actual text at this pixel, so as to not make
    // background_opacity non-linear
    // See https://github.com/kovidgoyal/kitty/issues/6209 for discussion.
    // ans = text_fg_alpha * linear2srgb(final_alpha) + (1 - text_fg_alpha) * final_alpha
    return mix(final_alpha, linear2srgb(final_alpha), text_fg_alpha);
}

void main() {
    vec4 final_color;
    vec4 text_fg = load_text_foreground_color();
    text_fg = adjust_foreground_contrast_with_background(text_fg, background);
    vec4 text_fg_premul = calculate_premul_foreground_from_sprites(text_fg);
    final_color = alpha_blend_premul(text_fg_premul, vec4_premul(background, bg_alpha));
    final_color.a = adjust_alpha_for_incorrect_blending_by_compositor(text_fg_premul.a, final_color.a);
    output_color = final_color;
}
