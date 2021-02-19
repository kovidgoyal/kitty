/*
 * launcher.c
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
#include <sys/stat.h>
#else
#include <limits.h>
#endif
#include <Python.h>
#include <wchar.h>
#include <stdbool.h>

#ifndef KITTY_LIB_PATH
#define KITTY_LIB_PATH "../.."
#endif
#ifndef KITTY_LIB_DIR_NAME
#define KITTY_LIB_DIR_NAME "lib"
#endif

static inline void cleanup_free(void *p) { free(*(void**) p); }
#define FREE_AFTER_FUNCTION __attribute__((cleanup(cleanup_free)))


#ifndef __FreeBSD__
static inline bool
safe_realpath(const char* src, char *buf, size_t buf_sz) {
    FREE_AFTER_FUNCTION char* ans = realpath(src, NULL);
    if (ans == NULL) return false;
    snprintf(buf, buf_sz, "%s", ans);
    return true;
}
#endif

static inline bool
set_xoptions(const char *exe_dir_c, const char *lc_ctype, bool from_source) {
    wchar_t *exe_dir = Py_DecodeLocale(exe_dir_c, NULL);
    if (exe_dir == NULL) { fprintf(stderr, "Fatal error: cannot decode exe_dir: %s\n", exe_dir_c); return false; }
    wchar_t buf[PATH_MAX+1] = {0};
    swprintf(buf, PATH_MAX, L"bundle_exe_dir=%ls", exe_dir);
    PySys_AddXOption(buf);
    PyMem_RawFree(exe_dir);
    if (from_source) PySys_AddXOption(L"kitty_from_source=1");
    if (lc_ctype) {
        swprintf(buf, PATH_MAX, L"lc_ctype_before_python=%s", lc_ctype);
        PySys_AddXOption(buf);
    }
    return true;
}

typedef struct {
    const char *exe, *exe_dir, *lc_ctype, *lib_dir;
    char **argv;
    int argc;
} RunData;

#ifdef FOR_BUNDLE
#include <bypy-freeze.h>

static bool
canonicalize_path(const char *srcpath, char *dstpath, size_t sz) {
    // remove . and .. path segments
    bool ok = false;
    size_t plen = strlen(srcpath) + 1, chk;
    FREE_AFTER_FUNCTION char *wtmp = malloc(plen);
    FREE_AFTER_FUNCTION char **tokv = malloc(sizeof(char*) * plen);
    if (!wtmp || !tokv) goto end;
    char *s, *tok, *sav;
    bool relpath = *srcpath != '/';

    // use a buffer as strtok modifies its input
    memcpy(wtmp, srcpath, plen);

    tok = strtok_r(wtmp, "/", &sav);
    int ti = 0;
    while (tok != NULL) {
        if (strcmp(tok, "..") == 0) {
            if (ti > 0) ti--;
        } else if (strcmp(tok, ".") != 0) {
            tokv[ti++] = tok;
        }
        tok = strtok_r(NULL, "/", &sav);
    }

    chk = 0;
    s = dstpath;
    for (int i = 0; i < ti; i++) {
        size_t token_sz = strlen(tokv[i]);

        if (i > 0 || !relpath) {
            if (++chk >= sz) goto end;
            *s++ = '/';
        }

        chk += token_sz;
        if (chk >= sz) goto end;

        memcpy(s, tokv[i], token_sz);
        s += token_sz;
    }

    if (s == dstpath) {
        if (++chk >= sz) goto end;
        *s++ = relpath ? '.' : '/';
    }
    *s = '\0';
    ok = true;

end:
    return ok;
}

static bool
canonicalize_path_wide(const char *srcpath, wchar_t *dest, size_t sz) {
    char buf[sz + 1];
    bool ret = canonicalize_path(srcpath, buf, sz);
    buf[sz] = 0;
    mbstowcs(dest, buf, sz - 1);
    dest[sz-1] = 0;
    return ret;
}

static int
run_embedded(const RunData run_data) {
    bypy_pre_initialize_interpreter(false);
    char extensions_dir_full[PATH_MAX+1] = {0}, python_home_full[PATH_MAX+1] = {0};
#ifdef __APPLE__
    const char *python_relpath = "../Resources/Python/lib";
#else
    const char *python_relpath = "../" KITTY_LIB_DIR_NAME;
#endif
    int num = snprintf(extensions_dir_full, PATH_MAX, "%s/%s/kitty-extensions", run_data.exe_dir, python_relpath);
    if (num < 0 || num >= PATH_MAX) { fprintf(stderr, "Failed to create path to extensions_dir: %s/%s\n", run_data.exe_dir, python_relpath); return 1; }
    wchar_t extensions_dir[num+2];
    if (!canonicalize_path_wide(extensions_dir_full, extensions_dir, num+1)) {
        fprintf(stderr, "Failed to canonicalize the path: %s\n", extensions_dir_full); return 1; }

    num = snprintf(python_home_full, PATH_MAX, "%s/%s/python%s", run_data.exe_dir, python_relpath, PYVER);
    if (num < 0 || num >= PATH_MAX) { fprintf(stderr, "Failed to create path to python home: %s/%s\n", run_data.exe_dir, python_relpath); return 1; }
    wchar_t python_home[num+2];
    if (!canonicalize_path_wide(python_home_full, python_home, num+1)) {
        fprintf(stderr, "Failed to canonicalize the path: %s\n", python_home_full); return 1; }

    bypy_initialize_interpreter(L"kitty", python_home, L"kitty_main", extensions_dir, run_data.argc, run_data.argv);
    if (!set_xoptions(run_data.exe_dir, run_data.lc_ctype, false)) return 1;
    set_sys_bool("frozen", true);
    set_sys_string("kitty_extensions_dir", extensions_dir);
    return bypy_run_interpreter();
}

#else

static int
free_argv(wchar_t **argv) {
    wchar_t **p = argv;
    while (*p) { PyMem_RawFree(*p); p++; }
    free(argv);
    return 1;
}

static int
run_embedded(const RunData run_data) {
    bool from_source = false;
#ifdef FROM_SOURCE
    from_source = true;
#endif
    if (!set_xoptions(run_data.exe_dir, run_data.lc_ctype, from_source)) return 1;
    int argc = run_data.argc + 1;
    wchar_t **argv = calloc(argc, sizeof(wchar_t*));
    if (!argv) { fprintf(stderr, "Out of memory creating argv\n"); return 1; }
    memset(argv, 0, sizeof(wchar_t*) * argc);
    argv[0] = Py_DecodeLocale(run_data.exe, NULL);
    if (!argv[0]) { fprintf(stderr, "Failed to decode path to exe\n"); return free_argv(argv); }
    argv[1] = Py_DecodeLocale(run_data.lib_dir, NULL);
    if (!argv[1]) { fprintf(stderr, "Failed to decode path to lib_dir\n"); return free_argv(argv); }
    for (int i=1; i < run_data.argc; i++) {
        argv[i+1] = Py_DecodeLocale(run_data.argv[i], NULL);
        if (!argv[i+1]) { fprintf(stderr, "Failed to decode the command line argument: %s\n", run_data.argv[i]); return free_argv(argv); }
    }
    int ret = Py_Main(argc, argv);
    // we cannot free argv properly as Py_Main modifies it
    free(argv);
    return ret;
}

#endif

// read_exe_path() {{{
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
    if (!safe_realpath("/proc/curproc/exe", exe, buf_sz)) { fprintf(stderr, "Failed to read /proc/curproc/exe\n"); return false; }
    return true;
}

#elif defined(__OpenBSD__)
static inline bool
read_exe_path(char *exe, size_t buf_sz) {
    const char *path = getenv("PATH");
    if (!path) { fprintf(stderr, "No PATH environment variable set, aborting\n"); return false; }
    char buf[PATH_MAX + 1] = {0};
    strncpy(buf, path, PATH_MAX);
    char *token = strtok(buf, ":");
    while (token != NULL) {
        char q[PATH_MAX + 1] = {0};
        snprintf(q, PATH_MAX, "%s/kitty", token);
        if (safe_realpath(q, exe, buf_sz)) return true;
        token = strtok(NULL, ":");
    }
    fprintf(stderr, "kitty not found in PATH aborting\n");
    return false;
}

#else

static inline bool
read_exe_path(char *exe, size_t buf_sz) {
    if (!safe_realpath("/proc/self/exe", exe, buf_sz)) { fprintf(stderr, "Failed to read /proc/self/exe\n"); return false; }
    return true;
}
#endif // }}}

int main(int argc, char *argv[]) {
    char exe[PATH_MAX+1] = {0};
    char exe_dir_buf[PATH_MAX+1] = {0};
    FREE_AFTER_FUNCTION const char *lc_ctype = NULL;
#ifdef __APPLE__
    lc_ctype = getenv("LC_CTYPE");
#endif
    if (!read_exe_path(exe, sizeof(exe))) return 1;
    strncpy(exe_dir_buf, exe, sizeof(exe_dir_buf));
    char *exe_dir = dirname(exe_dir_buf);
    int num, ret=0;
    char lib[PATH_MAX+1] = {0};
    num = snprintf(lib, PATH_MAX, "%s/%s", exe_dir, KITTY_LIB_PATH);

    if (num < 0 || num >= PATH_MAX) { fprintf(stderr, "Failed to create path to kitty lib\n"); return 1; }
#if PY_VERSION_HEX >= 0x03070000
    // Always use UTF-8 mode, see https://github.com/kovidgoyal/kitty/issues/924
    Py_UTF8Mode = 1;
#endif
    if (lc_ctype) lc_ctype = strdup(lc_ctype);
    RunData run_data = {.exe = exe, .exe_dir = exe_dir, .lib_dir = lib, .argc = argc, .argv = argv, .lc_ctype = lc_ctype};
    ret = run_embedded(run_data);
    return ret;
}
