#version GLSL_VERSION
#define {WHICH_PROGRAM}
#define NOT_TRANSPARENT

#if defined(SIMPLE) || defined(BACKGROUND) || defined(SPECIAL)
#define NEEDS_BACKROUND
#endif

#if defined(SIMPLE) || defined(FOREGROUND)
#define NEEDS_FOREGROUND
#endif

#ifdef NEEDS_BACKROUND
in vec3 background;
in float draw_bg;
#if defined(TRANSPARENT) || defined(SPECIAL)
in float bg_alpha;
#endif
#endif

#ifdef NEEDS_FOREGROUND
uniform sampler2DArray sprites;
uniform int text_old_gamma;
uniform float text_contrast;
uniform float text_gamma_adjustment;
in float effective_text_alpha;
in vec3 sprite_pos;
in vec3 underline_pos;
in vec3 cursor_pos;
in vec3 strike_pos;
in vec3 foreground;
in vec4 cursor_color_vec;
in vec3 decoration_fg;
in float colored_sprite;
#endif

out vec4 final_color;

// Util functions {{{
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

vec4 vec4_premul(vec3 rgb, float a) {
    return vec4(rgb * a, a);
}

vec4 vec4_premul(vec4 rgba) {
    return vec4(rgba.rgb * rgba.a, rgba.a);
}
// }}}


/*
 * Explanation of rendering:
 * There are a couple of cases, in order of increasing complexity:
 * 1) Simple -- this path is used when there are either no images, or all images are
 *    drawn on top of text and the background is opaque. In this case, there is a single pass,
 *    of this shader with cell foreground and background colors blended directly.
 *    Expected output is a color premultiplied by alpha, with an alpha specified as well.
 *
 * 2) Interleaved -- this path is used if background is not opaque and there are images or
 *    if the background is opaque but there are images under text. Rendering happens in
 *    multiple passes drawing the background and foreground separately and blending.
 *
 *    2a) Opaque bg with images under text
 *        There are multiple passes, each pass is blended onto the previous using the opaque blend func (alpha, 1- alpha):
 *        1) Draw background for all cells
 *        2) Draw the images that are supposed to be below both the background and text, if any. This happens in the graphics shader
 *        3) Draw the background of cells that don't have the default background if any images were drawn in 2 above
 *        4) Draw the images that are supposed to be below text but not background, again in graphics shader.
 *        5) Draw the special cells (selection/cursor). Output is same as from step 1, with bg_alpha 1 for special cells and 0 otherwise
 *        6) Draw the foreground -- expected output is color with alpha premultiplied which is blended using the premult blend func
 *        7) Draw the images that are supposed to be above text again in the graphics shader
 *
 *    2b) Transparent bg with images
 *        First everything is rendered into a framebuffer, and then the framebuffer is blended onto
 *        the screen. The framebuffer is needed because it allows access to the background color pixels
 *        to blend with the image pixels. The steps are basically the same as for 2a.
 *
 *  In this shader exactly *one* of SIMPLE, SPECIAL, FOREGROUND or BACKGROUND will be defined, corresponding
 *  to the appropriate rendering pass from above.
 */
#ifdef NEEDS_FOREGROUND
// sRGB luminance values
const vec3 Y = vec3(0.2126, 0.7152, 0.0722);
const float gamma_factor = 2.2;
// Scaling factor for the extra text-alpha adjustment for luminance-difference.
const float text_gamma_scaling = 0.5;

float linear2srgb(float x) {
    // Approximation of linear-to-sRGB conversion
    return pow(x, 1.0 / gamma_factor);
}

float srgb2linear(float x) {
    // Approximation of sRGB-to-linear conversion
    return pow(x, gamma_factor);
}

float clamp_to_unit_float(float x) {
    // Clamp value to suitable output range
    return clamp(x, 0.0f, 1.0f);
}

vec4 foreground_contrast(vec4 over, vec3 under) {
    float underL = dot(under, Y);
    float overL = dot(over.rgb, Y);
    // Apply additional gamma-adjustment scaled by the luminance difference, the darker the foreground the more adjustment we apply.
    // A multiplicative contrast is also available to increase saturation.
    over.a = clamp_to_unit_float(mix(over.a, pow(over.a, text_gamma_adjustment), (1 - overL + underL) * text_gamma_scaling) * text_contrast);
    return over;
}

vec4 foreground_contrast_incorrect(vec4 over, vec3 under) {
    // Simulation of gamma-incorrect blending
    float underL = dot(under, Y);
    float overL = dot(over.rgb, Y);
    // This is the original gamma-incorrect rendering, it is the solution of the following equation:
    //
    // linear2srgb(over * overA2 + under * (1 - overA2)) = linear2srgb(over) * over.a + linear2srgb(under) * (1 - over.a)
    // ^ gamma correct blending with new alpha             ^ gamma incorrect blending with old alpha
    over.a = clamp_to_unit_float((srgb2linear(linear2srgb(overL) * over.a + linear2srgb(underL) * (1.0f - over.a)) - underL) / (overL - underL));
    return over;
}

vec4 foreground_color() {
    vec4 text_fg = texture(sprites, sprite_pos);
    return vec4(mix(foreground, text_fg.rgb, colored_sprite), text_fg.a);
}

vec4 foreground_with_decorations(vec4 text_fg) {
    float underline_alpha = texture(sprites, underline_pos).a;
    float strike_alpha = texture(sprites, strike_pos).a;
    float cursor_alpha = texture(sprites, cursor_pos).a;
    // Since strike and text are the same color, we simply add the alpha values
    float combined_alpha = min(text_fg.a + strike_alpha, 1.0f);
    // Underline color might be different, so alpha blend
    vec4 ans = alpha_blend(vec4(text_fg.rgb, combined_alpha * effective_text_alpha), vec4(decoration_fg, underline_alpha * effective_text_alpha));
    return mix(ans, cursor_color_vec, cursor_alpha);
}

vec4 calculate_foreground() {
    // returns the effective foreground color in pre-multiplied form
    vec4 text_fg = foreground_color();
    return foreground_with_decorations(text_fg);
}
vec4 calculate_foreground(vec3 bg) {
    // When rendering on a background we can adjust the alpha channel contrast
    // to improve legibility based on the source and destination colors
    vec4 text_fg = foreground_color();
    text_fg = mix(foreground_contrast(text_fg, bg), foreground_contrast_incorrect(text_fg, bg), text_old_gamma);
    return foreground_with_decorations(text_fg);
}

#endif

void main() {
#ifdef SIMPLE
    vec4 fg = calculate_foreground(background);
#ifdef TRANSPARENT
    final_color = alpha_blend_premul(fg, vec4_premul(background, bg_alpha));
#else
    final_color = alpha_blend_premul(fg, background);
#endif
#endif

#ifdef SPECIAL
#ifdef TRANSPARENT
    final_color = vec4_premul(background, bg_alpha);
#else
    final_color = vec4(background, bg_alpha);
#endif
#endif

#ifdef BACKGROUND
#if defined(TRANSPARENT)
    final_color = vec4_premul(background, bg_alpha);
#else
    final_color = vec4(background, draw_bg);
#endif
#endif

#ifdef FOREGROUND
    final_color = calculate_foreground();  // pre-multiplied foreground
#endif

}
