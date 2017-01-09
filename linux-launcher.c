/*
 * linux-launcher.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include <unistd.h>
#include <linux/limits.h>
#include <stdio.h>
#include <libgen.h>

#define MIN(x, y) ((x) < (y)) ? (x) : (y)
#define MAX_ARGC 1024

int main(int argc, char *argv[]) {
		char exe[PATH_MAX+1] = {0};
		char lib[PATH_MAX+1] = {0};
		char *final_argv[MAX_ARGC + 1] = {0};
		if (readlink("/proc/self/exe", exe, PATH_MAX) == -1) { fprintf(stderr, "Failed to read /proc/self/exe"); return 1; }
		char *exe_dir = dirname(exe);
		int num = snprintf(lib, PATH_MAX, "%s%s", exe_dir, "/../lib/kitty");
		if (num < 0 || num >= PATH_MAX) { fprintf(stderr, "Failed to create path to /../lib/kitty"); return 1; }
		final_argv[0] = "python3";
		final_argv[1] = lib;
		for (int i = 1; i < argc && i + 1 <= MAX_ARGC; i++) {
				final_argv[i+1] = argv[i];
		}
		execvp(final_argv[0], final_argv);
		return 0;
}


