/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef struct FastFileCopyBuffer {
    uint8_t *buf;
    size_t sz;
} FastFileCopyBuffer;

static inline void
free_fast_file_copy_buffer(FastFileCopyBuffer *fcb) { free(fcb->buf); fcb->buf = NULL; }

#define FREE_FCB_AFTER_FUNCTION __attribute__ ((__cleanup__(free_fast_file_copy_buffer)))
#define AutoFreeFastFileCopyBuffer FREE_FCB_AFTER_FUNCTION FastFileCopyBuffer

bool copy_between_files(int infd, int outfd, off_t in_pos, size_t len, FastFileCopyBuffer *fcb);
