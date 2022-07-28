#version GLSL_VERSION
#define {WHICH_PROGRAM}
#define NOT_TRANSPARENT

#if defined(SIMPLE) || defined(BACKGROUND) || defined(SPECIAL)
#define NEEDS_BACKROUND
#endif

#if defined(SIMPLE) || defined(FOREGROUND)
#define NEEDS_FOREGROUND
#endif

// All non-texture inputs are already in linear colorspace from the vertex-shader

#ifdef NEEDS_BACKROUND
in vec3 background;
in float draw_bg;
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
#endif

out vec4 final_color;

// Util functions {{{
vec4 alpha_blend_premul(vec4 over, vec4 under) {
    // Alpha blend two colors returning the resulting color pre-multiplied by its alpha
    // and its alpha.
    // See https://en.wikipedia.org/wiki/Alpha_compositing
    float inv_over_alpha = 1.0f - over.a;
    float alpha = over.a + under.a * inv_over_alpha;

    return vec4(over.rgb + under.rgb * inv_over_alpha, alpha);
}

vec4 alpha_blend_premul(vec4 over, vec3 under) {
    float inv_over_alpha = 1.0f - over.a;

    return vec4(over.rgb + under.rgb * inv_over_alpha, 1.0);
}

vec4 vec4_premul(vec3 rgb, float a) {
    return vec4(rgb * a, a);
}

vec4 vec4_premul(vec4 rgba) {
    return vec4(rgba.rgb * rgba.a, rgba.a);
}

// sRGB gamma functions
vec3 from_linear(vec3 linear) {
    bvec3 cutoff = lessThan(linear, vec3(0.0031308));
    vec3 higher = vec3(1.055) * pow(linear, vec3(1.0 / 2.4)) - vec3(0.055);
    vec3 lower = linear * vec3(12.92);

    return mix(higher, lower, cutoff);
}

vec3 to_linear(vec3 srgb) {
    bvec3 cutoff = lessThan(srgb, vec3(0.04045));
    vec3 higher = pow((srgb + vec3(0.055)) / vec3(1.055), vec3(2.4));
    vec3 lower = srgb / vec3(12.92);

    return mix(higher, lower, cutoff);
}

vec4 from_linear(vec4 linear_a) {
    return vec4(from_linear(linear_a.rgb), linear_a.a);
}

vec4 to_linear(vec4 srgba) {
    return vec4(to_linear(srgba.rgb), srgba.a);
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
 *        First everything is rendered into a framebuffer, and then the framebauffer is blended onto
 *        the screen. The framebuffer is needed because it allows access to the background color pixels
 *        to blend with the image pixels. The steps are basically the same as for 2a.
 *
 *  In this shader exactly *one* of SIMPLE, SPECIAL, FOREGROUND or BACKGROUND will be defined, corresponding
 *  to the appropriate rendering pass from above.
 */
#ifdef NEEDS_FOREGROUND
vec4 calculate_foreground() {
    // returns the effective foreground color in pre-multiplied form in linear space

    // TODO: Skip to_linear on texture input if the texture is GL_SRGB_ALPHA
    vec4 text_fg = to_linear(texture(sprites, sprite_pos));
    vec3 fg = mix(foreground, text_fg.rgb, colored_sprite);
    float text_alpha = text_fg.a;
    float underline_alpha = texture(sprites, underline_pos).a;
    float strike_alpha = texture(sprites, strike_pos).a;
    float cursor_alpha = texture(sprites, cursor_pos).a;

    // Since strike and text are the same color, we simply add the alpha values
    float combined_alpha = min(text_alpha + strike_alpha, 1.0f);

    // Underline color might be different, so alpha blend
    vec4 ans = alpha_blend_premul(vec4_premul(fg, combined_alpha * effective_text_alpha), vec4_premul(decoration_fg, underline_alpha * effective_text_alpha));

    return mix(ans, cursor_color_vec, cursor_alpha);
}
#endif

void main() {
#ifdef NEEDS_FOREGROUND
    final_color = calculate_foreground();

#ifdef NEEDS_BACKROUND
#ifdef TRANSPARENT
    final_color = alpha_blend_premul(final_color, vec4_premul(background.rgb, bg_alpha));
#else
    final_color = alpha_blend_premul(final_color, background.rgb);
#endif
#endif
#else
    // TODO: Maybe always provide vec4 for background?
#ifdef TRANSPARENT
    final_color = vec4(background.rgb, bg_alpha);
#else
    final_color = vec4(background.rgb, draw_bg);
#endif
#endif

    // TODO: Disable if we are using GL_FRAMEBUFFER_SRGB
    // convert back to sRGB if we are not using GL_FRAMEBUFFER_SRGB
    final_color = from_linear(final_color);
}
