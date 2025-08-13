#define left 0
#define top 1
#define right 2
#define bottom 3

const ivec2 vertex_pos_map[4] = ivec2[4](
    ivec2(right, top),
    ivec2(right, bottom),
    ivec2(left, bottom),
    ivec2(left, top)
);
const vec4 dest_rect = vec4(-1, 1, 1, -1);

void main() {
    ivec2 pos = vertex_pos_map[gl_VertexID];
    gl_Position = vec4(dest_rect[pos.x], dest_rect[pos.y], 0, 1);
}
