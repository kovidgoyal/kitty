/*
 * shaders.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "screen.h"
#ifdef __APPLE__
#include <OpenGL/gl3.h>
#include <OpenGL/gl3ext.h>
#else
#include <GL/glew.h>
#endif
#include <string.h>

static char glbuf[4096];

// GL setup and error handling {{{
// Required minimum OpenGL version
#define REQUIRED_VERSION_MAJOR 3
#define REQUIRED_VERSION_MINOR 3
#define GLSL_VERSION (REQUIRED_VERSION_MAJOR * 100 + REQUIRED_VERSION_MINOR * 10)

#ifndef GL_STACK_UNDERFLOW
#define GL_STACK_UNDERFLOW 0x0504
#endif

#ifndef GL_STACK_OVERFLOW
#define GL_STACK_OVERFLOW 0x0503
#endif

#define fatal(...) { fprintf(stderr, __VA_ARGS__); fprintf(stderr, "\n"); exit(EXIT_FAILURE); }
#define fatal_msg(msg) fatal("%s", msg);

static void
check_for_gl_error(int line) {
#define f(msg) fatal("%s (at line: %d)", msg, line); break;
    int code = glGetError();
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
            f("An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_OVERFLOW)"); 
        default: 
            fatal("An unknown OpenGL error occurred with code: %d (at line: %d)", code, line); 
            break;
    }
}

static bool _enable_error_checking = false;
#define check_gl() { if (_enable_error_checking) check_for_gl_error(__LINE__); }

static PyObject* 
glew_init(PyObject UNUSED *self) {
#ifndef __APPLE__
    GLenum err = glewInit();
    if (err != GLEW_OK) {
        PyErr_Format(PyExc_RuntimeError, "GLEW init failed: %s", glewGetErrorString(err));
        return NULL;
    }
#define ARB_TEST(name) \
    if (!GLEW_ARB_##name) { \
        PyErr_Format(PyExc_RuntimeError, "The OpenGL driver on this system is missing the required extension: ARB_%s", #name); \
        return NULL; \
    }
    ARB_TEST(texture_storage);
#undef ARB_TEST
#endif
    Py_RETURN_NONE;
}
// }}}

// Programs {{{
enum ProgramNames { CELL_PROGRAM, CURSOR_PROGRAM, BORDERS_PROGRAM, NUM_PROGRAMS };

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

static Program programs[NUM_PROGRAMS] = {{0}};

static inline GLuint
compile_shader(GLenum shader_type, const char *source) {
    GLuint shader_id = glCreateShader(shader_type);
    check_gl();
    glShaderSource(shader_id, 1, (const GLchar **)&source, NULL);
    check_gl();
    glCompileShader(shader_id);
    check_gl();
    GLint ret = GL_FALSE;
    glGetShaderiv(shader_id, GL_COMPILE_STATUS, &ret);
    if (ret != GL_TRUE) {
        GLsizei len;
        glGetShaderInfoLog(shader_id, sizeof(glbuf), &len, glbuf);
        fprintf(stderr, "Failed to compile GLSL shader!\n%s", glbuf);
        glDeleteShader(shader_id);
        PyErr_SetString(PyExc_ValueError, "Failed to compile shader");
        return 0;
    }
    return shader_id;
}


static inline void
init_uniforms(int program) {
    Program *p = programs + program;
    glGetProgramiv(p->id, GL_ACTIVE_UNIFORMS, &(p->num_of_uniforms));
    check_gl();
    for (GLint i = 0; i < p->num_of_uniforms; i++) {
        Uniform *u = p->uniforms + i;
        glGetActiveUniform(p->id, (GLuint)i, sizeof(u->name)/sizeof(u->name[0]), NULL, &(u->size), &(u->type), u->name);
        check_gl();
        u->location = glGetUniformLocation(p->id, u->name);
        u->idx = i;
    }
}


static inline GLint
attrib_location(int program, const char *name) {
    GLint ans = glGetAttribLocation(programs[program].id, name);
    check_gl();
    return ans;
}

static inline GLuint
block_index(int program, const char *name) {
    GLuint ans = glGetUniformBlockIndex(programs[program].id, name);
    check_gl();
    if (ans == GL_INVALID_INDEX) { fatal("Could not find block index"); }
    return ans;
}


static inline GLint
block_size(int program, GLuint block_index) {
    GLint ans;
    glGetActiveUniformBlockiv(programs[program].id, block_index, GL_UNIFORM_BLOCK_DATA_SIZE, &ans);
    check_gl();
    return ans;
}

static GLint
block_offset(int program, GLuint uniform_idx) {
    GLint program_id = programs[program].id;
    GLint ans;
    glGetActiveUniformsiv(program_id, 1, &uniform_idx, GL_UNIFORM_OFFSET, &ans);
    check_gl();
    return ans;
}

static void
bind_program(int program) {
    glUseProgram(programs[program].id);
    check_gl();
}

static void
unbind_program() {
    glUseProgram(0);
    check_gl();
}
// }}}

// Buffers {{{

typedef struct {
    GLuint id;
    GLsizeiptr size;
    GLenum usage;
} Buffer;


static Buffer buffers[MAX_CHILDREN * 4 + 4] = {{0}};

static ssize_t
create_buffer(GLenum usage) {
    GLuint buffer_id;
    glGenBuffers(1, &buffer_id);
    check_gl();
    for (size_t i = 0; i < sizeof(buffers)/sizeof(buffers[0]); i++) {
        if (buffers[i].id == 0) {
            buffers[i].id = buffer_id;
            buffers[i].size = 0;
            buffers[i].usage = usage;
            return i;
        }
    }
    glDeleteBuffers(1, &buffer_id);
    fatal("too many buffers");
    return -1;
}

static void
delete_buffer(ssize_t buf_idx) {
    glDeleteBuffers(1, &(buffers[buf_idx].id));
    check_gl();
    buffers[buf_idx].id = 0;
    buffers[buf_idx].size = 0;
}

static GLuint
bind_buffer(ssize_t buf_idx) {
    glBindBuffer(buffers[buf_idx].usage, buffers[buf_idx].id);
    check_gl();
    return buffers[buf_idx].id;
}

static void
unbind_buffer(ssize_t buf_idx) {
    glBindBuffer(buffers[buf_idx].usage, 0);
    check_gl();
}

static inline void
alloc_buffer(ssize_t idx, GLsizeiptr size, GLenum usage) {
    Buffer *b = buffers + idx;
    if (b->size == size) return;
    b->size = size;
    glBufferData(b->usage, size, NULL, usage);
    check_gl();
}

static inline void*
map_buffer(ssize_t idx, GLenum access) {
    void *ans = glMapBuffer(buffers[idx].usage, access);
    check_gl();
    return ans;
}

static inline void
unmap_buffer(ssize_t idx) {
    glUnmapBuffer(buffers[idx].usage);
    check_gl();
}

// }}}

// Vertex Array Objects (VAO) {{{

typedef struct {
    GLuint id;
    size_t num_buffers;
    ssize_t buffers[10];
} VAO;

static VAO vaos[MAX_CHILDREN + 10] = {{0}};

static ssize_t
create_vao() {
    GLuint vao_id;
    glGenVertexArrays(1, &vao_id);
    check_gl();
    for (size_t i = 0; i < sizeof(vaos)/sizeof(vaos[0]); i++) {
        if (!vaos[i].id) {
            vaos[i].id = vao_id;
            vaos[i].num_buffers = 0;
            glBindVertexArray(vao_id);
            check_gl();
            return i;
        }
    }
    glDeleteVertexArrays(1, &vao_id);
    fatal("too many VAOs");
    return -1;
}

static void
add_buffer_to_vao(ssize_t vao_idx, GLenum usage) {
    VAO* vao = vaos + vao_idx;
    if (vao->num_buffers >= sizeof(vao->buffers) / sizeof(vao->buffers[0])) {
        fatal("too many buffers in a single VAO");
        return;
    }
    ssize_t buf = create_buffer(usage);
    vao->buffers[vao->num_buffers++] = buf;
}

static void
add_attribute_to_vao(int p, ssize_t vao_idx, const char *name, GLint size, GLenum data_type, GLsizei stride, void *offset, GLuint divisor) {
    VAO *vao = vaos + vao_idx;
    if (!vao->num_buffers) { fatal("You must create a buffer for this attribute first"); return; }
    GLint aloc = attrib_location(p, name);
    if (aloc == -1) { fatal("No attribute named: %s found in this program", name); return; }
    ssize_t buf = vao->buffers[vao->num_buffers - 1];
    bind_buffer(buf);
    glEnableVertexAttribArray(aloc);
    check_gl();
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
    check_gl();
    if (divisor) {
        glVertexAttribDivisor(aloc, divisor);
        check_gl();
    }
    unbind_buffer(buf);
    return;
}

static void
remove_vao(ssize_t vao_idx) {
    VAO *vao = vaos + vao_idx;
    while (vao->num_buffers) {
        vao->num_buffers--;
        delete_buffer(vao->buffers[vao->num_buffers]);
    }
    glDeleteVertexArrays(1, &(vao->id));
    check_gl();
    vaos[vao_idx].id = 0;
}

static void
bind_vertex_array(ssize_t vao_idx) {
    glBindVertexArray(vaos[vao_idx].id);
    check_gl();
}

static void
unbind_vertex_array() {
    glBindVertexArray(0);
    check_gl();
}

static void*
map_vao_buffer(ssize_t vao_idx, GLsizeiptr size, size_t bufnum, GLenum usage, GLenum access) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    bind_buffer(buf_idx);
    alloc_buffer(buf_idx, size, usage);
    void *ans = map_buffer(buf_idx, access);
    return ans;
}

static void
bind_vao_uniform_buffer(ssize_t vao_idx, size_t bufnum, GLuint block_index) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    glBindBufferBase(GL_UNIFORM_BUFFER, block_index, buffers[buf_idx].id);
    check_gl();
}

static void
unmap_vao_buffer(ssize_t vao_idx, size_t bufnum) {
    ssize_t buf_idx = vaos[vao_idx].buffers[bufnum];
    unmap_buffer(buf_idx);
    unbind_buffer(buf_idx);
}

// }}}

// Cell {{{

enum CellUniforms { CELL_dimensions, CELL_default_colors, CELL_color_indices, CELL_steps, CELL_sprites, CELL_sprite_layout, CELL_color_table, NUM_CELL_UNIFORMS };
static GLint cell_uniform_locations[NUM_CELL_UNIFORMS] = {0};
static GLint cell_color_table_stride = 0, cell_color_table_offset = 0, cell_color_table_size = 0, cell_color_table_block_index = 0;

static void
init_cell_program() {
    Program *p = programs + CELL_PROGRAM;
    int left = NUM_CELL_UNIFORMS;
    GLint ctable_idx = 0;
    for (int i = 0; i < p->num_of_uniforms; i++, left--) {
#define SET_LOC(which) if (strcmp(p->uniforms[i].name, #which) == 0) cell_uniform_locations[CELL_##which] = p->uniforms[i].location
        SET_LOC(dimensions);
        else SET_LOC(default_colors);
        else SET_LOC(color_indices);
        else SET_LOC(steps);
        else SET_LOC(sprites);
        else SET_LOC(sprite_layout);
        else if (strcmp(p->uniforms[i].name, "color_table[0]") == 0) { ctable_idx = i; cell_uniform_locations[CELL_color_table] = p->uniforms[i].location; }
        else { fatal("Unknown uniform in cell program: %s", p->uniforms[i].name); }
    }
    if (left) { fatal("Left over uniforms in cell program"); }
    cell_color_table_block_index = block_index(CELL_PROGRAM, "ColorTable");
    cell_color_table_size = block_size(CELL_PROGRAM, cell_color_table_block_index);
    cell_color_table_stride = cell_color_table_size / (256 * sizeof(GLuint));
    cell_color_table_offset = block_offset(CELL_PROGRAM, ctable_idx);
#undef SET_LOC
}

static ssize_t
create_cell_vao() {
    ssize_t vao_idx = create_vao();
#define A(name, size, dtype, offset, stride) \
    add_attribute_to_vao(CELL_PROGRAM, vao_idx, #name, \
            /*size=*/size, /*dtype=*/dtype, /*stride=*/stride, /*offset=*/offset, /*divisor=*/1);
#define A1(name, size, dtype, offset) A(name, size, dtype, (void*)(offsetof(Cell, offset)), sizeof(Cell))

    add_buffer_to_vao(vao_idx, GL_ARRAY_BUFFER);
    A1(text_attrs, 1, GL_UNSIGNED_INT, ch);
    A1(sprite_coords, 3, GL_UNSIGNED_SHORT, sprite_x);
    A1(colors, 3, GL_UNSIGNED_INT, fg);
    add_buffer_to_vao(vao_idx, GL_ARRAY_BUFFER);
    A(is_selected, 1, GL_FLOAT, NULL, 0);
    add_buffer_to_vao(vao_idx, GL_UNIFORM_BUFFER);
    bind_vao_uniform_buffer(vao_idx, 2, cell_color_table_block_index);
    return vao_idx;
#undef A
#undef A1
}

static void 
draw_cells(ssize_t vao_idx, GLfloat xstart, GLfloat ystart, GLfloat dx, GLfloat dy, bool inverted, Screen *screen) {
    size_t sz;
    void *address;
    if (screen->modes.mDECSCNM) inverted = inverted ? false : true;
    if (screen->scroll_changed || screen->is_dirty) {
        sz = sizeof(Cell) * screen->lines * screen->columns;
        address = map_vao_buffer(vao_idx, sz, 0, GL_STREAM_DRAW, GL_WRITE_ONLY);
        screen_update_cell_data(screen, address, sz);
        unmap_vao_buffer(vao_idx, 0);
    }
    if (screen_is_selection_dirty(screen)) {
        sz = sizeof(GLfloat) * screen->lines * screen->columns;
        address = map_vao_buffer(vao_idx, sz, 1, GL_STREAM_DRAW, GL_WRITE_ONLY);
        screen_apply_selection(screen, address, sz);
        unmap_vao_buffer(vao_idx, 1);
    }
    if (UNLIKELY(screen->color_profile->dirty)) {
        address = map_vao_buffer(vao_idx, cell_color_table_size, 2, GL_STATIC_DRAW, GL_WRITE_ONLY);
        copy_color_table_to_buffer(screen->color_profile, address, cell_color_table_offset, cell_color_table_stride);
        unmap_vao_buffer(vao_idx, 2);
    }
#define UL(name) cell_uniform_locations[CELL_##name]
    bind_program(CELL_PROGRAM); 
    glUniform2ui(UL(dimensions), screen->columns, screen->lines);
    check_gl();
    glUniform4f(UL(steps), xstart, ystart, dx, dy);
    check_gl();
    glUniform2i(UL(color_indices), inverted & 1, 1 - (inverted & 1));
    check_gl();
#define COLOR(name) colorprofile_to_color(screen->color_profile, screen->color_profile->overridden.name, screen->color_profile->configured.name)
    glUniform4ui(UL(default_colors), COLOR(default_fg), COLOR(default_bg), COLOR(highlight_fg), COLOR(highlight_bg));
    check_gl();
#undef COLOR
    glUniform1i(UL(sprites), 0);
    check_gl();
    unsigned int x, y, z;
    sprite_map_current_layout(&x, &y, &z);
    glUniform2f(UL(sprite_layout), 1.0 / (float)x, 1.0 / (float)y);
    check_gl();
    bind_vertex_array(vao_idx);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns);
    check_gl();
    unbind_vertex_array();
    unbind_program();
#undef UL
}
// }}}

// Cursor {{{
enum CursorUniforms { CURSOR_color, CURSOR_xpos, CURSOR_ypos, NUM_CURSOR_UNIFORMS };
static GLint cursor_uniform_locations[NUM_CURSOR_UNIFORMS] = {0};
static ssize_t cursor_vertex_array;

static void
init_cursor_program() {
    Program *p = programs + CURSOR_PROGRAM;
    int left = NUM_CURSOR_UNIFORMS;
    cursor_vertex_array = create_vao();
    for (int i = 0; i < p->num_of_uniforms; i++, left--) {
#define SET_LOC(which) if (strcmp(p->uniforms[i].name, #which) == 0) cursor_uniform_locations[CURSOR_##which] = p->uniforms[i].location
        SET_LOC(color);
        else SET_LOC(xpos);
        else SET_LOC(ypos);
        else { fatal("Unknown uniform in cursor program"); }
    }
    if (left) { fatal("Left over uniforms in cursor program"); }
#undef SET_LOC
}

static void 
draw_cursor(bool semi_transparent, bool is_focused, color_type color, float alpha, float left, float right, float top, float bottom) {
    if (semi_transparent) { glEnable(GL_BLEND); check_gl(); }
    bind_program(CURSOR_PROGRAM); bind_vertex_array(cursor_vertex_array);
    glUniform4f(cursor_uniform_locations[CURSOR_color], ((color >> 16) & 0xff) / 255.0, ((color >> 8) & 0xff) / 255.0, (color & 0xff) / 255.0, alpha);
    check_gl();
    glUniform2f(cursor_uniform_locations[CURSOR_xpos], left, right);
    check_gl();
    glUniform2f(cursor_uniform_locations[CURSOR_ypos], top, bottom);
    check_gl();
    glDrawArrays(is_focused ? GL_TRIANGLE_FAN : GL_LINE_LOOP, 0, 4);
    check_gl();
    unbind_vertex_array(); unbind_program();
    if (semi_transparent) { glDisable(GL_BLEND); check_gl(); }
}
// }}}

// Borders {{{
enum BorderUniforms { BORDER_viewport, NUM_BORDER_UNIFORMS };
static GLint border_uniform_locations[NUM_BORDER_UNIFORMS] = {0};
static ssize_t border_vertex_array;
static GLsizei num_border_rects = 0;
static GLuint rect_buf[5 * 1024];
static GLuint *rect_pos = NULL;

static void
init_borders_program() {
    Program *p = programs + BORDERS_PROGRAM;
    int left = NUM_BORDER_UNIFORMS;
    border_vertex_array = create_vao();
    for (int i = 0; i < p->num_of_uniforms; i++, left--) {
#define SET_LOC(which) if (strcmp(p->uniforms[i].name, #which) == 0) border_uniform_locations[BORDER_##which] = p->uniforms[i].location
        SET_LOC(viewport);
        else { fatal("Unknown uniform in borders program"); return; }
    }
    if (left) { fatal("Left over uniforms in borders program"); return; }
#undef SET_LOC
    add_buffer_to_vao(border_vertex_array, GL_ARRAY_BUFFER);
    add_attribute_to_vao(BORDERS_PROGRAM, border_vertex_array, "rect",
            /*size=*/4, /*dtype=*/GL_UNSIGNED_INT, /*stride=*/sizeof(GLuint)*5, /*offset=*/0, /*divisor=*/1);
    add_attribute_to_vao(BORDERS_PROGRAM, border_vertex_array, "rect_color",
            /*size=*/1, /*dtype=*/GL_UNSIGNED_INT, /*stride=*/sizeof(GLuint)*5, /*offset=*/(void*)(sizeof(GLuint)*4), /*divisor=*/1);
}

static void
draw_borders() {
    if (num_border_rects) {
        bind_program(BORDERS_PROGRAM);
        bind_vertex_array(border_vertex_array);
        glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, num_border_rects);
        check_gl();
        unbind_vertex_array();
        unbind_program();
    }
}

static void
add_borders_rect(GLuint left, GLuint top, GLuint right, GLuint bottom, GLuint color) {
    if (!left && !top && !right && !bottom) { num_border_rects = 0;  rect_pos = rect_buf; return; }
    num_border_rects++;
    *(rect_pos++) = left;
    *(rect_pos++) = top;
    *(rect_pos++) = right;
    *(rect_pos++) = bottom;
    *(rect_pos++) = color;
}

static void
send_borders_rects(GLuint vw, GLuint vh) {
    if (num_border_rects) {
        size_t sz = sizeof(GLuint) * 5 * num_border_rects;
        void *borders_buf_address = map_vao_buffer(border_vertex_array, sz, 0, GL_STATIC_DRAW, GL_WRITE_ONLY);
        if (borders_buf_address) memcpy(borders_buf_address, rect_buf, sz);
        unmap_vao_buffer(border_vertex_array, 0);
    }
    bind_program(BORDERS_PROGRAM);
    glUniform2ui(border_uniform_locations[BORDER_viewport], vw, vh);
    check_gl();
    unbind_program();
}
// }}}

// Python API {{{
static PyObject*
enable_automatic_opengl_error_checking(PyObject UNUSED *self, PyObject *val) {
    _enable_error_checking = PyObject_IsTrue(val) ? true : false;
    Py_RETURN_NONE;
}

static PyObject*
compile_program(PyObject UNUSED *self, PyObject *args) {
    const char *vertex_shader, *fragment_shader;
    int which;
    GLuint vertex_shader_id = 0, fragment_shader_id = 0;
    if (!PyArg_ParseTuple(args, "iss", &which, &vertex_shader, &fragment_shader)) return NULL;
    if (which < CELL_PROGRAM || which >= NUM_PROGRAMS) { PyErr_Format(PyExc_ValueError, "Unknown program: %d", which); return NULL; }
    if (programs[which].id != 0) { PyErr_SetString(PyExc_ValueError, "program already compiled"); return NULL; }
    programs[which].id = glCreateProgram();
    check_gl();
    vertex_shader_id = compile_shader(GL_VERTEX_SHADER, vertex_shader);
    fragment_shader_id = compile_shader(GL_FRAGMENT_SHADER, fragment_shader);
    glAttachShader(programs[which].id, vertex_shader_id);
    check_gl();
    glAttachShader(programs[which].id, fragment_shader_id);
    check_gl();
    glLinkProgram(programs[which].id);
    check_gl();
    GLint ret = GL_FALSE;
    glGetProgramiv(programs[which].id, GL_LINK_STATUS, &ret);
    if (ret != GL_TRUE) {
        GLsizei len;
        glGetProgramInfoLog(programs[which].id, sizeof(glbuf), &len, glbuf);
        fprintf(stderr, "Failed to compile GLSL shader!\n%s", glbuf);
        PyErr_SetString(PyExc_ValueError, "Failed to compile shader");
        goto end;
    }
    init_uniforms(which);

end:
    if (vertex_shader_id != 0) glDeleteShader(vertex_shader_id);
    if (fragment_shader_id != 0) glDeleteShader(fragment_shader_id);
    check_gl();
    if (PyErr_Occurred()) { glDeleteProgram(programs[which].id); programs[which].id = 0; return NULL;}
    return Py_BuildValue("I", programs[which].id);
    Py_RETURN_NONE;
}

#define PYWRAP0(name) static PyObject* py##name(PyObject UNUSED *self)
#define PYWRAP1(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args)
#define PYWRAP2(name) static PyObject* py##name(PyObject UNUSED *self, PyObject *args, PyObject *kw)
#define PA(fmt, ...) if(!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;
#define ONE_INT(name) PYWRAP1(name) { name(PyLong_AsSsize_t(args)); Py_RETURN_NONE; } 
#define TWO_INT(name) PYWRAP1(name) { int a, b; PA("ii", &a, &b); name(a, b); Py_RETURN_NONE; } 
#define NO_ARG(name) PYWRAP0(name) { name(); Py_RETURN_NONE; }
#define NO_ARG_INT(name) PYWRAP0(name) { return PyLong_FromSsize_t(name()); }

ONE_INT(bind_program)
NO_ARG(unbind_program)

PYWRAP0(create_vao) {
    int ans = create_vao();
    if (ans < 0) return NULL;
    return Py_BuildValue("i", ans);
}

ONE_INT(remove_vao)

ONE_INT(bind_vertex_array)
NO_ARG(unbind_vertex_array)
TWO_INT(unmap_vao_buffer)
PYWRAP1(map_vao_buffer) {
    int vao_idx, bufnum=0, size, usage=GL_STREAM_DRAW, access=GL_WRITE_ONLY;
    PA("ii|iii", &vao_idx, &size, &bufnum, &usage, &access); 
    void *ans = map_vao_buffer(vao_idx, size, bufnum, usage, access); 
    return PyLong_FromVoidPtr(ans); 
}

NO_ARG(init_cursor_program)
PYWRAP1(draw_cursor) {
    int semi_transparent, is_focused;
    unsigned int color;
    float alpha, left, right, top, bottom;
    PA("ppIfffff", &semi_transparent, &is_focused, &color, &alpha, &left, &right, &top, &bottom);
    draw_cursor(semi_transparent, is_focused, color, alpha, left, right, top, bottom);
    Py_RETURN_NONE;
}

NO_ARG(init_borders_program)
NO_ARG(draw_borders)
PYWRAP1(add_borders_rect) { unsigned int a, b, c, d, e; PA("IIIII", &a, &b, &c, &d, &e); add_borders_rect(a, b, c, d, e); Py_RETURN_NONE; }
TWO_INT(send_borders_rects)

NO_ARG(init_cell_program)
NO_ARG_INT(create_cell_vao)
PYWRAP1(draw_cells) { 
    float xstart, ystart, dx, dy;
    int vao_idx, inverted;
    Screen *screen;

    PA("iffffpO", &vao_idx, &xstart, &ystart, &dx, &dy, &inverted, &screen); 
    draw_cells(vao_idx, xstart, ystart, dx, dy, inverted & 1, screen);
    Py_RETURN_NONE;
}

#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, NULL}
#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}
static PyMethodDef module_methods[] = {
    M(enable_automatic_opengl_error_checking, METH_O),
    {"glewInit", (PyCFunction)glew_init, METH_NOARGS, NULL}, 
    M(compile_program, METH_VARARGS),
    MW(create_vao, METH_NOARGS),
    MW(remove_vao, METH_O),
    MW(bind_vertex_array, METH_O),
    MW(unbind_vertex_array, METH_NOARGS),
    MW(map_vao_buffer, METH_VARARGS),
    MW(unmap_vao_buffer, METH_VARARGS),
    MW(bind_program, METH_O),
    MW(unbind_program, METH_NOARGS),
    MW(init_cursor_program, METH_NOARGS),
    MW(draw_cursor, METH_VARARGS),
    MW(init_borders_program, METH_NOARGS),
    MW(draw_borders, METH_NOARGS),
    MW(add_borders_rect, METH_VARARGS),
    MW(send_borders_rects, METH_VARARGS),
    MW(init_cell_program, METH_NOARGS),
    MW(create_cell_vao, METH_NOARGS),
    MW(draw_cells, METH_VARARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_shaders(PyObject *module) {
#define C(x) if (PyModule_AddIntConstant(module, #x, x) != 0) { PyErr_NoMemory(); return false; }
    C(CELL_PROGRAM); C(CURSOR_PROGRAM); C(BORDERS_PROGRAM);
    C(GLSL_VERSION);
    C(GL_VERSION);
    C(GL_VENDOR);
    C(GL_SHADING_LANGUAGE_VERSION);
    C(GL_RENDERER);
    C(GL_TRIANGLE_FAN); C(GL_TRIANGLE_STRIP); C(GL_TRIANGLES); C(GL_LINE_LOOP);
    C(GL_COLOR_BUFFER_BIT);
    C(GL_VERTEX_SHADER);
    C(GL_FRAGMENT_SHADER);
    C(GL_TRUE);
    C(GL_FALSE);
    C(GL_COMPILE_STATUS);
    C(GL_LINK_STATUS);
    C(GL_TEXTURE0); C(GL_TEXTURE1); C(GL_TEXTURE2); C(GL_TEXTURE3); C(GL_TEXTURE4); C(GL_TEXTURE5); C(GL_TEXTURE6); C(GL_TEXTURE7); C(GL_TEXTURE8);
    C(GL_MAX_ARRAY_TEXTURE_LAYERS); C(GL_TEXTURE_BINDING_BUFFER); C(GL_MAX_TEXTURE_BUFFER_SIZE);
    C(GL_MAX_TEXTURE_SIZE);
    C(GL_TEXTURE_2D_ARRAY);
    C(GL_LINEAR); C(GL_CLAMP_TO_EDGE); C(GL_NEAREST);
    C(GL_TEXTURE_MIN_FILTER); C(GL_TEXTURE_MAG_FILTER);
    C(GL_TEXTURE_WRAP_S); C(GL_TEXTURE_WRAP_T);
    C(GL_UNPACK_ALIGNMENT);
    C(GL_R8); C(GL_RED); C(GL_UNSIGNED_BYTE); C(GL_UNSIGNED_SHORT); C(GL_R32UI); C(GL_RGB32UI); C(GL_RGBA);
    C(GL_TEXTURE_BUFFER); C(GL_STATIC_DRAW); C(GL_STREAM_DRAW); C(GL_DYNAMIC_DRAW);
    C(GL_SRC_ALPHA); C(GL_ONE_MINUS_SRC_ALPHA); 
    C(GL_WRITE_ONLY); C(GL_READ_ONLY); C(GL_READ_WRITE);
    C(GL_BLEND); C(GL_FLOAT); C(GL_UNSIGNED_INT); C(GL_ARRAY_BUFFER); C(GL_UNIFORM_BUFFER);

#undef C
    PyModule_AddObject(module, "GL_VERSION_REQUIRED", Py_BuildValue("II", REQUIRED_VERSION_MAJOR, REQUIRED_VERSION_MINOR));
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
// }}}
