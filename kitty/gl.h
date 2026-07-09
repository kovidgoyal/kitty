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
    GLint offset;  // byte offset from start of UBO
    GLint stride;  // element stride in bytes
    GLint size;    // umber of elements
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

typedef struct Viewport { unsigned left, top, width, height; } Viewport;

typedef enum { PROGRAM_UNIFORM, PROGRAM_ATTRIBUTE, PROGRAM_BLOCK, PROGRAM_ARRAY } ProgramMetadataKind;
typedef struct ProgramMetadataEntry {
    ProgramMetadataKind kind;
    union { GLint location; UniformBlock block; ArrayInformation array; };
} ProgramMetadataEntry;

void gl_init(void);
const char* gl_version_string(void);
void set_gpu_viewport(unsigned w, unsigned h);
Viewport get_gpu_viewport(void);
void draw_quad(bool blend, unsigned instance_count);
void save_texture_as_png(uint32_t texture_id, const char *filename);
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
ArrayInformation get_uniform_array_information(int program, const char *name);
GLint attrib_location(int program, const char *name);
void set_program_layout(int program, PyObject *metadata);
void free_program_layouts(void);
GLint program_uniform_location(int program, const char *name);
GLint program_attribute_location(int program, const char *name);
UniformBlock program_uniform_block(int program, const char *name);
ArrayInformation program_uniform_array(int program, const char *name);
ssize_t create_vao(void);
size_t add_buffer_to_vao(ssize_t vao_idx, GLenum usage);
void add_attribute_to_vao(ssize_t vao_idx, int location, GLint size, GLenum data_type, GLsizei stride, void *offset, GLuint divisor);
void set_vao_attribute(ssize_t vao_idx, size_t buffer_idx, int location, GLint size, GLenum data_type, GLsizei stride, void *offset, GLuint divisor);
ssize_t alloc_vao_buffer(ssize_t vao_idx, GLsizeiptr size, size_t bufnum, GLenum usage);
void* alloc_and_map_vao_buffer(ssize_t vao_idx, GLsizeiptr size, size_t bufnum, bool frequently_updated);
void unmap_vao_buffer(ssize_t vao_idx, size_t bufnum);
void* map_vao_buffer(ssize_t vao_idx, size_t bufnum, GLenum access);
void* map_vao_buffer_for_write_only(ssize_t vao_idx, size_t bufnum, int offset, unsigned size);
void bind_program(int program);
void bind_vertex_array(ssize_t vao_idx);
void bind_vao_uniform_buffer(ssize_t vao_idx, size_t bufnum, GLuint block_index);
void unbind_vertex_array(void);
void unbind_program(void);
GLuint compile_shaders(GLenum shader_type, GLsizei count, const GLchar * const * string);
void save_viewport_using_top_left_origin(GLsizei x, GLsizei y, GLsizei width, GLsizei height, GLsizei full_framebuffer_height);
void save_viewport_using_bottom_left_origin(GLsizei x, GLsizei y, GLsizei width, GLsizei height);
const char* check_framebuffer_status(void);
void restore_viewport(void);
void bind_framebuffer_for_output(unsigned fbid);
void set_framebuffer_to_use_for_output(unsigned fbid);
void enable_scissor_using_top_left_origin(Viewport, unsigned);
void disable_scissor(void);
