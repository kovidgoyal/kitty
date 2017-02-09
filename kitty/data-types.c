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

static char drain_buf[1024] = {0};

static PyObject*
drain_read(PyObject UNUSED *self, PyObject *fd) {
    ALLOW_UNUSED_RESULT
    read(PyLong_AsLong(fd), drain_buf, sizeof(drain_buf));
    END_ALLOW_UNUSED_RESULT 
    Py_RETURN_NONE;
}

static PyObject*
wcwidth_wrap(PyObject UNUSED *self, PyObject *chr) {
    return PyLong_FromUnsignedLong(safe_wcwidth(PyLong_AsLong(chr)));
}

static PyObject*
change_wcwidth_wrap(PyObject UNUSED *self, PyObject *use9) {
    change_wcwidth(PyObject_IsTrue(use9));
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    GL_METHODS
    {"drain_read", (PyCFunction)drain_read, METH_O, ""},
    {"parse_bytes", (PyCFunction)parse_bytes, METH_VARARGS, ""},
    {"parse_bytes_dump", (PyCFunction)parse_bytes_dump, METH_VARARGS, ""},
    {"read_bytes", (PyCFunction)read_bytes, METH_VARARGS, ""},
    {"read_bytes_dump", (PyCFunction)read_bytes_dump, METH_VARARGS, ""},
    {"wcwidth", (PyCFunction)wcwidth_wrap, METH_O, ""},
    {"change_wcwidth", (PyCFunction)change_wcwidth_wrap, METH_O, ""},
#ifndef __APPLE__
    {"get_fontconfig_font", (PyCFunction)get_fontconfig_font, METH_VARARGS, ""},
#endif
    GLFW_FUNC_WRAPPERS
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


static struct PyModuleDef module = {
   .m_base = PyModuleDef_HEAD_INIT,
   .m_name = "fast_data_types",   /* name of module */
   .m_doc = NULL, 
   .m_size = -1,       
   .m_methods = module_methods
};

PyMODINIT_FUNC
PyInit_fast_data_types(void) {
    PyObject *m;

    m = PyModule_Create(&module);
    if (m == NULL) return NULL;

    if (m != NULL) {
        if (!init_LineBuf(m)) return NULL;
        if (!init_HistoryBuf(m)) return NULL;
        if (!init_Line(m)) return NULL;
        if (!init_Cursor(m)) return NULL;
        if (!init_ColorProfile(m)) return NULL;
        if (!init_SpriteMap(m)) return NULL;
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
