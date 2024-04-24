/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"
#include "gl-wrapper.h"

typedef struct {
    GLint size, index;
} UniformBlock;

typedef struct {
    GLint offset, stride, size;
} ArrayInformation;

typedef struct {
    char name[256];
    GLint size, location, idx;
    GLenum type;
} Uniform;

typedef struct {
    GLuint id;
    Uniform uniforms[256];
    GLint num_of_uniforms;
} Program;


void gl_init(void);
const char* gl_version_string(void);
void update_surface_size(int w, int h, GLuint offscreen_texture_id);
void free_texture(GLuint *tex_id);
void free_framebuffer(GLuint *fb_id);
void remove_vao(ssize_t vao_idx);
void init_uniforms(int program);
GLuint program_id(int program);
Program* program_ptr(int program);
GLuint block_index(int program, const char *name);
GLint block_size(int program, GLuint block_index);
GLint get_uniform_location(int program, const char *name);
GLint get_uniform_information(int program, const char *name, GLenum information_type);
GLint attrib_location(int program, const char *name);
ssize_t create_vao(void);
size_t add_buffer_to_vao(ssize_t vao_idx, GLenum usage);
void add_attribute_to_vao(int p, ssize_t vao_idx, const char *name, GLint size, GLenum data_type, GLsizei stride, void *offset, GLuint divisor);
ssize_t alloc_vao_buffer(ssize_t vao_idx, GLsizeiptr size, size_t bufnum, GLenum usage);
void* alloc_and_map_vao_buffer(ssize_t vao_idx, GLsizeiptr size, size_t bufnum, GLenum usage, GLenum access);
void unmap_vao_buffer(ssize_t vao_idx, size_t bufnum);
void* map_vao_buffer(ssize_t vao_idx, size_t bufnum, GLenum access);
void bind_program(int program);
void bind_vertex_array(ssize_t vao_idx);
void bind_vao_uniform_buffer(ssize_t vao_idx, size_t bufnum, GLuint block_index);
void unbind_vertex_array(void);
void unbind_program(void);
GLuint compile_shaders(GLenum shader_type, GLsizei count, const GLchar * const * string);
