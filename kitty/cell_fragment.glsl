#version GLSL_VERSION
#define WHICH_PROGRAM
#define NOT_TRANSPARENT
#define NOT_SUBPIXEL

#if defined(SIMPLE) || defined(BACKGROUND) || defined(SPECIAL) || defined(SUBPIXEL)
#define NEEDS_BACKROUND
#endif

#if defined(SIMPLE) || defined(FOREGROUND)
#define NEEDS_FOREGROUND
#endif

#ifdef NEEDS_BACKROUND
in vec3 background;
#if defined(TRANSPARENT) || defined(SPECIAL)
in float bg_alpha;
#endif
#endif

#ifdef NEEDS_FOREGROUND
uniform sampler2DArray sprites;
in float effective_text_alpha;
in vec3 sprite_pos;
in vec3 underline_pos;
in vec3 cursor_pos;
in vec3 strike_pos;
in vec3 foreground;
in vec4 cursor_color_vec;
in vec3 decoration_fg;
in float colored_sprite;
in float subpixel;
#endif

out vec4 final_color;

// Util functions {{{
vec4 alpha_blend(vec3 over, float over_alpha, vec3 under, float under_alpha) {
    // Alpha blend two colors returning the resulting color pre-multiplied by its alpha
    // and its alpha.
    // See https://en.wikipedia.org/wiki/Alpha_compositing
    float alpha = mix(under_alpha, 1.0f, over_alpha);
    vec3 combined_color = mix(under * under_alpha, over, over_alpha);
    return vec4(combined_color, alpha);
}

vec3 premul_blend(vec3 over, float over_alpha, vec3 under) {
    return over + (1.0f - over_alpha) * under;
}

vec4 alpha_blend_premul(vec3 over, float over_alpha, vec3 under, float under_alpha) {
    // Same as alpha_blend() except that it assumes over and under are both premultiplied.
    float alpha = mix(under_alpha, 1.0f, over_alpha);
    return vec4(premul_blend(over, over_alpha, under), alpha);
}

vec4 blend_onto_opaque_premul(vec3 over, float over_alpha, vec3 under) {
    // same as alpha_blend_premul with under_alpha = 1 outputs a blended color
    // with alpha 1 which is effectively pre-multiplied since alpha is 1
    return vec4(premul_blend(over, over_alpha, under), 1.0);
}

float max3(vec3 v) {
    return max(max(v.r, v.g), v.b);
}

float rgb_to_grayscale(vec3 color) {
    return dot(vec3(0.3, 0.59, 0.11), color);
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
 *        1) Draw only the background -- expected output is color with alpha 1
 *        2) Draw the images that are supposed to be below text. This happens in the graphics shader
 *        3) Draw the special cells (selection/cursor). Output is same as from step 1, with bg_alpha 1 for special cells and 0 otherwise
 *        4) Draw the foreground -- expected output is color with alpha which is blended using the opaque blend func
 *        5) Draw the images that are supposed to be above text again in the graphics shader
 *
 *    2b) Transparent bg with images
 *        First everything is rendered into a framebuffer, and then the framebauffer is blended onto
 *        the screen. The framebuffer is needed because it allows access to the background color pixels
 *        to blend with the image pixels. The steps are basically the same as for 2a.
 *
 *  In this shader exactly *one* of SIMPLE, SPECIAL, FOREGROUND or BACKGROUND will be defined, corresponding
 *  to the appropriate rendering pass from above.
 */
#ifdef NEEDS_FOREGROUND
vec4 calculate_foreground() {
    // returns the effective foreground color in pre-multiplied form
    vec4 text_fg = texture(sprites, sprite_pos);
#ifdef SUBPIXEL
    vec3 unblended_fg = mix(foreground, text_fg.rgb, colored_sprite);
#ifdef TRANSPARENT
    // According to https://stackoverflow.com/questions/33507617/blending-text-rendered-by-freetype-in-color-and-alpha
    // it's impossible to precisely blend it if we use RGBA. Hence, the following hack is used.
    float alpha = rgb_to_grayscale(text_fg.rgb); // Grayscale looks much nicer than max3
    vec3 scaled_mask = mix(vec3(1.0), text_fg.rgb / alpha, bvec3(alpha > 0)); // TODO: May get not normalized values?
    vec3 blended_fg = mix(background * bg_alpha * bg_alpha, foreground, scaled_mask); // TODO: Check whether we should multiply by bg_alpha
    float text_alpha = mix(text_fg.a, alpha, subpixel);
#else
    vec3 blended_fg = mix(background, foreground, text_fg.rgb);
    float text_alpha = text_fg.a;
#endif
    vec3 fg = mix(unblended_fg, blended_fg, subpixel);
#else
    vec3 fg = mix(foreground, text_fg.rgb, colored_sprite);
    float text_alpha = text_fg.a;
#endif
    float underline_alpha = texture(sprites, underline_pos).a;
    float strike_alpha = texture(sprites, strike_pos).a;
    float cursor_alpha = texture(sprites, cursor_pos).a;
    // Since strike and text are the same color, we simply add the alpha values
    float combined_alpha = min(text_alpha + strike_alpha, 1.0f);
    // Underline color might be different, so alpha blend
    vec4 ans = alpha_blend(fg, combined_alpha * effective_text_alpha, decoration_fg, underline_alpha * effective_text_alpha);
    return mix(ans, cursor_color_vec, cursor_alpha);
}
#endif

void main() {
#ifdef SIMPLE
    vec4 fg = calculate_foreground();
#ifdef TRANSPARENT
    final_color = alpha_blend_premul(fg.rgb, fg.a, background.rgb * bg_alpha, bg_alpha);
#else
    final_color = blend_onto_opaque_premul(fg.rgb, fg.a, background.rgb);
#endif
#endif

#ifdef SPECIAL
#ifdef TRANSPARENT
    final_color = vec4(background.rgb * bg_alpha, bg_alpha);
#else
    final_color = vec4(background.rgb, bg_alpha);
#endif
#endif

#ifdef BACKGROUND
#ifdef TRANSPARENT
    final_color = vec4(background.rgb * bg_alpha, bg_alpha);
#else
    final_color = vec4(background.rgb, 1.0f);
#endif
#endif

#ifdef FOREGROUND
    vec4 fg = calculate_foreground();  // pre-multiplied foreground
#ifdef TRANSPARENT
    final_color = fg;
#else
    final_color = vec4(fg.rgb / fg.a, fg.a);
#endif

#endif

}
