/*
 * gl.c
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "gl.h"
#include <string.h>
#include <stddef.h>
#include "glfw-wrapper.h"
#include "state.h"
#include "png-reader.h"

// GL setup and error handling {{{
static void
check_for_gl_error(void UNUSED *ret, const char *name, GLADapiproc UNUSED funcptr, int UNUSED len_args, ...) {
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

const char*
gl_version_string(void) {
    static char buf[256];
    int gl_major = GLAD_VERSION_MAJOR(global_state.gl_version);
    int gl_minor = GLAD_VERSION_MINOR(global_state.gl_version);
    const char *gvs = (const char*)glGetString(GL_VERSION);
    snprintf(buf, sizeof(buf), "'%s' Detected version: %d.%d", gvs, gl_major, gl_minor);
    return buf;
}

void
gl_init(void) {
    static bool glad_loaded = false;
    if (!glad_loaded) {
        global_state.gl_version = gladLoadGL(glfwGetProcAddress);
        if (!global_state.gl_version) {
            fatal("Loading the OpenGL library failed");
        }
        if (!global_state.debug_rendering) {
            gladUninstallGLDebug();
        }
        gladSetGLPostCallback(check_for_gl_error);
#define ARB_TEST(name) \
        if (!GLAD_GL_ARB_##name) { \
            fatal("The OpenGL driver on this system is missing the required extension: ARB_%s", #name); \
        }
        ARB_TEST(texture_storage);
#undef ARB_TEST
#ifdef __APPLE__
        // See nsgl_context.m srgb is always supported on macOS but its OpenGL
        // drivers dont report the extensions, so hardcode to true.
        global_state.supports_framebuffer_srgb = true;
#else
        global_state.supports_framebuffer_srgb = (GLAD_GL_ARB_framebuffer_sRGB + GLAD_GL_EXT_framebuffer_sRGB) != 0;
#endif
        glad_loaded = true;
        int gl_major = GLAD_VERSION_MAJOR(global_state.gl_version);
        int gl_minor = GLAD_VERSION_MINOR(global_state.gl_version);
        if (global_state.debug_rendering) printf("[%.3f] GL version string: %s\n", monotonic_t_to_s_double(monotonic()), gl_version_string());
        if (gl_major < OPENGL_REQUIRED_VERSION_MAJOR || (gl_major == OPENGL_REQUIRED_VERSION_MAJOR && gl_minor < OPENGL_REQUIRED_VERSION_MINOR)) {
            fatal("OpenGL version is %d.%d, version >= %d.%d required for kitty", gl_major, gl_minor, OPENGL_REQUIRED_VERSION_MAJOR, OPENGL_REQUIRED_VERSION_MINOR);
        }
    }
}

const char*
check_framebuffer_status(void) {
    GLenum status = glCheckFramebufferStatus(GL_FRAMEBUFFER);
    switch (status) {
        case GL_FRAMEBUFFER_COMPLETE: return NULL;
        case GL_FRAMEBUFFER_UNDEFINED: return("GL_FRAMEBUFFER_UNDEFINED");
        case GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT: return("GL_FRAMEBUFFER_INCOMPLETE_ATTACHMENT");
        case GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT: return("GL_FRAMEBUFFER_INCOMPLETE_MISSING_ATTACHMENT");
        case GL_FRAMEBUFFER_INCOMPLETE_DRAW_BUFFER: return("GL_FRAMEBUFFER_INCOMPLETE_DRAW_BUFFER");
        case GL_FRAMEBUFFER_INCOMPLETE_READ_BUFFER: return("GL_FRAMEBUFFER_INCOMPLETE_READ_BUFFER");
        case GL_FRAMEBUFFER_UNSUPPORTED: return("GL_FRAMEBUFFER_UNSUPPORTED");
        case GL_FRAMEBUFFER_INCOMPLETE_MULTISAMPLE: return("GL_FRAMEBUFFER_INCOMPLETE_MULTISAMPLE");
        default: return("Unknown error");
    }
}

void
free_texture(GLuint *tex_id) {
    glDeleteTextures(1, tex_id);
    *tex_id = 0;
}

void
free_framebuffer(GLuint *fb_id) {
    glDeleteFramebuffers(1, fb_id);
    *fb_id = 0;
}

static GLuint output_framebuffer = 0;

void
bind_framebuffer_for_output(unsigned fbid) {
    glBindFramebuffer(GL_FRAMEBUFFER, fbid ? fbid : output_framebuffer);
}

void
set_framebuffer_to_use_for_output(unsigned fbid) {
    output_framebuffer = fbid;
}

static void
set_blending(bool allowed) {
    if (allowed) { glEnable(GL_BLEND); glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA); }  // blending of pre-multiplied colors
    else { glDisable(GL_BLEND); glBlendFunc(GL_ONE, GL_ZERO); }  // no blending
}

void
draw_quad(bool blend, unsigned instance_count) {
    set_blending(blend);
    if (instance_count) glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, instance_count);
    else glDrawArrays(GL_TRIANGLE_FAN, 0, 4);
}

static struct {
    GLsizei items[16][4];
    size_t used;
} saved_viewports;

void
set_gpu_viewport(unsigned w, unsigned h) { glViewport(0, 0, w, h); }

Viewport
get_gpu_viewport(void) {
    GLsizei v[4];
    glGetIntegerv(GL_VIEWPORT, v);
    return (Viewport){.left=v[0], .top=v[1], .width=v[2], .height=v[3]};
}

void
save_viewport_using_bottom_left_origin(GLsizei newx, GLsizei newy, GLsizei width, GLsizei height) {
    if (saved_viewports.used >= arraysz(saved_viewports.items)) fatal("Too many nested saved viewports");
    GLsizei *saved_viewport = saved_viewports.items[saved_viewports.used++];
    glGetIntegerv(GL_VIEWPORT, saved_viewport);
    glViewport(newx, newy, width, height);
}

void
save_viewport_using_top_left_origin(GLsizei newx, GLsizei newy, GLsizei width, GLsizei height, GLsizei full_framebuffer_height) {
    // Converts the viewport defined by the specified arguments which are
    // assumed to be in the usual co-ord system with origin at top left to the
    // OpenGL viewport co-ord system with origin at bottom left.
    // Use restore_viewport() to restore the viewport to what it was before.
    if (saved_viewports.used >= arraysz(saved_viewports.items)) fatal("Too many nested saved viewports");
    GLsizei *saved_viewport = saved_viewports.items[saved_viewports.used++];
    glGetIntegerv(GL_VIEWPORT, saved_viewport);
    newy = full_framebuffer_height - (newy + height);
    glViewport(newx, newy, width, height);
}

void
restore_viewport(void) {
    if (!saved_viewports.used) fatal("Trying to restore a viewport when none is saved");
    GLsizei *saved_viewport = saved_viewports.items[--saved_viewports.used];
    glViewport(saved_viewport[0], saved_viewport[1], saved_viewport[2], saved_viewport[3]);
}

void
enable_scissor_using_top_left_origin(Viewport vp, unsigned full_framebuffer_height) {
    glEnable(GL_SCISSOR_TEST);
    GLsizei newy = full_framebuffer_height - (vp.top + vp.height);
    glScissor(vp.left, newy, vp.width, vp.height);
}

void
disable_scissor(void) { glDisable(GL_SCISSOR_TEST); }

static float
linear_to_srgb(float c) { return (c <= 0.0031308f) ? 12.92f * c : 1.055f * powf(c, 1.0f / 2.4f) - 0.055f; }

void
save_texture_as_png(uint32_t texture_id, const char *filename) {
    GLint prev_tex = 0; glGetIntegerv(GL_TEXTURE_BINDING_2D, &prev_tex);
    glBindTexture(GL_TEXTURE_2D, texture_id);
    int width = 0, height = 0;
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH, &width);
    glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_HEIGHT, &height);
    size_t sz = sizeof(uint32_t) * width * height;
    uint32_t* data = malloc(sz);
    glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE, data);
    // assume data is linear and pre-multiplied
    for (int i = 0; i < width * height; i++) {
        uint32_t px = data[i];
        uint8_t r = (px >>  0) & 0xFF; uint8_t g = (px >>  8) & 0xFF; uint8_t b = (px >> 16) & 0xFF;
        uint8_t a = (px >> 24) & 0xFF; float alpha = a / 255.0f;
        float rf = 0, gf = 0, bf = 0;
        if (alpha > 0.0f) { rf = (r / 255.0f) / alpha; gf = (g / 255.0f) / alpha; bf = (b / 255.0f) / alpha; }
        rf = linear_to_srgb(rf); gf = linear_to_srgb(gf); bf = linear_to_srgb(bf);
        r = (uint8_t)(rf*255); g = (uint8_t)(gf * 255); b = (uint8_t)(bf * 255);
        data[i] = (r <<  0) | (g << 8) | (b << 16) | (a << 24);
    }

    const char *png = png_from_32bit_rgba((char*)data, width, height, &sz, true);
    if (!sz) fatal("Failed to save PNG to %s with error: %s", filename, png);
    free(data);
    FILE* file = fopen(filename, "wb");
    fwrite(png, 1, sz, file);
    fclose(file);
    glBindTexture(GL_TEXTURE_2D, prev_tex);
}


// }}}

// Programs {{{

static Program programs[64] = {{0}};

GLuint
compile_shaders(GLenum shader_type, GLsizei count, const GLchar * const * source) {
    GLuint shader_id = glCreateShader(shader_type);
    glShaderSource(shader_id, count, source, NULL);
    glCompileShader(shader_id);
    GLint ret = GL_FALSE;
    glGetShaderiv(shader_id, GL_COMPILE_STATUS, &ret);
    if (ret != GL_TRUE) {
        GLsizei len;
        static char glbuf[4096];
        glGetShaderInfoLog(shader_id, sizeof(glbuf), &len, glbuf);
        glDeleteShader(shader_id);
        const char *shader_type_name = "unknown_type";
        switch(shader_type) {
            case GL_VERTEX_SHADER:
                shader_type_name = "vertex"; break;
            case GL_FRAGMENT_SHADER:
                shader_type_name = "fragment"; break;
        }
        PyErr_Format(PyExc_ValueError, "Failed to compile GLSL %s shader:\n%s", shader_type_name, glbuf);
        return 0;
    }
    return shader_id;
}

Program*
program_ptr(int program) { return programs + (size_t)program; }

GLuint
program_id(int program) { return programs[program].id; }


void
init_uniforms(int program) {
    Program *p = programs + program;
    glGetProgramiv(p->id, GL_ACTIVE_UNIFORMS, &(p->num_of_uniforms));
    for (GLint i = 0; i < p->num_of_uniforms; i++) {
        Uniform *u = p->uniforms + i;
        glGetActiveUniform(p->id, (GLuint)i, sizeof(u->name)/sizeof(u->name[0]), NULL, &(u->size), &(u->type), u->name);
        char *l = strchr(u->name, '[');
        if (l) *l = 0;
        u->location = glGetUniformLocation(p->id, u->name);
        u->idx = i;
    }
}

GLint
get_uniform_location(int program, const char *name) {
    Program *p = programs + program;
    const size_t n = strlen(name) + 1;
    for (GLint i = 0; i < p->num_of_uniforms; i++) {
        Uniform *u = p->uniforms + i;
        if (strncmp(u->name, name, n) == 0) return u->location;
    }
    return -1;
}

GLint
get_uniform_information(int program, const char *name, GLenum information_type) {
    GLint q; GLuint t;
    const char* names[] = {""};
    names[0] = name;
    GLuint pid = program_id(program);
    glGetUniformIndices(pid, 1, (void*)names, &t);
    glGetActiveUniformsiv(pid, 1, &t, information_type, &q);
    return q;
}

GLint
attrib_location(int program, const char *name) {
    GLint ans = glGetAttribLocation(programs[program].id, name);
    return ans;
}

GLuint
block_index(int program, const char *name) {
    GLuint ans = glGetUniformBlockIndex(programs[program].id, name);
    if (ans == GL_INVALID_INDEX) { fatal("Could not find block index for %s", name); }
    return ans;
}


GLint
block_size(int program, GLuint block_index) {
    GLint ans;
    glGetActiveUniformBlockiv(programs[program].id, block_index, GL_UNIFORM_BLOCK_DATA_SIZE, &ans);
    return ans;
}

void
bind_program(int program) {
    glUseProgram(programs[program].id);
}

void
unbind_program(void) {
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

static void
alloc_buffer(ssize_t idx, GLsizeiptr size, GLenum usage) {
    Buffer *b = buffers + idx;
    if (b->size == size) return;
    b->size = size;
    glBufferData(b->usage, size, NULL, usage);
}

static void*
map_buffer(ssize_t idx, GLenum access) {
    void *ans = glMapBuffer(buffers[idx].usage, access);
    return ans;
}

static void
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

ssize_t
create_vao(void) {
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

size_t
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
        glVertexAttribDivisorARB(aloc, divisor);
    }
    unbind_buffer(buf);
}


void
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

void
bind_vertex_array(ssize_t vao_idx) {
    glBindVertexArray(vaos[vao_idx].id);
}

void
unbind_vertex_array(void) {
    glBindVertexArray(0);
}

ssize_t
alloc_vao_buffer(ssize_t vao_idx, GLsizeiptr size, size_t bufnum, GLenum usage) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    bind_buffer(buf_idx);
    alloc_buffer(buf_idx, size, usage);
    return buf_idx;
}

void*
map_vao_buffer(ssize_t vao_idx, size_t bufnum, GLenum access) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    bind_buffer(buf_idx);
    return map_buffer(buf_idx, access);
}

void*
alloc_and_map_vao_buffer(ssize_t vao_idx, GLsizeiptr size, size_t bufnum, GLenum usage, GLenum access) {
    ssize_t buf_idx = alloc_vao_buffer(vao_idx, size, bufnum, usage);
    return map_buffer(buf_idx, access);
}

void
bind_vao_uniform_buffer(ssize_t vao_idx, size_t bufnum, GLuint block_index) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    glBindBufferBase(GL_UNIFORM_BUFFER, block_index, buffers[buf_idx].id);
}

void
unmap_vao_buffer(ssize_t vao_idx, size_t bufnum) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    unmap_buffer(buf_idx);
    unbind_buffer(buf_idx);
}

// }}}
