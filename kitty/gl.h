/*
 * gl.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <GL/glew.h>

#define STRINGIFY(x) #x
#define METH(name, argtype) {STRINGIFY(gl##name), (PyCFunction)name, argtype, NULL},

static int _enable_error_checking = 1;

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
enable_automatic_error_checking(PyObject UNUSED *self, PyObject *val) {
    _enable_error_checking = PyObject_IsTrue(val) ? 1 : 0;
    Py_RETURN_NONE;
}

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
// }}}


static PyObject* 
CheckError(PyObject UNUSED *self) {
    CHECK_ERROR; Py_RETURN_NONE;
}

static PyObject* 
_glewInit(PyObject UNUSED *self) {
    GLenum err = glewInit();
    if (err != GLEW_OK) {
        PyErr_Format(PyExc_RuntimeError, "GLEW init failed: %s", glewGetErrorString(err));
        return NULL;
    }
    if(!GLEW_ARB_copy_image) {
        PyErr_SetString(PyExc_RuntimeError, "OpenGL is missing the required ARB_copy_image extension");
        return NULL;
    }
    if(!GLEW_ARB_texture_storage) {
        PyErr_SetString(PyExc_RuntimeError, "OpenGL is missing the required ARB_texture_storage extension");
        return NULL;
    }
    Py_RETURN_NONE;
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
    glShaderSource(shader_id, 1, (const GLchar * const*)&src, NULL);
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
GetAttribLocation(PyObject UNUSED *self, PyObject *args) {
    char *name;
    unsigned int program_id;
    if(!PyArg_ParseTuple(args, "Is", &program_id, &name)) return NULL;
    GLint ans = glGetAttribLocation(program_id, name);
    CHECK_ERROR;
    return PyLong_FromLong((long) ans);
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
 
int add_module_gl_constants(PyObject *module) {
#define GLC(x) if (PyModule_AddIntConstant(module, #x, x) != 0) { PyErr_NoMemory(); return 0; }
    GLC(GL_VERSION);
    GLC(GL_VENDOR);
    GLC(GL_SHADING_LANGUAGE_VERSION);
    GLC(GL_RENDERER);
    GLC(GL_TRIANGLE_FAN);
    GLC(GL_COLOR_BUFFER_BIT);
    GLC(GL_VERTEX_SHADER);
    GLC(GL_FRAGMENT_SHADER);
    GLC(GL_TRUE);
    GLC(GL_FALSE);
    GLC(GL_COMPILE_STATUS);
    GLC(GL_LINK_STATUS);
    GLC(GL_TEXTURE0); GLC(GL_TEXTURE1); GLC(GL_TEXTURE2); GLC(GL_TEXTURE3); GLC(GL_TEXTURE4); GLC(GL_TEXTURE5); GLC(GL_TEXTURE6); GLC(GL_TEXTURE7); GLC(GL_TEXTURE8);
    GLC(GL_MAX_ARRAY_TEXTURE_LAYERS); 
    GLC(GL_MAX_TEXTURE_SIZE);
    GLC(GL_TEXTURE_2D_ARRAY);
    GLC(GL_LINEAR); GLC(GL_CLAMP_TO_EDGE);
    GLC(GL_TEXTURE_MIN_FILTER); GLC(GL_TEXTURE_MAG_FILTER);
    GLC(GL_TEXTURE_WRAP_S); GLC(GL_TEXTURE_WRAP_T);
    GLC(GL_UNPACK_ALIGNMENT);
    GLC(GL_R8); GLC(GL_RED); GLC(GL_UNSIGNED_BYTE); GLC(GL_RGB32UI);
    GLC(GL_TEXTURE_BUFFER); GLC(GL_STATIC_DRAW);
    return 1;
}


#define GL_METHODS \
    {"enable_automatic_opengl_error_checking", (PyCFunction)enable_automatic_error_checking, METH_O, NULL}, \
    {"glewInit", (PyCFunction)_glewInit, METH_NOARGS, NULL}, \
    METH(Viewport, METH_VARARGS) \
    METH(CheckError, METH_NOARGS) \
    METH(ClearColor, METH_VARARGS) \
    METH(GetProgramiv, METH_VARARGS) \
    METH(GetShaderiv, METH_VARARGS) \
    METH(Uniform2ui, METH_VARARGS) \
    METH(Uniform1i, METH_VARARGS) \
    METH(Uniform2f, METH_VARARGS) \
    METH(Uniform4f, METH_VARARGS) \
    METH(GetUniformLocation, METH_VARARGS) \
    METH(GetAttribLocation, METH_VARARGS) \
    METH(ShaderSource, METH_VARARGS) \
    METH(CompileShader, METH_O) \
    METH(DeleteTexture, METH_O) \
    METH(GetString, METH_O) \
    METH(GetIntegerv, METH_O) \
    METH(Clear, METH_O) \
    METH(CreateShader, METH_O) \
    METH(GenVertexArrays, METH_O) \
    METH(GenTextures, METH_O) \
    METH(GenBuffers, METH_O) \
    METH(LinkProgram, METH_O) \
    METH(UseProgram, METH_O) \
    METH(BindVertexArray, METH_O) \
    METH(DeleteProgram, METH_O) \
    METH(DeleteShader, METH_O) \
    METH(GetProgramInfoLog, METH_O) \
    METH(GetShaderInfoLog, METH_O) \
    METH(ActiveTexture, METH_O) \
    METH(DrawArraysInstanced, METH_VARARGS) \
    METH(CreateProgram, METH_NOARGS) \
    METH(AttachShader, METH_VARARGS) \
    METH(BindTexture, METH_VARARGS) \
    METH(TexParameteri, METH_VARARGS) \
    METH(PixelStorei, METH_VARARGS) \
    METH(BindBuffer, METH_VARARGS) \
    METH(TexBuffer, METH_VARARGS) \

