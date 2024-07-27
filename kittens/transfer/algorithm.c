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
void log_error(const char *fmt, ...) { va_list args; va_start(args, fmt); vfprintf(stderr, fmt, args); va_end(args); }

// hashers {{{
typedef void*(*new_hash_t)(void);
typedef void(*delete_hash_t)(void*);
typedef bool(*reset_hash_t)(void*);
typedef bool(*update_hash_t)(void*, const void *input, size_t length);
typedef void(*digest_hash_t)(const void*, void *output);
typedef uint64_t(*digest_hash64_t)(const void*);
typedef uint64_t(*oneshot_hash64_t)(const void*, size_t);

typedef struct hasher_t {
    size_t hash_size, block_size;
    void *state;
    new_hash_t new;
    delete_hash_t delete;
    reset_hash_t reset;
    update_hash_t update;
    digest_hash_t digest;
    digest_hash64_t digest64;
    oneshot_hash64_t oneshot64;
} hasher_t;

static void xxh64_delete(void* s) { XXH3_freeState(s); }
static bool xxh64_reset(void* s) { return XXH3_64bits_reset(s) == XXH_OK; }
static void* xxh64_create(void) { void *ans = XXH3_createState(); if (ans != NULL) xxh64_reset(ans); return ans; }
static bool xxh64_update(void* s, const void *input, size_t length) { return XXH3_64bits_update(s, input, length) == XXH_OK; }
static uint64_t xxh64_digest64(const void* s) { return XXH3_64bits_digest(s); }
static uint64_t xxh64_oneshot64(const void* s, size_t len) { return XXH3_64bits(s, len); }
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
        .new=xxh64_create, .delete=xxh64_delete, .reset=xxh64_reset, .update=xxh64_update, .digest=xxh64_digest,
        .digest64=xxh64_digest64, .oneshot64=xxh64_oneshot64
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
    if (ans->hasher.state == NULL) { free_rsync(ans); return "Out of memory"; }
    ans->checksummer.state = ans->checksummer.new();
    if (ans->checksummer.state == NULL) { free_rsync(ans); return "Out of memory"; }
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

typedef struct buffer {
    uint8_t *data;
    size_t len, cap;
} buffer;

static bool
ensure_space(buffer *b, size_t amt) {
    const size_t len = b->len;
    if (amt > 0 && b->cap < len + amt) {
        size_t newcap = MAX(b->cap * 2, len + (amt * 2));
        b->data = realloc(b->data, newcap);
        if (b->data == NULL) { PyErr_NoMemory(); return false; }
        b->cap = newcap;
    }
    return true;
}

static bool
write_to_buffer(buffer *b, void *data, size_t len) {
    if (!ensure_space(b, len)) return false;
    memcpy(b->data + b->len, data, len);
    b->len += len;
    return true;
}

static void
shift_left(buffer *b, size_t amt) {
    if (amt > b->len) amt = b->len;
    if (amt > 0) {
        b->len -= amt;
        memmove(b->data, b->data + amt, b->len);
    }
}

// Patcher {{{
typedef struct {
    PyObject_HEAD
    rolling_checksum rc;
    uint64_t signature_idx;
    size_t total_data_in_delta;
    Rsync rsync;
    buffer buf, block_buf;
    PyObject *block_buf_view;
    bool checksum_done;
} Patcher;

static int
Patcher_init(PyObject *s, PyObject *args, PyObject *kwds) {
    Patcher *self = (Patcher*)s;
    static char *kwlist[] = {"expected_input_size", NULL};
    unsigned long long expected_input_size = 0;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|K", kwlist, &expected_input_size)) return -1;
    self->rsync.block_size = default_block_size;
    if (expected_input_size > 0) {
        self->rsync.block_size = (size_t)round(sqrt((double)expected_input_size));
    }
    const char *err = init_rsync(&self->rsync, self->rsync.block_size, 0, 0);
    if (err != NULL) { PyErr_SetString(RsyncError, err); return -1; }
    self->block_buf.cap = self->rsync.block_size;
    self->block_buf.data = malloc(self->rsync.block_size);
    if (self->block_buf.data == NULL) { PyErr_NoMemory(); return -1; }
    if (!(self->block_buf_view = PyMemoryView_FromMemory((char*)self->block_buf.data, self->rsync.block_size, PyBUF_WRITE))) return -1;
    return 0;
}

static void
Patcher_dealloc(PyObject *self) {
    Patcher *p = (Patcher*)self;
    if (p->buf.data) free(p->buf.data);
    Py_CLEAR(p->block_buf_view);
    if (p->block_buf.data) free(p->block_buf.data);
    free_rsync(&p->rsync);
    Py_TYPE(self)->tp_free(self);
}

static PyObject*
signature_header(Patcher *self, PyObject *a2) {
    RAII_PY_BUFFER(dest);
    if (PyObject_GetBuffer(a2, &dest, PyBUF_WRITEABLE) == -1) return NULL;
    static const ssize_t header_size = 12;
    if (dest.len < header_size) {
        PyErr_SetString(RsyncError, "Output buffer is too small");
    }
    uint8_t *o = dest.buf;
    le16enc(o, 0); // version
    le16enc(o + 2, 0);  // checksum type
    le16enc(o + 4, 0);  // strong hash type
    le16enc(o + 6, 0);  // weak hash type
    le32enc(o + 8, self->rsync.block_size);  // block size
    return PyLong_FromSsize_t(header_size);
}

static PyObject*
sign_block(Patcher *self, PyObject *args) {
    PyObject *a1, *a2;
    if (!PyArg_ParseTuple(args, "OO", &a1, &a2)) return NULL;
    RAII_PY_BUFFER(src); RAII_PY_BUFFER(dest);
    if (PyObject_GetBuffer(a1, &src, PyBUF_SIMPLE) == -1) return NULL;
    if (PyObject_GetBuffer(a2, &dest, PyBUF_WRITEABLE) == -1) return NULL;
    if (dest.len < (ssize_t)signature_block_size) {
        PyErr_SetString(RsyncError, "Output buffer is too small");
    }
    self->rsync.hasher.reset(self->rsync.hasher.state);
    if (!self->rsync.hasher.update(self->rsync.hasher.state, src.buf, src.len)) { PyErr_SetString(PyExc_ValueError, "String hashing failed"); return NULL; }
    uint64_t strong_hash = self->rsync.hasher.oneshot64(src.buf, src.len);
    uint32_t weak_hash = rolling_checksum_full(&self->rc, src.buf, src.len);
    uint8_t *o = dest.buf;
    le64enc(o, self->signature_idx++);
    le32enc(o + 8, weak_hash);
    le64enc(o + 12, strong_hash);
    return PyLong_FromSize_t(signature_block_size);
}

typedef enum { OpBlock, OpData, OpHash, OpBlockRange } OpType;

typedef struct Operation {
    OpType type;
    uint64_t block_index, block_index_end;
    struct { uint8_t *buf; size_t len; } data;
} Operation;

static size_t
unserialize_op(uint8_t *data, size_t len, Operation *op) {
    size_t consumed = 0;
    switch ((OpType)(data[0])) {
        case OpBlock:
            consumed = 9;
            if (len < consumed) return 0;
            op->block_index = le64dec(data + 1);
            break;
        case OpBlockRange:
            consumed = 13;
            if (len < consumed) return 0;
            op->block_index = le64dec(data + 1);
            op->block_index_end = op->block_index + le32dec(data + 9);
            break;
        case OpHash:
            consumed = 3;
            if (len < consumed) return 0;
            op->data.len = le16dec(data + 1);
            if (len < consumed + op->data.len) return 0;
            op->data.buf = data + 3;
            consumed += op->data.len;
            break;
        case OpData:
            consumed = 5;
            if (len < consumed) return 0;
            op->data.len = le32dec(data + 1);
            if (len < consumed + op->data.len) return 0;
            op->data.buf = data + 5;
            consumed += op->data.len;
            break;
    }
    if (consumed) op->type = data[0];
    return consumed;
}

static bool
write_block(Patcher *self, uint64_t block_index, PyObject *read, PyObject *write) {
    RAII_PyObject(pos, PyLong_FromUnsignedLongLong((unsigned long long)(self->rsync.block_size * block_index)));
    if (!pos) return false;
    RAII_PyObject(ret, PyObject_CallFunctionObjArgs(read, pos, self->block_buf_view, NULL));
    if (ret == NULL) return false;
    if (!PyLong_Check(ret)) { PyErr_SetString(PyExc_TypeError, "read callback function did not return an integer"); return false; }
    size_t n = PyLong_AsSize_t(ret);
    self->rsync.checksummer.update(self->rsync.checksummer.state, self->block_buf.data, n);
    RAII_PyObject(view, PyMemoryView_FromMemory((char*)self->block_buf.data, n, PyBUF_READ));
    if (!view) return false;
    RAII_PyObject(wret, PyObject_CallFunctionObjArgs(write, view, NULL));
    if (wret == NULL) return false;
    return true;
}

static void
bytes_as_hex(const uint8_t *bytes, const size_t len, char *ans) {
    static const char * hex = "0123456789abcdef";
    char *pout = ans; const uint8_t *pin = bytes;
    for (; pin < bytes + len; pin++) {
        *pout++ = hex[(*pin>>4) & 0xF];
        *pout++ = hex[ *pin     & 0xF];
    }
    *pout++ = 0;
}

static bool
apply_op(Patcher *self, Operation op, PyObject *read, PyObject *write) {
    switch (op.type) {
        case OpBlock:
            return write_block(self, op.block_index, read, write);
        case OpBlockRange:
            for (size_t i = op.block_index; i <= op.block_index_end; i++) {
                if (!write_block(self, i, read, write)) return false;
            }
            return true;
        case OpData: {
            self->total_data_in_delta += op.data.len;
            self->rsync.checksummer.update(self->rsync.checksummer.state, op.data.buf, op.data.len);
            RAII_PyObject(view, PyMemoryView_FromMemory((char*)op.data.buf, op.data.len, PyBUF_READ));
            if (!view) return false;
            RAII_PyObject(wret, PyObject_CallFunctionObjArgs(write, view, NULL));
            if (!wret) return false;
        } return true;
        case OpHash: {
            uint8_t actual[64];
            if (op.data.len != self->rsync.checksummer.hash_size) { PyErr_SetString(RsyncError, "checksum digest not the correct size"); return false; }
            self->rsync.checksummer.digest(self->rsync.checksummer.state, actual);
            if (memcmp(actual, op.data.buf, self->rsync.checksummer.hash_size) != 0) {
                char hexdigest[129];
                bytes_as_hex(actual, self->rsync.checksummer.hash_size, hexdigest);
                RAII_PyObject(h1, PyUnicode_FromStringAndSize(hexdigest, 2*self->rsync.checksummer.hash_size));
                bytes_as_hex(op.data.buf, op.data.len, hexdigest);
                RAII_PyObject(h2, PyUnicode_FromStringAndSize(hexdigest, 2*self->rsync.checksummer.hash_size));
                PyErr_Format(RsyncError, "Failed to verify overall file checksum actual: %S != expected: %S, this usually happens because one of the involved files was altered while the operation was in progress.", h1, h2);
                return false;
            }
            self->checksum_done = true;
        } return true;
    }
    PyErr_SetString(RsyncError, "Unknown operation type");
    return false;
}

static PyObject*
apply_delta_data(Patcher *self, PyObject *args) {
    PyObject *read, *write;
    RAII_PY_BUFFER(data);
    if (!PyArg_ParseTuple(args, "y*OO", &data, &read, &write)) return NULL;
    if (!write_to_buffer(&self->buf, data.buf, data.len)) return NULL;
    size_t pos = 0;
    Operation op = {0};
    while (pos < self->buf.len) {
        size_t consumed = unserialize_op(self->buf.data + pos, self->buf.len - pos, &op);
        if (!consumed) { break; }
        pos += consumed;
        if (!apply_op(self, op, read, write)) break;
    }
    shift_left(&self->buf, pos);
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
finish_delta_data(Patcher *self, PyObject *args UNUSED) {
    if (self->buf.len > 0) { PyErr_Format(RsyncError, "%zu bytes of unused delta data", self->buf.len); return NULL; }
    if (!self->checksum_done) { PyErr_SetString(RsyncError, "The checksum was not received at the end of the delta data"); return NULL; }
    Py_RETURN_NONE;
}

static PyObject*
Patcher_block_size(Patcher* self, void* closure UNUSED) { return PyLong_FromSize_t(self->rsync.block_size); }
static PyObject*
Patcher_total_data_in_delta(Patcher* self, void* closure UNUSED) { return PyLong_FromSize_t(self->total_data_in_delta); }

PyGetSetDef Patcher_getsets[] = {
    {"block_size", (getter)Patcher_block_size, NULL, NULL, NULL},
    {"total_data_in_delta", (getter)Patcher_total_data_in_delta, NULL, NULL, NULL},
    {NULL}
};


static PyMethodDef Patcher_methods[] = {
    METHODB(sign_block, METH_VARARGS),
    METHODB(signature_header, METH_O),
    METHODB(apply_delta_data, METH_VARARGS),
    METHODB(finish_delta_data, METH_NOARGS),
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
    .tp_getset = Patcher_getsets,
};
// }}} Patcher

// Differ {{{
typedef struct Signature { uint64_t index, strong_hash; } Signature;

typedef struct SignatureVal {
    Signature sig, *weak_hash_collisions;
    size_t len, cap;
} SignatureVal;
#define NAME SignatureMap
#define KEY_TY int
#define VAL_TY SignatureVal
static void free_signature_val(SignatureVal x) { free(x.weak_hash_collisions); }
#define VAL_DTOR_FN free_signature_val
#include "kitty-verstable.h"

typedef struct Differ {
    PyObject_HEAD
    rolling_checksum rc;
    uint64_t signature_idx;
    Rsync rsync;
    bool signature_header_parsed;
    buffer buf;
    SignatureMap signature_map;

    PyObject *read, *write;
    bool written, finished;
    struct { size_t pos, sz; } window, data;
    Operation pending_op; bool has_pending;
    uint8_t checksum[32];
} Differ;

static int
Differ_init(PyObject *s, PyObject *args, PyObject *kwds) {
    Differ *self = (Differ*)s;
    static char *kwlist[] = {NULL};
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "", kwlist)) return -1;
    const char *err = init_rsync(&self->rsync, default_block_size, 0, 0);
    if (err != NULL) { PyErr_SetString(RsyncError, err); return -1; }
    vt_init(&self->signature_map);
    return 0;
}

static void
Differ_dealloc(PyObject *self) {
    Differ *p = (Differ*)self;
    if (p->buf.data) free(p->buf.data);
    free_rsync(&p->rsync);
    vt_cleanup(&p->signature_map);
    Py_TYPE(self)->tp_free(self);
}

static void
parse_signature_header(Differ *self) {
    if (self->buf.len < 12) return;
    uint8_t *p = self->buf.data;
    uint32_t x;
    if ((x = le16dec(p)) != 0) {
        PyErr_Format(RsyncError, "Invalid version in signature header: %u", x); return;
    } p += 2;
    if ((x = le16dec(p)) != 0) {
        PyErr_Format(RsyncError, "Invalid checksum type in signature header: %u", x); return;
    } p += 2;
    if ((x = le16dec(p)) != 0) {
        PyErr_Format(RsyncError, "Invalid strong hash type in signature header: %u", x); return;
    } p += 2;
    if ((x = le16dec(p)) != 0) {
        PyErr_Format(RsyncError, "Invalid weak hash type in signature header: %u", x); return;
    } p += 2;
    const char *err = init_rsync(&self->rsync, le32dec(p), 0, 0);
    if (err != NULL) { PyErr_SetString(RsyncError, err); return; }
    p += 4;
    shift_left(&self->buf, p - self->buf.data);
    self->signature_header_parsed = true;
}

static bool
add_collision(SignatureVal *sm, Signature s) {
    if (sm->cap < sm->len + 1) {
        size_t new_cap = MAX(sm->cap * 2, 8u);
        sm->weak_hash_collisions = realloc(sm->weak_hash_collisions, new_cap * sizeof(sm->weak_hash_collisions[0]));
        if (!sm->weak_hash_collisions) { PyErr_NoMemory(); return false; }
        sm->cap = new_cap;
    }
    sm->weak_hash_collisions[sm->len++] = s;
    return true;
}

static size_t
parse_signature_block(Differ *self, uint8_t *data, size_t len) {
    if (len < 20) return 0;
    int weak_hash = le32dec(data + 8);
    SignatureMap_itr i = vt_get(&self->signature_map, weak_hash);
    if (vt_is_end(i)) {
        SignatureVal s = {0};
        s.sig.index = le64dec(data);
        s.sig.strong_hash = le64dec(data+12);
        vt_insert(&self->signature_map, weak_hash, s);
    } else {
        if (!add_collision(&i.data->val, (Signature){.index=le64dec(data), .strong_hash=le64dec(data+12)})) return 0;
    }
    return 20;
}

static PyObject*
add_signature_data(Differ *self, PyObject *args) {
    RAII_PY_BUFFER(data);
    if (!PyArg_ParseTuple(args, "y*", &data)) return NULL;
    if (!write_to_buffer(&self->buf, data.buf, data.len)) return NULL;
    if (!self->signature_header_parsed) {
        parse_signature_header(self);
        if (PyErr_Occurred()) return NULL;
        if (!self->signature_header_parsed) { Py_RETURN_NONE; }
    }
    size_t pos = 0;
    while (pos < self->buf.len) {
        size_t consumed = parse_signature_block(self, self->buf.data + pos, self->buf.len - pos);
        if (!consumed) { break; }
        pos += consumed;
    }
    shift_left(&self->buf, pos);
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
finish_signature_data(Differ *self, PyObject *args UNUSED) {
    if (self->buf.len > 0) { PyErr_Format(RsyncError, "%zu bytes of unused signature data", self->buf.len); return NULL; }
    self->buf.len = 0;
    self->buf.cap = 8 * self->rsync.block_size;
    self->buf.data = realloc(self->buf.data, self->buf.cap);
    if (!self->buf.data) return PyErr_NoMemory();
    Py_RETURN_NONE;
}

static bool
send_op(Differ *self, Operation *op) {
    uint8_t metadata[32];
    size_t len = 0;
    metadata[0] = op->type;
    switch (op->type) {
        case OpBlock:
            le64enc(metadata + 1, op->block_index);
            len = 9;
            break;
        case OpBlockRange:
            le64enc(metadata + 1, op->block_index);
            le32enc(metadata + 9, op->block_index_end - op->block_index);
            len = 13;
            break;
        case OpHash:
            le16enc(metadata + 1, op->data.len);
            memcpy(metadata + 3, op->data.buf, op->data.len);
            len = 3 + op->data.len;
            break;
        case OpData:
            le32enc(metadata + 1, op->data.len);
            len = 5;
            break;
    }
    RAII_PyObject(mv, PyMemoryView_FromMemory((char*)metadata, len, PyBUF_READ));
    RAII_PyObject(ret, PyObject_CallFunctionObjArgs(self->write, mv, NULL));
    if (ret == NULL) return false;
    if (op->type == OpData) {
        RAII_PyObject(mv, PyMemoryView_FromMemory((char*)op->data.buf, op->data.len, PyBUF_READ));
        RAII_PyObject(ret, PyObject_CallFunctionObjArgs(self->write, mv, NULL));
        if (ret == NULL) return false;
    }
    self->written = true;
    return true;
}

static bool
send_pending(Differ *self) {
    bool ret = true;
    if (self->has_pending) {
        ret = send_op(self, &self->pending_op);
        self->has_pending = false;
    }
    return ret;
}

static bool
send_data(Differ *self) {
    if (self->data.sz > 0) {
        if (!send_pending(self)) return false;
        Operation op = {.type=OpData};
        op.data.buf = self->buf.data + self->data.pos;
        op.data.len = self->data.sz;
        self->data.pos += self->data.sz;
        self->data.sz = 0;
        return send_op(self, &op);
    }
    return true;
}

static bool
ensure_idx_valid(Differ *self, size_t idx) {
    if (idx < self->buf.len) return true;
    if (idx >= self->buf.cap) {
		// need to wrap the buffer, so send off any data present behind the window
        if (!send_data(self)) return false;
		// copy the window and any data present after it to the start of the buffer
		size_t distance_from_window_pos = idx - self->window.pos;
		size_t amt_to_copy = self->buf.len - self->window.pos;
        memmove(self->buf.data, self->buf.data + self->window.pos, amt_to_copy);
        self->buf.len = amt_to_copy;
		self->window.pos = 0;
		self->data.pos = 0;
		return ensure_idx_valid(self, distance_from_window_pos);
    }
    RAII_PyObject(mv, PyMemoryView_FromMemory((char*)self->buf.data + self->buf.len, self->buf.cap - self->buf.len, PyBUF_WRITE));
    if (!mv) return false;
    RAII_PyObject(ret, PyObject_CallFunctionObjArgs(self->read, mv, NULL));
    if (!ret) return false;
    if (!PyLong_Check(ret)) { PyErr_SetString(PyExc_TypeError, "read callback did not return an integer"); return false; }
    size_t n = PyLong_AsSize_t(ret);
    self->rsync.checksummer.update(self->rsync.checksummer.state, self->buf.data + self->buf.len, n);
    self->buf.len += n;
    return self->buf.len > idx;
}

static bool
find_strong_hash(const SignatureVal *sm, uint64_t q, uint64_t *block_index) {
    if (sm->sig.strong_hash == q) { *block_index = sm->sig.index; return true; }
    for (size_t i = 0; i < sm->len; i++) {
        if (sm->weak_hash_collisions[i].strong_hash == q) { *block_index = sm->weak_hash_collisions[i].index; return true; }
    }
    return false;
}

static bool
enqueue(Differ *self, Operation op) {
    switch (op.type) {
        case OpBlock:
            if (self->has_pending) {
                switch (self->pending_op.type) {
                    case OpBlock:
                        if (self->pending_op.block_index+1 == op.block_index) {
                            self->pending_op.type = OpBlockRange;
                            self->pending_op.block_index_end = op.block_index;
                            return true;
                        }
                        break;
                    case OpBlockRange:
                        if (self->pending_op.block_index_end+1 == op.block_index) {
                            self->pending_op.block_index_end = op.block_index;
                            return true;
                        }
                    case OpHash: case OpData: break;
                }
                if (!send_pending(self)) return false;
            }
            self->pending_op = op;
            self->has_pending = true;
            return true;
        case OpHash:
            if (!send_pending(self)) return false;
            return send_op(self, &op);
        case OpBlockRange: case OpData:
            PyErr_SetString(RsyncError, "enqueue() must never be called with anything other than OpHash and OpBlock");
            return false;
    }
    return false;
}

static bool
finish_up(Differ *self) {
    if (!send_data(self)) return false;
    self->data.pos = self->window.pos;
	self->data.sz = self->buf.len - self->window.pos;
    if (!send_data(self)) return false;
    self->rsync.checksummer.digest(self->rsync.checksummer.state, self->checksum);
    Operation op = {.type=OpHash};
    op.data.buf = self->checksum; op.data.len = self->rsync.checksummer.hash_size;
    if (!enqueue(self, op)) return false;
    self->finished = true;
    return true;
}

static bool
read_next(Differ *self) {
    if (self->window.sz > 0) {
        if (!ensure_idx_valid(self, self->window.pos + self->window.sz)) {
            if (PyErr_Occurred()) return false;
            return finish_up(self);
        }
		self->window.pos++;
		self->data.sz++;
        rolling_checksum_add_one_byte(&self->rc, self->buf.data[self->window.pos], self->buf.data[self->window.pos + self->window.sz - 1]);
    } else {
        if (!ensure_idx_valid(self, self->window.pos + self->rsync.block_size - 1)) {
            if (PyErr_Occurred()) return false;
            return finish_up(self);
        }
		self->window.sz = self->rsync.block_size;
        rolling_checksum_full(&self->rc, self->buf.data + self->window.pos, self->window.sz);
    }
    int weak_hash = self->rc.val;
    uint64_t block_index = 0;
    SignatureMap_itr i = vt_get(&self->signature_map, weak_hash);
    if (!vt_is_end(i) && find_strong_hash(&i.data->val, self->rsync.hasher.oneshot64(self->buf.data + self->window.pos, self->window.sz), &block_index)) {
        if (!send_data(self)) return false;
        if (!enqueue(self, (Operation){.type=OpBlock, .block_index=block_index})) return false;
		self->window.pos += self->window.sz;
		self->data.pos = self->window.pos;
		self->window.sz = 0;
    }
    return true;
}

static PyObject*
next_op(Differ *self, PyObject *args) {
    if (!PyArg_ParseTuple(args, "OO", &self->read, &self->write)) return NULL;
    self->written = false;
    while (!self->written && !self->finished) {
        if (!read_next(self)) break;
    }
    if (self->finished && !PyErr_Occurred()) {
        send_pending(self);
    }
    self->read = NULL; self->write = NULL;
    if (PyErr_Occurred()) return NULL;
    if (self->finished) { Py_RETURN_FALSE; }
    Py_RETURN_TRUE;
}

static PyMethodDef Differ_methods[] = {
    METHODB(add_signature_data, METH_VARARGS),
    METHODB(finish_signature_data, METH_NOARGS),
    METHODB(next_op, METH_VARARGS),
    {NULL}  /* Sentinel */
};


PyTypeObject Differ_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "rsync.Differ",
    .tp_basicsize = sizeof(Differ),
    .tp_dealloc = Differ_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Differ",
    .tp_methods = Differ_methods,
    .tp_new = PyType_GenericNew,
    .tp_init = Differ_init,
};
// }}} Differ

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
    RAII_PY_BUFFER(data);
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
    RAII_PY_BUFFER(data);
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
    bytes_as_hex(digest, self->h.hash_size, hexdigest);
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

static bool
call_ftc_callback(PyObject *callback, char *src, Py_ssize_t key_start, Py_ssize_t key_length, Py_ssize_t val_start, Py_ssize_t val_length) {
    while(src[key_start] == ';' && key_length > 0 ) { key_start++; key_length--; }
    RAII_PyObject(k, PyMemoryView_FromMemory(src + key_start, key_length, PyBUF_READ));
    if (!k) return false;
    RAII_PyObject(v, PyMemoryView_FromMemory(src + val_start, val_length, PyBUF_READ));
    if (!v) return false;
    RAII_PyObject(ret, PyObject_CallFunctionObjArgs(callback, k, v, NULL));
    return ret != NULL;
}

static PyObject*
parse_ftc(PyObject *self UNUSED, PyObject *args) {
    RAII_PY_BUFFER(buf);
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

static PyObject*
pyxxh128_hash(PyObject *self UNUSED, PyObject *b) {
    RAII_PY_BUFFER(data);
    if (PyObject_GetBuffer(b, &data, PyBUF_SIMPLE) == -1) return NULL;
    XXH128_canonical_t c;
    XXH128_canonicalFromHash(&c, XXH3_128bits(data.buf, data.len));
    return PyBytes_FromStringAndSize((char*)c.digest, sizeof(c.digest));
}

static PyObject*
pyxxh128_hash_with_seed(PyObject *self UNUSED, PyObject *args) {
    RAII_PY_BUFFER(data);
    unsigned long long seed;
    if (!PyArg_ParseTuple(args, "y*K", &data, &seed)) return NULL;
    XXH128_canonical_t c;
    XXH128_canonicalFromHash(&c, XXH3_128bits_withSeed(data.buf, data.len, seed));
    return PyBytes_FromStringAndSize((char*)c.digest, sizeof(c.digest));
}


static PyMethodDef module_methods[] = {
    {"parse_ftc", parse_ftc, METH_VARARGS, ""},
    {"xxh128_hash", pyxxh128_hash, METH_O, ""},
    {"xxh128_hash_with_seed", pyxxh128_hash_with_seed, METH_VARARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static int
exec_module(PyObject *m) {
    RsyncError = PyErr_NewException("rsync.RsyncError", NULL, NULL);
    if (RsyncError == NULL) return -1;
    PyModule_AddObject(m, "RsyncError", RsyncError);
#define T(which) if (PyType_Ready(& which##_Type) < 0) return -1; Py_INCREF(&which##_Type);\
    if (PyModule_AddObject(m, #which, (PyObject *) &which##_Type) < 0) return -1;
    T(Hasher); T(Patcher); T(Differ);
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
