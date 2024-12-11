uniform vec2 cursor_edge_x;
uniform vec2 cursor_edge_y;
uniform vec3 trail_color;
uniform float trail_opacity;

in vec2 frag_pos;
out vec4 final_color;

void main() {
    final_color = vec4(trail_color, trail_opacity);
}
