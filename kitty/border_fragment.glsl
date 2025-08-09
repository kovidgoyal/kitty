#pragma kitty_include_shader <alpha_blend.glsl>
#pragma kitty_include_shader <utils.glsl>
#pragma kitty_include_shader <linear2srgb.glsl>

uniform sampler2D bgimage;
uniform float has_background_image;

in vec4 color_premul;
in vec2 texcoord;
in float use_background_image;
out vec4 final_color;

void main() {
    // There are many variables that control the color drawn.
    // 1) color itself which is applied unconditionally when
    // use_background_image == 0 as it means we are drawing an opaque border
    // 2) When not applying an opaque border we can either have a background
    // image or not. When a background image is present, we apply it
    // unconditionally as it includes background_opacity and tint.
    // 3) Otherwise we draw color + tint ( tinting of color happens in vertex shader).
    vec4 background_premul = texture(bgimage, texcoord);  // either from background image or blank
    vec4 ans = if_one_then(use_background_image * has_background_image, background_premul, color_premul);
    final_color = vec4_premul(linear2srgb(ans.rgb / ans.a), ans.a);
}
