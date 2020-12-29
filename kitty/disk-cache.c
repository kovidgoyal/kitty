/*
 * disk-cache.c
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "disk-cache.h"
#include "state.h"
#include "loop-utils.h"
#include <stdlib.h>

typedef struct {
    PyObject_HEAD
    char *path;
    pthread_mutex_t lock;
    pthread_t write_thread;
    bool thread_started, lock_inited, loop_data_inited, shutting_down, fully_initialized;
    LoopData loop_data;
    PyObject *rmtree;
} DiskCache;

#define mutex(op) pthread_mutex_##op(&self->lock)

static PyObject*
new(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    DiskCache *self;
    self = (DiskCache*)type->tp_alloc(type, 0);
    if (self) {
        PyObject *shutil = PyImport_ImportModule("shutil");
        if (!shutil) { Py_CLEAR(self); return NULL; }
        self->rmtree = PyObject_GetAttrString(shutil, "rmtree");
        Py_CLEAR(shutil);
        if (!self->rmtree) { Py_CLEAR(self); return NULL; }
    }
    return (PyObject*) self;
}

static void*
write_loop(void *data) {
    DiskCache *self = (DiskCache*)data;
    while (!self->shutting_down) {
    }
    return 0;
}

static bool
ensure_state(DiskCache *self) {
    int ret;
    if (self->fully_initialized) return true;
    if (!self->loop_data_inited) {
        if (!init_loop_data(&self->loop_data)) { PyErr_SetFromErrno(PyExc_OSError); return false; }
        self->loop_data_inited = true;
    }

    if (!self->lock_inited) {
        if ((ret = pthread_mutex_init(&self->lock, NULL)) != 0) {
            PyErr_Format(PyExc_OSError, "Failed to create disk cache lock mutex: %s", strerror(ret));
            return false;
        }
        self->lock_inited = true;
    }

    if (!self->thread_started) {
        if ((ret = pthread_create(&self->write_thread, NULL, write_loop, self)) != 0) {
            PyErr_Format(PyExc_OSError, "Failed to start disk cache write thread with error: %s", strerror(ret));
            return false;
        }
        self->thread_started = true;
    }

    if (!self->path) {
        PyObject *kc = NULL, *cache_dir = NULL;
        kc = PyImport_ImportModule("kitty.constants");
        if (kc) {
            cache_dir = PyObject_CallMethod(kc, "dir_for_disk_cache", NULL);
            if (cache_dir) {
                self->path = strdup(PyUnicode_AsUTF8(cache_dir));
                if (!self->path) PyErr_NoMemory();
            }
        }
        Py_CLEAR(kc); Py_CLEAR(cache_dir);
        if (PyErr_Occurred()) return false;
    }

    self->fully_initialized = true;
    return true;
}

static void
wakeup_write_loop(DiskCache *self) {
    if (self->thread_started) wakeup_loop(&self->loop_data, false, "disk_cache_write_loop");
}

static void
dealloc(DiskCache* self) {
    self->shutting_down = true;
    if (self->thread_started) {
        wakeup_write_loop(self);
        pthread_join(self->write_thread, NULL);
        self->thread_started = false;
    }
    if (self->lock_inited) {
        pthread_mutex_destroy(&self->lock);
        self->lock_inited = false;
    }
    if (self->loop_data_inited) {
        free_loop_data(&self->loop_data);
        self->loop_data_inited = false;
    }

    if (self->path) {
        PyObject_CallFunction(self->rmtree, "sO", self->path, Py_True);
        free(self->path); self->path = NULL;
    }
    Py_CLEAR(self->rmtree);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

#define PYWRAP0(name) static PyObject* py##name(DiskCache *self, PyObject *args UNUSED)
PYWRAP0(ensure_state) {
    ensure_state(self);
    Py_RETURN_NONE;
}

#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}
static PyMethodDef methods[] = {
    MW(ensure_state, METH_NOARGS),
    {NULL}  /* Sentinel */
};


PyTypeObject DiskCache_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.DiskCache",
    .tp_basicsize = sizeof(DiskCache),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "A disk based secure cache",
    .tp_methods = methods,
    .tp_new = new,
};


INIT_TYPE(DiskCache)
PyObject* create_disk_cache(void) { return new(&DiskCache_Type, NULL, NULL); }
