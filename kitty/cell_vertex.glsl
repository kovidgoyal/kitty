#version GLSL_VERSION
#define WHICH_PROGRAM
#define NOT_TRANSPARENT

// Inputs {{{
layout(std140) uniform CellRenderData {
    float xstart, ystart, dx, dy, sprite_dx, sprite_dy, background_opacity;

    uint default_fg, default_bg, highlight_fg, highlight_bg, cursor_color, url_color, url_style;

    int color1, color2;

    uint xnum, ynum, cursor_x, cursor_y, cursor_w, url_xl, url_yl, url_xr, url_yr;

    uint color_table[256]; 
};

// Have to use fixed locations here as all variants of the cell program share the same VAO
layout(location=0) in uvec3 colors;
layout(location=1) in uvec4 sprite_coords;
layout(location=2) in float is_selected;


    
const uvec2 cell_pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);
// }}}


#if defined(SIMPLE) || defined(BACKGROUND) || defined(SPECIAL)
#define NEEDS_BACKROUND
#endif

#if defined(SIMPLE) || defined(FOREGROUND)
#define NEEDS_FOREGROUND
#endif

#ifdef NEEDS_BACKROUND
out vec3 background;
#if defined(TRANSPARENT) || defined(SPECIAL)
out float bg_alpha;
#endif
#endif

#ifdef NEEDS_FOREGROUND
out vec3 sprite_pos;
out vec3 underline_pos;
out vec3 strike_pos;
out vec3 foreground;
out vec3 decoration_fg;
out float colored_sprite;
#endif


// Utility functions {{{
const uint BYTE_MASK = uint(0xFF);
const uint Z_MASK = uint(0xFFF);
const uint COLOR_MASK = uint(0x4000);
const uint ZERO = uint(0);
const uint ONE = uint(1);
const uint TWO = uint(2);
const uint THREE = uint(3);
const uint FOUR = uint(4);
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

uint resolve_color(uint c, uint defval) {
    // Convert a cell color to an actual color based on the color table
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
    return color_to_vec(resolve_color(c, defval));
}

vec3 to_sprite_pos(uvec2 pos, uint x, uint y, uint z) {
    vec2 s_xpos = vec2(x, float(x) + 1.0) * sprite_dx;
    vec2 s_ypos = vec2(y, float(y) + 1.0) * sprite_dy;
    return vec3(s_xpos[pos.x], s_ypos[pos.y], z);
}

vec3 choose_color(float q, vec3 a, vec3 b) {
    return mix(b, a, q);
}

float in_range(uint x, uint y) {
    if (url_yl == y && url_xl <= x && x <= url_xr) return 1.0;
    return 0.0;
}

float is_cursor(uint x, uint y) {
    if (y == cursor_y && (x == cursor_x || x == cursor_w)) return 1.0;
    return 0.0;
}
// }}}


void main() {

    // set cell vertex position  {{{
    uint instance_id = uint(gl_InstanceID); 
    /* The current cell being rendered */
    uint r = instance_id / xnum; 
    uint c = instance_id - r * xnum; 

    /* The position of this vertex, at a corner of the cell  */ 
    float left = xstart + c * dx; 
    float top = ystart - r * dy; 
    vec2 xpos = vec2(left, left + dx); 
    vec2 ypos = vec2(top, top - dy); 
    uvec2 pos = cell_pos_map[gl_VertexID]; 
    gl_Position = vec4(xpos[pos.x], ypos[pos.y], 0, 1);

    // }}}
    
    // set cell color indices {{{
    uvec2 default_colors = uvec2(default_fg, default_bg); 
    ivec2 color_indices = ivec2(color1, color2); 
    uint text_attrs = sprite_coords[3]; 
    int fg_index = color_indices[(text_attrs >> 6) & REVERSE_MASK]; 
    int bg_index = color_indices[1 - fg_index]; 
    float cursor = is_cursor(c, r);
    vec3 bg = to_color(colors[bg_index], default_colors[bg_index]);
    // }}}

    // Foreground {{{
#ifdef NEEDS_FOREGROUND

    // The character sprite being rendered
    sprite_pos = to_sprite_pos(pos, sprite_coords.x, sprite_coords.y, sprite_coords.z & Z_MASK);
    colored_sprite = float((sprite_coords.z & COLOR_MASK) >> 14);

    // Foreground 
    uint resolved_fg = resolve_color(colors[fg_index], default_colors[fg_index]);
    foreground = color_to_vec(resolved_fg);
    // Selection
    foreground = choose_color(is_selected, color_to_vec(highlight_fg), foreground);
    // Underline and strike through (rendered via sprites)
    float in_url = in_range(c, r);
    decoration_fg = choose_color(in_url, color_to_vec(url_color), to_color(colors[2], resolved_fg));
    underline_pos = choose_color(in_url, to_sprite_pos(pos, url_style, ZERO, ZERO), to_sprite_pos(pos, (text_attrs >> 2) & DECORATION_MASK, ZERO, ZERO));
    strike_pos = to_sprite_pos(pos, ((text_attrs >> 7) & STRIKE_MASK) * FOUR, ZERO, ZERO);

    // Cursor
    foreground = choose_color(cursor, bg, foreground);
    decoration_fg = choose_color(cursor, bg, decoration_fg);
#endif
    // }}} 

    // Background {{{
#ifdef NEEDS_BACKROUND

#if defined(BACKGROUND)
    background = bg;
#endif

#if defined(TRANSPARENT) && !defined(SPECIAL)
    // If the background color is default, set its opacity to background_opacity, otherwise it should be opaque
    bg_alpha = step(0.5, float(colors[bg_index] & BYTE_MASK));
    // Cursor must not be affected by background_opacity
    bg_alpha = mix(bg_alpha, 1.0, cursor);
    bg_alpha = bg_alpha + (1.0f - bg_alpha) * background_opacity;
#endif

#if defined(SPECIAL) || defined(SIMPLE)
    // Selection and cursor
    bg = choose_color(is_selected, color_to_vec(highlight_bg), bg);
    background = choose_color(cursor, color_to_vec(cursor_color), bg);
#ifdef SPECIAL
    // bg_alpha should be 1 if cursor/selection otherwise 0
    bg_alpha = mix(0.0, 1.0, step(0.5, is_selected + cursor));
#endif
#endif

#endif
    // }}}

}
