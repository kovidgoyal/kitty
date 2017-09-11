#version GLSL_VERSION
uniform uvec2 viewport;
in uvec4 rect;  // left, top, right, bottom
in uint rect_color;
out vec3 color;

// indices into the rect vector
const int LEFT = 0;
const int TOP = 1;
const int RIGHT = 2;
const int BOTTOM = 3;

const uvec2 pos_map[] = uvec2[4](
    uvec2(RIGHT, TOP),  
    uvec2(RIGHT, BOTTOM),  
    uvec2(LEFT, BOTTOM),  
    uvec2(LEFT, TOP)   
);

vec2 to_opengl(uint x, uint y) {
    return vec2(
        -1.0 + 2.0 * (float(x) / float(viewport.x)),
        1.0 - 2.0 * (float(y) / float(viewport.y))
    );
}

float to_color(uint c) {
    return float(c & uint(0xff)) / 255.0;
}

void main() {
    uvec2 pos = pos_map[gl_VertexID];
    gl_Position = vec4(to_opengl(rect[pos.x], rect[pos.y]), 0, 1);
    color = vec3(to_color(rect_color >> 16), to_color(rect_color >> 8), to_color(rect_color));
}
