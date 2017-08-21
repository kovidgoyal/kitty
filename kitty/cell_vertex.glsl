uniform uvec2 dimensions;  // xnum, ynum
uniform vec4 steps;  // xstart, ystart, dx, dy
uniform vec2 sprite_layout;  // dx, dy
uniform usamplerBuffer sprite_map; // gl_InstanceID -> x, y, z
uniform ivec2 color_indices;  // which color to use as fg and which as bg
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

const uint BYTE_MASK = uint(255);
const uint ZERO = uint(0);
const uint SMASK = uint(3);

vec3 to_color(uint c) {
    uint r, g, b;
    r = (c >> 16) & BYTE_MASK;
    g = (c >> 8) & BYTE_MASK;
    b = c & BYTE_MASK;
    return vec3(float(r) / 255.0, float(g) / 255.0, float(b) / 255.0);
}

vec3 to_sprite_pos(uvec2 pos, uint x, uint y, uint z) {
    vec2 s_xpos = vec2(x, float(x) + 1.0) * sprite_layout[0];
    vec2 s_ypos = vec2(y, float(y) + 1.0) * sprite_layout[1];
    return vec3(s_xpos[pos[0]], s_ypos[pos[1]], z);
}

void main() {
    uint instance_id = uint(gl_InstanceID);
    uint r = instance_id / dimensions[0];
    uint c = instance_id - r * dimensions[0];
    float left = steps[0] + c * steps[2];
    float top = steps[1] - r * steps[3];
    vec2 xpos = vec2(left, left + steps[2]);
    vec2 ypos = vec2(top, top - steps[3]);
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(xpos[pos[0]], ypos[pos[1]], 0, 1);

    int sprite_id = gl_InstanceID * STRIDE;
    uint x = texelFetch(sprite_map, sprite_id).r;
    uint y = texelFetch(sprite_map, sprite_id + 1).r;
    uint z = texelFetch(sprite_map, sprite_id + 2).r;
    sprite_pos = to_sprite_pos(pos, x, y, z);
    sprite_id += 3;
    uint fg = texelFetch(sprite_map, sprite_id + color_indices[0]).r;
    uint bg = texelFetch(sprite_map, sprite_id + color_indices[1]).r;
    uint decoration = texelFetch(sprite_map, sprite_id + 2).r;
    foreground = to_color(fg);
    background = to_color(bg);
    decoration_fg = to_color(decoration);
    underline_pos = to_sprite_pos(pos, (decoration >> 24) & SMASK, ZERO, ZERO);
    strike_pos = to_sprite_pos(pos, (decoration >> 26) & SMASK, ZERO, ZERO);
}
