/*
 * gl.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
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

#define STRINGIFY(x) #x
#define METH(name, argtype) {STRINGIFY(gl##name), (PyCFunction)name, argtype, NULL},

static bool _enable_error_checking = 1;

#ifndef GL_STACK_UNDERFLOW
#define GL_STACK_UNDERFLOW 0x0504
#endif

#ifndef GL_STACK_OVERFLOW
#define GL_STACK_OVERFLOW 0x0503
#endif

#define SET_GL_ERR \
    switch(glGetError()) { \
        case GL_NO_ERROR: break; \
        case GL_INVALID_ENUM: \
            PyErr_SetString(PyExc_ValueError, "An enum value is invalid (GL_INVALID_ENUM)"); break; \
        case GL_INVALID_VALUE: \
            PyErr_SetString(PyExc_ValueError, "An numeric value is invalid (GL_INVALID_VALUE)"); break; \
        case GL_INVALID_OPERATION: \
            PyErr_SetString(PyExc_ValueError, "This operation is not allowed in the current state (GL_INVALID_OPERATION)"); break; \
        case GL_INVALID_FRAMEBUFFER_OPERATION: \
            PyErr_SetString(PyExc_ValueError, "The framebuffer object is not complete (GL_INVALID_FRAMEBUFFER_OPERATION)"); break; \
        case GL_OUT_OF_MEMORY: \
            PyErr_SetString(PyExc_MemoryError, "There is not enough memory left to execute the command. (GL_OUT_OF_MEMORY)"); break; \
        case GL_STACK_UNDERFLOW: \
            PyErr_SetString(PyExc_OverflowError, "An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_UNDERFLOW)"); break; \
        case GL_STACK_OVERFLOW: \
            PyErr_SetString(PyExc_OverflowError, "An attempt has been made to perform an operation that would cause an internal stack to underflow. (GL_STACK_OVERFLOW)"); break; \
        default: \
            PyErr_SetString(PyExc_RuntimeError, "An unknown OpenGL error occurred."); break; \
    }

#define CHECK_ERROR if (_enable_error_checking) { SET_GL_ERR; if (PyErr_Occurred()) return NULL; }

static PyObject* 
Viewport(PyObject UNUSED *self, PyObject *args) {
    unsigned int x, y, w, h;
    if (!PyArg_ParseTuple(args, "IIII", &x, &y, &w, &h)) return NULL;
    glViewport(x, y, w, h);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
ClearColor(PyObject UNUSED *self, PyObject *args) {
    float x, y, w, h;
    if (!PyArg_ParseTuple(args, "ffff", &x, &y, &w, &h)) return NULL;
    glClearColor(x, y, w, h);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

// Uniforms {{{
static PyObject* 
Uniform2ui(PyObject UNUSED *self, PyObject *args) {
    int location;
    unsigned int x, y;
    if (!PyArg_ParseTuple(args, "iII", &location, &x, &y)) return NULL;
    glUniform2ui(location, x, y);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
Uniform4ui(PyObject UNUSED *self, PyObject *args) {
    int location;
    unsigned int a, b, c, d;
    if (!PyArg_ParseTuple(args, "iIIII", &location, &a, &b, &c, &d)) return NULL;
    glUniform4ui(location, a, b, c, d);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
Uniform1uiv(PyObject UNUSED *self, PyObject *args) {
    int location;
    unsigned int count;
    PyObject *value;
    if (!PyArg_ParseTuple(args, "iIO", &location, &count, &value)) return NULL;
    glUniform1uiv(location, count, (GLuint*)PyLong_AsVoidPtr(value));
    CHECK_ERROR;
    Py_RETURN_NONE;
}


static PyObject* 
Uniform2i(PyObject UNUSED *self, PyObject *args) {
    int location;
    int x, y;
    if (!PyArg_ParseTuple(args, "iii", &location, &x, &y)) return NULL;
    glUniform2i(location, x, y);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
Uniform1i(PyObject UNUSED *self, PyObject *args) {
    int location;
    int x;
    if (!PyArg_ParseTuple(args, "ii", &location, &x)) return NULL;
    glUniform1i(location, x);
    CHECK_ERROR;
    Py_RETURN_NONE;
}


static PyObject* 
Uniform2f(PyObject UNUSED *self, PyObject *args) {
    int location;
    float x, y;
    if (!PyArg_ParseTuple(args, "iff", &location, &x, &y)) return NULL;
    glUniform2f(location, x, y);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
Uniform4f(PyObject UNUSED *self, PyObject *args) {
    int location;
    float x, y, a, b;
    if (!PyArg_ParseTuple(args, "iffff", &location, &x, &y, &a, &b)) return NULL;
    glUniform4f(location, x, y, a, b);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
Uniform3fv(PyObject UNUSED *self, PyObject *args) {
    int location;
    unsigned int count;
    PyObject *l;
    if (!PyArg_ParseTuple(args, "iIO!", &location, &count, &PyLong_Type, &l)) return NULL;
    glUniform3fv(location, count, PyLong_AsVoidPtr(l));
    CHECK_ERROR;
    Py_RETURN_NONE;
}
// }}}


static PyObject* 
CheckError(PyObject UNUSED *self) {
    CHECK_ERROR; Py_RETURN_NONE;
}

static PyObject* 
GetString(PyObject UNUSED *self, PyObject *val) {
    const unsigned char *ans = glGetString(PyLong_AsUnsignedLong(val));
    if (ans == NULL) { SET_GL_ERR; return NULL; }
    return PyBytes_FromString((const char*)ans);
}

static PyObject* 
Clear(PyObject UNUSED *self, PyObject *val) {
    unsigned long m = PyLong_AsUnsignedLong(val);
    glClear((GLbitfield)m);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
DrawArrays(PyObject UNUSED *self, PyObject *args) {
    int mode, first;
    unsigned int count;
    if (!PyArg_ParseTuple(args, "iiI", &mode, &first, &count)) return NULL;
    glDrawArrays(mode, first, count);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
 
static PyObject* 
MultiDrawArrays(PyObject UNUSED *self, PyObject *args) {
    int mode;
    unsigned int draw_count;
    PyObject *a, *b;
    if (!PyArg_ParseTuple(args, "iO!O!I", &mode, &PyLong_Type, &a, &PyLong_Type, &b, &draw_count)) return NULL;
    glMultiDrawArrays(mode, PyLong_AsVoidPtr(a), PyLong_AsVoidPtr(b), draw_count);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
 
static PyObject* 
DrawArraysInstanced(PyObject UNUSED *self, PyObject *args) {
    int mode, first;
    unsigned int count, primcount;
    if (!PyArg_ParseTuple(args, "iiII", &mode, &first, &count, &primcount)) return NULL;
    glDrawArraysInstanced(mode, first, count, primcount);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
 
static PyObject* 
CreateProgram(PyObject UNUSED *self) {
    GLuint ans = glCreateProgram();
    if (!ans) { SET_GL_ERR; return NULL; }
    return PyLong_FromUnsignedLong(ans);
}

static PyObject* 
AttachShader(PyObject UNUSED *self, PyObject *args) {
    unsigned int program_id, shader_id;
    if (!PyArg_ParseTuple(args, "II", &program_id, &shader_id)) return NULL;
    glAttachShader(program_id, shader_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
LinkProgram(PyObject UNUSED *self, PyObject *val) {
    unsigned long program_id = PyLong_AsUnsignedLong(val);
    glLinkProgram(program_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
GetProgramiv(PyObject UNUSED *self, PyObject *args) {
    unsigned int program_id;
    int pname, ans = 0;
    if (!PyArg_ParseTuple(args, "Ii", &program_id, &pname)) return NULL;
    glGetProgramiv(program_id, pname, &ans);
    CHECK_ERROR;
    return PyLong_FromLong((long)ans);
}

static PyObject* 
GetProgramInfoLog(PyObject UNUSED *self, PyObject *val) {
    unsigned long program_id = PyLong_AsUnsignedLong(val);
    int log_len = 0;
    GLchar *buf = NULL;
    glGetProgramiv(program_id, GL_INFO_LOG_LENGTH, &log_len);
    buf = PyMem_Calloc(log_len + 10, sizeof(GLchar));
    if (buf == NULL) return PyErr_NoMemory();
    glGetProgramInfoLog(program_id, log_len, &log_len, buf);
    PyObject *ans = PyBytes_FromStringAndSize(buf, log_len);
    PyMem_Free(buf);
    return ans;
}

static PyObject* 
GetShaderInfoLog(PyObject UNUSED *self, PyObject *val) {
    unsigned long program_id = PyLong_AsUnsignedLong(val);
    int log_len = 0;
    GLchar *buf = NULL;
    glGetShaderiv(program_id, GL_INFO_LOG_LENGTH, &log_len);
    buf = PyMem_Calloc(log_len + 10, sizeof(GLchar));
    if (buf == NULL) return PyErr_NoMemory();
    glGetShaderInfoLog(program_id, log_len, &log_len, buf);
    PyObject *ans = PyBytes_FromStringAndSize(buf, log_len);
    PyMem_Free(buf);
    return ans;
}

static PyObject* 
ActiveTexture(PyObject UNUSED *self, PyObject *val) {
    long tex_id = PyLong_AsLong(val);
    glActiveTexture(tex_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
DeleteProgram(PyObject UNUSED *self, PyObject *val) {
    unsigned long program_id = PyLong_AsUnsignedLong(val);
    glDeleteProgram(program_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
 
static PyObject* 
DeleteShader(PyObject UNUSED *self, PyObject *val) {
    unsigned long program_id = PyLong_AsUnsignedLong(val);
    glDeleteShader(program_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
GenVertexArrays(PyObject UNUSED *self, PyObject *val) {
    GLuint arrays[256] = {0};
    unsigned long n = PyLong_AsUnsignedLong(val);
    if (n > 256) { PyErr_SetString(PyExc_ValueError, "Generating more than 256 arrays in a single call is not supported"); return NULL; }
    glGenVertexArrays(n, arrays);
    CHECK_ERROR;
    if (n == 1) return PyLong_FromUnsignedLong((unsigned long)arrays[0]);
    PyObject *ans = PyTuple_New(n);
    if (ans == NULL) return PyErr_NoMemory();
    for (size_t i = 0; i < n; i++) {
        PyObject *t = PyLong_FromUnsignedLong((unsigned long)arrays[i]);
        if (t == NULL) { Py_DECREF(ans); return PyErr_NoMemory(); }
        PyTuple_SET_ITEM(ans, i, t);
    }
    return ans;
}

static PyObject* 
GenTextures(PyObject UNUSED *self, PyObject *val) {
    GLuint arrays[256] = {0};
    unsigned long n = PyLong_AsUnsignedLong(val);
    if (n > 256) { PyErr_SetString(PyExc_ValueError, "Generating more than 256 textures in a single call is not supported"); return NULL; }
    glGenTextures(n, arrays);
    CHECK_ERROR;
    if (n == 1) return PyLong_FromUnsignedLong((unsigned long)arrays[0]);
    PyObject *ans = PyTuple_New(n);
    if (ans == NULL) return PyErr_NoMemory();
    for (size_t i = 0; i < n; i++) {
        PyObject *t = PyLong_FromUnsignedLong((unsigned long)arrays[i]);
        if (t == NULL) { Py_DECREF(ans); return PyErr_NoMemory(); }
        PyTuple_SET_ITEM(ans, i, t);
    }
    return ans;
}

static PyObject* 
GenBuffers(PyObject UNUSED *self, PyObject *val) {
    GLuint arrays[256] = {0};
    unsigned long n = PyLong_AsUnsignedLong(val);
    if (n > 256) { PyErr_SetString(PyExc_ValueError, "Generating more than 256 buffers in a single call is not supported"); return NULL; }
    glGenBuffers(n, arrays);
    CHECK_ERROR;
    if (n == 1) return PyLong_FromUnsignedLong((unsigned long)arrays[0]);
    PyObject *ans = PyTuple_New(n);
    if (ans == NULL) return PyErr_NoMemory();
    for (size_t i = 0; i < n; i++) {
        PyObject *t = PyLong_FromUnsignedLong((unsigned long)arrays[i]);
        if (t == NULL) { Py_DECREF(ans); return PyErr_NoMemory(); }
        PyTuple_SET_ITEM(ans, i, t);
    }
    return ans;
}


static PyObject* 
CreateShader(PyObject UNUSED *self, PyObject *val) {
    long shader_type = PyLong_AsLong(val);
    GLuint ans = glCreateShader(shader_type);
    CHECK_ERROR;
    return PyLong_FromUnsignedLong(ans);
}

static PyObject* 
ShaderSource(PyObject UNUSED *self, PyObject *args) {
    char *src; Py_ssize_t src_len = 0;
    unsigned int shader_id;
    if(!PyArg_ParseTuple(args, "Is#", &shader_id, &src, &src_len)) return NULL;
    glShaderSource(shader_id, 1, (const GLchar **)&src, NULL);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
CompileShader(PyObject UNUSED *self, PyObject *val) {
    unsigned long shader_id = PyLong_AsUnsignedLong(val);
    glCompileShader((GLuint)shader_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
GetShaderiv(PyObject UNUSED *self, PyObject *args) {
    unsigned int program_id;
    int pname, ans = 0;
    if (!PyArg_ParseTuple(args, "Ii", &program_id, &pname)) return NULL;
    glGetShaderiv(program_id, pname, &ans);
    CHECK_ERROR;
    return PyLong_FromLong((long)ans);
}

static PyObject* 
GetUniformLocation(PyObject UNUSED *self, PyObject *args) {
    char *name;
    unsigned int program_id;
    if(!PyArg_ParseTuple(args, "Is", &program_id, &name)) return NULL;
    GLint ans = glGetUniformLocation(program_id, name);
    CHECK_ERROR;
    return PyLong_FromLong((long) ans);
}

static PyObject* 
GetUniformBlockIndex(PyObject UNUSED *self, PyObject *args) {
    char *name;
    unsigned int program_id;
    if(!PyArg_ParseTuple(args, "Is", &program_id, &name)) return NULL;
    GLuint ans = glGetUniformBlockIndex(program_id, name);
    if (ans == GL_INVALID_INDEX) { PyErr_SetString(PyExc_ValueError, "No such uniform block is active"); return NULL; }
    return PyLong_FromUnsignedLong((unsigned long) ans);
}

static PyObject* 
GetAttribLocation(PyObject UNUSED *self, PyObject *args) {
    char *name;
    unsigned int program_id;
    if(!PyArg_ParseTuple(args, "Is", &program_id, &name)) return NULL;
    GLint ans = glGetAttribLocation(program_id, name);
    CHECK_ERROR;
    return PyLong_FromLong((long) ans);
}

static PyObject* 
get_uniform_block_size(PyObject UNUSED *self, PyObject *args) {
    unsigned int program_id, block_index;
    if(!PyArg_ParseTuple(args, "II", &program_id, &block_index)) return NULL;
    GLint ans;
    glGetActiveUniformBlockiv(program_id, block_index, GL_UNIFORM_BLOCK_DATA_SIZE, &ans);
    CHECK_ERROR;
    return PyLong_FromLong((long) ans);
}

static PyObject* 
get_uniform_block_offsets(PyObject UNUSED *self, PyObject *args) {
    unsigned int program_id;
    PyObject *pynames;
    if(!PyArg_ParseTuple(args, "IO", &program_id, &pynames)) return NULL;
    if (!PySequence_Check(pynames)) { PyErr_SetString(PyExc_TypeError, "names must be a sequence"); return NULL; }
    GLsizei count = PySequence_Size(pynames);
    char **names = PyMem_Calloc(count, sizeof(char*));
    GLuint *indices = PyMem_Calloc(count, sizeof(GLuint));
    GLint *offsets = PyMem_Calloc(count, sizeof(GLint));
    PyObject *ans = PyTuple_New(count);
    if (ans == NULL || indices == NULL || names == NULL) return PyErr_NoMemory();
    for (GLsizei i = 0; i < count; i++) { 
        PyObject *t = PySequence_ITEM(pynames, i);
        names[i] = PyUnicode_AsUTF8(t);
        Py_CLEAR(t);
    }
    glGetUniformIndices(program_id, count, (void*)names, indices);
    glGetActiveUniformsiv(program_id, count, indices, GL_UNIFORM_OFFSET, offsets);
    for (GLsizei i = 0; i < count; i++) PyTuple_SET_ITEM(ans, i, PyLong_FromLong(offsets[i]));
    PyMem_Free(names); PyMem_Free(indices); PyMem_Free(offsets);
    if (_enable_error_checking) { 
        SET_GL_ERR; 
        if (PyErr_Occurred()) { Py_CLEAR(ans); return NULL; }
    }
    return ans;
}
 
static PyObject* 
UseProgram(PyObject UNUSED *self, PyObject *val) {
    unsigned long program_id = PyLong_AsUnsignedLong(val);
    glUseProgram(program_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
BindVertexArray(PyObject UNUSED *self, PyObject *val) {
    unsigned long program_id = PyLong_AsUnsignedLong(val);
    glBindVertexArray(program_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
 
static PyObject* 
GetIntegerv(PyObject UNUSED *self, PyObject *val) {
    unsigned long program_id = PyLong_AsUnsignedLong(val);
    GLint ans = 0;
    glGetIntegerv(program_id, &ans);
    CHECK_ERROR;
    return PyLong_FromLong((long)ans);
}

static PyObject* 
BindTexture(PyObject UNUSED *self, PyObject *args) {
    unsigned int tex_id; int target;
    if (!PyArg_ParseTuple(args, "iI", &target, &tex_id)) return NULL;
    glBindTexture(target, tex_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
TexStorage3D(PyObject UNUSED *self, PyObject *args) {
    int target, fmt;
    unsigned int levels, width, height, depth;
    if (!PyArg_ParseTuple(args, "iIiIII", &target, &levels, &fmt, &width, &height, &depth)) return NULL;
    glTexStorage3D(target, levels, fmt, width, height, depth);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
#if defined(__APPLE__) && !defined(glCopyImageSubData)
CopyImageSubData(PyObject UNUSED *self, UNUSED PyObject *args) {
    PyErr_SetString(PyExc_RuntimeError, "OpenGL is missing the required ARB_copy_image extension");
    return NULL;
}
#else
CopyImageSubData(PyObject UNUSED *self, PyObject *args) {
    if(!GLEW_ARB_copy_image) {
        PyErr_SetString(PyExc_RuntimeError, "OpenGL is missing the required ARB_copy_image extension");
        return NULL;
    }
    int src_target, src_level, srcX, srcY, srcZ, dest_target, dest_level, destX, destY, destZ;
    unsigned int src, dest, width, height, depth;
    if (!PyArg_ParseTuple(args, "IiiiiiIiiiiiIII",
        &src, &src_target, &src_level, &srcX, &srcY, &srcZ,
        &dest, &dest_target, &dest_level, &destX, &destY, &destZ,
        &width, &height, &depth
    )) return NULL;
    glCopyImageSubData(src, src_target, src_level, srcX, srcY, srcZ, dest, dest_target, dest_level, destX, destY, destZ, width, height, depth);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
#endif

static PyObject*
copy_image_sub_data(PyObject UNUSED *self, PyObject *args) {
    int src_target, dest_target;
    unsigned int width, height, num_levels;
    if (!PyArg_ParseTuple(args, "iiIII", &src_target, &dest_target, &width, &height, &num_levels)) return NULL;
    uint8_t *src = (uint8_t*)PyMem_Malloc(5 * width * height * num_levels);
    if (src == NULL) return PyErr_NoMemory();
    uint8_t *dest = src + (4 * width * height * num_levels);
    glBindTexture(GL_TEXTURE_2D_ARRAY, src_target);
    glGetTexImage(GL_TEXTURE_2D_ARRAY, 0, GL_RGBA, GL_UNSIGNED_BYTE, src);
    glBindTexture(GL_TEXTURE_2D_ARRAY, dest_target);
    glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
    for(unsigned int i = 0; i < width * height * num_levels; i++) dest[i] = src[4*i];
    glTexSubImage3D(GL_TEXTURE_2D_ARRAY, 0, 0, 0, 0, width, height, num_levels, GL_RED, GL_UNSIGNED_BYTE, dest);
    PyMem_Free(src);
    Py_RETURN_NONE;
}

static PyObject* 
TexSubImage3D(PyObject UNUSED *self, PyObject *args) {
    int target, level, x, y, z, fmt, type;
    unsigned int width, height, depth;
    PyObject *pixels;
    if (!PyArg_ParseTuple(args, "iiiiiIIIiiO!", &target, &level, &x, &y, &z, &width, &height, &depth, &fmt, &type, &PyLong_Type, &pixels)) return NULL;
    void *data = PyLong_AsVoidPtr(pixels);
    if (data == NULL) { PyErr_SetString(PyExc_TypeError, "Not a valid data pointer"); return NULL; }
    glTexSubImage3D(target, level, x, y, z, width, height, depth, fmt, type, data);
    CHECK_ERROR;
    Py_RETURN_NONE;
}


static PyObject*
GetTexImage(PyObject UNUSED *self, PyObject *args) {
    int target, level, fmt, type;
    PyObject *pixels;
    if (!PyArg_ParseTuple(args, "iiiiO!", &target, &level, &fmt, &type, &PyLong_Type, &pixels)) return NULL;
    void *data = PyLong_AsVoidPtr(pixels);
    if (data == NULL) { PyErr_SetString(PyExc_TypeError, "Not a valid data pointer"); return NULL; }
    glGetTexImage(target, level, fmt, type, data);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
GetBufferSubData(PyObject UNUSED *self, PyObject *args) {
    int buftype;
    unsigned long size, target, offset;
    PyObject *address;
    if (!PyArg_ParseTuple(args, "ikkkO!", &buftype, &target, &size, &offset, &PyLong_Type, &address)) return NULL;
    void *data = PyLong_AsVoidPtr(address);
    if (data == NULL) { PyErr_SetString(PyExc_TypeError, "Not a valid data pointer"); return NULL; }
    glBindBuffer(buftype, target); 
    glGetBufferSubData(buftype, offset, size, data);
    CHECK_ERROR;
    glBindBuffer(buftype, 0);
    Py_RETURN_NONE;
}

static PyObject* 
replace_or_create_buffer(PyObject UNUSED *self, PyObject *args) {
    int usage, buftype;
    unsigned long size, prev_sz, target;
    void *data = NULL;
    PyObject *address;
    if (!PyArg_ParseTuple(args, "kkkO!ii", &target, &size, &prev_sz, &PyLong_Type, &address, &usage, &buftype)) return NULL;
    data = PyLong_AsVoidPtr(address);
    glBindBuffer(buftype, target); 
    if (prev_sz == 0 || prev_sz != size) glBufferData(buftype, size, data, usage); 
    else glBufferSubData(buftype, 0, size, data);
    CHECK_ERROR;
    glBindBuffer(buftype, 0);
    Py_RETURN_NONE;
}

static PyObject* 
MapBuffer(PyObject UNUSED *self, PyObject *args) {
    int target, access;
    if (!PyArg_ParseTuple(args, "ii", &target, &access)) return NULL;
    void *address = glMapBuffer(target, access);
    if (address == NULL) { SET_GL_ERR; return NULL; }
    return PyLong_FromVoidPtr(address);
}

static PyObject* 
UnmapBuffer(PyObject UNUSED *self, PyObject *args) {
    int target;
    if (!PyArg_ParseTuple(args, "i", &target)) return NULL;
    if (!glUnmapBuffer(target)) { SET_GL_ERR; return NULL; }
    Py_RETURN_NONE;
}

static PyObject* 
TexParameteri(PyObject UNUSED *self, PyObject *args) {
    int target, name, param;
    if (!PyArg_ParseTuple(args, "iii", &target, &name, &param)) return NULL;
    glTexParameteri(target, name, param);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
PixelStorei(PyObject UNUSED *self, PyObject *args) {
    int name, param;
    if (!PyArg_ParseTuple(args, "ii", &name, &param)) return NULL;
    glPixelStorei(name, param);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
BindBuffer(PyObject UNUSED *self, PyObject *args) {
    int tgt; unsigned int buf_id;
    if (!PyArg_ParseTuple(args, "iI", &tgt, &buf_id)) return NULL;
    glBindBuffer(tgt, buf_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
BindBufferBase(PyObject UNUSED *self, PyObject *args) {
    int tgt; unsigned int index, buf_id;
    if (!PyArg_ParseTuple(args, "iII", &tgt, &index, &buf_id)) return NULL;
    glBindBufferBase(tgt, index, buf_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
TexBuffer(PyObject UNUSED *self, PyObject *args) {
    int tgt, fmt; unsigned int buf_id;
    if (!PyArg_ParseTuple(args, "iiI", &tgt, &fmt, &buf_id)) return NULL;
    glTexBuffer(tgt, fmt, buf_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
DeleteTexture(PyObject UNUSED *self, PyObject *val) {
    GLuint tex_id = (GLuint)PyLong_AsUnsignedLong(val);
    glDeleteTextures(1, &tex_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
 
static PyObject* 
DeleteBuffer(PyObject UNUSED *self, PyObject *val) {
    GLuint tex_id = (GLuint)PyLong_AsUnsignedLong(val);
    glDeleteBuffers(1, &tex_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
 
static PyObject* 
DeleteVertexArray(PyObject UNUSED *self, PyObject *val) {
    GLuint tex_id = (GLuint)PyLong_AsUnsignedLong(val);
    glDeleteVertexArrays(1, &tex_id);
    CHECK_ERROR;
    Py_RETURN_NONE;
}
 
static PyObject* 
BlendFunc(PyObject UNUSED *self, PyObject *args) {
    int s, d;
    if (!PyArg_ParseTuple(args, "ii", &s, &d)) return NULL;
    glBlendFunc(s, d);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
Enable(PyObject UNUSED *self, PyObject *val) {
    long x = PyLong_AsLong(val);
    glEnable(x);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
Disable(PyObject UNUSED *self, PyObject *val) {
    long x = PyLong_AsLong(val);
    glDisable(x);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
EnableVertexAttribArray(PyObject UNUSED *self, PyObject *val) {
    long x = PyLong_AsLong(val);
    glEnableVertexAttribArray(x);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
VertexAttribPointer(PyObject UNUSED *self, PyObject *args) {
    unsigned int index;
    int type, normalized, size, stride;
    unsigned long offset;
    if (!PyArg_ParseTuple(args, "Iiipik", &index, &size, &type, &normalized, &stride, &offset)) return NULL;
    switch(type) {
        case GL_BYTE:
        case GL_UNSIGNED_BYTE:
        case GL_SHORT:
        case GL_UNSIGNED_SHORT:
        case GL_INT:
        case GL_UNSIGNED_INT:
            glVertexAttribIPointer(index, size, type, stride, (GLvoid*)offset);
            break;
        default:
            glVertexAttribPointer(index, size, type, normalized ? GL_TRUE : GL_FALSE, stride, (GLvoid*)offset);
            break;
    }
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
VertexAttribDivisor(PyObject UNUSED *self, PyObject *args) {
    unsigned int index, divisor;
    if (!PyArg_ParseTuple(args, "II", &index, &divisor)) return NULL;
    glVertexAttribDivisor(index, divisor);
    CHECK_ERROR;
    Py_RETURN_NONE;
}

static PyObject* 
Flush(PyObject UNUSED *self) {
    glFinish();
    Py_RETURN_NONE;
}

static PyObject* 
Finish(PyObject UNUSED *self) {
    glFinish();
    Py_RETURN_NONE;
}

static PyObject*
check_for_extensions(PyObject UNUSED *self) {
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

static PyMethodDef module_methods[] = {
    {"copy_image_sub_data", (PyCFunction)copy_image_sub_data, METH_VARARGS, NULL}, 
    {"replace_or_create_buffer", (PyCFunction)replace_or_create_buffer, METH_VARARGS, NULL}, 
    {"check_for_extensions", (PyCFunction)check_for_extensions, METH_NOARGS, NULL}, 
    {"get_uniform_block_size", (PyCFunction)get_uniform_block_size, METH_VARARGS, NULL}, 
    {"get_uniform_block_offsets", (PyCFunction)get_uniform_block_offsets, METH_VARARGS, NULL}, 
    METH(Viewport, METH_VARARGS) 
    METH(CheckError, METH_NOARGS) 
    METH(ClearColor, METH_VARARGS) 
    METH(GetProgramiv, METH_VARARGS) 
    METH(GetShaderiv, METH_VARARGS) 
    METH(Uniform2ui, METH_VARARGS) 
    METH(Uniform4ui, METH_VARARGS) 
    METH(Uniform1uiv, METH_VARARGS) 
    METH(Uniform2i, METH_VARARGS) 
    METH(Uniform1i, METH_VARARGS) 
    METH(Uniform2f, METH_VARARGS) 
    METH(Uniform4f, METH_VARARGS) 
    METH(Uniform3fv, METH_VARARGS) 
    METH(GetUniformLocation, METH_VARARGS) 
    METH(GetUniformBlockIndex, METH_VARARGS) 
    METH(GetAttribLocation, METH_VARARGS) 
    METH(ShaderSource, METH_VARARGS) 
    METH(CompileShader, METH_O) 
    METH(DeleteTexture, METH_O) 
    METH(DeleteBuffer, METH_O) 
    METH(DeleteVertexArray, METH_O) 
    METH(GetString, METH_O) 
    METH(GetIntegerv, METH_O) 
    METH(Clear, METH_O) 
    METH(CreateShader, METH_O) 
    METH(GenVertexArrays, METH_O) 
    METH(GenTextures, METH_O) 
    METH(GenBuffers, METH_O) 
    METH(LinkProgram, METH_O) 
    METH(UseProgram, METH_O) 
    METH(BindVertexArray, METH_O) 
    METH(DeleteProgram, METH_O) 
    METH(DeleteShader, METH_O) 
    METH(Enable, METH_O) 
    METH(Disable, METH_O) 
    METH(EnableVertexAttribArray, METH_O) 
    METH(VertexAttribPointer, METH_VARARGS) 
    METH(VertexAttribDivisor, METH_VARARGS) 
    METH(GetProgramInfoLog, METH_O) 
    METH(GetShaderInfoLog, METH_O) 
    METH(ActiveTexture, METH_O) 
    METH(DrawArraysInstanced, METH_VARARGS) 
    METH(DrawArrays, METH_VARARGS) 
    METH(MultiDrawArrays, METH_VARARGS) 
    METH(CreateProgram, METH_NOARGS) 
    METH(AttachShader, METH_VARARGS) 
    METH(BindTexture, METH_VARARGS) 
    METH(TexParameteri, METH_VARARGS) 
    METH(MapBuffer, METH_VARARGS) 
    METH(UnmapBuffer, METH_VARARGS) 
    METH(PixelStorei, METH_VARARGS) 
    METH(BindBuffer, METH_VARARGS) 
    METH(BindBufferBase, METH_VARARGS) 
    METH(TexBuffer, METH_VARARGS) 
    METH(TexStorage3D, METH_VARARGS) 
    METH(CopyImageSubData, METH_VARARGS) 
    METH(TexSubImage3D, METH_VARARGS) 
    METH(GetTexImage, METH_VARARGS) 
    METH(GetBufferSubData, METH_VARARGS) 
    METH(BlendFunc, METH_VARARGS) 
    METH(Finish, METH_NOARGS) 
    METH(Flush, METH_NOARGS) 

    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
add_module_gl_constants(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}



