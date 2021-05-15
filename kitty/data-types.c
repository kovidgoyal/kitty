/*
 * data-types.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#ifdef __APPLE__
// Needed for _CS_DARWIN_USER_CACHE_DIR
#define _DARWIN_C_SOURCE
#include <unistd.h>
#undef _DARWIN_C_SOURCE
#endif
#include "data-types.h"
#include "cleanup.h"
#include "safe-wrappers.h"
#include "control-codes.h"
#include "wcwidth-std.h"
#include "wcswidth.h"
#include "modes.h"
#include <stddef.h>
#include <termios.h>
#include <signal.h>
#include <fcntl.h>
#include <stdio.h>
#ifdef WITH_PROFILER
#include <gperftools/profiler.h>
#endif
#include "monotonic.h"

#ifdef __APPLE__
#include <libproc.h>

static PyObject*
user_cache_dir() {
    static char buf[1024];
    if (!confstr(_CS_DARWIN_USER_CACHE_DIR, buf, sizeof(buf) - 1)) return PyErr_SetFromErrno(PyExc_OSError);
    return PyUnicode_FromString(buf);
}

static PyObject*
process_group_map() {
    int num_of_processes = proc_listallpids(NULL, 0);
    size_t bufsize = sizeof(pid_t) * (num_of_processes + 1024);
    FREE_AFTER_FUNCTION pid_t *buf = malloc(bufsize);
    if (!buf) return PyErr_NoMemory();
    num_of_processes = proc_listallpids(buf, (int)bufsize);
    PyObject *ans = PyTuple_New(num_of_processes);
    if (ans == NULL) { return PyErr_NoMemory(); }
    for (int i = 0; i < num_of_processes; i++) {
        long pid = buf[i], pgid = getpgid(buf[i]);
        PyObject *t = Py_BuildValue("ll", pid, pgid);
        if (t == NULL) { Py_DECREF(ans); return NULL; }
        PyTuple_SET_ITEM(ans, i, t);
    }
    return ans;
}
#endif

static PyObject*
redirect_std_streams(PyObject UNUSED *self, PyObject *args) {
    char *devnull = NULL;
    if (!PyArg_ParseTuple(args, "s", &devnull)) return NULL;
    if (freopen(devnull, "r", stdin) == NULL) return PyErr_SetFromErrno(PyExc_OSError);
    if (freopen(devnull, "w", stdout) == NULL) return PyErr_SetFromErrno(PyExc_OSError);
    if (freopen(devnull, "w", stderr) == NULL)  return PyErr_SetFromErrno(PyExc_OSError);
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
stop_profiler(PyObject UNUSED *self, PyObject *args UNUSED) {
    ProfilerStop();
    Py_RETURN_NONE;
}
#endif

static inline bool
put_tty_in_raw_mode(int fd, const struct termios* termios_p, bool read_with_timeout, int optional_actions) {
    struct termios raw_termios = *termios_p;
    cfmakeraw(&raw_termios);
    if (read_with_timeout) {
        raw_termios.c_cc[VMIN] = 0; raw_termios.c_cc[VTIME] = 1;
    } else {
        raw_termios.c_cc[VMIN] = 1; raw_termios.c_cc[VTIME] = 0;
    }
    if (tcsetattr(fd, optional_actions, &raw_termios) != 0) { PyErr_SetFromErrno(PyExc_OSError); return false; }
    return true;
}

static PyObject*
open_tty(PyObject *self UNUSED, PyObject *args) {
    int read_with_timeout = 0, optional_actions = TCSAFLUSH;
    if (!PyArg_ParseTuple(args, "|pi", &read_with_timeout, &optional_actions)) return NULL;
    int flags = O_RDWR | O_CLOEXEC | O_NOCTTY;
    if (!read_with_timeout) flags |= O_NONBLOCK;
    static char ctty[L_ctermid+1];
    int fd = safe_open(ctermid(ctty), flags, 0);
    if (fd == -1) { PyErr_Format(PyExc_OSError, "Failed to open controlling terminal: %s (identified with ctermid()) with error: %s", ctty, strerror(errno)); return NULL; }
    struct termios *termios_p = calloc(1, sizeof(struct termios));
    if (!termios_p) return PyErr_NoMemory();
    if (tcgetattr(fd, termios_p) != 0) { free(termios_p); PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    if (!put_tty_in_raw_mode(fd, termios_p, read_with_timeout != 0, optional_actions)) { free(termios_p); return NULL; }
    return Py_BuildValue("iN", fd, PyLong_FromVoidPtr(termios_p));
}

#define TTY_ARGS \
    PyObject *tp; int fd; int optional_actions = TCSAFLUSH; \
    if (!PyArg_ParseTuple(args, "iO!|i", &fd, &PyLong_Type, &tp, &optional_actions)) return NULL; \
    struct termios *termios_p = PyLong_AsVoidPtr(tp);

static PyObject*
normal_tty(PyObject *self UNUSED, PyObject *args) {
    TTY_ARGS
    if (tcsetattr(fd, optional_actions, termios_p) != 0) { PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    Py_RETURN_NONE;
}

static PyObject*
raw_tty(PyObject *self UNUSED, PyObject *args) {
    TTY_ARGS
    if (!put_tty_in_raw_mode(fd, termios_p, false, optional_actions)) return NULL;
    Py_RETURN_NONE;
}


static PyObject*
close_tty(PyObject *self UNUSED, PyObject *args) {
    TTY_ARGS
    tcsetattr(fd, optional_actions, termios_p);  // deliberately ignore failure
    free(termios_p);
    safe_close(fd, __FILE__, __LINE__);
    Py_RETURN_NONE;
}

#undef TTY_ARGS

static PyObject*
wcwidth_wrap(PyObject UNUSED *self, PyObject *chr) {
    return PyLong_FromLong(wcwidth_std(PyLong_AsLong(chr)));
}


static PyMethodDef module_methods[] = {
    {"wcwidth", (PyCFunction)wcwidth_wrap, METH_O, ""},
    {"wcswidth", (PyCFunction)wcswidth_std, METH_O, ""},
    {"open_tty", open_tty, METH_VARARGS, ""},
    {"normal_tty", normal_tty, METH_VARARGS, ""},
    {"raw_tty", raw_tty, METH_VARARGS, ""},
    {"close_tty", close_tty, METH_VARARGS, ""},
    {"set_iutf8_fd", (PyCFunction)pyset_iutf8, METH_VARARGS, ""},
    {"thread_write", (PyCFunction)cm_thread_write, METH_VARARGS, ""},
    {"parse_bytes", (PyCFunction)parse_bytes, METH_VARARGS, ""},
    {"parse_bytes_dump", (PyCFunction)parse_bytes_dump, METH_VARARGS, ""},
    {"redirect_std_streams", (PyCFunction)redirect_std_streams, METH_VARARGS, ""},
#ifdef __APPLE__
    METHODB(user_cache_dir, METH_NOARGS),
    METHODB(process_group_map, METH_NOARGS),
#endif
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


extern int init_LineBuf(PyObject *);
extern int init_HistoryBuf(PyObject *);
extern int init_Cursor(PyObject *);
extern int init_DiskCache(PyObject *);
extern bool init_child_monitor(PyObject *);
extern int init_Line(PyObject *);
extern int init_ColorProfile(PyObject *);
extern int init_Screen(PyObject *);
extern bool init_fontconfig_library(PyObject*);
extern bool init_desktop(PyObject*);
extern bool init_fonts(PyObject*);
extern bool init_glfw(PyObject *m);
extern bool init_child(PyObject *m);
extern bool init_state(PyObject *module);
extern bool init_keys(PyObject *module);
extern bool init_graphics(PyObject *module);
extern bool init_shaders(PyObject *module);
extern bool init_mouse(PyObject *module);
extern bool init_kittens(PyObject *module);
extern bool init_logging(PyObject *module);
extern bool init_png_reader(PyObject *module);
#ifdef __APPLE__
extern int init_CoreText(PyObject *);
extern bool init_cocoa(PyObject *module);
extern bool init_macos_process_info(PyObject *module);
#else
extern bool init_freetype_library(PyObject*);
extern bool init_freetype_render_ui_text(PyObject*);
#endif


EXPORTED PyMODINIT_FUNC
PyInit_fast_data_types(void) {
    PyObject *m;

    m = PyModule_Create(&module);
    if (m == NULL) return NULL;
    if (Py_AtExit(run_at_exit_cleanup_functions) != 0) {
        PyErr_SetString(PyExc_RuntimeError, "Failed to register the atexit cleanup handler");
        return NULL;
    }
    init_monotonic();

    if (!init_logging(m)) return NULL;
    if (!init_LineBuf(m)) return NULL;
    if (!init_HistoryBuf(m)) return NULL;
    if (!init_Line(m)) return NULL;
    if (!init_Cursor(m)) return NULL;
    if (!init_DiskCache(m)) return NULL;
    if (!init_child_monitor(m)) return NULL;
    if (!init_ColorProfile(m)) return NULL;
    if (!init_Screen(m)) return NULL;
    if (!init_glfw(m)) return NULL;
    if (!init_child(m)) return NULL;
    if (!init_state(m)) return NULL;
    if (!init_keys(m)) return NULL;
    if (!init_graphics(m)) return NULL;
    if (!init_shaders(m)) return NULL;
    if (!init_mouse(m)) return NULL;
    if (!init_kittens(m)) return NULL;
    if (!init_png_reader(m)) return NULL;
#ifdef __APPLE__
    if (!init_macos_process_info(m)) return NULL;
    if (!init_CoreText(m)) return NULL;
    if (!init_cocoa(m)) return NULL;
#else
    if (!init_freetype_library(m)) return NULL;
    if (!init_fontconfig_library(m)) return NULL;
    if (!init_desktop(m)) return NULL;
    if (!init_freetype_render_ui_text(m)) return NULL;
#endif
    if (!init_fonts(m)) return NULL;

    PyModule_AddIntConstant(m, "BOLD", BOLD_SHIFT);
    PyModule_AddIntConstant(m, "ITALIC", ITALIC_SHIFT);
    PyModule_AddIntConstant(m, "REVERSE", REVERSE_SHIFT);
    PyModule_AddIntConstant(m, "STRIKETHROUGH", STRIKE_SHIFT);
    PyModule_AddIntConstant(m, "DIM", DIM_SHIFT);
    PyModule_AddIntConstant(m, "DECORATION", DECORATION_SHIFT);
    PyModule_AddIntConstant(m, "MARK", MARK_SHIFT);
    PyModule_AddIntConstant(m, "MARK_MASK", MARK_MASK);
    PyModule_AddStringMacro(m, ERROR_PREFIX);
#ifdef KITTY_VCS_REV
    PyModule_AddStringMacro(m, KITTY_VCS_REV);
#endif
    PyModule_AddIntMacro(m, CURSOR_BLOCK);
    PyModule_AddIntMacro(m, CURSOR_BEAM);
    PyModule_AddIntMacro(m, CURSOR_UNDERLINE);
    PyModule_AddIntMacro(m, NO_CURSOR_SHAPE);
    PyModule_AddIntMacro(m, DECAWM);
    PyModule_AddIntMacro(m, DECCOLM);
    PyModule_AddIntMacro(m, DECOM);
    PyModule_AddIntMacro(m, IRM);
    PyModule_AddIntMacro(m, CSI);
    PyModule_AddIntMacro(m, DCS);
    PyModule_AddIntMacro(m, APC);
    PyModule_AddIntMacro(m, OSC);

    return m;
}
