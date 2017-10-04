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

out vec4 final_color;

vec3 blend(float alpha, vec3 over, vec3 under) {
    return over + (1 - alpha) * under;
}

void main() {
#if defined(FOREGROUND) || defined(ALL)
    float text_alpha = texture(sprites, sprite_pos).r;
    float underline_alpha = texture(sprites, underline_pos).r;
    float strike_alpha = texture(sprites, strike_pos).r;
    vec3 underline = underline_alpha * decoration_fg;
    vec3 strike = strike_alpha * foreground;
    vec3 fg = text_alpha * foreground;
    vec3 decoration = blend(underline_alpha, underline, strike);
    vec3 combined_fg = blend(text_alpha, fg, decoration);
    float combined_alpha = max(max(underline_alpha, strike_alpha), text_alpha);
#ifdef ALL
    final_color = vec4(blend(combined_alpha, combined_fg, background), 1);
#else
    final_color = vec4(combined_fg, combined_alpha);
#endif

#else
    final_color = vec4(background, 1);
#endif
}
