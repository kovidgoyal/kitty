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

#define EC_KEY_CAPSULE_NAME "EC-key-capsule"

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

static void
destroy_ec_key_capsule(PyObject *cap) {
    EVP_PKEY *key = PyCapsule_GetPointer(cap, EC_KEY_CAPSULE_NAME);
    if (key) EVP_PKEY_free(key);
}

static PyObject*
elliptic_curve_key_create(PyObject *self UNUSED, PyObject *args) {
    const char *curve_name = "X25519";
    if (!PyArg_ParseTuple(args, "|s", &curve_name)) return NULL;
    int nid = NID_X25519;
    if (strcmp(curve_name, "X25519") != 0) { PyErr_Format(PyExc_KeyError, "Unknown curve: %s", curve_name); return NULL; }
    EVP_PKEY *key = NULL;
    EVP_PKEY_CTX *pctx = NULL;
#define cleanup() { if (key) EVP_PKEY_free(key); key = NULL; if (pctx) EVP_PKEY_CTX_free(pctx); pctx = NULL; }
#define ssl_error(text) { cleanup(); return set_error_from_openssl(text); }

    if (NULL == (pctx = EVP_PKEY_CTX_new_id(nid, NULL))) ssl_error("Failed to create context for key generation");
    if(1 != EVP_PKEY_keygen_init(pctx)) ssl_error("Failed to initialize keygen context");
	if (1 != EVP_PKEY_keygen(pctx, &key)) ssl_error("Failed to generate key");

    PyObject *ans = PyCapsule_New(key, EC_KEY_CAPSULE_NAME, destroy_ec_key_capsule);
    if (ans) key = NULL;
    cleanup();
    return ans;
#undef cleanup
#undef ssl_error
}

static PyObject*
elliptic_curve_key_public(PyObject *self UNUSED, PyObject *key_capsule) {
    if (!PyCapsule_IsValid(key_capsule, EC_KEY_CAPSULE_NAME)) { PyErr_SetString(PyExc_TypeError, "Not a valid elliptic curve key capsule"); return NULL; }
    EVP_PKEY *pkey = PyCapsule_GetPointer(key_capsule, EC_KEY_CAPSULE_NAME);
    /* PEM_write_PUBKEY(stdout, pkey); */
    size_t len = 0;
    if (1 != EVP_PKEY_get_raw_public_key(pkey, NULL, &len)) return set_error_from_openssl("Could not get public key from EVP_KEY");
    PyObject *ans = PyBytes_FromStringAndSize(NULL, len);
    if (!ans) return NULL;
    if (1 != EVP_PKEY_get_raw_public_key(pkey, (unsigned char*)PyBytes_AS_STRING(ans), &len)) return set_error_from_openssl("Could not get public key from EVP_KEY");
    return ans;
}

static PyObject*
elliptic_curve_key_private(PyObject *self UNUSED, PyObject *key_capsule) {
    if (!PyCapsule_IsValid(key_capsule, EC_KEY_CAPSULE_NAME)) { PyErr_SetString(PyExc_TypeError, "Not a valid elliptic curve key capsule"); return NULL; }
    EVP_PKEY *pkey = PyCapsule_GetPointer(key_capsule, EC_KEY_CAPSULE_NAME);
    size_t len = 0;
    if (1 != EVP_PKEY_get_raw_private_key(pkey, NULL, &len)) return set_error_from_openssl("Could not get public key from EVP_KEY");
    PyObject *ans = PyBytes_FromStringAndSize(NULL, len);
    if (!ans) return NULL;
    if (1 != EVP_PKEY_get_raw_private_key(pkey, (unsigned char*)PyBytes_AS_STRING(ans), &len)) return set_error_from_openssl("Could not get public key from EVP_KEY");
    return ans;
}


static PyMethodDef module_methods[] = {
    METHODB(elliptic_curve_key_create, METH_VARARGS),
    METHODB(elliptic_curve_key_public, METH_O),
    METHODB(elliptic_curve_key_private, METH_O),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};


bool
init_crypto_library(PyObject *module) {
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    return true;
}
