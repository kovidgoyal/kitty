uniform vec4 x_coords;
uniform vec4 y_coords;

void main() {
    gl_Position = vec4(x_coords[gl_VertexID], y_coords[gl_VertexID], -1.0, 1.0);
}
