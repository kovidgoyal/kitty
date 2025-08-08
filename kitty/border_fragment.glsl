#pragma kitty_include_shader <alpha_blend.glsl>
#pragma kitty_include_shader <utils.glsl>
#pragma kitty_include_shader <linear2srgb.glsl>

in vec4 color;
in vec2 texcoord;
in float use_background_image;
out vec4 final_color;
uniform sampler2D bgimage;

void main() {
    vec4 ans = vec4_premul(texture(bgimage, texcoord));
    ans.a *= color.a;  // apply background_opacity to the color from the bgimage
    ans = if_one_then(use_background_image, ans, color);
    final_color = vec4_premul(linear2srgb(ans.rgb / ans.a), ans.a);
}
