#!/usr/bin/env python
# vim:fileencoding=utf-8
# License: GPL v3 Copyright: 2016, Kovid Goyal <kovid at kovidgoyal.net>

from functools import lru_cache

from OpenGL.GL import (
    glCreateProgram, GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, glAttachShader,
    glLinkProgram, glGetProgramiv, glGetProgramInfoLog, GL_LINK_STATUS,
    GL_TRUE, glDeleteProgram, glDeleteShader, glCreateShader, glCompileShader,
    glGetShaderiv, GL_COMPILE_STATUS, glShaderSource, glGetShaderInfoLog,
    glGetUniformLocation, glGetAttribLocation
)


class ShaderProgram:
    """ Helper class for using GLSL shader programs """

    def __init__(self, vertex: str, fragment: str):
        """
        Create a shader program.

        :param vertex: The vertex shader
        :param fragment: The fragment shader

        """
        self.program_id = glCreateProgram()
        vs_id = self.add_shader(vertex, GL_VERTEX_SHADER)
        frag_id = self.add_shader(fragment, GL_FRAGMENT_SHADER)

        glAttachShader(self.program_id, vs_id)
        glAttachShader(self.program_id, frag_id)
        glLinkProgram(self.program_id)

        if glGetProgramiv(self.program_id, GL_LINK_STATUS) != GL_TRUE:
            info = glGetProgramInfoLog(self.program_id)
            glDeleteProgram(self.program_id)
            glDeleteShader(vs_id)
            glDeleteShader(frag_id)
            raise ValueError('Error linking shader program: %s' % info)
        glDeleteShader(vs_id)
        glDeleteShader(frag_id)

    def __hash__(self) -> int:
        return self.program_id

    def __eq__(self, other) -> bool:
        return isinstance(other, ShaderProgram) and other.program_id == self.program_id

    def __ne__(self, other) -> bool:
        return not self.__eq__(other)

    def add_shader(self, source: str, shader_type: int) -> int:
        ' Compile a shader and return its id, or raise an exception if compilation fails '
        shader_id = glCreateShader(shader_type)
        try:
            glShaderSource(shader_id, source)
            glCompileShader(shader_id)
            if glGetShaderiv(shader_id, GL_COMPILE_STATUS) != GL_TRUE:
                info = glGetShaderInfoLog(shader_id)
                raise ValueError('GLSL Shader compilation failed: %s' % info)
            return shader_id
        except Exception:
            glDeleteShader(shader_id)
            raise

    @lru_cache(maxlen=None)
    def uniform_location(self, name: str) -> int:
        ' Return the id for the uniform variable `name` or -1 if not found. '
        return glGetUniformLocation(self.program_id, name)

    @lru_cache(maxlen=None)
    def attribute_location(self, name: str) -> int:
        ' Return the id for the attribute variable `name` or -1 if not found. '
        return glGetAttribLocation(self.program_id, name)
