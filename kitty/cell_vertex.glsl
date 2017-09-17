#version GLSL_VERSION
uniform uvec4 dimensions;  // xnum, ynum, cursor.x, cursor.y
uniform float geom[6];
uniform ivec2 color_indices;  // which color to use as fg and which as bg
uniform uint default_colors[6]; // The default colors
uniform uvec4 url_range; // The range for the currently highlighted URL (start_x, end_x, start_y, end_y)
uniform ColorTable {
    uint color_table[256]; // The color table
};
#define xstart geom[0]
#define ystart geom[1]
#define dx geom[2]
#define dy geom[3]
#define highlight_fg default_colors[2]
#define highlight_bg default_colors[3]
#define cursor_color default_colors[4]
#define url_color default_colors[5]
#define cursor_x dimensions[2]
#define cursor_y dimensions[3]
#define sprite_dx geom[4]
#define sprite_dy geom[5]

in uvec4 sprite_coords;
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

const uint BYTE_MASK = uint(0xFF);
const uint SHORT_MASK = uint(0xFFFF);
const uint ZERO = uint(0);
const uint ONE = uint(1);
const uint TWO = uint(2);
const uint THREE = uint(3);
const uint DECORATION_MASK = uint(3);
const uint STRIKE_MASK = uint(1);
const uint REVERSE_MASK = uint(1);

vec3 color_to_vec(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return vec3(float(r) / 255.0, float(g) / 255.0, float(b) / 255.0);
}

uint as_color(uint c, uint defval) {
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
    return r;
}

vec3 to_color(uint c, uint defval) {
    return color_to_vec(as_color(c, defval));
}

vec3 to_sprite_pos(uvec2 pos, uint x, uint y, uint z) {
    vec2 s_xpos = vec2(x, float(x) + 1.0) * sprite_dx;
    vec2 s_ypos = vec2(y, float(y) + 1.0) * sprite_dy;
    return vec3(s_xpos[pos.x], s_ypos[pos.y], z);
}

vec3 apply_selection(vec3 color, uint which) {
    return is_selected * color_to_vec(which) + (1.0 - is_selected) * color;
}

vec3 mix_vecs(float q, vec3 a, vec3 b) {
    return q * a + (1.0 - q) * b;
}

float in_range(uvec4 range, uint x, uint y) {
    if (range[2] == y && range[0] <= x && x <= range[1]) return 1.0;
    return 0.0;
}

float is_cursor(uint x, uint y) {
    if (x == cursor_x && y == cursor_y) return 1.0;
    return 0.0;
}

void main() {
    uint instance_id = uint(gl_InstanceID);
    // The current cell being rendered
    uint r = instance_id / dimensions.x;
    uint c = instance_id - r * dimensions.x;

    // The position of this vertex, at a corner of the cell
    float left = xstart + c * dx;
    float top = ystart - r * dy;
    vec2 xpos = vec2(left, left + dx);
    vec2 ypos = vec2(top, top - dy);
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(xpos[pos.x], ypos[pos.y], 0, 1);

    // The character sprite being rendered
    sprite_pos = to_sprite_pos(pos, sprite_coords.x, sprite_coords.y, sprite_coords.z & SHORT_MASK);

    // Foreground and background colors
    uint text_attrs = sprite_coords[3];
    int fg_index = color_indices[(text_attrs >> 6) & REVERSE_MASK];
    int bg_index = color_indices[1 - fg_index];
    uint resolved_fg = as_color(colors[fg_index], default_colors[fg_index]);
    foreground = apply_selection(color_to_vec(resolved_fg), highlight_fg);
    background = apply_selection(to_color(colors[bg_index], default_colors[bg_index]), highlight_bg);
    float cursor = is_cursor(c, r);
    foreground = cursor * background + (1.0 - cursor) * foreground;
    background = cursor * color_to_vec(cursor_color) + (1.0 - cursor) * background;

    // Underline and strike through (rendered via sprites)
    float in_url = in_range(url_range, c, r);
    decoration_fg = mix_vecs(in_url, color_to_vec(url_color), to_color(colors[2], resolved_fg));
    underline_pos = mix_vecs(in_url, to_sprite_pos(pos, TWO, ZERO, ZERO), to_sprite_pos(pos, (text_attrs >> 2) & DECORATION_MASK, ZERO, ZERO));
    strike_pos = to_sprite_pos(pos, ((text_attrs >> 7) & STRIKE_MASK) * THREE, ZERO, ZERO);
}
