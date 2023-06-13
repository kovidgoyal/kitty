
uniform vec4 edges;

void main() {
    float left = edges[0];
    float top = edges[1];
    float right = edges[2];
    float bottom = edges[3];
    vec2 pos_map[] = vec2[4](
        vec2(left, top),
        vec2(left, bottom),
        vec2(right, bottom),
        vec2(right, top)
    );


    gl_Position = vec4(pos_map[gl_VertexID], 0, 1);
}
