/*
 * shaders.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "gl.h"

// Sprites {{{
typedef struct {
    int xnum, ynum, x, y, z, last_num_of_layers, last_ynum;
    unsigned int cell_width, cell_height;
    GLuint texture_id;
    GLenum texture_unit;
    GLint max_texture_size, max_array_texture_layers;
    PyObject *render_cell;
} SpriteMap;

static SpriteMap sprite_map = { .xnum = 1, .ynum = 1, .last_num_of_layers = 1, .last_ynum = -1, .texture_unit = GL_TEXTURE0 };

#ifdef __APPLE__ 
#define glCopyImageSubData(...)
#define GLEW_ARB_copy_image false
#endif

static bool copy_image_warned = false;

static void
copy_image_sub_data(GLuint src_texture_id, GLuint dest_texture_id, unsigned int width, unsigned int height, unsigned int num_levels) {
    if (!GLEW_ARB_copy_image) {
        // ARB_copy_image not available, do a slow roundtrip copy
        if (!copy_image_warned) {
            copy_image_warned = true;
            fprintf(stderr, "WARNING: Your system's OpenGL implementation does not have glCopyImageSubData, falling back to a slower implementation.\n");
        }
        uint8_t *src = malloc(5 * width * height * num_levels);
        if (src == NULL) { fatal("Out of memory."); }
        uint8_t *dest = src + (4 * width * height * num_levels);
        glBindTexture(GL_TEXTURE_2D_ARRAY, src_texture_id); check_gl();
        glGetTexImage(GL_TEXTURE_2D_ARRAY, 0, GL_RGBA, GL_UNSIGNED_BYTE, src); check_gl();
        glBindTexture(GL_TEXTURE_2D_ARRAY, dest_texture_id); check_gl();
        glPixelStorei(GL_UNPACK_ALIGNMENT, 1); check_gl();
        for(size_t i = 0; i < width * height * num_levels; i++) dest[i] = src[4*i];
        glTexSubImage3D(GL_TEXTURE_2D_ARRAY, 0, 0, 0, 0, width, height, num_levels, GL_RED, GL_UNSIGNED_BYTE, dest); check_gl();
        free(src);
    } else {
        glCopyImageSubData(src_texture_id, GL_TEXTURE_2D_ARRAY, 0, 0, 0, 0, dest_texture_id, GL_TEXTURE_2D_ARRAY, 0, 0, 0, 0, width, height, num_levels); check_gl();
    }
}


static void
realloc_sprite_texture() {
    GLuint tex;
    glGenTextures(1, &tex); check_gl();
    glBindTexture(GL_TEXTURE_2D_ARRAY, tex); check_gl();
    // We use GL_NEAREST otherwise glyphs that touch the edge of the cell
    // often show a border between cells
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
    glTexParameteri(GL_TEXTURE_2D_ARRAY, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE); check_gl();
    unsigned int xnum, ynum, z, znum, width, height, src_ynum;
    sprite_map_current_layout(&xnum, &ynum, &z);
    znum = z + 1;
    width = xnum * sprite_map.cell_width; height = ynum * sprite_map.cell_height;
    glTexStorage3D(GL_TEXTURE_2D_ARRAY, 1, GL_R8, width, height, znum); check_gl();
    if (sprite_map.texture_id) {
        // need to re-alloc
        src_ynum = MAX(1, sprite_map.last_ynum);
        copy_image_sub_data(sprite_map.texture_id, tex, width, src_ynum * sprite_map.cell_height, sprite_map.last_num_of_layers);
        glDeleteTextures(1, &sprite_map.texture_id); check_gl();
    }
    glBindTexture(GL_TEXTURE_2D_ARRAY, 0);
    sprite_map.last_num_of_layers = znum;
    sprite_map.last_ynum = ynum;
    sprite_map.texture_id = tex;
}

static inline PyObject*
render_cell(PyObject *text, bool bold, bool italic, unsigned int underline, bool strikethrough, bool is_second) {
#define B(x) (x ? Py_True : Py_False)
    PyObject *ret = PyObject_CallFunction(sprite_map.render_cell, "OOOIOO", text, B(bold), B(italic), underline, B(strikethrough), B(is_second));
    if (ret == NULL) { PyErr_Print(); fatal("Rendering of a cell failed, aborting"); }
    return ret;
#undef B
}

enum {SPRITE_MAP_UNIT};

static inline void
ensure_sprite_map() {
    static GLuint bound_texture_id = 0;
    if (!sprite_map.texture_id) realloc_sprite_texture();
    if (bound_texture_id != sprite_map.texture_id) {
        glActiveTexture(GL_TEXTURE0 + SPRITE_MAP_UNIT); check_gl();
        glBindTexture(GL_TEXTURE_2D_ARRAY, sprite_map.texture_id); check_gl();
        bound_texture_id = sprite_map.texture_id;
    }
}

static void 
sprite_send_to_gpu(unsigned int x, unsigned int y, unsigned int z, PyObject *buf) {
    unsigned int xnum, ynum, znum;
    sprite_map_current_layout(&xnum, &ynum, &znum);
    if ((int)znum >= sprite_map.last_num_of_layers || (znum == 0 && (int)ynum > sprite_map.last_ynum)) realloc_sprite_texture();
    glBindTexture(GL_TEXTURE_2D_ARRAY, sprite_map.texture_id); check_gl();
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1); check_gl();
    x *= sprite_map.cell_width; y *= sprite_map.cell_height;
    PyObject *ret = PyObject_CallObject(buf, NULL);
    if (ret == NULL) { PyErr_Print(); fatal("Failed to get address of rendered cell buffer"); }
    void *address = PyLong_AsVoidPtr(ret);
    Py_DECREF(ret);
    glTexSubImage3D(GL_TEXTURE_2D_ARRAY, 0, x, y, z, sprite_map.cell_width, sprite_map.cell_height, 1, GL_RED, GL_UNSIGNED_BYTE, address); check_gl();
    Py_DECREF(buf);
}

static void 
render_and_send_dirty_sprites(PyObject *text, bool bold, bool italic, bool is_second, sprite_index x, sprite_index y, sprite_index z) {
    if (text == NULL) { fatal("The text for a sprite was NULL, probably out of memory."); }
    PyObject *buf = render_cell(text, bold, italic, false, false, is_second);
    sprite_send_to_gpu(x, y, z, buf);
}

static inline sprite_index
send_prerendered(unsigned int underline, bool strikethrough) {
    sprite_index x, y, z;
    PyObject *blank = PyUnicode_FromString(" ");
    if (blank == NULL) { fatal("Out of memory"); }
    PyObject *buf = render_cell(blank, false, false, underline, strikethrough, false);
    Py_CLEAR(blank);
    if (sprite_map_increment(&x, &y, &z) != 0) { fatal("Failed to increment sprite map for prerendering"); }
    sprite_send_to_gpu(x, y, z, buf);
    return x;
}

static void 
layout_sprite_map(unsigned int cell_width, unsigned int cell_height, PyObject *render_cell) {
    sprite_map.cell_width = MAX(1, cell_width);
    sprite_map.cell_height = MAX(1, cell_height);
    global_state.cell_width = sprite_map.cell_width;
    global_state.cell_height = sprite_map.cell_height;
    if (sprite_map.max_texture_size == 0) {
        glGetIntegerv(GL_MAX_TEXTURE_SIZE, &(sprite_map.max_texture_size)); check_gl();
        glGetIntegerv(GL_MAX_ARRAY_TEXTURE_LAYERS, &(sprite_map.max_array_texture_layers)); check_gl();
        sprite_map_set_limits(sprite_map.max_texture_size, sprite_map.max_array_texture_layers);
    }
    sprite_map_set_layout(sprite_map.cell_width, sprite_map.cell_height);
    Py_CLEAR(sprite_map.render_cell);
    sprite_map.render_cell = render_cell; Py_INCREF(sprite_map.render_cell);
    if (sprite_map.texture_id) { glDeleteTextures(1, &(sprite_map.texture_id)); sprite_map.texture_id = 0; }
    realloc_sprite_texture();
    // Pre-render the basic cells to ensure they have known sprite numbers
    send_prerendered(0, false);
    send_prerendered(1, false);
    send_prerendered(2, false);
    if (send_prerendered(0, true) != 3) { fatal("Available OpenGL texture size is too small"); }
}

static void
destroy_sprite_map() {
    sprite_map_free();
    Py_CLEAR(sprite_map.render_cell);
    if (sprite_map.texture_id) {
        glDeleteTextures(1, &(sprite_map.texture_id));
        check_gl();
        sprite_map.texture_id = 0;
    }
}

// }}}

// Cell {{{

static UniformBlock cell_render_data;
static ArrayInformation cell_color_table;

static void
init_cell_program() {
    cell_render_data.index = block_index(CELL_PROGRAM, "CellRenderData");
    cell_render_data.size = block_size(CELL_PROGRAM, cell_render_data.index);
    cell_color_table.size = get_uniform_information(CELL_PROGRAM, "color_table[0]", GL_UNIFORM_SIZE);
    cell_color_table.offset = get_uniform_information(CELL_PROGRAM, "color_table[0]", GL_UNIFORM_OFFSET);
    cell_color_table.stride = get_uniform_information(CELL_PROGRAM, "color_table[0]", GL_UNIFORM_ARRAY_STRIDE);
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
    A1(sprite_coords, 4, GL_UNSIGNED_SHORT, sprite_x);
    A1(colors, 3, GL_UNSIGNED_INT, fg);
    add_buffer_to_vao(vao_idx, GL_ARRAY_BUFFER);
    A(is_selected, 1, GL_FLOAT, NULL, 0);
    size_t bufnum = add_buffer_to_vao(vao_idx, GL_UNIFORM_BUFFER);
    alloc_vao_buffer(vao_idx, cell_render_data.size, bufnum, GL_STREAM_DRAW);
    return vao_idx;
#undef A
#undef A1
}


static void 
draw_cells_impl(ssize_t vao_idx, GLfloat xstart, GLfloat ystart, GLfloat dx, GLfloat dy, Screen *screen, CursorRenderInfo *cursor) {
    size_t sz;
    void *address;
    bool inverted = screen_invert_colors(screen);
    struct CellRenderData {
        GLfloat xstart, ystart, dx, dy, sprite_dx, sprite_dy;

        GLuint default_fg, default_bg, highlight_fg, highlight_bg, cursor_color, url_color;

        GLint color1, color2;

        GLuint xnum, ynum, cursor_x, cursor_y, cursor_w, url_xl, url_yl, url_xr, url_yr;
    };
    enum { cell_data_buffer, selection_buffer, uniform_buffer };
    static struct CellRenderData *rd;

    if (screen->scroll_changed || screen->is_dirty) {
        sz = sizeof(Cell) * screen->lines * screen->columns;
        address = alloc_and_map_vao_buffer(vao_idx, sz, cell_data_buffer, GL_STREAM_DRAW, GL_WRITE_ONLY);
        screen_update_cell_data(screen, address, sz);
        unmap_vao_buffer(vao_idx, cell_data_buffer); address = NULL;
    }

    if (screen_is_selection_dirty(screen)) {
        sz = sizeof(GLfloat) * screen->lines * screen->columns;
        address = alloc_and_map_vao_buffer(vao_idx, sz, selection_buffer, GL_STREAM_DRAW, GL_WRITE_ONLY);
        screen_apply_selection(screen, address, sz);
        unmap_vao_buffer(vao_idx, selection_buffer); address = NULL;
    }

    // Send the uniform data
    rd = (struct CellRenderData*)map_vao_buffer(vao_idx, uniform_buffer, GL_WRITE_ONLY);
    if (UNLIKELY(screen->color_profile->dirty)) {
        copy_color_table_to_buffer(screen->color_profile, (GLuint*)rd, cell_color_table.offset / sizeof(GLuint), cell_color_table.stride / sizeof(GLuint));
    }
    // Cursor position
    if (cursor->is_visible && cursor->shape == CURSOR_BLOCK) { 
        rd->cursor_x = screen->cursor->x, rd->cursor_y = screen->cursor->y; 
    } else {
        rd->cursor_x = screen->columns, rd->cursor_y = screen->lines; 
    }
    rd->cursor_w = rd->cursor_x + MAX(1, screen_current_char_width(screen)) - 1;

    rd->xnum = screen->columns; rd->ynum = screen->lines;
    screen_url_range(screen, &rd->url_xl);
    
    rd->xstart = xstart; rd->ystart = ystart; rd->dx = dx; rd->dy = dy;
    unsigned int x, y, z;
    sprite_map_current_layout(&x, &y, &z);
    rd->sprite_dx = 1.0f / (float)x; rd->sprite_dy = 1.0f / (float)y;
    rd->color1 = inverted & 1; rd->color2 = 1 - (inverted & 1);

#define COLOR(name) colorprofile_to_color(screen->color_profile, screen->color_profile->overridden.name, screen->color_profile->configured.name)
    rd->default_fg = COLOR(default_fg); rd->default_bg = COLOR(default_bg); rd->highlight_fg = COLOR(highlight_fg); rd->highlight_bg = COLOR(highlight_bg);
#undef COLOR
    rd->cursor_color = cursor->color; rd->url_color = OPT(url_color);

    unmap_vao_buffer(vao_idx, uniform_buffer); rd = NULL;

    ensure_sprite_map();
    render_dirty_sprites(render_and_send_dirty_sprites);

    bind_program(CELL_PROGRAM); 
    static bool cell_constants_set = false;
    if (!cell_constants_set) { 
        glUniform1i(glGetUniformLocation(program_id(CELL_PROGRAM), "sprites"), SPRITE_MAP_UNIT); check_gl(); 
        cell_constants_set = true; 
    }
    bind_vao_uniform_buffer(vao_idx, uniform_buffer, cell_render_data.index);
    bind_vertex_array(vao_idx);
    glDrawArraysInstanced(GL_TRIANGLE_FAN, 0, 4, screen->lines * screen->columns); check_gl();
    unbind_vertex_array();
    unbind_program();
}
// }}}

// Cursor {{{
enum CursorUniforms { CURSOR_color, CURSOR_pos, NUM_CURSOR_UNIFORMS };
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
        else SET_LOC(pos);
        else { fatal("Unknown uniform in cursor program"); }
    }
    if (left) { fatal("Left over uniforms in cursor program"); }
#undef SET_LOC
}

static void 
draw_cursor_impl(CursorRenderInfo *cursor) {
    bind_program(CURSOR_PROGRAM); bind_vertex_array(cursor_vertex_array); check_gl();
    glUniform3f(cursor_uniform_locations[CURSOR_color], ((cursor->color >> 16) & 0xff) / 255.0, ((cursor->color >> 8) & 0xff) / 255.0, (cursor->color & 0xff) / 255.0); check_gl();
    glUniform4f(cursor_uniform_locations[CURSOR_pos], cursor->left, cursor->top, cursor->right, cursor->bottom); check_gl();
    glDrawArrays(global_state.application_focused ? GL_TRIANGLE_FAN : GL_LINE_LOOP, 0, 4); check_gl();
    unbind_vertex_array(); unbind_program();
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
draw_borders_impl() {
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
        void *borders_buf_address = alloc_and_map_vao_buffer(border_vertex_array, sz, 0, GL_STATIC_DRAW, GL_WRITE_ONLY);
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
compile_program(PyObject UNUSED *self, PyObject *args) {
    const char *vertex_shader, *fragment_shader;
    int which;
    GLuint vertex_shader_id = 0, fragment_shader_id = 0;
    if (!PyArg_ParseTuple(args, "iss", &which, &vertex_shader, &fragment_shader)) return NULL;
    if (which < CELL_PROGRAM || which >= NUM_PROGRAMS) { PyErr_Format(PyExc_ValueError, "Unknown program: %d", which); return NULL; }
    if (programs[which].id != 0) { PyErr_SetString(PyExc_ValueError, "program already compiled"); return NULL; }
    programs[which].id = glCreateProgram();
    check_gl();
    vertex_shader_id = compile_shader(GL_VERTEX_SHADER, vertex_shader); check_gl();
    fragment_shader_id = compile_shader(GL_FRAGMENT_SHADER, fragment_shader); check_gl();
    glAttachShader(programs[which].id, vertex_shader_id); check_gl();
    glAttachShader(programs[which].id, fragment_shader_id); check_gl();
    glLinkProgram(programs[which].id); check_gl();
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

NO_ARG(init_cursor_program)

NO_ARG(init_borders_program)
PYWRAP1(add_borders_rect) { unsigned int a, b, c, d, e; PA("IIIII", &a, &b, &c, &d, &e); add_borders_rect(a, b, c, d, e); Py_RETURN_NONE; }
TWO_INT(send_borders_rects)

NO_ARG(init_cell_program)
NO_ARG_INT(create_cell_vao)
NO_ARG(destroy_sprite_map)
PYWRAP1(layout_sprite_map) {
    unsigned int cell_width, cell_height;
    PyObject *render_cell;
    PA("IIO", &cell_width, &cell_height, &render_cell);
    layout_sprite_map(cell_width, cell_height, render_cell);
    Py_RETURN_NONE;
}

PYWRAP1(clear_buffers) {
    PyObject *swap_buffers;
    unsigned int bg;
    PA("OI", &swap_buffers, &bg);
#define C(shift) ((float)((bg >> shift) & 0xff)) / 255.0
    glClearColor(C(16), C(8), C(0), 1);
#undef C
    glClear(GL_COLOR_BUFFER_BIT);
    PyObject *ret = PyObject_CallFunctionObjArgs(swap_buffers, NULL);
    if (ret == NULL) return NULL;
    Py_DECREF(ret);
    glClear(GL_COLOR_BUFFER_BIT);
    Py_RETURN_NONE;
}

PYWRAP0(check_for_extensions) {
    GLint n = 0, i, left = 2;
    glGetIntegerv(GL_NUM_EXTENSIONS, &n);
    bool texture_storage = false;
#define CHECK(name) if (!name) { \
    if (strstr((const char*)ext, "GL_ARB_" #name) == (const char *)ext) { left--; name = true; } \
}
    for (i = 0; i < n; i++) {
        const GLubyte *ext = glGetStringi(GL_EXTENSIONS, i);
        CHECK(texture_storage); 
        if (left < 1) break;
    }
#undef CHECK
    if (left > 0) {
#define CHECK(name) if (!name) { PyErr_Format(PyExc_RuntimeError, "The OpenGL driver on this system is missing the required extension: GL_ARB_%s", #name); return NULL; }
        CHECK(texture_storage); 
#undef CHECK
    }
    Py_RETURN_NONE;
}

#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, NULL}
#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}
static PyMethodDef module_methods[] = {
    {"glewInit", (PyCFunction)glew_init, METH_NOARGS, NULL}, 
    M(compile_program, METH_VARARGS),
    MW(check_for_extensions, METH_NOARGS),
    MW(create_vao, METH_NOARGS),
    MW(remove_vao, METH_O),
    MW(bind_vertex_array, METH_O),
    MW(unbind_vertex_array, METH_NOARGS),
    MW(unmap_vao_buffer, METH_VARARGS),
    MW(bind_program, METH_O),
    MW(unbind_program, METH_NOARGS),
    MW(init_cursor_program, METH_NOARGS),
    MW(init_borders_program, METH_NOARGS),
    MW(add_borders_rect, METH_VARARGS),
    MW(send_borders_rects, METH_VARARGS),
    MW(init_cell_program, METH_NOARGS),
    MW(create_cell_vao, METH_NOARGS),
    MW(layout_sprite_map, METH_VARARGS),
    MW(destroy_sprite_map, METH_NOARGS),
    MW(clear_buffers, METH_VARARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
#ifdef ENABLE_DEBUG_GL
init_shaders_debug(PyObject *module) {
#else
init_shaders(PyObject *module) {
#endif
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
    update_viewport_size = &update_viewport_size_impl;
    draw_borders = &draw_borders_impl;
    draw_cells = &draw_cells_impl;
    draw_cursor = &draw_cursor_impl;
    return true;
}
// }}}
