#version GLSL_VERSION
#define WHICH_PROGRAM
#if defined(FOREGROUND) || defined(ALL)
uniform sampler2DArray sprites;
in vec3 sprite_pos;
in vec3 underline_pos;
in vec3 strike_pos;
in vec3 foreground;
in vec3 decoration_fg;
#endif
in vec3 background;
#ifdef SPECIAL
in vec4 special_bg;
#endif

out vec4 final_color;

vec4 alpha_blend(vec3 over, float over_alpha, vec3 under, float under_alpha) {
    // Alpha blend two colors returning the resulting color pre-multiplied by its alpha
    // and its alpha.
    // See https://en.wikipedia.org/wiki/Alpha_compositing
    float alpha = mix(under_alpha, 1.0f, over_alpha);  
    vec3 combined_color = mix(under * under_alpha, over, over_alpha);
    return vec4(combined_color, alpha);
}

void main() {
#if defined(FOREGROUND) || defined(ALL)
    float text_alpha = texture(sprites, sprite_pos).r;
    float underline_alpha = texture(sprites, underline_pos).r;
    float strike_alpha = texture(sprites, strike_pos).r;
    // Since strike and text are the same color, we simply add the alpha values
    float combined_alpha = min(text_alpha + strike_alpha, 1.0f);
    // Underline color might be different, so alpha blend
    vec4 fg = alpha_blend(decoration_fg, underline_alpha, foreground, combined_alpha);

#ifdef ALL
    // since background alpha is 1.0 and fg color is pre-multiplied by its alpha,
    // we can simplify the alpha blend equation 
    final_color = vec4(fg.rgb + (1.0f - fg.a) * background, 1.0f);
#else
    // FOREGROUND
    // fg is pre-multipled so divide it by alpha
    final_color = vec4(fg.rgb / fg.a, fg.a);
#endif

#else

#ifdef SPECIAL
    final_color = special_bg;
#else
    // BACKGROUND
    final_color = vec4(background, 1.0f);
#endif

#endif
}
