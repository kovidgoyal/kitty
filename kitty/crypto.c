/*
 * crypto.c
 * Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

#include <openssl/evp.h>
#include <openssl/ec.h>
#include <openssl/err.h>
#include <openssl/pem.h>
#include <openssl/bio.h>
#include <sys/mman.h>

#define SHA1_DIGEST_LENGTH SHA_DIGEST_LENGTH

typedef enum HASH_ALGORITHM { SHA1_HASH, SHA224_HASH, SHA256_HASH, SHA384_HASH, SHA512_HASH } HASH_ALGORITHM;

typedef struct {
    PyObject_HEAD

    EVP_PKEY *key;
    int algorithm, nid;
} EllipticCurveKey;

typedef struct {
    PyObject_HEAD

    void *secret;
    size_t secret_len;
} Secret;


static PyObject*
set_error_from_openssl(const char *prefix) {
    BIO *bio = BIO_new(BIO_s_mem());
    ERR_print_errors(bio);
    char *buf = NULL;
    size_t len = BIO_get_mem_data(bio, &buf);
    PyObject *msg = PyUnicode_FromStringAndSize(buf, len);
    if (msg) PyErr_Format(PyExc_ValueError, "%s: %U", prefix, msg);
    BIO_free(bio);
    Py_CLEAR(msg);
    return NULL;
}


static PyObject *
new_secret(PyTypeObject *type UNUSED, PyObject *args UNUSED, PyObject *kwds UNUSED) {
    PyErr_SetString(PyExc_TypeError, "Cannot create Secret objects directly"); return NULL;
}

static Secret* alloc_secret(size_t len);

static void
dealloc_secret(Secret *self) {
    if (self->secret) OPENSSL_clear_free(self->secret, self->secret_len);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static int
__eq__(Secret *a, Secret *b) {
    const size_t l = a->secret_len < b->secret_len ? a->secret_len : b->secret_len;
    return memcmp(a->secret, b->secret, l) == 0;
}

static Py_ssize_t
__len__(PyObject *self) {
    return (Py_ssize_t)(((Secret*)self)->secret_len);
}


static PySequenceMethods sequence_methods = {
    .sq_length = __len__,
};


static PyObject *
new_ec_key(PyTypeObject *type, PyObject *args, PyObject *kwds) {
    EllipticCurveKey *self;
    static const char* kwlist[] = {"algorithm", NULL};
    int algorithm = EVP_PKEY_X25519, nid = NID_X25519;
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|i", (char**)kwlist, &algorithm)) return NULL;
    switch(algorithm) {
        case EVP_PKEY_X25519: break;
        default: PyErr_SetString(PyExc_KeyError, "Unknown algorithm"); return NULL;
    }
    EVP_PKEY *key = NULL;
    EVP_PKEY_CTX *pctx = NULL;
#define cleanup() { if (key) EVP_PKEY_free(key); key = NULL; if (pctx) EVP_PKEY_CTX_free(pctx); pctx = NULL; }
#define ssl_error(text) { cleanup(); return set_error_from_openssl(text); }

    if (NULL == (pctx = EVP_PKEY_CTX_new_id(nid, NULL))) ssl_error("Failed to create context for key generation");
    if(1 != EVP_PKEY_keygen_init(pctx)) ssl_error("Failed to initialize keygen context");
	if (1 != EVP_PKEY_keygen(pctx, &key)) ssl_error("Failed to generate key");

    self = (EllipticCurveKey *)type->tp_alloc(type, 0);
    if (self) {
        self->key = key; key = NULL;
        self->nid = nid; self->algorithm = algorithm;
    }
    cleanup();
    return (PyObject*) self;
#undef cleanup
#undef ssl_error
}

static void
dealloc_ec_key(EllipticCurveKey* self) {
    if (self->key) EVP_PKEY_free(self->key);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
hash_data_to_secret(const unsigned char *data, size_t len, int hash_algorithm) {
    size_t hash_size;
#define H(which) case which##_HASH: hash_size = which##_DIGEST_LENGTH; break;
    switch (hash_algorithm) {
        H(SHA1) H(SHA224) H(SHA256) H(SHA384) H(SHA512)
        default: PyErr_Format(PyExc_KeyError, "Unknown hash algorithm: %d", hash_algorithm); return NULL;
    }
#undef H
    Secret *ans = alloc_secret(hash_size);
    if (!ans) return NULL;
#define H(which) case which##_HASH: if (which(data, len, ans->secret) == NULL) { Py_CLEAR(ans); return set_error_from_openssl("Failed to " #which); } break;
    switch ((HASH_ALGORITHM)hash_algorithm) { H(SHA1) H(SHA224) H(SHA256) H(SHA384) H(SHA512) }
#undef H
    return (PyObject*)ans;
}

static PyObject*
derive_secret(EllipticCurveKey *self, PyObject *args) {
    const char *pubkey_raw;
    int hash_algorithm = SHA256_HASH;
    Py_ssize_t pubkey_len;
    if (!PyArg_ParseTuple(args, "y#|i", &pubkey_raw, &pubkey_len, &hash_algorithm)) return NULL;

    EVP_PKEY_CTX *ctx = NULL;
    unsigned char *secret = NULL; size_t secret_len = 0;
    EVP_PKEY *public_key = EVP_PKEY_new_raw_public_key(self->algorithm, NULL, (const unsigned char*)pubkey_raw, pubkey_len);
#define cleanup() { if (public_key) EVP_PKEY_free(public_key); public_key = NULL; if (ctx) EVP_PKEY_CTX_free(ctx); ctx = NULL; if (secret) OPENSSL_clear_free(secret, secret_len); secret = NULL; }
#define ssl_error(text) { cleanup(); return set_error_from_openssl(text); }
    if (!public_key) ssl_error("Failed to create public key");

    if (NULL == (ctx = EVP_PKEY_CTX_new(self->key, NULL))) ssl_error("Failed to create context for shared secret derivation");
    if (1 != EVP_PKEY_derive_init(ctx)) ssl_error("Failed to initialize derivation");
    if (1 != EVP_PKEY_derive_set_peer(ctx, public_key)) ssl_error("Failed to add public key");

    if (1 != EVP_PKEY_derive(ctx, NULL, &secret_len)) ssl_error("Failed to get length for secret");
    if (NULL == (secret = OPENSSL_malloc(secret_len))) ssl_error("Failed to allocate secret key");
    if (mlock(secret, secret_len) != 0) { cleanup(); return PyErr_SetFromErrno(PyExc_OSError); }
    if (1 != (EVP_PKEY_derive(ctx, secret, &secret_len))) ssl_error("Failed to derive the secret");

    PyObject *ans = hash_data_to_secret(secret, secret_len, hash_algorithm);
    cleanup();
    return ans;
#undef cleanup
#undef ssl_error
}


static PyObject*
elliptic_curve_key_get_public(EllipticCurveKey *self, void UNUSED *closure) {
    /* PEM_write_PUBKEY(stdout, pkey); */
    size_t len = 0;
    if (1 != EVP_PKEY_get_raw_public_key(self->key, NULL, &len)) return set_error_from_openssl("Could not get public key from EVP_PKEY");
    PyObject *ans = PyBytes_FromStringAndSize(NULL, len);
    if (!ans) return NULL;
    if (1 != EVP_PKEY_get_raw_public_key(self->key, (unsigned char*)PyBytes_AS_STRING(ans), &len)) { Py_CLEAR(ans); return set_error_from_openssl("Could not get public key from EVP_PKEY"); }
    return ans;

}


static PyObject*
elliptic_curve_key_get_private(EllipticCurveKey *self, void UNUSED *closure) {
    size_t len = 0;
    if (1 != EVP_PKEY_get_raw_private_key(self->key, NULL, &len)) return set_error_from_openssl("Could not get public key from EVP_PKEY");
    PyObject *ans = PyBytes_FromStringAndSize(NULL, len);
    if (!ans) return NULL;
    if (mlock(PyBytes_AS_STRING(ans), len) != 0) { Py_CLEAR(ans); return PyErr_SetFromErrno(PyExc_OSError); }
    if (1 != EVP_PKEY_get_raw_private_key(self->key, (unsigned char*)PyBytes_AS_STRING(ans), &len)) { Py_CLEAR(ans); return set_error_from_openssl("Could not get public key from EVP_PKEY"); }
    return ans;

}


static PyGetSetDef getsetters[] = {
    {"public", (getter)elliptic_curve_key_get_public, NULL, "Get the public key as raw bytes", NULL},
    {"private", (getter)elliptic_curve_key_get_private, NULL, "Get the private key as raw bytes", NULL},
    {NULL}  /* Sentinel */
};

static PyMethodDef methods[] = {
    METHODB(derive_secret, METH_VARARGS),
    {NULL}  /* Sentinel */
};


PyTypeObject EllipticCurveKey_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.EllipticCurveKey",
    .tp_basicsize = sizeof(EllipticCurveKey),
    .tp_dealloc = (destructor)dealloc_ec_key,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Keys for use with Elliptic Curve crypto",
    .tp_new = new_ec_key,
    .tp_methods = methods,
    .tp_getset = getsetters,
};


static PyObject *
richcmp(PyObject *obj1, PyObject *obj2, int op);

PyTypeObject Secret_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Secret",
    .tp_basicsize = sizeof(Secret),
    .tp_dealloc = (destructor)dealloc_secret,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Secure storage for secrets",
    .tp_new = new_secret,
    .tp_richcompare = richcmp,
    .tp_as_sequence = &sequence_methods,
};

RICHCMP(Secret)

static PyMethodDef module_methods[] = {
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static Secret*
alloc_secret(size_t len) {
    Secret *self = (Secret*)Secret_Type.tp_alloc(&Secret_Type, 0);
    if (self) {
        self->secret_len = len;
        if (NULL == (self->secret = OPENSSL_malloc(len))) { Py_CLEAR(self); return (Secret*)set_error_from_openssl("Failed to malloc"); }
        if (0 != mlock(self->secret, self->secret_len)) { Py_CLEAR(self); return (Secret*)PyErr_SetFromErrno(PyExc_OSError); }
    }
    return self;
}

bool
init_crypto_library(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (PyType_Ready(&EllipticCurveKey_Type) < 0) return false;
    if (PyModule_AddObject(module, "EllipticCurveKey", (PyObject *)&EllipticCurveKey_Type) != 0) return false;
    if (PyType_Ready(&Secret_Type) < 0) return false;
    if (PyModule_AddObject(module, "Secret", (PyObject *)&EllipticCurveKey_Type) != 0) return false;
    if (PyModule_AddIntConstant(module, "X25519", EVP_PKEY_X25519) != 0) return false;
    if (PyModule_AddIntMacro(module, SHA1_HASH) != 0) return false;
    if (PyModule_AddIntMacro(module, SHA224_HASH) != 0) return false;
    if (PyModule_AddIntMacro(module, SHA256_HASH) != 0) return false;
    if (PyModule_AddIntMacro(module, SHA384_HASH) != 0) return false;
    if (PyModule_AddIntMacro(module, SHA512_HASH) != 0) return false;
    Py_INCREF(&EllipticCurveKey_Type);
    return true;
}
