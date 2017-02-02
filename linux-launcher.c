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
#ifdef __APPLE__
#include <mach-o/dyld.h>
#include <sys/syslimits.h>
#else
#include <limits.h>
#endif
#include <Python.h>

#define MIN(x, y) ((x) < (y)) ? (x) : (y)
#define MAX_ARGC 1024

int main(int argc, char *argv[]) {
    int num, num_args, i, ret=0;
    char exe[PATH_MAX+1] = {0};
    char lib[PATH_MAX+1] = {0};
    char *final_argv[MAX_ARGC + 1] = {0};
    wchar_t *argvw[MAX_ARGC + 1] = {0};

#ifdef __APPLE__
    uint32_t size = PATH_MAX;
    char apple[PATH_MAX+1] = {0};
    if (_NSGetExecutablePath(apple, &size) != 0) { fprintf(stderr, "Failed to get path to executable\n"); return 1; }
    if (realpath(apple, exe) == NULL) { fprintf(stderr, "realpath() failed on the executable's path\n"); return 1; }
#else
    if (realpath("/proc/self/exe", exe) == NULL) { fprintf(stderr, "Failed to read /proc/self/exe\n"); return 1; }
#endif

    char *exe_dir = dirname(exe);

#ifdef FOR_BUNDLE
    num = snprintf(lib, PATH_MAX, "%s%s", exe_dir, "/../Frameworks/kitty");
#else
    num = snprintf(lib, PATH_MAX, "%s%s", exe_dir, "/../lib/kitty");
#endif

    if (num < 0 || num >= PATH_MAX) { fprintf(stderr, "Failed to create path to /../lib/kitty\n"); return 1; }
    final_argv[0] = exe;
    final_argv[1] = lib;
    for (i = 1, num_args=2; i < argc && i + 1 <= MAX_ARGC; i++) {
        final_argv[i+1] = argv[i];
        num_args++;
    }
    for (i = 0; i < num_args; i++) {
        argvw[i] = Py_DecodeLocale(final_argv[i], NULL);
        if (argvw[i] == NULL) {
            fprintf(stderr, "Fatal error: cannot decode argv[%d]\n", i);
            goto end;
        }
    }
    ret = Py_Main(num_args, argvw);
end:
    for (i = 0; i < num_args; i++) { if(argvw[i]) PyMem_RawFree(argvw[i]); }
    return ret;
}
