/*
 * shaders.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#ifdef __APPLE__
#include <OpenGL/gl3.h>
#include <OpenGL/gl3ext.h>
#else
#include <GL/glew.h>
#endif


// GL setup and error handling {{{
// Required minimum OpenGL version
#define REQUIRED_VERSION_MAJOR 3
#define REQUIRED_VERSION_MINOR 3
#define GLSL_VERSION (REQUIRED_VERSION_MAJOR * 100 + REQUIRED_VERSION_MINOR * 10)

static inline bool
set_error_from_gl() {
    int code = glGetError();
    switch(code) { 
        case GL_NO_ERROR: return false; 
        case GL_INVALID_ENUM: 
            PyErr_SetString(PyExc_ValueError, "An enum value is invalid (GL_INVALID_ENUM)"); break; 
        case GL_INVALID_VALUE: 
            PyErr_SetString(PyExc_ValueError, "An numeric value is invalid (GL_INVALID_VALUE)"); break; 
        case GL_INVALID_OPERATION: 
            PyErr_SetString(PyExc_ValueError, "This operation is not allowed in the current state (GL_INVALID_OPERATION)"); break; 
        case GL_INVALID_FRAMEBUFFER_OPERATION: 
            PyErr_SetString(PyExc_ValueError, "The framebuffer object is not complete (GL_INVALID_FRAMEBUFFER_OPERATION)"); break; 
        case GL_OUT_OF_MEMORY: 
            PyErr_SetString(PyExc_MemoryError, "There is not enough memory left to execute the command. (GL_OUT_OF_MEMORY)"); break; 
        case GL_STACK_UNDERFLOW: 
            PyErr_SetString(PyExc_OverflowError, "An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_UNDERFLOW)"); break; 
        case GL_STACK_OVERFLOW: 
            PyErr_SetString(PyExc_OverflowError, "An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_OVERFLOW)"); break; 
        default: 
            PyErr_Format(PyExc_RuntimeError, "An unknown OpenGL error occurred with code: %d", code); break; 
    }
    return true;
}

static bool _enable_error_checking = false;
#define CHECK_ERROR if (_enable_error_checking) { if (set_error_from_gl()) return NULL; }


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

enum Program { CELL_PROGRAM, CURSOR_PROGRAM, BORDERS_PROGRAM, NUM_PROGRAMS };

static GLuint program_ids[NUM_PROGRAMS] = {0};
static char glbuf[4096];

static inline GLuint
compile_shader(GLenum shader_type, const char *source) {
    GLuint shader_id = glCreateShader(shader_type);
    if (!shader_id) { set_error_from_gl(); return 0; }
    glShaderSource(shader_id, 1, (const GLchar **)&source, NULL);
    if (set_error_from_gl()) { glDeleteShader(shader_id); return 0; }
    glCompileShader(shader_id);
    if (set_error_from_gl()) { glDeleteShader(shader_id); return 0; }
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
    if (program_ids[which] != 0) { PyErr_SetString(PyExc_ValueError, "program already compiled"); return NULL; }
    program_ids[which] = glCreateProgram();
    if (program_ids[which] == 0) { set_error_from_gl(); return NULL; }
    vertex_shader_id = compile_shader(GL_VERTEX_SHADER, vertex_shader);
    if (vertex_shader_id == 0) goto end;
    fragment_shader_id = compile_shader(GL_FRAGMENT_SHADER, fragment_shader);
    if (vertex_shader_id == 0) goto end;
    glAttachShader(program_ids[which], vertex_shader_id);
    if (set_error_from_gl()) goto end;
    glAttachShader(program_ids[which], fragment_shader_id);
    glLinkProgram(program_ids[which]);
    GLint ret = GL_FALSE;
    glGetProgramiv(program_ids[which], GL_LINK_STATUS, &ret);
    if (ret != GL_TRUE) {
        GLsizei len;
        glGetProgramInfoLog(program_ids[which], sizeof(glbuf), &len, glbuf);
        fprintf(stderr, "Failed to compile GLSL shader!\n%s", glbuf);
        PyErr_SetString(PyExc_ValueError, "Failed to compile shader");
        goto end;
    }

end:
    if (vertex_shader_id != 0) glDeleteShader(vertex_shader_id);
    if (fragment_shader_id != 0) glDeleteShader(fragment_shader_id);
    if (PyErr_Occurred()) { glDeleteProgram(program_ids[which]); program_ids[which] = 0; return NULL;}
    return Py_BuildValue("I", program_ids[which]);
    Py_RETURN_NONE;
}

#define M(name, arg_type) {#name, (PyCFunction)name, arg_type, ""}
static PyMethodDef module_methods[] = {
    M(enable_automatic_opengl_error_checking, METH_O),
    {"glewInit", (PyCFunction)glew_init, METH_NOARGS, NULL}, 
    M(compile_program, METH_VARARGS),

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_shaders(PyObject *module) {
#define C(x) if (PyModule_AddIntConstant(module, #x, x) != 0) { PyErr_NoMemory(); return false; }
    C(CELL_PROGRAM); C(CURSOR_PROGRAM); C(BORDERS_PROGRAM);
    C(GLSL_VERSION);
#undef C
    PyModule_AddObject(module, "GL_VERSION_REQUIRED", Py_BuildValue("II", REQUIRED_VERSION_MAJOR, REQUIRED_VERSION_MINOR));
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
// }}}
