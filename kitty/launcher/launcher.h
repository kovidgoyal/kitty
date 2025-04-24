/*
 * launcher.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdbool.h>

typedef struct CLIOptions {
    const char *session, *instance_group, *detached_log;
    bool single_instance, version_requested, wait_for_single_instance_window_close, detach;
    int open_url_count; char **open_urls;
} CLIOptions;


void
single_instance_main(int argc, char *argv[], const CLIOptions *opts);
