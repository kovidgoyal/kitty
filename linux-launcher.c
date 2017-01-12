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

#define MIN(x, y) ((x) < (y)) ? (x) : (y)
#define MAX_ARGC 1024

int main(int argc, char *argv[]) {
		char exe[PATH_MAX+1] = {0};
		char lib[PATH_MAX+1] = {0};
		char *final_argv[MAX_ARGC + 1] = {0};
#ifdef __APPLE__
        uint32_t size = PATH_MAX;
        char apple[PATH_MAX+1] = {0};
        if (_NSGetExecutablePath(apple, &size) != 0) { fprintf(stderr, "Failed to get path to executable\n"); return 1; }
		if (realpath(apple, exe) == NULL) { fprintf(stderr, "realpath() failed on the executable's path\n"); return 1; }
#else
		if (realpath("/proc/self/exe", exe) == NULL) { fprintf(stderr, "Failed to read /proc/self/exe\n"); return 1; }
#endif
		char *exe_dir = dirname(exe);
		int num = snprintf(lib, PATH_MAX, "%s%s", exe_dir, "/../lib/kitty");
		if (num < 0 || num >= PATH_MAX) { fprintf(stderr, "Failed to create path to /../lib/kitty\n"); return 1; }
		final_argv[0] = "python3";
		final_argv[1] = lib;
		for (int i = 1; i < argc && i + 1 <= MAX_ARGC; i++) {
				final_argv[i+1] = argv[i];
		}
		execvp(final_argv[0], final_argv);
		fprintf(stderr, "Failed to run %s: %s\n", final_argv[0], strerror(errno));
		return 0;
}


