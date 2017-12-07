#version GLSL_VERSION
#define WHICH_PROGRAM
#define NOT_TRANSPARENT

#if defined(SIMPLE) || defined(BACKGROUND) || defined(SPECIAL)
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
in vec3 sprite_pos;
in vec3 underline_pos;
in vec3 strike_pos;
in vec3 foreground;
in vec3 decoration_fg;
in float colored_sprite;
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
// }}}

#ifdef NEEDS_FOREGROUND
vec4 calculate_foreground() {
    vec4 text_fg = texture(sprites, sprite_pos);
    vec3 fg = mix(foreground, text_fg.rgb, colored_sprite);
    float text_alpha = text_fg.a;
    float underline_alpha = texture(sprites, underline_pos).a;
    float strike_alpha = texture(sprites, strike_pos).a;
    // Since strike and text are the same color, we simply add the alpha values
    float combined_alpha = min(text_alpha + strike_alpha, 1.0f);
    // Underline color might be different, so alpha blend
    return alpha_blend(decoration_fg, underline_alpha, fg, combined_alpha);
}
#endif

void main() {
#ifdef BACKGROUND
#ifdef TRANSPARENT
    final_color = vec4(background.rgb * bg_alpha, bg_alpha);
#else
    final_color = vec4(background.rgb, 1.0f);
#endif 
#endif

#ifdef SPECIAL
#ifdef TRANSPARENT
    final_color = vec4(background.rgb * bg_alpha, bg_alpha);
#else
    final_color = vec4(background.rgb, bg_alpha);
#endif 
#endif

#if defined(FOREGROUND) || defined(SIMPLE) 
    // FOREGROUND or SIMPLE
    vec4 fg = calculate_foreground();  // pre-multiplied foreground

#ifdef FOREGROUND
    // FOREGROUND
#ifdef TRANSPARENT
    final_color = fg;
#else
    final_color = vec4(fg.rgb / fg.a, fg.a);
#endif

#else
    // SIMPLE
#ifdef TRANSPARENT
    final_color = alpha_blend_premul(fg.rgb, fg.a, background * bg_alpha, bg_alpha);
    final_color = vec4(final_color.rgb / final_color.a, final_color.a);
#else
    // since background alpha is 1.0, it is effectively premultipled
    final_color = vec4(premul_blend(fg.rgb, fg.a, background), 1.0f);
    final_color = vec4(final_color.rgb / final_color.a, final_color.a);
#endif
#endif

#endif
}
