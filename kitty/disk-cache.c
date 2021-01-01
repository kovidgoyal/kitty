/*
 * disk-cache.c
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define EXTRA_INIT if (PyModule_AddFunctions(module, module_methods) != 0) return false;
#define MAX_KEY_SIZE 256u
#if __linux__
#define HAS_SENDFILE
#endif

#include "disk-cache.h"
#include "uthash.h"
#include "loop-utils.h"
#include "threading.h"
#include "cross-platform-random.h"
#include <stdlib.h>
#include <sys/stat.h>
#include <fcntl.h>
#ifdef HAS_SENDFILE
#include <sys/sendfile.h>
#endif


typedef struct {
    void *hash_key;
    uint8_t *data;
    size_t data_sz;
    unsigned short hash_keylen;
    bool written_to_disk;
    off_t pos_in_cache_file;
    uint8_t encryption_key[64];
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
    size_t total_size;
} DiskCache;

static void
xor_data(const uint8_t* restrict key, const size_t key_sz, uint8_t* restrict data, const size_t data_sz) {
    size_t unaligned_sz = data_sz % key_sz;
    size_t aligned_sz = data_sz - unaligned_sz;
    for (size_t offset = 0; offset < aligned_sz; offset += key_sz) {
        for (size_t i = 0; i < key_sz; i++) data[offset + i] ^= key[i];
    }
    for (size_t i = 0; i < unaligned_sz; i++) data[aligned_sz + i] ^= key[i];
}


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

static bool
copy_between_files(int infd, int outfd, off_t in_pos, size_t len, uint8_t *buf, size_t bufsz) {
#ifdef HAS_SENDFILE
    (void)buf; (void)bufsz;
    while (len) {
        off_t r = in_pos;
        ssize_t n = sendfile(outfd, infd, &r, len);
        if (n < 0) {
            if (errno != EAGAIN) return false;
            continue;
        }
        in_pos += n; len -= n;
    }
#else
    const size_t bufsz = 1024 * 1024;
    if (!buf) { errno = ENOMEM; return false; }
    while (len) {
        ssize_t amt_read = pread(infd, buf, MIN(len, bufsz), in_pos);
        if (amt_read < 0) {
            if (errno == EINTR || errno == EAGAIN) continue;
            return false;
        }
        if (amt_read == 0) {
            errno = EIO;
            return false;
        }
        len -= amt_read;
        in_pos += amt_read;
        uint8_t *p = buf;
        while(amt_read) {
            ssize_t amt_written = write(outfd, p, amt_read);
            if (amt_written < 0) {
                if (errno == EINTR || errno == EAGAIN) continue;
                return false;
            }
            if (amt_written == 0) {
                errno = EIO;
                return false;
            }
            amt_read -= amt_written;
            p += amt_written;
        }
    }
#endif
    return true;
}

typedef struct {
    uint8_t hash_key[MAX_KEY_SIZE];
    unsigned short hash_keylen;
    off_t old_offset, new_offset;
    size_t data_sz;
} DefragEntry;

static void
defrag(DiskCache *self) {
    int new_cache_file = -1;
    DefragEntry *defrag_entries = NULL;
    uint8_t *buf = NULL;
    const size_t bufsz = 1024 * 1024;
    bool lock_released = false, ok = false;

    off_t size_on_disk = lseek(self->cache_file_fd, 0, SEEK_CUR);
    if (size_on_disk <= 0) goto cleanup;
    size_t num_entries = HASH_COUNT(self->entries);
    if (!num_entries) goto cleanup;
    new_cache_file = open_cache_file(self->cache_dir);
    if (new_cache_file < 0) {
        perror("Failed to open second file for defrag of disk cache");
        goto cleanup;
    }
    defrag_entries = calloc(num_entries, sizeof(DefragEntry));
    if (!defrag_entries) goto cleanup;
    size_t total_data_size = 0, num_entries_to_defrag = 0;
    CacheEntry *tmp, *s;
    HASH_ITER(hh, self->entries, s, tmp) {
        if (s->pos_in_cache_file > -1 && s->data_sz) {
            total_data_size += s->data_sz;
            DefragEntry *e = defrag_entries + num_entries_to_defrag++;
            e->hash_keylen = s->hash_keylen;
            e->old_offset = s->pos_in_cache_file;
            e->data_sz = s->data_sz;
            if (s->hash_key) memcpy(e->hash_key, s->hash_key, s->hash_keylen);
            num_entries_to_defrag++;
        }
    }
    if (ftruncate(new_cache_file, total_data_size) != 0) {
        perror("Failed to allocate space for new disk cache file during defrag");
        goto cleanup;
    }
#ifndef HAS_SENDFILE
    buf = malloc(bufsz);
    if (!buf) goto cleanup;
#endif

    mutex(unlock); lock_released = true;

    off_t current_pos = 0;
    for (size_t i = 0; i < num_entries_to_defrag; i++) {
        DefragEntry *e = defrag_entries + i;
        if (!copy_between_files(self->cache_file_fd, new_cache_file, e->old_offset, e->data_sz, buf, bufsz)) {
            perror("Failed to copy data to new disk cache file during defrag");
            goto cleanup;
        }
        e->new_offset = current_pos;
        current_pos += e->data_sz;
    }
    ok = true;

cleanup:
    if (lock_released) mutex(lock);
    if (ok) {
        safe_close(self->cache_file_fd, __FILE__, __LINE__);
        self->cache_file_fd = new_cache_file; new_cache_file = -1;
        for (size_t i = 0; i < num_entries_to_defrag; i++) {
            DefragEntry *e = defrag_entries + i;
            s = NULL;
            HASH_FIND(hh, self->entries, e->hash_key, e->hash_keylen, s);
            if (s) s->pos_in_cache_file = e->new_offset;
        }
    }
    if (defrag_entries) free(defrag_entries);
    if (buf) free(buf);
    if (new_cache_file > -1) safe_close(new_cache_file, __FILE__, __LINE__);
}

static inline bool
find_cache_entry_to_write(DiskCache *self) {
    CacheEntry *tmp, *s;
    off_t size_on_disk = lseek(self->cache_file_fd, 0, SEEK_END);
    if (self->total_size && size_on_disk > 0 && (size_t)size_on_disk > self->total_size * 2) defrag(self);
    HASH_ITER(hh, self->entries, s, tmp) {
        if (!s->written_to_disk) {
            if (s->data) {
                self->currently_writing.data = s->data;
                s->data = NULL;
                self->currently_writing.data_sz = s->data_sz;
                xor_data(s->encryption_key, sizeof(s->encryption_key), self->currently_writing.data, s->data_sz);
                self->currently_writing.hash_keylen = MIN(s->hash_keylen, MAX_KEY_SIZE);
                memcpy(self->currently_writing.hash_key, s->hash_key, self->currently_writing.hash_keylen);
            }
            return true;
        }
    }
    return false;
}

static inline bool
write_dirty_entry(DiskCache *self) {
    size_t left = self->currently_writing.data_sz;
    uint8_t *p = self->currently_writing.data;
    self->currently_writing.pos_in_cache_file = lseek(self->cache_file_fd, 0, SEEK_CUR);
    if (self->currently_writing.pos_in_cache_file < 0) {
        perror("Failed to seek in disk cache file");
        return false;
    }
    while (left > 0) {
        ssize_t n = write(self->cache_file_fd, p, left);
        if (n < 0) {
            if (errno == EINTR || errno == EAGAIN) continue;
            perror("Failed to write to disk-cache file");
            self->currently_writing.pos_in_cache_file = -1;
            return false;
        }
        if (n == 0) {
            fprintf(stderr, "Failed to write to disk-cache file with zero return\n");
            self->currently_writing.pos_in_cache_file = -1;
            return false;
        }
        left -= n;
        p += n;
    }
    return true;
}

static inline void
retire_currently_writing(DiskCache *self) {
    CacheEntry *s = NULL;
    HASH_FIND(hh, self->entries, self->currently_writing.hash_key, self->currently_writing.hash_keylen, s);
    if (s) {
        s->written_to_disk = true;
        s->pos_in_cache_file = self->currently_writing.pos_in_cache_file;
    }
    free(self->currently_writing.data);
    self->currently_writing.data = NULL;
    self->currently_writing.data_sz = 0;
}

static void*
write_loop(void *data) {
    DiskCache *self = (DiskCache*)data;
    set_thread_name("DiskCacheWrite");
    struct pollfd fds[1] = {0};
    fds[0].fd = self->loop_data.wakeup_read_fd;
    fds[0].events = POLLIN;
    bool found_dirty_entry = false;

    while (!self->shutting_down) {
        mutex(lock);
        found_dirty_entry = find_cache_entry_to_write(self);
        mutex(unlock);
        if (found_dirty_entry) {
            write_dirty_entry(self);
            mutex(lock);
            retire_currently_writing(self);
            mutex(unlock);
            continue;
        }

        if (poll(fds, 1, -1) > 0 && fds[0].revents & POLLIN) {
            drain_fd(fds[0].fd);  // wakeup
        }
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
    if (!self->currently_writing.hash_key) {
        self->currently_writing.hash_key = malloc(MAX_KEY_SIZE);
        if (!self->currently_writing.hash_key) { PyErr_NoMemory(); return false; }
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
    if (self->currently_writing.hash_key) {
        free(self->currently_writing.hash_key); self->currently_writing.hash_key = NULL;
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
    if (self->currently_writing.data) free(self->currently_writing.data);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static inline CacheEntry*
create_cache_entry(const void *key, const size_t key_sz) {
    CacheEntry *s = calloc(1, sizeof(CacheEntry));
    if (!s) return (CacheEntry*)PyErr_NoMemory();
    if (!secure_random_bytes(s->encryption_key, sizeof(s->encryption_key))) { free(s); PyErr_SetFromErrno(PyExc_OSError); return NULL; }
    s->hash_key = malloc(key_sz);
    if (!s->hash_key) { free(s); PyErr_NoMemory(); return NULL; }
    s->hash_keylen = key_sz;
    memcpy(s->hash_key, key, key_sz);
    s->pos_in_cache_file = -2;
    return s;
}

bool
add_to_disk_cache(PyObject *self_, const void *key, size_t key_sz, const uint8_t *data, size_t data_sz) {
    DiskCache *self = (DiskCache*)self_;
    if (!ensure_state(self)) return false;
    if (key_sz > MAX_KEY_SIZE) { PyErr_SetString(PyExc_KeyError, "cache key is too long"); return false; }
    CacheEntry *s = NULL;
    uint8_t *copied_data = malloc(data_sz);
    if (!copied_data) { PyErr_NoMemory(); return false; }
    memcpy(copied_data, data, data_sz);

    mutex(lock);
    HASH_FIND(hh, self->entries, key, key_sz, s);
    if (s == NULL) {
        if (!(s = create_cache_entry(key, key_sz))) goto end;
        HASH_ADD_KEYPTR(hh, self->entries, s->hash_key, s->hash_keylen, s);
    } else {
        s->written_to_disk = false;
        if (s->data) free(s->data);
        if (data_sz <= self->total_size) self->total_size -= data_sz;
        else self->total_size = 0;
    }
    s->data = copied_data; s->data_sz = data_sz; copied_data = NULL;
    self->total_size += s->data_sz;
end:
    mutex(unlock);

    if (copied_data) free(copied_data);
    if (PyErr_Occurred()) return false;
    wakeup_write_loop(self);
    return true;
}

static void
read_from_cache_entry(const DiskCache *self, const CacheEntry *s, uint8_t *dest) {
    uint8_t *p = dest;
    size_t sz = s->data_sz;
    off_t pos = s->pos_in_cache_file;
    if (pos < 0) {
        PyErr_SetString(PyExc_OSError, "Cache entry was not written, could not read from it");
        return;
    }
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
        xor_data(s->encryption_key, sizeof(s->encryption_key), *data, *data_sz);
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
