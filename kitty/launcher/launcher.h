/*
 * launcher.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdbool.h>
#include <stddef.h>

typedef struct CLIOptions {
    const char *session, *instance_group;
    bool wait_for_single_instance_window_close;
    int open_url_count; char **open_urls;
} CLIOptions;


typedef struct argv_array {
    char **argv, *buf; size_t capacity, count, pos;
    bool needs_free;
} argv_array;


void single_instance_main(int argc, char *argv[], const CLIOptions *opts);
bool get_argv_from(const char *filename, const char* argv0, argv_array *ans);
void free_argv_array(argv_array *a);
