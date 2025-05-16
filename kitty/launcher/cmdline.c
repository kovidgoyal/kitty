/*
 * cmdline.c
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define _POSIX_C_SOURCE 200809L
#include "shlex.h"
#include "utils.h"
#include "launcher.h"
#ifdef __APPLE__
#include <os/log.h>
#endif

void
free_argv_array(argv_array *a) {
    if (a && a->needs_free) {
        free(a->buf); free(a->argv);
        *a = (argv_array){0};
    }
}

static bool
add_to_argv(argv_array *a, const char* arg, size_t sz) {
    if (a->count + 2 > a->capacity) {
        size_t cap = a->capacity * 2;
        if (!cap) cap = 256;
        void *m = realloc(a->argv, cap * sizeof(a->argv[0]));
        if (!m) return false;
        a->argv = m;
        a->argv[a->count] = 0;
        a->capacity = cap;
        a->needs_free = true;
    }
    memcpy(a->buf + a->pos, arg, sz);
    a->argv[a->count++] = a->buf + a->pos;
    a->argv[a->count] = 0;
    a->pos += sz;
    a->buf[a->pos++] = 0;
    return true;
}

bool
get_argv_from(const char *filename, const char *argv0, argv_array *final_ans) {
    (void)get_config_dir;
    if (!filename || !filename[0]) return true;
    size_t src_sz;
    char* src = read_full_file(filename, &src_sz);
    if (!src) {
        if (errno == ENOENT || errno == ENOTDIR) return true;
#ifdef __APPLE__
        int saved = errno;
        os_log_error(OS_LOG_DEFAULT, "Failed to read from %{public}s with error: %{darwin.errno}d", filename, errno);
        errno = saved;
#endif
        fprintf(stderr, "Failed to read from %s ", filename); perror("with error");
        return true;
    }
    ShlexState s = {0};
    argv_array ans = {0};
    bool ok = false;
    ans.buf = malloc(src_sz + strlen(argv0) + 64);
    if (!ans.buf) goto oom;
    ans.needs_free = true;
    if (!add_to_argv(&ans, argv0, strlen(argv0))) goto oom;
    if (!alloc_shlex_state(&s, src, src_sz, false)) goto oom;
    bool keep_going = true;
    while (keep_going) {
        ssize_t q = next_word(&s);
        switch(q) {
            case -1: fprintf(stderr, "Failed to parse %s with error: %s\n", filename, s.err); goto end;
            case -2: keep_going = false; break;
            default:
                if (ans.count == 1 && strcmp(s.buf, "kitty") == 0) continue;
                if (!add_to_argv(&ans, s.buf, q)) goto oom;
                break;
        }
    }
    ok = true;
oom:
    if (!ok) {
        errno = ENOMEM;
        fprintf(stderr, "Failed to read from %s ", filename); perror("with error");
    }
end:
    free(src); dealloc_shlex_state(&s);
    if (ok) *final_ans = ans;
    else free_argv_array(final_ans);
    return ok;
}

