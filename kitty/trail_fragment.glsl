uniform vec2 cursor_edge_x;
uniform vec2 cursor_edge_y;
uniform vec3 trail_color;
uniform float trail_opacity;

in vec2 frag_pos;
out vec4 final_color;

void main() {
    float opacity = trail_opacity;
    // Dont render if fragment is within cursor area
    float in_x = step(cursor_edge_x[0], frag_pos.x) * step(frag_pos.x, cursor_edge_x[1]);
    float in_y = step(cursor_edge_y[1], frag_pos.y) * step(frag_pos.y, cursor_edge_y[0]);
    opacity *= 1.0f - in_x * in_y;
    final_color = vec4(trail_color, opacity);
}
