/*
 * algorithm.c
 * Copyright (C) 2023 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#define XXH_INLINE_ALL
#include <xxhash.h>

static PyObject *RsyncError = NULL;
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

typedef struct Rsync {
    size_t block_size;

    hasher_constructor_t hasher_constructor, checksummer_constructor;
    hasher_t hasher, checksummer;

    void *buffer; size_t buffer_cap, buffer_sz;
} Rsync;

static void
free_rsync(Rsync* r) {
    if (r->hasher.state) { r->hasher.delete(r->hasher.state); r->hasher.state = NULL; }
    if (r->checksummer.state) { r->checksummer.delete(r->checksummer.state); r->checksummer.state = NULL; }
    if (r->buffer) { free(r->buffer); r->buffer = NULL; }
    free(r);
}

static Rsync*
new_rsync(size_t block_size, int strong_hash_type, int checksum_type) {
    Rsync *ans = calloc(1, sizeof(Rsync));
    if (ans != NULL) {
        ans->block_size = block_size;
        if (strong_hash_type == 0) ans->hasher_constructor = xxh64_hasher;
        if (checksum_type == 0) ans->checksummer_constructor = xxh128_hasher;
        if (ans->hasher_constructor == NULL) { free_rsync(ans); return NULL; }
        if (ans->checksummer_constructor == NULL) { free_rsync(ans); return NULL; }
        ans->hasher = ans->hasher_constructor();
        ans->checksummer = ans->checksummer_constructor();
        ans->buffer = malloc(block_size);
        if (ans->buffer == NULL) { free(ans); return NULL; }
        ans->buffer_cap = block_size;
    }
    return ans;
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

static void
rolling_checksum_add_one_byte(rolling_checksum *self, uint8_t first_byte, uint8_t last_byte) {
	self->alpha = (self->alpha - self->first_byte_of_previous_window + last_byte) % _M;
	self->beta = (self->beta - (self->l)*self->first_byte_of_previous_window + self->alpha) % _M;
	self->val = self->alpha + _M*self->beta;
	self->first_byte_of_previous_window = first_byte;
}

// Python interface {{{

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
reset(Hasher *self) {
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
digest(Hasher *self) {
    PyObject *ans = PyBytes_FromStringAndSize(NULL, self->h.hash_size);
    if (ans) self->h.digest(self->h.state, PyBytes_AS_STRING(ans));
    return ans;
}

static PyObject*
hexdigest(Hasher *self) {
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

static PyMethodDef module_methods[] = {
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static int
exec_module(PyObject *m) {
    RsyncError = PyErr_NewException("rsync.RsyncError", NULL, NULL);
    if (RsyncError == NULL) return -1;
    PyModule_AddObject(m, "RsyncError", RsyncError);
    if (PyType_Ready(&Hasher_Type) < 0) return -1;
    Py_INCREF(&Hasher_Type);
    if (PyModule_AddObject(m, "Hasher", (PyObject *) &Hasher_Type) < 0) return -1;

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
