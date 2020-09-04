/*
 * main.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "choose-data-types.h"
#include "charsets.h"

#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <ctype.h>
#include <fcntl.h>
#ifndef ISWINDOWS
#include <unistd.h>
#endif

typedef struct {
    size_t start, count;
    void *workspace;
    len_t max_haystack_len;
    bool started;
    GlobalData *global;
} JobData;


static unsigned int STDCALL
run_scoring(JobData *job_data) {
    GlobalData *global = job_data->global;
    for (size_t i = job_data->start; i < job_data->start + job_data->count; i++) {
        global->haystack[i].score = score_item(job_data->workspace, global->haystack[i].src, global->haystack[i].haystack_len, global->haystack[i].positions);
    }
    return 0;
}

static void*
run_scoring_pthreads(void *job_data) {
    run_scoring((JobData*)job_data);
    return NULL;
}
#ifdef ISWINDOWS
#define START_FUNC run_scoring
#else
#define START_FUNC run_scoring_pthreads
#endif

static JobData*
create_job(size_t i, size_t blocksz, GlobalData *global) {
    JobData *ans = (JobData*)calloc(1, sizeof(JobData));
    if (ans == NULL) return NULL;
    ans->start = i * blocksz;
    if (ans->start >= global->haystack_count) ans->count = 0;
    else ans->count = global->haystack_count - ans->start;
    ans->max_haystack_len = 0;
    for (size_t i = ans->start; i < ans->start + ans->count; i++) ans->max_haystack_len = MAX(ans->max_haystack_len, global->haystack[i].haystack_len);
    if (ans->count > 0) {
        ans->workspace = alloc_workspace(ans->max_haystack_len, global);
        if (!ans->workspace) { free(ans); return NULL; }
    }
    ans->global = global;
    return ans;
}

static JobData*
free_job(JobData *job) {
    if (job) {
        if (job->workspace) free_workspace(job->workspace);
        free(job);
    }
    return NULL;
}


static int
run_threaded(int num_threads_asked, GlobalData *global) {
    int ret = 0;
    size_t i, blocksz;
    size_t num_threads = MAX(1, num_threads_asked > 0 ? num_threads_asked : cpu_count());
    if (global->haystack_size < 10000) num_threads = 1;
    /* printf("num_threads: %lu asked: %d sysconf: %ld\n", num_threads, num_threads_asked, sysconf(_SC_NPROCESSORS_ONLN)); */

    void *threads = alloc_threads(num_threads);
    JobData **job_data = calloc(num_threads, sizeof(JobData*));
    if (threads == NULL || job_data == NULL) { ret = 1; goto end; }

    blocksz = global->haystack_count / num_threads + global->haystack_count % num_threads;

    for (i = 0; i < num_threads; i++) {
        job_data[i] = create_job(i, blocksz, global);
        if (job_data[i] == NULL) { ret = 1; goto end; }
    }

    if (num_threads == 1) {
        run_scoring(job_data[0]);
    } else {
        for (i = 0; i < num_threads; i++) {
            job_data[i]->started = false;
            if (job_data[i]->count > 0) {
                if (!start_thread(threads, i, START_FUNC, job_data[i])) ret = 1;
                else job_data[i]->started = true;
            }
        }
    }

end:
    if (num_threads > 1 && job_data) {
        for (i = 0; i < num_threads; i++) {
            if (job_data[i] && job_data[i]->started) wait_for_thread(threads, i);
        }
    }
    if (job_data) { for (i = 0; i < num_threads; i++) job_data[i] = free_job(job_data[i]); }
    free(job_data);
    free_threads(threads);
    return ret;
}


static int
run_search(Options *opts, GlobalData *global, const char * const *lines, const size_t* sizes, size_t num_lines) {
    const char *linebuf = NULL;
    size_t idx = 0;
    ssize_t sz = 0;
    int ret = 0;
    Candidates candidates = {0};
    Chars chars = {0};

    ALLOC_VEC(text_t, chars, 8192 * 20);
    if (chars.data == NULL) return 1;
    ALLOC_VEC(Candidate, candidates, 8192);
    if (candidates.data == NULL) { FREE_VEC(chars); return 1; }

    for (size_t i = 0; i < num_lines; i++) {
        sz = sizes[i];
        linebuf = lines[i];
        if (sz > 0) {
            ENSURE_SPACE(text_t, chars, sz);
            ENSURE_SPACE(Candidate, candidates, 1);
            sz = decode_utf8_string(linebuf, sz, &(NEXT(chars)));
            NEXT(candidates).src_sz = sz;
            NEXT(candidates).haystack_len = (len_t)(MIN(LEN_MAX, sz));
            global->haystack_size += NEXT(candidates).haystack_len;
            NEXT(candidates).idx = idx++;
            INC(candidates, 1); INC(chars, sz);
        }
    }

    // Prepare the haystack allocating space for positions arrays and settings
    // up the src pointers to point to the correct locations
    Candidate *haystack = &ITEM(candidates, 0);
    len_t *positions = (len_t*)calloc(SIZE(candidates), sizeof(len_t) * global->needle_len);
    if (positions) {
        text_t *cdata = &ITEM(chars, 0);
        for (size_t i = 0, off = 0; i < SIZE(candidates); i++) {
            haystack[i].positions = positions + (i * global->needle_len);
            haystack[i].src = cdata + off;
            off += haystack[i].src_sz;
        }
        global->haystack = haystack;
        global->haystack_count = SIZE(candidates);
        ret = run_threaded(opts->num_threads, global);
        if (ret == 0) output_results(global, haystack, SIZE(candidates), opts, global->needle_len);
        else { REPORT_OOM; }
    } else { ret = 1; REPORT_OOM; }

    FREE_VEC(chars); free(positions); FREE_VEC(candidates);
    return ret;
}

static size_t
copy_unicode_object(PyObject *src, text_t *dest, size_t dest_sz) {
    PyUnicode_READY(src);
    int kind = PyUnicode_KIND(src);
    void *data = PyUnicode_DATA(src);
    size_t len = PyUnicode_GetLength(src);
    for (size_t i = 0; i < len && i < dest_sz; i++) {
        dest[i] = PyUnicode_READ(kind, data, i);
    }
    return len;
}

static PyObject*
match(PyObject *self, PyObject *args) {
    (void)(self);
    int output_positions;
    unsigned long limit;
    PyObject *lines, *levels, *needle, *mark_before, *mark_after, *delimiter;
    Options opts = {0};
    GlobalData global = {0};
    if (!PyArg_ParseTuple(args, "O!O!UpkiUUU",
            &PyList_Type, &lines, &PyTuple_Type, &levels, &needle,
            &output_positions, &limit, &opts.num_threads,
            &mark_before, &mark_after, &delimiter
    )) return NULL;
    opts.output_positions = output_positions ? true : false;
    opts.limit = limit;
    global.level1_len = copy_unicode_object(PyTuple_GET_ITEM(levels, 0), global.level1, arraysz(global.level1));
    global.level2_len = copy_unicode_object(PyTuple_GET_ITEM(levels, 1), global.level2, arraysz(global.level2));
    global.level3_len = copy_unicode_object(PyTuple_GET_ITEM(levels, 2), global.level3, arraysz(global.level3));
    global.needle_len = copy_unicode_object(needle, global.needle, arraysz(global.needle));
    opts.mark_before_sz = copy_unicode_object(mark_before, opts.mark_before, arraysz(opts.mark_before));
    opts.mark_after_sz = copy_unicode_object(mark_after, opts.mark_after, arraysz(opts.mark_after));
    opts.delimiter_sz = copy_unicode_object(delimiter, opts.delimiter, arraysz(opts.delimiter));
    size_t num_lines = PyList_GET_SIZE(lines);
    char **clines = malloc(sizeof(char*) * num_lines);
    if (!clines) { return PyErr_NoMemory(); }
    size_t *sizes = malloc(sizeof(size_t) * num_lines);
    if (!sizes) { free(clines); clines = NULL; return PyErr_NoMemory(); }
    for (size_t i = 0; i < num_lines; i++) {
        clines[i] = PyBytes_AS_STRING(PyList_GET_ITEM(lines, i));
        sizes[i] = PyBytes_GET_SIZE(PyList_GET_ITEM(lines, i));
    }
    Py_BEGIN_ALLOW_THREADS;
    run_search(&opts, &global, (const char* const *)clines, sizes, num_lines);
    Py_END_ALLOW_THREADS;
    free(clines); free(sizes);
    if (global.oom) { free(global.output); return PyErr_NoMemory(); }
    if (global.output) {
        PyObject *ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, global.output, global.output_pos);
        free(global.output);
        return ans;
    }
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    {"match", match, METH_VARARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static struct PyModuleDef module = {
   .m_base = PyModuleDef_HEAD_INIT,
   .m_name = "subseq_matcher",   /* name of module */
   .m_doc = NULL,
   .m_size = -1,
   .m_methods = module_methods
};

EXPORTED PyMODINIT_FUNC
PyInit_subseq_matcher(void) {
    return PyModule_Create(&module);
}
