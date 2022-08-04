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

typedef struct {
    PyObject_HEAD

    EVP_PKEY *key;
} EllipticCurveKey;


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
new_ec_key(PyTypeObject *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    EllipticCurveKey *self;
    static const char* kwlist[] = {"curve_name", NULL};
    const char *curve_name = "X25519";
    if (!PyArg_ParseTupleAndKeywords(args, kwds, "|s", (char**)kwlist, &curve_name)) return NULL;
    int nid = NID_X25519;
    if (strcmp(curve_name, "X25519") != 0) { PyErr_Format(PyExc_KeyError, "Unknown curve: %s", curve_name); return NULL; }
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


PyTypeObject EllipticCurveKey_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.EllipticCurveKey",
    .tp_basicsize = sizeof(EllipticCurveKey),
    .tp_dealloc = (destructor)dealloc_ec_key,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Keys for use with Elliptic Curve crypto",
    .tp_new = new_ec_key,
    .tp_getset = getsetters,
};


static PyMethodDef module_methods[] = {
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_crypto_library(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    if (PyType_Ready(&EllipticCurveKey_Type) < 0) return false;
    if (PyModule_AddObject(module, "EllipticCurveKey", (PyObject *)&EllipticCurveKey_Type) != 0) return false;
    Py_INCREF(&EllipticCurveKey_Type);
    return true;
}
