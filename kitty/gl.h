/*
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "gl-wrapper.h"
#include "state.h"
#include "screen.h"
#include <string.h>
#include <stddef.h>
#include "glfw-wrapper.h"

static char glbuf[4096];

// GL setup and error handling {{{
#define GLSL_VERSION (OPENGL_REQUIRED_VERSION_MAJOR * 100 + OPENGL_REQUIRED_VERSION_MINOR * 10)

static void
check_for_gl_error(const char *name, void UNUSED *funcptr, int UNUSED len_args, ...) {
#define f(msg) fatal("OpenGL error: %s (calling function: %s)", msg, name); break;
    GLenum code = glad_glGetError();
    switch(code) {
        case GL_NO_ERROR: break;
        case GL_INVALID_ENUM:
            f("An enum value is invalid (GL_INVALID_ENUM)");
        case GL_INVALID_VALUE:
            f("An numeric value is invalid (GL_INVALID_VALUE)");
        case GL_INVALID_OPERATION:
            f("This operation is invalid (GL_INVALID_OPERATION)");
        case GL_INVALID_FRAMEBUFFER_OPERATION:
            f("The framebuffer object is not complete (GL_INVALID_FRAMEBUFFER_OPERATION)");
        case GL_OUT_OF_MEMORY:
            f("There is not enough memory left to execute the command. (GL_OUT_OF_MEMORY)");
        case GL_STACK_UNDERFLOW:
            f("An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_UNDERFLOW)");
        case GL_STACK_OVERFLOW:
            f("An attempt has been made to perform an operation that would cause an internal stack to overflow. (GL_STACK_OVERFLOW)");
        default:
            fatal("An unknown OpenGL error occurred with code: %d (calling function: %s)", code, name);
            break;
    }
}

void
gl_init() {
    static bool glad_loaded = false;
    if (!glad_loaded) {
        if (!init_glad((GLADloadproc) glfwGetProcAddress, global_state.debug_gl)) {
            fatal("Loading the OpenGL library failed");
        }
        glad_set_post_callback(check_for_gl_error);
#define ARB_TEST(name) \
        if (!GLAD_GL_ARB_##name) { \
            fatal("The OpenGL driver on this system is missing the required extension: ARB_%s", #name); \
        }
        ARB_TEST(texture_storage);
#undef ARB_TEST
        glad_loaded = true;
        if (global_state.debug_gl) printf("GL version string: '%s' Detected version: %d.%d\n", glGetString(GL_VERSION), GLVersion.major, GLVersion.minor);
        if (GLVersion.major < OPENGL_REQUIRED_VERSION_MAJOR || (GLVersion.major == OPENGL_REQUIRED_VERSION_MAJOR && GLVersion.minor < OPENGL_REQUIRED_VERSION_MINOR)) {
            fatal("OpenGL version is %d.%d, version >= 3.3 required for kitty", GLVersion.major, GLVersion.minor);
        }
    }
}

void
update_surface_size(int w, int h, GLuint offscreen_texture_id) {
    glViewport(0, 0, w, h);
    if (offscreen_texture_id) {
        glBindTexture(GL_TEXTURE_2D, offscreen_texture_id);
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, 0);
    }
}

void
free_texture(GLuint *tex_id) {
    glDeleteTextures(1, tex_id);
    *tex_id = 0;
}


// }}}

// Programs {{{

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

static Program programs[64] = {{0}};

static inline GLuint
compile_shader(GLenum shader_type, const char *source) {
    GLuint shader_id = glCreateShader(shader_type);
    glShaderSource(shader_id, 1, (const GLchar **)&source, NULL);
    glCompileShader(shader_id);
    GLint ret = GL_FALSE;
    glGetShaderiv(shader_id, GL_COMPILE_STATUS, &ret);
    if (ret != GL_TRUE) {
        GLsizei len;
        glGetShaderInfoLog(shader_id, sizeof(glbuf), &len, glbuf);
        log_error("Failed to compile GLSL shader!\n%s", glbuf);
        glDeleteShader(shader_id);
        PyErr_SetString(PyExc_ValueError, "Failed to compile shader");
        return 0;
    }
    return shader_id;
}

static inline GLuint
program_id(int program) { return programs[program].id; }

static inline void
init_uniforms(int program) {
    Program *p = programs + program;
    glGetProgramiv(p->id, GL_ACTIVE_UNIFORMS, &(p->num_of_uniforms));
    for (GLint i = 0; i < p->num_of_uniforms; i++) {
        Uniform *u = p->uniforms + i;
        glGetActiveUniform(p->id, (GLuint)i, sizeof(u->name)/sizeof(u->name[0]), NULL, &(u->size), &(u->type), u->name);
        u->location = glGetUniformLocation(p->id, u->name);
        u->idx = i;
    }
}

static inline GLint
get_uniform_information(int program, const char *name, GLenum information_type) {
    GLint q; GLuint t;
    static const char* names[] = {""};
    names[0] = name;
    GLuint pid = program_id(program);
    glGetUniformIndices(pid, 1, (void*)names, &t);
    glGetActiveUniformsiv(pid, 1, &t, information_type, &q);
    return q;
}

static inline GLint
attrib_location(int program, const char *name) {
    GLint ans = glGetAttribLocation(programs[program].id, name);
    return ans;
}

static inline GLuint
block_index(int program, const char *name) {
    GLuint ans = glGetUniformBlockIndex(programs[program].id, name);
    if (ans == GL_INVALID_INDEX) { fatal("Could not find block index"); }
    return ans;
}


static inline GLint
block_size(int program, GLuint block_index) {
    GLint ans;
    glGetActiveUniformBlockiv(programs[program].id, block_index, GL_UNIFORM_BLOCK_DATA_SIZE, &ans);
    return ans;
}

static inline void
bind_program(int program) {
    glUseProgram(programs[program].id);
}

static inline void
unbind_program() {
    glUseProgram(0);
}
// }}}

// Buffers {{{

typedef struct {
    GLuint id;
    GLsizeiptr size;
    GLenum usage;
} Buffer;


static Buffer buffers[MAX_CHILDREN * 6 + 4] = {{0}};

static ssize_t
create_buffer(GLenum usage) {
    GLuint buffer_id;
    glGenBuffers(1, &buffer_id);
    for (size_t i = 0; i < sizeof(buffers)/sizeof(buffers[0]); i++) {
        if (buffers[i].id == 0) {
            buffers[i].id = buffer_id;
            buffers[i].size = 0;
            buffers[i].usage = usage;
            return i;
        }
    }
    glDeleteBuffers(1, &buffer_id);
    fatal("Too many buffers");
    return -1;
}

static void
delete_buffer(ssize_t buf_idx) {
    glDeleteBuffers(1, &(buffers[buf_idx].id));
    buffers[buf_idx].id = 0;
    buffers[buf_idx].size = 0;
}

static GLuint
bind_buffer(ssize_t buf_idx) {
    glBindBuffer(buffers[buf_idx].usage, buffers[buf_idx].id);
    return buffers[buf_idx].id;
}

static void
unbind_buffer(ssize_t buf_idx) {
    glBindBuffer(buffers[buf_idx].usage, 0);
}

static inline void
alloc_buffer(ssize_t idx, GLsizeiptr size, GLenum usage) {
    Buffer *b = buffers + idx;
    if (b->size == size) return;
    b->size = size;
    glBufferData(b->usage, size, NULL, usage);
}

static inline void*
map_buffer(ssize_t idx, GLenum access) {
    void *ans = glMapBuffer(buffers[idx].usage, access);
    return ans;
}

static inline void
unmap_buffer(ssize_t idx) {
    glUnmapBuffer(buffers[idx].usage);
}

// }}}

// Vertex Array Objects (VAO) {{{

typedef struct {
    GLuint id;
    size_t num_buffers;
    ssize_t buffers[10];
} VAO;

static VAO vaos[4*MAX_CHILDREN + 10] = {{0}};

static ssize_t
create_vao() {
    GLuint vao_id;
    glGenVertexArrays(1, &vao_id);
    for (size_t i = 0; i < sizeof(vaos)/sizeof(vaos[0]); i++) {
        if (!vaos[i].id) {
            vaos[i].id = vao_id;
            vaos[i].num_buffers = 0;
            glBindVertexArray(vao_id);
            return i;
        }
    }
    glDeleteVertexArrays(1, &vao_id);
    fatal("Too many VAOs");
    return -1;
}

static size_t
add_buffer_to_vao(ssize_t vao_idx, GLenum usage) {
    VAO* vao = vaos + vao_idx;
    if (vao->num_buffers >= sizeof(vao->buffers) / sizeof(vao->buffers[0])) {
        fatal("Too many buffers in a single VAO");
    }
    ssize_t buf = create_buffer(usage);
    vao->buffers[vao->num_buffers++] = buf;
    return vao->num_buffers - 1;
}

static void
add_located_attribute_to_vao(ssize_t vao_idx, GLint aloc, GLint size, GLenum data_type, GLsizei stride, void *offset, GLuint divisor) {
    VAO *vao = vaos + vao_idx;
    if (!vao->num_buffers) fatal("You must create a buffer for this attribute first");
    ssize_t buf = vao->buffers[vao->num_buffers - 1];
    bind_buffer(buf);
    glEnableVertexAttribArray(aloc);
    switch(data_type) {
        case GL_BYTE:
        case GL_UNSIGNED_BYTE:
        case GL_SHORT:
        case GL_UNSIGNED_SHORT:
        case GL_INT:
        case GL_UNSIGNED_INT:
            glVertexAttribIPointer(aloc, size, data_type, stride, offset);
            break;
        default:
            glVertexAttribPointer(aloc, size, data_type, GL_FALSE, stride, offset);
            break;
    }
    if (divisor) {
        glVertexAttribDivisor(aloc, divisor);
    }
    unbind_buffer(buf);
}


static inline void
add_attribute_to_vao(int p, ssize_t vao_idx, const char *name, GLint size, GLenum data_type, GLsizei stride, void *offset, GLuint divisor) {
    GLint aloc = attrib_location(p, name);
    if (aloc == -1) fatal("No attribute named: %s found in this program", name);
    add_located_attribute_to_vao(vao_idx, aloc, size, data_type, stride, offset, divisor);
}

void
remove_vao(ssize_t vao_idx) {
    VAO *vao = vaos + vao_idx;
    while (vao->num_buffers) {
        vao->num_buffers--;
        delete_buffer(vao->buffers[vao->num_buffers]);
    }
    glDeleteVertexArrays(1, &(vao->id));
    vaos[vao_idx].id = 0;
}

static void
bind_vertex_array(ssize_t vao_idx) {
    glBindVertexArray(vaos[vao_idx].id);
}

static void
unbind_vertex_array() {
    glBindVertexArray(0);
}

static ssize_t
alloc_vao_buffer(ssize_t vao_idx, GLsizeiptr size, size_t bufnum, GLenum usage) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    bind_buffer(buf_idx);
    alloc_buffer(buf_idx, size, usage);
    return buf_idx;
}

static void*
map_vao_buffer(ssize_t vao_idx, size_t bufnum, GLenum access) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    bind_buffer(buf_idx);
    return map_buffer(buf_idx, access);
}

static void*
alloc_and_map_vao_buffer(ssize_t vao_idx, GLsizeiptr size, size_t bufnum, GLenum usage, GLenum access) {
    ssize_t buf_idx = alloc_vao_buffer(vao_idx, size, bufnum, usage);
    return map_buffer(buf_idx, access);
}

static void
bind_vao_uniform_buffer(ssize_t vao_idx, size_t bufnum, GLuint block_index) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    glBindBufferBase(GL_UNIFORM_BUFFER, block_index, buffers[buf_idx].id);
}

static void
unmap_vao_buffer(ssize_t vao_idx, size_t bufnum) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    unmap_buffer(buf_idx);
    unbind_buffer(buf_idx);
}

// }}}
