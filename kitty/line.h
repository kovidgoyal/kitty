/*
 * line.h
 * Copyright (C) 2024 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "text-cache.h"

typedef struct {
    PyObject_HEAD

    GPUCell *gpu_cells;
    CPUCell *cpu_cells;
    index_type xnum, ynum;
    bool needs_free;
    LineAttrs attrs;
    TextCache *text_cache;
} Line;

Line* alloc_line(TextCache *text_cache);
