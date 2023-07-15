//go:build exclude_me
/*
 * algorithm.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "binary.h"
#include <math.h>
#include <xxhash.h>

static PyObject *RsyncError = NULL;
static const size_t default_block_size = 6 * 1024;
static const size_t signature_block_size = 20;

// hashers {{{
typedef void*(*new_hash_t)(void);
typedef void(*delete_hash_t)(void*);
typedef bool(*reset_hash_t)(void*);
typedef bool(*update_hash_t)(void*, const void *input, size_t length);
typedef void(*digest_hash_t)(const void*, void *output);
typedef uint64_t(*digest_hash64_t)(const void*);

typedef struct hasher_t {
    size_t hash_size, block_size;
    void *state;
    new_hash_t new;
    delete_hash_t delete;
    reset_hash_t reset;
    update_hash_t update;
    digest_hash_t digest;
    digest_hash64_t digest64;
} hasher_t;

static void xxh64_delete(void* s) { XXH3_freeState(s); }
static bool xxh64_reset(void* s) { return XXH3_64bits_reset(s) == XXH_OK; }
static void* xxh64_create(void) { void *ans = XXH3_createState(); if (ans != NULL) xxh64_reset(ans); return ans; }
static bool xxh64_update(void* s, const void *input, size_t length) { return XXH3_64bits_update(s, input, length) == XXH_OK; }
static uint64_t xxh64_digest64(const void* s) { return XXH3_64bits_digest(s); }
static void xxh64_digest(const void* s, void *output) {
    XXH64_hash_t ans = XXH3_64bits_digest(s);
    XXH64_canonical_t c;
    XXH64_canonicalFromHash(&c, ans);
    memcpy(output, c.digest, sizeof(c.digest));
}

static hasher_t
xxh64_hasher(void) {
    hasher_t ans = {
        .hash_size=sizeof(XXH64_hash_t), .block_size = 64,
        .new=xxh64_create, .delete=xxh64_delete, .reset=xxh64_reset, .update=xxh64_update, .digest=xxh64_digest, .digest64=xxh64_digest64
    };
    return ans;
}

static bool xxh128_reset(void* s) { return XXH3_128bits_reset(s) == XXH_OK; }
static void* xxh128_create(void) { void *ans = XXH3_createState(); if (ans != NULL) xxh128_reset(ans); return ans; }
static bool xxh128_update(void* s, const void *input, size_t length) { return XXH3_128bits_update(s, input, length) == XXH_OK; }
static void xxh128_digest(const void* s, void *output) {
    XXH128_hash_t ans = XXH3_128bits_digest(s);
    XXH128_canonical_t c;
    XXH128_canonicalFromHash(&c, ans);
    memcpy(output, c.digest, sizeof(c.digest));
}

static hasher_t
xxh128_hasher(void) {
    hasher_t ans = {
        .hash_size=sizeof(XXH128_hash_t), .block_size = 64,
        .new=xxh128_create, .delete=xxh64_delete, .reset=xxh128_reset, .update=xxh128_update, .digest=xxh128_digest,
    };
    return ans;
}


typedef hasher_t(*hasher_constructor_t)(void);
// }}}

typedef struct Rsync {
    size_t block_size;

    hasher_constructor_t hasher_constructor, checksummer_constructor;
    hasher_t hasher, checksummer;

    size_t buffer_cap, buffer_sz;
} Rsync;

static void
free_rsync(Rsync* r) {
    if (r->hasher.state) { r->hasher.delete(r->hasher.state); r->hasher.state = NULL; }
    if (r->checksummer.state) { r->checksummer.delete(r->checksummer.state); r->checksummer.state = NULL; }
}

static const char*
init_rsync(Rsync *ans, size_t block_size, int strong_hash_type, int checksum_type) {
    memset(ans, 0, sizeof(*ans));
    ans->block_size = block_size;
    if (strong_hash_type == 0) ans->hasher_constructor = xxh64_hasher;
    if (checksum_type == 0) ans->checksummer_constructor = xxh128_hasher;
    if (ans->hasher_constructor == NULL) { free_rsync(ans); return "Unknown strong hash type"; }
    if (ans->checksummer_constructor == NULL) { free_rsync(ans); return "Unknown checksum type"; }
    ans->hasher = ans->hasher_constructor();
    ans->checksummer = ans->checksummer_constructor();
    ans->hasher.state = ans->hasher.new();
    if (ans->hasher.state == NULL) { free(ans); return "Out of memory"; }
    ans->checksummer.state = ans->checksummer.new();
    if (ans->checksummer.state == NULL) { free(ans); return "Out of memory"; }
    return NULL;
}

typedef struct rolling_checksum {
    uint32_t alpha, beta, val, l, first_byte_of_previous_window;
} rolling_checksum;

static const uint32_t _M = (1 << 16);

static uint32_t
rolling_checksum_full(rolling_checksum *self, uint8_t *data, uint32_t len) {
    uint32_t alpha = 0, beta = 0;
    self->l = len;
    for (uint32_t i = 0; i < len; i++) {
		alpha += data[i];
		beta += (self->l - i) * data[i];
    }
	self->first_byte_of_previous_window = data[0];
	self->alpha = alpha % _M;
	self->beta = beta % _M;
	self->val = self->alpha + _M*self->beta;
	return self->val;
}

inline static void
rolling_checksum_add_one_byte(rolling_checksum *self, uint8_t first_byte, uint8_t last_byte) {
	self->alpha = (self->alpha - self->first_byte_of_previous_window + last_byte) % _M;
	self->beta = (self->beta - (self->l)*self->first_byte_of_previous_window + self->alpha) % _M;
	self->val = self->alpha + _M*self->beta;
	self->first_byte_of_previous_window = first_byte;
}

// Python interface {{{

typedef struct {
    PyObject_HEAD
    rolling_checksum rc;
    uint64_t signature_idx;
    size_t block_size;
    Rsync rsync;
} Patcher;

static int
Patcher_init(PyObject *s, PyObject *args, PyObject *kwds) {
    Patcher *self = (Patcher*)s;
    static char *kwlist[] = {"expected_input_size", NULL};
    unsigned long long expected_input_size;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "K", kwlist, &expected_input_size)) return -1;
    self->block_size = default_block_size;
    if (expected_input_size > 0) {
        self->block_size = (size_t)round(sqrt((double)expected_input_size));
    }
    const char *err = init_rsync(&self->rsync, self->block_size, 0, 0);
    if (err != NULL) { PyErr_SetString(RsyncError, err); return -1; }
    return 0;
}

static void
Patcher_dealloc(PyObject *self) {
    Patcher *p = (Patcher*)self;
    (void)p;
    Py_TYPE(self)->tp_free(self);
}

static PyObject*
signature_header(Patcher *self, PyObject *a2) {
    FREE_BUFFER_AFTER_FUNCTION Py_buffer dest = {0};
    if (PyObject_GetBuffer(a2, &dest, PyBUF_WRITE) == -1) return NULL;
    if (dest.len < 12) {
        PyErr_SetString(RsyncError, "Output buffer is too small");
    }
    uint8_t *o = dest.buf;
    le16b(o, 0); // version
    le16b(o + 2, 0);  // checksum type
    le16b(o + 4, 0);  // strong hash type
    le16b(o + 6, 0);  // weak hash type
    le32b(o + 8, self->block_size);  // weak hash type
    Py_RETURN_NONE;
}

static PyObject*
sign_block(Patcher *self, PyObject *args) {
    PyObject *a1, *a2;
    if (!PyArg_ParseTuple(args, "OO", &a1, &a2)) return NULL;
    FREE_BUFFER_AFTER_FUNCTION Py_buffer src = {0};
    FREE_BUFFER_AFTER_FUNCTION Py_buffer dest = {0};
    if (PyObject_GetBuffer(a1, &src, PyBUF_SIMPLE) == -1) return NULL;
    if (PyObject_GetBuffer(a2, &dest, PyBUF_WRITE) == -1) return NULL;
    if (dest.len < (ssize_t)signature_block_size) {
        PyErr_SetString(RsyncError, "Output buffer is too small");
    }
    self->rsync.hasher.reset(self->rsync.hasher.state);
    if (!self->rsync.hasher.update(self->rsync.hasher.state, src.buf, src.len)) { PyErr_SetString(PyExc_ValueError, "String hashing failed"); return NULL; }
    uint64_t strong_hash = self->rsync.hasher.digest64(self->rsync.hasher.state);
    uint32_t weak_hash = rolling_checksum_full(&self->rc, src.buf, src.len);
    uint8_t *o = dest.buf;
    le64b(o, self->signature_idx++);
    le32b(o + 8, weak_hash);
    le64b(o + 12, strong_hash);
    Py_RETURN_NONE;
}

static PyMethodDef Patcher_methods[] = {
    METHODB(sign_block, METH_VARARGS),
    METHODB(signature_header, METH_O),
    {NULL}  /* Sentinel */
};


PyTypeObject Patcher_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "rsync.Patcher",
    .tp_basicsize = sizeof(Patcher),
    .tp_dealloc = Patcher_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Patcher",
    .tp_methods = Patcher_methods,
    .tp_new = PyType_GenericNew,
    .tp_init = Patcher_init,
};

// Hasher {{{
typedef struct {
    PyObject_HEAD
    hasher_t h;
    const char *name;
} Hasher;

static int
Hasher_init(PyObject *s, PyObject *args, PyObject *kwds) {
    Hasher *self = (Hasher*)s;
    static char *kwlist[] = {"which", "data", NULL};
    const char *which = "xxh3-64";
    FREE_BUFFER_AFTER_FUNCTION Py_buffer data = {0};
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|sy*", kwlist, &which, &data)) return -1;
    if (strcmp(which, "xxh3-64") == 0) {
        self->h = xxh64_hasher();
        self->name = "xxh3-64";
    } else if (strcmp(which, "xxh3-128") == 0) {
        self->h = xxh128_hasher();
        self->name = "xxh3-128";
    } else {
        PyErr_Format(PyExc_KeyError, "Unknown hash type: %s", which);
        return -1;
    }
    self->h.state = self->h.new();
    if (self->h.state == NULL) { PyErr_NoMemory(); return -1; }
    if (data.buf && data.len > 0) {
        self->h.update(self->h.state, data.buf, data.len);
    }
    return 0;
}

static void
Hasher_dealloc(PyObject *self) {
    Hasher *h = (Hasher*)self;
    if (h->h.state) { h->h.delete(h->h.state); h->h.state = NULL; }
    Py_TYPE(self)->tp_free(self);
}

static PyObject*
reset(Hasher *self, PyObject *args UNUSED) {
    if (!self->h.reset(self->h.state)) return PyErr_NoMemory();
    Py_RETURN_NONE;
}

static PyObject*
update(Hasher *self, PyObject *o) {
    FREE_BUFFER_AFTER_FUNCTION Py_buffer data = {0};
    if (PyObject_GetBuffer(o, &data, PyBUF_SIMPLE) == -1) return NULL;
    if (data.buf && data.len > 0) {
        self->h.update(self->h.state, data.buf, data.len);
    }
    Py_RETURN_NONE;
}

static PyObject*
digest(Hasher *self, PyObject *args UNUSED) {
    PyObject *ans = PyBytes_FromStringAndSize(NULL, self->h.hash_size);
    if (ans) self->h.digest(self->h.state, PyBytes_AS_STRING(ans));
    return ans;
}

static PyObject*
digest64(Hasher *self, PyObject *args UNUSED) {
    if (self->h.digest64 == NULL) { PyErr_SetString(PyExc_TypeError, "Does not support 64-bit digests"); return NULL; }
    unsigned long long a = self->h.digest64(self->h.state);
    return PyLong_FromUnsignedLongLong(a);
}

static PyObject*
hexdigest(Hasher *self, PyObject *args UNUSED) {
    uint8_t digest[64]; char hexdigest[128];
    self->h.digest(self->h.state, digest);
    static const char * hex = "0123456789abcdef";
    char *pout = hexdigest; const uint8_t *pin = digest;
    for (; pin < digest + self->h.hash_size; pin++) {
        *pout++ = hex[(*pin>>4) & 0xF];
        *pout++ = hex[ *pin     & 0xF];
    }
    return PyUnicode_FromStringAndSize(hexdigest, self->h.hash_size * 2);
}


static PyObject*
Hasher_digest_size(Hasher* self, void* closure UNUSED) { return PyLong_FromSize_t(self->h.hash_size); }
static PyObject*
Hasher_block_size(Hasher* self, void* closure UNUSED) { return PyLong_FromSize_t(self->h.block_size); }
static PyObject*
Hasher_name(Hasher* self, void* closure UNUSED) { return PyUnicode_FromString(self->name); }

static PyMethodDef Hasher_methods[] = {
    METHODB(update, METH_O),
    METHODB(digest, METH_NOARGS),
    METHODB(digest64, METH_NOARGS),
    METHODB(hexdigest, METH_NOARGS),
    METHODB(reset, METH_NOARGS),
    {NULL}  /* Sentinel */
};

PyGetSetDef Hasher_getsets[] = {
    {"digest_size", (getter)Hasher_digest_size, NULL, NULL, NULL},
    {"block_size", (getter)Hasher_block_size, NULL, NULL, NULL},
    {"name", (getter)Hasher_name, NULL, NULL, NULL},
    {NULL}
};


PyTypeObject Hasher_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "rsync.Hasher",
    .tp_basicsize = sizeof(Hasher),
    .tp_dealloc = Hasher_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Hasher",
    .tp_methods = Hasher_methods,
    .tp_new = PyType_GenericNew,
    .tp_init = Hasher_init,
    .tp_getset = Hasher_getsets,
};
// }}} end Hasher

static PyObject*
decode_utf8_buffer(PyObject *self UNUSED, PyObject *args) {
    FREE_BUFFER_AFTER_FUNCTION Py_buffer buf = {0};
    if (!PyArg_ParseTuple(args, "s*", &buf)) return NULL;
    return PyUnicode_FromStringAndSize(buf.buf, buf.len);
}

static bool
call_ftc_callback(PyObject *callback, char *src, Py_ssize_t key_start, Py_ssize_t key_length, Py_ssize_t val_start, Py_ssize_t val_length) {
    while(src[key_start] == ';' && key_length > 0 ) { key_start++; key_length--; }
    DECREF_AFTER_FUNCTION PyObject *k = PyMemoryView_FromMemory(src + key_start, key_length, PyBUF_READ);
    if (!k) return false;
    DECREF_AFTER_FUNCTION PyObject *v = PyMemoryView_FromMemory(src + val_start, val_length, PyBUF_READ);
    if (!v) return false;
    DECREF_AFTER_FUNCTION PyObject *ret = PyObject_CallFunctionObjArgs(callback, k, v, NULL);
    return ret != NULL;
}

static PyObject*
parse_ftc(PyObject *self UNUSED, PyObject *args) {
    FREE_BUFFER_AFTER_FUNCTION Py_buffer buf = {0};
    PyObject *callback;
    size_t i = 0, key_start = 0, key_length = 0, val_start = 0, val_length = 0;
    if (!PyArg_ParseTuple(args, "s*O", &buf, &callback)) return NULL;
    char *src = buf.buf;
    size_t sz = buf.len;
    if (!PyCallable_Check(callback)) { PyErr_SetString(PyExc_TypeError, "callback must be callable"); return NULL; }
    for (i = 0; i < sz; i++) {
        char ch = src[i];
        if (key_length == 0) {
            if (ch == '=') {
                key_length = i - key_start;
                val_start = i + 1;
            }
        } else {
            if (ch == ';') {
                val_length = i - val_start;
                if (!call_ftc_callback(callback, src, key_start, key_length, val_start, val_length)) return NULL;
                key_length = 0; key_start = i + 1; val_start = 0;
            }
        }
    }
    if (key_length && val_start) {
        val_length = sz - val_start;
        if (!call_ftc_callback(callback, src, key_start, key_length, val_start, val_length)) return NULL;
    }
    Py_RETURN_NONE;
}

static PyMethodDef module_methods[] = {
    {"parse_ftc", parse_ftc, METH_VARARGS, ""},
    {"decode_utf8_buffer", decode_utf8_buffer, METH_VARARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static int
exec_module(PyObject *m) {
    RsyncError = PyErr_NewException("rsync.RsyncError", NULL, NULL);
    if (RsyncError == NULL) return -1;
    PyModule_AddObject(m, "RsyncError", RsyncError);
#define T(which) if (PyType_Ready(& which##_Type) < 0) return -1; Py_INCREF(&which##_Type);\
    if (PyModule_AddObject(m, #which, (PyObject *) &which##_Type) < 0) return -1;
    T(Hasher); T(Patcher);
#undef T
    return 0;
}

IGNORE_PEDANTIC_WARNINGS
static PyModuleDef_Slot slots[] = { {Py_mod_exec, (void*)exec_module}, {0, NULL} };
END_IGNORE_PEDANTIC_WARNINGS

static struct PyModuleDef module = {
    .m_base = PyModuleDef_HEAD_INIT,
    .m_name = "rsync",   /* name of module */
    .m_doc = NULL,
    .m_slots = slots,
    .m_methods = module_methods
};

EXPORTED PyMODINIT_FUNC
PyInit_rsync(void) {
    return PyModuleDef_Init(&module);
}
// }}}
