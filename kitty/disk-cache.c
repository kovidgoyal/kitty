/*
 * disk-cache.c
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define EXTRA_INIT if (PyModule_AddFunctions(module, module_methods) != 0) return false;
#define MAX_KEY_SIZE 256u
#include "disk-cache.h"
#include "safe-wrappers.h"
#include "kitty-uthash.h"
#include "loop-utils.h"
#include "fast-file-copy.h"
#include "threading.h"
#include "cross-platform-random.h"
#include <structmember.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <time.h>


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
    unsigned long long total_size;
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
new_diskcache_object(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    DiskCache *self;
    self = (DiskCache*)type->tp_alloc(type, 0);
    if (self) {
        self->cache_file_fd = -1;
    }
    return (PyObject*) self;
}

static int
open_cache_file_without_tmpfile(const char *cache_path) {
    int fd = -1;
    static const char template[] = "%s/disk-cache-XXXXXXXXXXXX";
    const size_t sz = strlen(cache_path) + sizeof(template) + 4;
    RAII_ALLOC(char, buf, calloc(1, sz));
    if (!buf) { errno = ENOMEM; return -1; }
    snprintf(buf, sz - 1, template, cache_path);
    while (fd < 0) {
        fd = mkostemp(buf, O_CLOEXEC);
        if (fd > -1 || errno != EINTR) break;
    }
    if (fd > -1) unlink(buf);
    return fd;
}

static int
open_cache_file(const char *cache_path) {
    int fd = -1;
#ifdef O_TMPFILE
    while (fd < 0) {
        fd = safe_open(cache_path, O_TMPFILE | O_CLOEXEC | O_EXCL | O_RDWR, S_IRUSR | S_IWUSR);
        if (fd > -1 || errno != EINTR) break;
    }
    if (fd == -1) fd = open_cache_file_without_tmpfile(cache_path);
#else
    fd = open_cache_file_without_tmpfile(cache_path);
#endif
    return fd;
}

// Write loop {{{

static off_t
size_of_cache_file(DiskCache *self) {
    return lseek(self->cache_file_fd, 0, SEEK_END);
}

size_t
disk_cache_size_on_disk(PyObject *self) {
    if (((DiskCache*)self)->cache_file_fd > -1) {
        off_t ans = size_of_cache_file((DiskCache*)self);
        return MAX(0, ans);
    }
    return 0;
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
    RAII_ALLOC(DefragEntry, defrag_entries, NULL);
    RAII_FreeFastFileCopyBuffer(fcb);
    bool lock_released = false, ok = false;

    off_t size_on_disk = size_of_cache_file(self);
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
        }
    }
    if (ftruncate(new_cache_file, total_data_size) != 0) {
        perror("Failed to allocate space for new disk cache file during defrag");
        goto cleanup;
    }
    lseek(new_cache_file, 0, SEEK_SET);

    mutex(unlock); lock_released = true;

    off_t current_pos = 0;
    for (size_t i = 0; i < num_entries_to_defrag; i++) {
        DefragEntry *e = defrag_entries + i;
        if (!copy_between_files(self->cache_file_fd, new_cache_file, e->old_offset, e->data_sz, &fcb)) {
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
    if (new_cache_file > -1) safe_close(new_cache_file, __FILE__, __LINE__);
}

static int
cmp_pos_in_cache_file(void *a_, void *b_) {
    CacheEntry *a = a_, *b = b_;
    return a->pos_in_cache_file - b->pos_in_cache_file;
}

static void
find_hole(DiskCache *self) {
    off_t required_size = self->currently_writing.data_sz, prev = -100;
    HASH_SORT(self->entries, cmp_pos_in_cache_file);
    CacheEntry *s, *tmp;
    HASH_ITER(hh, self->entries, s, tmp) {
        if (s->pos_in_cache_file >= 0 && s->data_sz > 0) {
            if (prev >= 0 && s->pos_in_cache_file - prev >= required_size) {
                self->currently_writing.pos_in_cache_file = prev;
                return;
            }
            prev = s->pos_in_cache_file + s->data_sz;
        }
    }
}

static bool
find_cache_entry_to_write(DiskCache *self) {
    CacheEntry *tmp, *s;
    off_t size_on_disk = size_of_cache_file(self);
    if (self->total_size && size_on_disk > 0 && (size_t)size_on_disk > self->total_size * 2) defrag(self);
    HASH_ITER(hh, self->entries, s, tmp) {
        if (!s->written_to_disk) {
            if (s->data) {
                if (self->currently_writing.data) free(self->currently_writing.data);
                self->currently_writing.data = s->data;
                s->data = NULL;
                self->currently_writing.data_sz = s->data_sz;
                self->currently_writing.pos_in_cache_file = -1;
                xor_data(s->encryption_key, sizeof(s->encryption_key), self->currently_writing.data, s->data_sz);
                self->currently_writing.hash_keylen = MIN(s->hash_keylen, MAX_KEY_SIZE);
                memcpy(self->currently_writing.hash_key, s->hash_key, self->currently_writing.hash_keylen);
                find_hole(self);
                return true;
            }
            s->written_to_disk = true;
            s->pos_in_cache_file = 0;
            s->data_sz = 0;
        }
    }
    return false;
}

static bool
write_dirty_entry(DiskCache *self) {
    size_t left = self->currently_writing.data_sz;
    uint8_t *p = self->currently_writing.data;
    if (self->currently_writing.pos_in_cache_file < 0) {
        self->currently_writing.pos_in_cache_file = size_of_cache_file(self);
        if (self->currently_writing.pos_in_cache_file < 0) {
            perror("Failed to seek in disk cache file");
            return false;
        }
    }
    off_t offset = self->currently_writing.pos_in_cache_file;
    while (left > 0) {
        ssize_t n = pwrite(self->cache_file_fd, p, left, offset);
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
        offset += n;
    }
    return true;
}

static void
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
        size_t count = HASH_COUNT(self->entries);
        mutex(unlock);
        if (found_dirty_entry) {
            write_dirty_entry(self);
            mutex(lock);
            retire_currently_writing(self);
            mutex(unlock);
            continue;
        } else if (!count) {
            mutex(lock);
            if (self->cache_file_fd > -1) {
                if (ftruncate(self->cache_file_fd, 0) == 0) lseek(self->cache_file_fd, 0, SEEK_END);
            }
            mutex(unlock);
        }

        if (poll(fds, 1, -1) > 0 && fds[0].revents & POLLIN) {
            drain_fd(fds[0].fd);  // wakeup
        }
    }
    return 0;
}
// }}}

static bool
ensure_state(DiskCache *self) {
    int ret;
    if (self->fully_initialized) return true;
    if (!self->loop_data_inited) {
        if (!init_loop_data(&self->loop_data, 0)) { PyErr_SetFromErrno(PyExc_OSError); return false; }
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
            cache_dir = PyObject_CallMethod(kc, "cache_dir", NULL);
            if (cache_dir) {
                if (PyUnicode_Check(cache_dir)) {
                    self->cache_dir = strdup(PyUnicode_AsUTF8(cache_dir));
                    if (!self->cache_dir) PyErr_NoMemory();
                } else PyErr_SetString(PyExc_TypeError, "cache_dir() did not return a string");
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
    free(self->cache_dir); self->cache_dir = NULL;
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static CacheEntry*
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
add_to_disk_cache(PyObject *self_, const void *key, size_t key_sz, const void *data, size_t data_sz) {
    DiskCache *self = (DiskCache*)self_;
    if (!ensure_state(self)) return false;
    if (key_sz > MAX_KEY_SIZE) { PyErr_SetString(PyExc_KeyError, "cache key is too long"); return false; }
    CacheEntry *s = NULL;
    RAII_ALLOC(uint8_t, copied_data, malloc(data_sz));
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
    if (PyErr_Occurred()) return false;
    wakeup_write_loop(self);
    return true;
}

bool
remove_from_disk_cache(PyObject *self_, const void *key, size_t key_sz) {
    DiskCache *self = (DiskCache*)self_;
    if (!ensure_state(self)) return false;
    if (key_sz > MAX_KEY_SIZE) { PyErr_SetString(PyExc_KeyError, "cache key is too long"); return false; }
    CacheEntry *s = NULL;
    bool removed = false;

    mutex(lock);
    HASH_FIND(hh, self->entries, key, key_sz, s);
    if (s) {
        removed = true;
        HASH_DEL(self->entries, s);
        self->total_size = (self->total_size > s->data_sz) ? self->total_size - s->data_sz : 0;
        free_cache_entry(s);
    }
    mutex(unlock);
    wakeup_write_loop(self);
    return removed;
}

void
clear_disk_cache(PyObject *self_) {
    DiskCache *self = (DiskCache*)self_;
    if (!ensure_state(self)) return;
    CacheEntry *s, *tmp;
    mutex(lock);
    HASH_ITER(hh, self->entries, s, tmp) {
        HASH_DEL(self->entries, s);
        free_cache_entry(s);
    }
    self->total_size = 0;
    mutex(unlock);
    wakeup_write_loop(self);
}

static void
read_from_cache_file(const DiskCache *self, off_t pos, size_t sz, void *dest) {
    uint8_t *p = dest;
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

static void
read_from_cache_entry(const DiskCache *self, const CacheEntry *s, void *dest) {
    size_t sz = s->data_sz;
    off_t pos = s->pos_in_cache_file;
    if (pos < 0) {
        PyErr_SetString(PyExc_OSError, "Cache entry was not written, could not read from it");
        return;
    }
    read_from_cache_file(self, pos, sz, dest);
}

void*
read_from_disk_cache(PyObject *self_, const void *key, size_t key_sz, void*(allocator)(void*, size_t), void* allocator_data, bool store_in_ram) {
    DiskCache *self = (DiskCache*)self_;
    void *data = NULL;
    if (!ensure_state(self)) return data;
    if (key_sz > MAX_KEY_SIZE) { PyErr_SetString(PyExc_KeyError, "cache key is too long"); return data; }

    mutex(lock);
    CacheEntry *s = NULL;
    HASH_FIND(hh, self->entries, key, key_sz, s);
    if (!s) { PyErr_SetString(PyExc_KeyError, "No cached entry with specified key found"); goto end; }
    data = allocator(allocator_data, s->data_sz);
    if (!data) { PyErr_NoMemory(); goto end; }

    if (s->data) { memcpy(data, s->data, s->data_sz); }
    else if (self->currently_writing.data && self->currently_writing.hash_key && self->currently_writing.hash_keylen == key_sz && memcmp(self->currently_writing.hash_key, key, key_sz) == 0) {
        memcpy(data, self->currently_writing.data, s->data_sz);
        xor_data(s->encryption_key, sizeof(s->encryption_key), data, s->data_sz);
    }
    else {
        read_from_cache_entry(self, s, data);
        xor_data(s->encryption_key, sizeof(s->encryption_key), data, s->data_sz);
    }
    if (store_in_ram && !s->data && s->data_sz) {
        void *copy = malloc(s->data_sz);
        if (copy) {
            memcpy(copy, data, s->data_sz); s->data = copy;
        }
    }
end:
    mutex(unlock);
    return data;
}

size_t
disk_cache_clear_from_ram(PyObject *self_, bool(matches)(void*, void *key, unsigned keysz), void *data) {
    DiskCache *self = (DiskCache*)self_;
    size_t ans = 0;
    if (!ensure_state(self)) return ans;
    mutex(lock);
    CacheEntry *s, *tmp;
    HASH_ITER(hh, self->entries, s, tmp) {
        if (s->written_to_disk && s->data && matches(data, s->hash_key, s->hash_keylen)) {
            free(s->data); s->data = NULL;
            ans++;
        }
    }
    mutex(unlock);
    return ans;
}

bool
disk_cache_wait_for_write(PyObject *self_, monotonic_t timeout) {
    DiskCache *self = (DiskCache*)self_;
    if (!ensure_state(self)) return false;
    monotonic_t end_at = monotonic() + timeout;
    while (!timeout || monotonic() <= end_at) {
        bool pending = false;
        mutex(lock);
        CacheEntry *s, *tmp;
        HASH_ITER(hh, self->entries, s, tmp) {
            if (!s->written_to_disk) {
                pending = true;
                break;
            }
        }
        mutex(unlock);
        if (!pending) return true;
        wakeup_write_loop(self);
        struct timespec a = { .tv_nsec = 10L * MONOTONIC_T_1e6 }, b;  // 10ms sleep
        nanosleep(&a, &b);
    }
    return false;
}

size_t
disk_cache_total_size(PyObject *self) { return ((DiskCache*)self)->total_size; }

size_t
disk_cache_num_cached_in_ram(PyObject *self_) {
    DiskCache *self = (DiskCache*)self_;
    unsigned long ans = 0;
    if (ensure_state(self)) {
        mutex(lock);
        CacheEntry *tmp, *s;
        HASH_ITER(hh, self->entries, s, tmp) {
            if (s->written_to_disk && s->data) ans++;
        }
        mutex(unlock);
    }
    return ans;
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

PYWRAP(read_from_cache_file) {
    Py_ssize_t pos = 0, sz = -1;
    PA("|nn", &pos, &sz);
    if (sz < 0) sz = size_of_cache_file(self);
    PyObject *ans = PyBytes_FromStringAndSize(NULL, sz);
    if (ans) {
        read_from_cache_file(self, pos, sz, PyBytes_AS_STRING(ans));
    }
    return ans;
}

static PyObject*
wait_for_write(PyObject *self, PyObject *args) {
    double timeout = 0;
    PA("|d", &timeout);
    if (disk_cache_wait_for_write(self, s_double_to_monotonic_t(timeout))) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

static PyObject*
size_on_disk(PyObject *self, PyObject *args UNUSED) {
    unsigned long long ans = disk_cache_size_on_disk(self);
    return PyLong_FromUnsignedLongLong(ans);
}

static PyObject*
clear(PyObject *self, PyObject *args UNUSED) {
    clear_disk_cache(self);
    Py_RETURN_NONE;
}


static PyObject*
add(PyObject *self, PyObject *args) {
    const char *key, *data;
    Py_ssize_t keylen, datalen;
    PA("y#y#", &key, &keylen, &data, &datalen);
    if (!add_to_disk_cache(self, key, keylen, data, datalen)) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
pyremove(PyObject *self, PyObject *args) {
    const char *key;
    Py_ssize_t keylen;
    PA("y#", &key, &keylen);
    bool removed = remove_from_disk_cache(self, key, keylen);
    if (PyErr_Occurred()) return NULL;
    if (removed) Py_RETURN_TRUE;
    Py_RETURN_FALSE;
}

typedef struct {
    PyObject *bytes;
} BytesWrapper;

static void*
bytes_alloc(void *x, size_t sz) {
    BytesWrapper *w = x;
    w->bytes = PyBytes_FromStringAndSize(NULL, sz);
    if (!w->bytes) return NULL;
    return PyBytes_AS_STRING(w->bytes);
}

PyObject*
read_from_disk_cache_python(PyObject *self, const void *key, size_t keysz, bool store_in_ram) {
    BytesWrapper w = {0};
    read_from_disk_cache(self, key, keysz, bytes_alloc, &w, store_in_ram);
    if (PyErr_Occurred()) { Py_CLEAR(w.bytes); return NULL; }
    return w.bytes;
}

static PyObject*
get(PyObject *self, PyObject *args) {
    const char *key;
    Py_ssize_t keylen;
    int store_in_ram = 0;
    PA("y#|p", &key, &keylen, &store_in_ram);
    return read_from_disk_cache_python(self, key, keylen, store_in_ram);
}

static bool
python_clear_predicate(void *data, void *key, unsigned keysz) {
    PyObject *ret = PyObject_CallFunction(data, "y#", key, keysz);
    if (ret == NULL) { PyErr_Print(); return false; }
    bool ans = PyObject_IsTrue(ret);
    Py_DECREF(ret);
    return ans;
}

static PyObject*
remove_from_ram(PyObject *self, PyObject *callable) {
    if (!PyCallable_Check(callable)) { PyErr_SetString(PyExc_TypeError, "not a callable"); return NULL; }
    return PyLong_FromUnsignedLong(disk_cache_clear_from_ram(self, python_clear_predicate, callable));
}

static PyObject*
num_cached_in_ram(PyObject *self, PyObject *args UNUSED) {
    return PyLong_FromUnsignedLong(disk_cache_num_cached_in_ram(self));
}


#define MW(name, arg_type) {#name, (PyCFunction)py##name, arg_type, NULL}
static PyMethodDef methods[] = {
    MW(ensure_state, METH_NOARGS),
    MW(read_from_cache_file, METH_VARARGS),
    {"add", add, METH_VARARGS, NULL},
    {"remove", pyremove, METH_VARARGS, NULL},
    {"remove_from_ram", remove_from_ram, METH_O, NULL},
    {"num_cached_in_ram", num_cached_in_ram, METH_NOARGS, NULL},
    {"get", get, METH_VARARGS, NULL},
    {"wait_for_write", wait_for_write, METH_VARARGS, NULL},
    {"size_on_disk", size_on_disk, METH_NOARGS, NULL},
    {"clear", clear, METH_NOARGS, NULL},

    {NULL}  /* Sentinel */
};

static PyMemberDef members[] = {
    {"total_size", T_ULONGLONG, offsetof(DiskCache, total_size), READONLY, "total_size"},
    {NULL},
};


PyTypeObject DiskCache_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.DiskCache",
    .tp_basicsize = sizeof(DiskCache),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "A disk based secure cache",
    .tp_methods = methods,
    .tp_members = members,
    .tp_new = new_diskcache_object,
};

static PyMethodDef module_methods[] = {
    MW(xor_data, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

INIT_TYPE(DiskCache)
PyObject* create_disk_cache(void) { return new_diskcache_object(&DiskCache_Type, NULL, NULL); }
