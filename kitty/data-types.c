/*
 * data-types.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "glfw.h"
#include "gl.h"
#include "modes.h"
#include "sprites.h"
#include <stddef.h>
#ifdef WITH_PROFILER
#include <gperftools/profiler.h>
#endif


static PyObject*
wcwidth_wrap(PyObject UNUSED *self, PyObject *chr) {
    return PyLong_FromUnsignedLong(safe_wcwidth(PyLong_AsLong(chr)));
}

static PyObject*
change_wcwidth_wrap(PyObject UNUSED *self, PyObject *use9) {
    change_wcwidth(PyObject_IsTrue(use9));
    Py_RETURN_NONE;
}

static PyObject*
redirect_std_streams(PyObject UNUSED *self, PyObject *args) {
    char *devnull = NULL;
    if (!PyArg_ParseTuple(args, "s", &devnull)) return NULL;
    if (freopen(devnull, "r", stdin) == NULL) return PyErr_SetFromErrno(PyExc_EnvironmentError);
    if (freopen(devnull, "w", stdout) == NULL) return PyErr_SetFromErrno(PyExc_EnvironmentError);
    if (freopen(devnull, "w", stderr) == NULL)  return PyErr_SetFromErrno(PyExc_EnvironmentError);
    Py_RETURN_NONE;
}

static PyObject*
pyset_iutf8(PyObject UNUSED *self, PyObject *args) {
    int fd, on;
    if (!PyArg_ParseTuple(args, "ip", &fd, &on)) return NULL;
    if (!set_iutf8(fd, on & 1)) return PyErr_SetFromErrno(PyExc_OSError);
    Py_RETURN_NONE;
}

#ifdef WITH_PROFILER
static PyObject*
start_profiler(PyObject UNUSED *self, PyObject *args) {
    char *path;
    if (!PyArg_ParseTuple(args, "s", &path)) return NULL;
    ProfilerStart(path);
    Py_RETURN_NONE;
}

static PyObject*
stop_profiler(PyObject UNUSED *self) {
    ProfilerStop();
    Py_RETURN_NONE;
}
#endif

#ifdef __APPLE__
#include "core_text.h"
#endif

static PyMethodDef module_methods[] = {
    GL_METHODS
    {"set_iutf8", (PyCFunction)pyset_iutf8, METH_VARARGS, ""},
    {"thread_write", (PyCFunction)cm_thread_write, METH_VARARGS, ""},
    {"parse_bytes", (PyCFunction)parse_bytes, METH_VARARGS, ""},
    {"parse_bytes_dump", (PyCFunction)parse_bytes_dump, METH_VARARGS, ""},
    {"redirect_std_streams", (PyCFunction)redirect_std_streams, METH_VARARGS, ""},
    {"wcwidth", (PyCFunction)wcwidth_wrap, METH_O, ""},
    {"change_wcwidth", (PyCFunction)change_wcwidth_wrap, METH_O, ""},
#ifdef __APPLE__
    CORE_TEXT_FUNC_WRAPPERS
#else
    {"get_fontconfig_font", (PyCFunction)get_fontconfig_font, METH_VARARGS, ""},
#endif
    GLFW_FUNC_WRAPPERS
    SPRITE_FUNC_WRAPPERS
#ifdef WITH_PROFILER
    {"start_profiler", (PyCFunction)start_profiler, METH_VARARGS, ""},
    {"stop_profiler", (PyCFunction)stop_profiler, METH_NOARGS, ""},
#endif
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


static struct PyModuleDef module = {
   .m_base = PyModuleDef_HEAD_INIT,
   .m_name = "fast_data_types",   /* name of module */
   .m_doc = NULL, 
   .m_size = -1,       
   .m_methods = module_methods
};

#include <termios.h>

EXPORTED PyMODINIT_FUNC
PyInit_fast_data_types(void) {
    PyObject *m;

    m = PyModule_Create(&module);
    if (m == NULL) return NULL;

    if (m != NULL) {
        if (!init_LineBuf(m)) return NULL;
        if (!init_HistoryBuf(m)) return NULL;
        if (!init_Line(m)) return NULL;
        if (!init_Cursor(m)) return NULL;
        if (!init_Timers(m)) return NULL;
        if (!init_ChildMonitor(m)) return NULL;
        if (!init_ColorProfile(m)) return NULL;
        if (!init_ChangeTracker(m)) return NULL;
        if (!init_Screen(m)) return NULL;
        if (!add_module_gl_constants(m)) return NULL;
        if (!init_glfw(m)) return NULL;
        if (!init_Window(m)) return NULL;
#ifdef __APPLE__
        if (!init_CoreText(m)) return NULL;
#else
        if (!init_Face(m)) return NULL;
        if (!init_freetype_library(m)) return NULL;
        if (!init_fontconfig_library(m)) return NULL;
#endif

#define OOF(n) #n, offsetof(Cell, n)
        if (PyModule_AddObject(m, "CELL", Py_BuildValue("{sI sI sI sI sI sI sI sI sI}",
                    OOF(ch), OOF(fg), OOF(bg), OOF(decoration_fg), OOF(cc), OOF(sprite_x), OOF(sprite_y), OOF(sprite_z), "size", sizeof(Cell))) != 0) return NULL;
#undef OOF
        PyModule_AddIntConstant(m, "BOLD", BOLD_SHIFT);
        PyModule_AddIntConstant(m, "ITALIC", ITALIC_SHIFT);
        PyModule_AddIntConstant(m, "REVERSE", REVERSE_SHIFT);
        PyModule_AddIntConstant(m, "STRIKETHROUGH", STRIKE_SHIFT);
        PyModule_AddIntConstant(m, "DECORATION", DECORATION_SHIFT);
        PyModule_AddStringMacro(m, BRACKETED_PASTE_START);
        PyModule_AddStringMacro(m, BRACKETED_PASTE_END);
        PyModule_AddStringMacro(m, ERROR_PREFIX);
        PyModule_AddIntMacro(m, CURSOR_BLOCK);
        PyModule_AddIntMacro(m, CURSOR_BEAM);
        PyModule_AddIntMacro(m, CURSOR_UNDERLINE);
        PyModule_AddIntMacro(m, DECAWM);
        PyModule_AddIntMacro(m, DECCOLM);
        PyModule_AddIntMacro(m, DECOM);
        PyModule_AddIntMacro(m, IRM);
        PyModule_AddIntMacro(m, DATA_CELL_SIZE);
        PyModule_AddIntMacro(m, ANY_MODE);
        PyModule_AddIntMacro(m, MOTION_MODE);
        PyModule_AddIntMacro(m, BUTTON_MODE);
        PyModule_AddIntMacro(m, SGR_PROTOCOL);
        PyModule_AddIntMacro(m, NORMAL_PROTOCOL);
        PyModule_AddIntMacro(m, URXVT_PROTOCOL);
        PyModule_AddIntMacro(m, UTF8_PROTOCOL);
    }

    return m;
}
