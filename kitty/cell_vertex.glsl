#version GLSL_VERSION
uniform uvec2 dimensions;  // xnum, ynum
uniform vec4 steps;  // xstart, ystart, dx, dy
uniform vec2 sprite_layout;  // dx, dy
uniform ivec2 color_indices;  // which color to use as fg and which as bg
uniform uvec4 default_colors; // The default colors
uniform ColorTable {
    uint color_table[256]; // The color table
};
in uvec3 sprite_coords;
in uvec3 colors;
in float is_selected;
out vec3 sprite_pos;
out vec3 underline_pos;
out vec3 strike_pos;
out vec3 foreground;
out vec3 background;
out vec3 decoration_fg;

const uvec2 pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);

const uint strike_map[] = uint[2](uint(0), uint(3));
const uint BYTE_MASK = uint(0xFF);
const uint SHORT_MASK = uint(0xFFFF);
const uint ZERO = uint(0);
const uint SMASK = uint(3);

vec3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return vec3(float(r) / 255.0, float(g) / 255.0, float(b) / 255.0);
}

vec3 to_color(uint c, uint defval) {
    int t = int(c & BYTE_MASK);
    uint r;
    switch(t) {
        case 1:
            r = color_table[(c >> 8) & BYTE_MASK];
            break;
        case 2:
            r = c >> 8;
            break;
        default:
            r = defval;
    }
    return color_to_vec(r);
}

vec3 to_sprite_pos(uvec2 pos, uint x, uint y, uint z) {
    vec2 s_xpos = vec2(x, float(x) + 1.0) * sprite_layout.x;
    vec2 s_ypos = vec2(y, float(y) + 1.0) * sprite_layout.y;
    return vec3(s_xpos[pos.x], s_ypos[pos.y], z);
}

vec3 apply_selection(vec3 color, uint which) {
    return is_selected * color_to_vec(which) + (1.0 - is_selected) * color;
}

void main() {
    uint instance_id = uint(gl_InstanceID);
    uint r = instance_id / dimensions.x;
    uint c = instance_id - r * dimensions.x;
    float left = steps[0] + c * steps[2];
    float top = steps[1] - r * steps[3];
    vec2 xpos = vec2(left, left + steps[2]);
    vec2 ypos = vec2(top, top - steps[3]);
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(xpos[pos.x], ypos[pos.y], 0, 1);

    sprite_pos = to_sprite_pos(pos, sprite_coords.x, sprite_coords.y, sprite_coords.z & SHORT_MASK);
    uint fg = colors[color_indices[0]];
    uint bg = colors[color_indices[1]];
    uint decoration = colors[2];
    foreground = apply_selection(to_color(fg, default_colors[color_indices[0]]), default_colors[2]);
    background = apply_selection(to_color(bg, default_colors[color_indices[1]]), default_colors[3]);
    decoration_fg = to_color(decoration, default_colors[color_indices[0]]);
    underline_pos = to_sprite_pos(pos, (sprite_coords.z >> 24) & SMASK, ZERO, ZERO);
    strike_pos = to_sprite_pos(pos, strike_map[(sprite_coords.z >> 26)] & SMASK, ZERO, ZERO);
}
