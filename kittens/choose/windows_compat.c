/*
 * windows_compat.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "choose-data-types.h"

#include <windows.h>
#include <process.h>
#include <stdio.h>
#include <errno.h>

int
cpu_count() {
    SYSTEM_INFO sysinfo;
    GetSystemInfo(&sysinfo);
    return sysinfo.dwNumberOfProcessors;
}

void*
alloc_threads(size_t num_threads) {
    return calloc(num_threads, sizeof(uintptr_t));
}

bool
start_thread(void* vt, size_t i, unsigned int (STDCALL *start_routine) (void *), void *arg) {
    uintptr_t *threads = (uintptr_t*)vt;
    errno = 0;
    threads[i] = _beginthreadex(NULL, 0, start_routine, arg, 0, NULL);
    if (threads[i] == 0) {
        perror("Failed to create thread, with error");
        return false;
    }
    return true;
}

void
wait_for_thread(void *vt, size_t i) {
    uintptr_t *threads = vt;
    WaitForSingleObject((HANDLE)threads[i], INFINITE);
    CloseHandle((HANDLE)threads[i]);
    threads[i] = 0;
}

void
free_threads(void *threads) {
    free(threads);
}

ssize_t
getdelim(char **lineptr, size_t *n, int delim, FILE *stream) {
    char c, *cur_pos, *new_lineptr;
    size_t new_lineptr_len;

    if (lineptr == NULL || n == NULL || stream == NULL) {
        errno = EINVAL;
        return -1;
    }

    if (*lineptr == NULL) {
        *n = 8192; /* init len */
        if ((*lineptr = (char *)malloc(*n)) == NULL) {
            errno = ENOMEM;
            return -1;
        }
    }

    cur_pos = *lineptr;
    for (;;) {
        c = getc(stream);

        if (ferror(stream) || (c == EOF && cur_pos == *lineptr))
            return -1;

        if (c == EOF)
            break;

        if ((*lineptr + *n - cur_pos) < 2) {
            if (SSIZE_MAX / 2 < *n) {
#ifdef EOVERFLOW
                errno = EOVERFLOW;
#else
                errno = ERANGE; /* no EOVERFLOW defined */
#endif
                return -1;
            }
            new_lineptr_len = *n * 2;

            if ((new_lineptr = (char *)realloc(*lineptr, new_lineptr_len)) == NULL) {
                errno = ENOMEM;
                return -1;
            }
            *lineptr = new_lineptr;
            *n = new_lineptr_len;
        }

        *cur_pos++ = c;

        if (c == delim)
            break;
    }

    *cur_pos = '\0';
    return (ssize_t)(cur_pos - *lineptr);
}
