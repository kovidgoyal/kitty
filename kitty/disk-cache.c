/*
 * disk-cache.c
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define EXTRA_INIT if (PyModule_AddFunctions(module, module_methods) != 0) return false;

#include "disk-cache.h"
#include "uthash.h"
#include "loop-utils.h"
#include "cross-platform-random.h"
#include <stdlib.h>
#include <sys/stat.h>
#include <fcntl.h>


typedef struct {
    void *hash_key;
    uint8_t *data;
    size_t hash_keylen, data_sz;
    bool written_to_disk;
    uint8_t encryption_key[64];
    off_t pos_in_cache_file;
    UT_hash_handle hh;
} CacheEntry;


typedef struct {
    PyObject_HEAD
    char *cache_dir;
    int cache_file_fd;
    pthread_mutex_t lock;
    pthread_t write_thread;
    bool thread_started, lock_inited, loop_data_inited, shutting_down, fully_initialized;
    LoopData loop_data;
    CacheEntry *entries, currently_writing;
} DiskCache;


void
free_cache_entry(CacheEntry *e) {
    if (e->hash_key) { free(e->hash_key); e->hash_key = NULL; }
    if (e->data) { free(e->data); e->data = NULL; }
    free(e);
}

#define mutex(op) pthread_mutex_##op(&self->lock)

static PyObject*
new(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    DiskCache *self;
    self = (DiskCache*)type->tp_alloc(type, 0);
    if (self) {
        self->cache_file_fd = -1;
    }
    return (PyObject*) self;
}

static int
open_cache_file(const char *cache_path) {
    size_t sz = strlen(cache_path) + 16;
    char *buf = calloc(1, sz);
    if (!buf) { errno = ENOMEM; return -1; }
    snprintf(buf, sz - 1, "%s/XXXXXXXXXXXX", cache_path);
    int fd = -1;
    while (fd < 0) {
        fd = mkostemp(buf, O_CLOEXEC);
        if (fd > -1 || errno != EINTR) break;
    }
    if (fd > -1) unlink(buf);
    free(buf);
    return fd;
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

    if (!self->cache_dir) {
        PyObject *kc = NULL, *cache_dir = NULL;
        kc = PyImport_ImportModule("kitty.constants");
        if (kc) {
            cache_dir = PyObject_CallMethod(kc, "dir_for_disk_cache", NULL);
            if (cache_dir) {
                self->cache_dir = strdup(PyUnicode_AsUTF8(cache_dir));
                if (!self->cache_dir) PyErr_NoMemory();
            }
        }
        Py_CLEAR(kc); Py_CLEAR(cache_dir);
        if (PyErr_Occurred()) return false;
    }

    if (self->cache_file_fd < 0) {
        self->cache_file_fd = open_cache_file(self->cache_dir);
        if (self->cache_file_fd < 0) {
            PyErr_SetFromErrnoWithFilename(PyExc_OSError, self->cache_dir);
            return false;
        }
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
    if (self->entries) {
        CacheEntry *tmp, *s;
        HASH_ITER(hh, self->entries, s, tmp) {
            HASH_DEL(self->entries, s);
            free_cache_entry(s); s = NULL;
        }
        self->entries = NULL;
    }
    if (self->cache_file_fd > -1) {
        safe_close(self->cache_file_fd, __FILE__, __LINE__);
        self->cache_file_fd = -1;
    }
    if (self->currently_writing.hash_key) free(self->currently_writing.hash_key);
    if (self->currently_writing.data) free(self->currently_writing.data);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

bool
add_to_disk_cache(PyObject *self_, const void *key, size_t key_sz, const uint8_t *data, size_t data_sz) {
    DiskCache *self = (DiskCache*)self_;
    if (!ensure_state(self)) return false;
    CacheEntry *s = NULL;
    uint8_t *copied_data = malloc(data_sz);
    if (!copied_data) { PyErr_NoMemory(); return false; }
    memcpy(copied_data, data, data_sz);

    mutex(lock);
    HASH_FIND(hh, self->entries, key, key_sz, s);
    if (s == NULL) {
        s = calloc(1, sizeof(CacheEntry));
        if (!s) { PyErr_NoMemory(); goto end; }
        if (!secure_random_bytes(s->encryption_key, sizeof(s->encryption_key))) { free(s); PyErr_SetFromErrno(PyExc_OSError); goto end; }
        s->hash_key = malloc(key_sz);
        if (!s->hash_key) { free(s); PyErr_NoMemory(); goto end; }
        s->hash_keylen = key_sz;
        memcpy(s->hash_key, key, key_sz);
        HASH_ADD_KEYPTR(hh, self->entries, s->hash_key, s->hash_keylen, s);
    } else {
        s->written_to_disk = false;
        if (s->data) free(s->data);
    }
    s->data = copied_data; s->data_sz = data_sz; copied_data = NULL;
end:
    mutex(unlock);

    if (copied_data) free(copied_data);
    if (PyErr_Occurred()) return false;
    wakeup_write_loop(self);
    return true;
}

static void
xor_data(const uint8_t* restrict key, const size_t key_sz, uint8_t* restrict data, const size_t data_sz) {
    size_t unaligned_sz = data_sz % key_sz;
    size_t aligned_sz = data_sz - unaligned_sz;
    for (size_t offset = 0; offset < aligned_sz; offset += key_sz) {
        for (size_t i = 0; i < key_sz; i++) data[offset + i] ^= key[i];
    }
    for (size_t i = 0; i < unaligned_sz; i++) data[aligned_sz + i] ^= key[i];
}

static void
read_from_cache_entry(const DiskCache *self, const CacheEntry *s, uint8_t *dest) {
    uint8_t *p = dest;
    size_t sz = s->data_sz;
    off_t pos = s->pos_in_cache_file;
    while (sz) {
        ssize_t n = pread(self->cache_file_fd, p, sz, pos);
        if (n > 0) {
            sz -= n;
            p += n;
            pos += n;
            continue;
        }
        if (n < 0) {
            if (errno == EINTR || errno == EAGAIN) continue;
            PyErr_SetFromErrnoWithFilename(PyExc_OSError, self->cache_dir);
            break;
        }
        if (n == 0) {
            PyErr_SetString(PyExc_OSError, "Disk cache file truncated");
            break;
        }
    }
}

bool
read_from_disk_cache(PyObject *self_, const void *key, size_t key_sz, uint8_t **data, size_t *data_sz) {
    DiskCache *self = (DiskCache*)self_;
    if (!ensure_state(self)) return false;
    mutex(lock);
    CacheEntry *s = NULL;
    HASH_FIND(hh, self->entries, key, key_sz, s);
    if (!s) { PyErr_SetString(PyExc_KeyError, "No cached entry with specified key found"); goto end; }

    *data = (uint8_t*)malloc(s->data_sz);
    if (!*data) { PyErr_NoMemory(); goto end; }
    *data_sz = s->data_sz;

    if (s->data) { memcpy(*data, s->data, *data_sz); }
    else if (self->currently_writing.hash_key && self->currently_writing.hash_keylen == key_sz && memcmp(self->currently_writing.hash_key, key, key_sz) == 0) {
        memcpy(*data, self->currently_writing.data, *data_sz);
        xor_data(self->currently_writing.encryption_key, sizeof(self->currently_writing.encryption_key), *data, *data_sz);
    }
    else {
        read_from_cache_entry(self, s, *data);
        xor_data(s->encryption_key, sizeof(s->encryption_key), *data, *data_sz);
    }
end:
    mutex(unlock);
    if (PyErr_Occurred()) return false;
    return true;
}

#define PYWRAP(name) static PyObject* py##name(DiskCache *self, PyObject *args)
#define PA(fmt, ...) if (!PyArg_ParseTuple(args, fmt, __VA_ARGS__)) return NULL;
PYWRAP(ensure_state) {
    (void)args;
    ensure_state(self);
    Py_RETURN_NONE;
}

PYWRAP(xor_data) {
    (void) self;
    const char *key, *data;
    Py_ssize_t keylen, data_sz;
    PA("y#y#", &key, &keylen, &data, &data_sz);
    PyObject *ans = PyBytes_FromStringAndSize(NULL, data_sz);
    if (ans == NULL) return NULL;
    void *dest = PyBytes_AS_STRING(ans);
    memcpy(dest, data, data_sz);
    xor_data((const uint8_t*)key, keylen, dest, data_sz);
    return ans;
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

static PyMethodDef module_methods[] = {
    MW(xor_data, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

INIT_TYPE(DiskCache)
PyObject* create_disk_cache(void) { return new(&DiskCache_Type, NULL, NULL); }
