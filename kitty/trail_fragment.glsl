uniform vec2 cursor_edge_x;
uniform vec2 cursor_edge_y;
uniform vec3 trail_color;
uniform float trail_opacity;

in vec2 frag_pos;
out vec4 final_color;

void main() {
    if (cursor_edge_x[0] <= frag_pos.x && frag_pos.x <= cursor_edge_x[1] &&
        cursor_edge_y[1] <= frag_pos.y && frag_pos.y <= cursor_edge_y[0]) {
        discard;
    } else {
        final_color = vec4(trail_color, trail_opacity);
    }
}
