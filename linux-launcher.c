/*
 * linux-launcher.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include <unistd.h>
#include <stdio.h>
#include <stdlib.h>
#include <libgen.h>
#include <string.h>
#include <errno.h>
#include <stdbool.h>
#ifdef __APPLE__
#include <mach-o/dyld.h>
#include <sys/syslimits.h>
#else
#include <limits.h>
#endif
#include <Python.h>
#include <wchar.h>

#define MIN(x, y) ((x) < (y)) ? (x) : (y)
#define MAX_ARGC 1024

static inline bool
safe_realpath(const char* src, char *buf, size_t buf_sz) {
    char* ans = realpath(src, NULL);
    if (ans == NULL) return false;
    snprintf(buf, buf_sz, "%s", ans);
    free(ans);
    return true;
}

static inline void
set_bundle_exe_dir(const wchar_t *exe_dir) {
    wchar_t buf[PATH_MAX+1] = {0};
    swprintf(buf, PATH_MAX, L"bundle_exe_dir=%ls", exe_dir);
    PySys_AddXOption(buf);
}

#ifdef FOR_BUNDLE
static int run_embedded(const char* exe_dir_, int argc, wchar_t **argv) {
    int num;
    Py_NoSiteFlag = 1;
    Py_FrozenFlag = 1;
    Py_IgnoreEnvironmentFlag = 1;
    Py_DontWriteBytecodeFlag = 1;
    Py_NoUserSiteDirectory = 1;
    Py_IsolatedFlag = 1;
    Py_SetProgramName(L"kitty");

    int ret = 1;
    wchar_t *exe_dir = Py_DecodeLocale(exe_dir_, NULL);
    if (exe_dir == NULL) { fprintf(stderr, "Fatal error: cannot decode exe_dir\n"); return 1; }
    set_bundle_exe_dir(exe_dir);
    wchar_t stdlib[PATH_MAX+1] = {0};
#ifdef __APPLE__
    const char *python_relpath = "../Resources/Python/lib";
#else
    const char *python_relpath = "../lib";
#endif
    num = swprintf(stdlib, PATH_MAX, L"%ls/%s/python%s:%ls/%s/python%s/lib-dynload:%ls/%s/python%s/site-packages",
            exe_dir, python_relpath, PYVER,
            exe_dir, python_relpath, PYVER,
            exe_dir, python_relpath, PYVER
    );
    if (num < 0 || num >= PATH_MAX) { fprintf(stderr, "Failed to create path to python stdlib\n"); return 1; }
    Py_SetPath(stdlib);
#ifdef __APPLE__
    num = swprintf(stdlib, PATH_MAX, L"%ls/../Frameworks/kitty", exe_dir);
#else
    num = swprintf(stdlib, PATH_MAX, L"%ls/../lib/kitty", exe_dir);
#endif
    PyMem_RawFree(exe_dir);
    if (num < 0 || num >= PATH_MAX) { fprintf(stderr, "Failed to create path to kitty lib\n"); return 1; }
    Py_Initialize();
    PySys_SetArgvEx(argc - 1, argv + 1, 0);
    PySys_SetObject("frozen", Py_True);
    PyObject *kitty = PyUnicode_FromWideChar(stdlib, -1);
    if (kitty == NULL) { fprintf(stderr, "Failed to allocate python kitty lib object\n"); goto end; }
    PyObject *runpy = PyImport_ImportModule("runpy");
    if (runpy == NULL) { PyErr_Print(); fprintf(stderr, "Unable to import runpy\n"); Py_CLEAR(kitty); goto end; }
    PyObject *run_name = PyUnicode_FromString("__main__");
    if (run_name == NULL) { fprintf(stderr, "Failed to allocate run_name\n"); goto end; }
    PyObject *res = PyObject_CallMethod(runpy, "run_path", "OOO", kitty, Py_None, run_name);
    Py_CLEAR(runpy); Py_CLEAR(kitty); Py_CLEAR(run_name);
    if (res == NULL) PyErr_Print();
    else { ret = 0; Py_CLEAR(res); }
end:
    if (Py_FinalizeEx() < 0) ret = 120;
    return ret;
}

#else
static int run_embedded(const char* exe_dir_, int argc, wchar_t **argv) {
    (void)exe_dir_;
#ifdef __APPLE__
    wchar_t *exe_dir = Py_DecodeLocale(exe_dir_, NULL);
    if (exe_dir == NULL) { fprintf(stderr, "Fatal error: cannot decode exe_dir\n"); return 1; }
    set_bundle_exe_dir(exe_dir);
#endif
    return Py_Main(argc, argv);
}

#endif

#ifdef __APPLE__
static inline bool
read_exe_path(char *exe, size_t buf_sz) {
    (void)buf_sz;
    uint32_t size = PATH_MAX;
    char apple[PATH_MAX+1] = {0};
    if (_NSGetExecutablePath(apple, &size) != 0) { fprintf(stderr, "Failed to get path to executable\n"); return false; }
    if (!safe_realpath(apple, exe, buf_sz)) { fprintf(stderr, "realpath() failed on the executable's path\n"); return false; }
    return true;
}
#elif defined(__FreeBSD__)
#include <sys/param.h>
#include <sys/sysctl.h>

static inline bool
read_exe_path(char *exe, size_t buf_sz) {
    int name[] = { CTL_KERN, KERN_PROC, KERN_PROC_PATHNAME, -1 };
    size_t length = buf_sz;
    int error = sysctl(name, 4, exe, &length, NULL, 0);
    if (error < 0 || length <= 1) {
        fprintf(stderr, "failed to get path to executable, sysctl() failed\n");
        return false;
    }
    return true;
}
#elif defined(__NetBSD__)

static inline bool
read_exe_path(char *exe, size_t buf_sz) {
    if (!safe_realpath("/proc/curproc/exe", exe, buf_sz)) { fprintf(stderr, "Failed to read /proc/self/exe\n"); return false; }
    return true;
}

#else

static inline bool
read_exe_path(char *exe, size_t buf_sz) {
    if (!safe_realpath("/proc/self/exe", exe, buf_sz)) { fprintf(stderr, "Failed to read /proc/self/exe\n"); return false; }
    return true;
}
#endif

int main(int argc, char *argv[]) {
    char exe[PATH_MAX+1] = {0};
    if (!read_exe_path(exe, sizeof(exe))) return 1;

    char *exe_dir = dirname(exe);
    int num, num_args, i, ret=0;
    char lib[PATH_MAX+1] = {0};
    char *final_argv[MAX_ARGC + 1] = {0};
    wchar_t *argvw[MAX_ARGC + 1] = {0};
#ifdef WITH_PROFILER
    num = snprintf(lib, PATH_MAX, "%s%s", exe_dir, "/");
#else
#ifdef FOR_LAUNCHER
    num = snprintf(lib, PATH_MAX, "%s%s", exe_dir, "/../Frameworks/kitty");
#else
    num = snprintf(lib, PATH_MAX, "%s%s%s%s", exe_dir, "/../", LIB_DIR_NAME, "/kitty");
#endif
#endif

    if (num < 0 || num >= PATH_MAX) { fprintf(stderr, "Failed to create path to kitty lib\n"); return 1; }
    final_argv[0] = exe;
    final_argv[1] = lib;
    for (i = 1, num_args=2; i < argc && i + 1 <= MAX_ARGC; i++) {
        final_argv[i+1] = argv[i];
        num_args++;
    }
#if PY_VERSION_HEX >= 0x03070000
    // Always use UTF-8 mode, see https://github.com/kovidgoyal/kitty/issues/924
    Py_UTF8Mode = 1;
#endif
    for (i = 0; i < num_args; i++) {
        argvw[i] = Py_DecodeLocale(final_argv[i], NULL);
        if (argvw[i] == NULL) {
            fprintf(stderr, "Fatal error: cannot decode argv[%d]\n", i);
            ret = 1; goto end;
        }
    }
    ret = run_embedded(exe_dir, num_args, argvw);
end:
    for (i = 0; i < num_args; i++) { if(argvw[i]) PyMem_RawFree(argvw[i]); }
    return ret;
}
