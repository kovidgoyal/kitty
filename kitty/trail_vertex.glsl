uniform vec4 x_coords;
uniform vec4 y_coords;

out vec2 frag_pos;

void main() {
    vec2 pos = vec2(x_coords[gl_VertexID], y_coords[gl_VertexID]);
    gl_Position = vec4(pos, 1.0, 1.0);
    frag_pos = pos;
}
