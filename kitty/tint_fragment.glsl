uniform vec4 tint_color;
out vec4 color;  // must be in linear space and pre-multiplied

void main() {
    color = tint_color;
}
