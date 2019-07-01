/*
 * output.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "choose-data-types.h"
#include <string.h>
#include <ctype.h>
#include <stdlib.h>
#include <stdio.h>
#ifdef ISWINDOWS
#include <io.h>
#define STDOUT_FILENO 1
static inline ssize_t ms_write(int fd, const void* buf, size_t count) { return _write(fd, buf, (unsigned int)count); }
#define write ms_write
#else
#include <unistd.h>
#endif
#include <errno.h>


#define FIELD(x, which) (((Candidate*)(x))->which)

static inline bool
ensure_space(GlobalData *global, size_t sz) {
    if (global->output_sz < sz + global->output_pos || !global->output) {
        size_t before = global->output_sz;
        global->output_sz += MAX(sz, (64u * 1024u));
        global->output = realloc(global->output, sizeof(text_t) * global->output_sz);
        if (!global->output) {
            global->output_sz = before;
            return false;
        }
    }
    return true;
}

static inline void
output_text(GlobalData *global, const text_t *data, size_t sz) {
    if (ensure_space(global, sz)) {
        memcpy(global->output + global->output_pos, data, sizeof(text_t) * sz);
        global->output_pos += sz;
    }
}

static int
cmpscore(const void *a, const void *b) {
    double sa = FIELD(a, score), sb = FIELD(b, score);
    // Sort descending
    return (sa > sb) ? -1 : ((sa == sb) ? ((int)FIELD(a, idx) - (int)FIELD(b, idx)) : 1);
}

static void
output_with_marks(GlobalData *global, Options *opts, text_t *src, size_t src_sz, len_t *positions, len_t poslen) {
    size_t pos, i = 0;
    for (pos = 0; pos < poslen; pos++, i++) {
        output_text(global, src + i, MIN(src_sz, positions[pos]) - i);
        i = positions[pos];
        if (i < src_sz) {
            if (opts->mark_before_sz > 0) output_text(global, opts->mark_before, opts->mark_before_sz);
            output_text(global, src + i, 1);
            if (opts->mark_after_sz > 0) output_text(global, opts->mark_after, opts->mark_after_sz);
        }
    }
    i = positions[poslen - 1];
    if (i + 1 < src_sz) output_text(global, src + i + 1, src_sz - i - 1);
}

static void
output_positions(GlobalData *global, len_t *positions, len_t num) {
    wchar_t buf[128];
    for (len_t i = 0; i < num; i++) {
        int num = swprintf(buf, sizeof(buf)/sizeof(buf[0]), L"%u", positions[i]);
        if (num > 0 && ensure_space(global, num + 1)) {
            for (int i = 0; i < num; i++) global->output[global->output_pos++] = buf[i];
            global->output[global->output_pos++] = (i == num - 1) ? ',' : ':';
        }
    }
}


static void
output_result(GlobalData *global, Candidate *c, Options *opts, len_t needle_len) {
    if (opts->output_positions) output_positions(global, c->positions, needle_len);
    if (opts->mark_before_sz > 0 || opts->mark_after_sz > 0) {
        output_with_marks(global, opts, c->src, c->src_sz, c->positions, needle_len);
    } else {
        output_text(global, c->src, c->src_sz);
    }
    output_text(global, opts->delimiter, opts->delimiter_sz);
}


void
output_results(GlobalData *global, Candidate *haystack, size_t count, Options *opts, len_t needle_len) {
    Candidate *c;
    qsort(haystack, count, sizeof(*haystack), cmpscore);
    size_t left = opts->limit > 0 ? opts->limit : count;
    for (size_t i = 0; i < left; i++) {
        c = haystack + i;
        if (c->score > 0) output_result(global, c, opts, needle_len);
    }
}
