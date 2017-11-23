#version GLSL_VERSION
#define vleft  -1.0f
#define vtop  1.0f
#define vright  1.0f
#define vbottom  -1.0f

#define tleft 0.0f
#define ttop 1.0f
#define tright 1.0f
#define tbottom 0.0f

const vec2 viewport_xpos = vec2(vleft, vright);
const vec2 viewport_ypos = vec2(vtop, vbottom);
const vec2 texture_xpos = vec2(tleft, tright);
const vec2 texture_ypos = vec2(ttop, tbottom);

const uvec2 pos_map[] = uvec2[4](
    uvec2(1, 0),  // right, top
    uvec2(1, 1),  // right, bottom
    uvec2(0, 1),  // left, bottom
    uvec2(0, 0)   // left, top
);

out vec2 texcoord;

void main() {
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(viewport_xpos[pos[0]], viewport_ypos[pos[1]], 0, 1);
    texcoord = vec2(texture_xpos[pos[0]], texture_ypos[pos[1]]);
}
