/*
 * symlink-deref.c
 * Copyright (C) 2019 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */


#include <unistd.h>
#include <sys/stat.h>
#include <mach-o/dyld.h>
#include <sys/syslimits.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <libgen.h>
#include <unistd.h>

static inline bool
safe_realpath(const char* src, char *buf, size_t buf_sz) {
    char* ans = realpath(src, NULL);
    if (ans == NULL) return false;
    snprintf(buf, buf_sz, "%s", ans);
    free(ans);
    return true;
}

static inline bool
read_exe_path(char *exe, size_t buf_sz) {
    (void)buf_sz;
    uint32_t size = PATH_MAX;
    char apple[PATH_MAX+1] = {0};
    if (_NSGetExecutablePath(apple, &size) != 0) { fprintf(stderr, "Failed to get path to executable\n"); return false; }
    if (!safe_realpath(apple, exe, buf_sz)) { fprintf(stderr, "realpath() failed on the executable's path\n"); return false; }
    return true;
}


int
main(int argc, char *argv[]) {
    char exe[PATH_MAX+1] = {0};
    char real_exe[PATH_MAX+1] = {0};
    if (!read_exe_path(exe, sizeof(exe))) return 1;
    snprintf(real_exe, sizeof(real_exe), "%s/kitty", dirname(exe));
    return execv(real_exe, argv);
}
