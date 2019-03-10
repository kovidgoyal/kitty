#version GLSL_VERSION
layout (location = 0) in vec2 aPos;
layout (location = 1) in vec2 aTexCoords;

uniform float offset;

out vec2 TexCoords;

void main()
{
    gl_Position = vec4(aPos.x, aPos.y - offset, 0.0, 1.0);
    TexCoords = aTexCoords;
}
