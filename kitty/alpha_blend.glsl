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
