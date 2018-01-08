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
#include "control-codes.h"
#include "modes.h"
#include <stddef.h>
#include <termios.h>
#include <signal.h>
#include <sys/wait.h>
#ifdef WITH_PROFILER
#include <gperftools/profiler.h>
#endif

/* To millisecond (10^-3) */
#define SEC_TO_MS 1000

/* To microseconds (10^-6) */
#define MS_TO_US 1000
#define SEC_TO_US (SEC_TO_MS * MS_TO_US)

/* To nanoseconds (10^-9) */
#define US_TO_NS 1000
#define MS_TO_NS (MS_TO_US * US_TO_NS)
#define SEC_TO_NS (SEC_TO_MS * MS_TO_NS)

/* Conversion from nanoseconds */
#define NS_TO_MS (1000 * 1000)
#define NS_TO_US (1000)

#ifdef __APPLE__
#include <mach/mach_time.h>
static mach_timebase_info_data_t timebase = {0};

static inline double monotonic_() {
	return ((double)(mach_absolute_time() * timebase.numer) / timebase.denom)/SEC_TO_NS;
}

static PyObject*
user_cache_dir() {
    static char buf[1024];
    if (!confstr(_CS_DARWIN_USER_CACHE_DIR, buf, sizeof(buf) - 1)) return PyErr_SetFromErrno(PyExc_OSError);
    return PyUnicode_FromString(buf);
}

#else
#include <time.h>
static inline double monotonic_() {
    struct timespec ts = {0};
#ifdef CLOCK_HIGHRES
	clock_gettime(CLOCK_HIGHRES, &ts);
#elif CLOCK_MONOTONIC_RAW
	clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
#else
	clock_gettime(CLOCK_MONOTONIC, &ts);
#endif
	return (((double)ts.tv_nsec) / SEC_TO_NS) + (double)ts.tv_sec;
}
#endif

double monotonic() { return monotonic_(); }

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

static void
handle_sigchld(int UNUSED signum, siginfo_t *sinfo, void UNUSED *unused) {
    if (sinfo->si_code != CLD_EXITED) return;
    int sav_errno = errno, status;
    while(true) {
        if (waitpid(sinfo->si_pid, &status, WNOHANG) == -1) {
            if (errno != EINTR) break;
        } else break;
    }
    // wakeup I/O loop as without this on macOS sometimes poll() does not detect the fd close, so
    // kitty does not detect child death.
    wakeup_io_loop(true);
    errno = sav_errno;
}

static PyObject*
install_sigchld_handler(PyObject UNUSED *self) {
    struct sigaction sa;
    sa.sa_flags = SA_SIGINFO;
    sa.sa_sigaction = handle_sigchld;
    sigemptyset(&sa.sa_mask);
    if (sigaction(SIGCHLD, &sa, NULL) == -1) return PyErr_SetFromErrno(PyExc_OSError);
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

static PyMethodDef module_methods[] = {
    {"set_iutf8", (PyCFunction)pyset_iutf8, METH_VARARGS, ""},
    {"thread_write", (PyCFunction)cm_thread_write, METH_VARARGS, ""},
    {"parse_bytes", (PyCFunction)parse_bytes, METH_VARARGS, ""},
    {"parse_bytes_dump", (PyCFunction)parse_bytes_dump, METH_VARARGS, ""},
    {"redirect_std_streams", (PyCFunction)redirect_std_streams, METH_VARARGS, ""},
    {"wcwidth", (PyCFunction)wcwidth_wrap, METH_O, ""},
    {"change_wcwidth", (PyCFunction)change_wcwidth_wrap, METH_O, ""},
    {"install_sigchld_handler", (PyCFunction)install_sigchld_handler, METH_NOARGS, ""},
#ifdef __APPLE__
    METHODB(user_cache_dir, METH_NOARGS),
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
#ifdef __APPLE__
extern int init_CoreText(PyObject *);
extern bool init_cocoa(PyObject *module);
#else
extern bool init_freetype_library(PyObject*);
#endif


EXPORTED PyMODINIT_FUNC
PyInit_fast_data_types(void) {
    PyObject *m;

    m = PyModule_Create(&module);
    if (m == NULL) return NULL;
#ifdef __APPLE__
    mach_timebase_info(&timebase);
#endif

    if (m != NULL) {
        if (!init_LineBuf(m)) return NULL;
        if (!init_HistoryBuf(m)) return NULL;
        if (!init_Line(m)) return NULL;
        if (!init_Cursor(m)) return NULL;
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
#ifdef __APPLE__
        if (!init_CoreText(m)) return NULL;
        if (!init_cocoa(m)) return NULL;
#else
        if (!init_freetype_library(m)) return NULL;
        if (!init_fontconfig_library(m)) return NULL;
        if (!init_desktop(m)) return NULL;
#endif
        if (!init_fonts(m)) return NULL;

#define OOF(n) #n, offsetof(Cell, n)
        if (PyModule_AddObject(m, "CELL", Py_BuildValue("{sI sI sI sI sI sI sI sI sI}",
                    OOF(ch), OOF(fg), OOF(bg), OOF(decoration_fg), OOF(cc), OOF(sprite_x), OOF(sprite_y), OOF(sprite_z), "size", sizeof(Cell))) != 0) return NULL;
#undef OOF
        PyModule_AddIntConstant(m, "BOLD", BOLD_SHIFT);
        PyModule_AddIntConstant(m, "ITALIC", ITALIC_SHIFT);
        PyModule_AddIntConstant(m, "REVERSE", REVERSE_SHIFT);
        PyModule_AddIntConstant(m, "STRIKETHROUGH", STRIKE_SHIFT);
        PyModule_AddIntConstant(m, "DECORATION", DECORATION_SHIFT);
        PyModule_AddStringMacro(m, ERROR_PREFIX);
        PyModule_AddIntMacro(m, CURSOR_BLOCK);
        PyModule_AddIntMacro(m, CURSOR_BEAM);
        PyModule_AddIntMacro(m, CURSOR_UNDERLINE);
        PyModule_AddIntMacro(m, DECAWM);
        PyModule_AddIntMacro(m, DECCOLM);
        PyModule_AddIntMacro(m, DECOM);
        PyModule_AddIntMacro(m, IRM);
        PyModule_AddIntMacro(m, CSI);
        PyModule_AddIntMacro(m, DCS);
        PyModule_AddIntMacro(m, APC);
        PyModule_AddIntMacro(m, OSC);
    }

    return m;
}
