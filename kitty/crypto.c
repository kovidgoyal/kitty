/*
 * crypto.c
 * Copyright (C) 2022 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "cross-platform-random.h"

#include <openssl/evp.h>
#include <openssl/ec.h>
#include <openssl/err.h>
#include <openssl/pem.h>
#include <openssl/bio.h>
#include <openssl/rand.h>
#include <sys/mman.h>
#include <structmember.h>

#ifdef LIBRESSL_VERSION_NUMBER
/* from: https://github.com/libressl/portable/blob/master/include/compat/string.h#L63 */
#define explicit_bzero libressl_explicit_bzero
void explicit_bzero(void *, size_t);
/* from: https://github.com/libressl/portable/blob/master/crypto/compat/freezero.c */
void
freezero(void *ptr, size_t sz) {
    if (ptr == NULL) return;
    explicit_bzero(ptr, sz);
    free(ptr);
}
#define OPENSSL_clear_free freezero
#endif

#define SHA1_DIGEST_LENGTH SHA_DIGEST_LENGTH

typedef enum HASH_ALGORITHM { SHA1_HASH, SHA224_HASH, SHA256_HASH, SHA384_HASH, SHA512_HASH } HASH_ALGORITHM;
static PyObject* Crypto_Exception = NULL;

static PyObject*
set_error_from_openssl(const char *prefix) {
    BIO *bio = BIO_new(BIO_s_mem());
    ERR_print_errors(bio);
    char *buf = NULL;
    size_t len = BIO_get_mem_data(bio, &buf);
    PyObject *msg = PyUnicode_FromStringAndSize(buf, len);
    if (msg) PyErr_Format(Crypto_Exception, "%s: %U", prefix, msg);
    BIO_free(bio);
    Py_CLEAR(msg);
    return NULL;
}

// Secret {{{
typedef struct {
    PyObject_HEAD

    void *secret;
    size_t secret_len;
} Secret;

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
richcmp(PyObject *obj1, PyObject *obj2, int op);

static PyTypeObject Secret_Type = {
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
// }}}

// EllipticCurveKey {{{
typedef struct {
    PyObject_HEAD

    EVP_PKEY *key;
    int algorithm, nid;
} EllipticCurveKey;


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
    Secret *ans = alloc_secret(len);
    if (!ans) return NULL;
    if (mlock(PyBytes_AS_STRING(ans), len) != 0) { Py_CLEAR(ans); return PyErr_SetFromErrno(PyExc_OSError); }
    if (1 != EVP_PKEY_get_raw_private_key(self->key, (unsigned char*)ans->secret, &len)) { Py_CLEAR(ans); return set_error_from_openssl("Could not get public key from EVP_PKEY"); }
    return (PyObject*)ans;
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


static PyTypeObject EllipticCurveKey_Type = {
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
// }}}

// AES256GCMEncrypt {{{
typedef struct {
    PyObject_HEAD

    EVP_CIPHER_CTX *ctx;
    PyObject *iv, *tag;
    int state;
} AES256GCMEncrypt;

static PyObject *
new_aes256gcmencrypt(PyTypeObject *type, PyObject *args, PyObject *kwds UNUSED) {
    Secret *key;
    if (!PyArg_ParseTuple(args, "O!", &Secret_Type, &key)) return NULL;
    const EVP_CIPHER *cipher = EVP_get_cipherbynid(NID_aes_256_gcm);
    if (key->secret_len != (size_t)EVP_CIPHER_key_length(cipher)) { PyErr_Format(PyExc_ValueError, "The key for AES 256 GCM must be %d bytes long", EVP_CIPHER_key_length(cipher)); return NULL; }
    AES256GCMEncrypt *self = (AES256GCMEncrypt *)type->tp_alloc(type, 0);
    if (!self) return NULL;
    if (!(self->ctx = EVP_CIPHER_CTX_new())) { Py_CLEAR(self); return set_error_from_openssl("Failed to allocate encryption context"); }
    if (!(self->iv = PyBytes_FromStringAndSize(NULL, EVP_CIPHER_iv_length(cipher)))) { Py_CLEAR(self); return NULL; }
    if (!secure_random_bytes((unsigned char*)PyBytes_AS_STRING(self->iv), PyBytes_GET_SIZE(self->iv))) { Py_CLEAR(self); return NULL; }
    if (!(self->tag = PyBytes_FromStringAndSize(NULL, 0))) { Py_CLEAR(self); return NULL; }
    if (1 != EVP_EncryptInit_ex(self->ctx, cipher, NULL, key->secret, (const unsigned char*)PyBytes_AS_STRING(self->iv))) {
        Py_CLEAR(self); return set_error_from_openssl("Failed to initialize encryption context"); }
    return (PyObject*)self;
}

static void
dealloc_aes256gcmencrypt(AES256GCMEncrypt *self) {
    Py_CLEAR(self->iv); Py_CLEAR(self->tag);
    if (self->ctx) EVP_CIPHER_CTX_free(self->ctx);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
add_authenticated_but_unencrypted_data(AES256GCMEncrypt *self, PyObject *args) {
    if (self->state > 0) { PyErr_SetString(Crypto_Exception, "Cannot add data once encryption has started"); return NULL; }
    const char *aad; Py_ssize_t aad_len;
    if (!PyArg_ParseTuple(args, "y#", &aad, &aad_len)) return NULL;
    int len;
    if (aad_len > 0 && 1 != EVP_EncryptUpdate(self->ctx, NULL, &len, (const unsigned char*)aad, aad_len)) return set_error_from_openssl("Failed to add AAD data");
    Py_RETURN_NONE;
}

static int
cipher_ctx_tag_length(const EVP_CIPHER_CTX *ctx) {
#if OPENSSL_VERSION_NUMBER >= 0x30000000L
    return EVP_CIPHER_CTX_tag_length(ctx);
#else
    (void)ctx;
    return 16;
#endif
}

static PyObject*
add_data_to_be_encrypted(AES256GCMEncrypt *self, PyObject *args) {
    if (self->state > 1) { PyErr_SetString(Crypto_Exception, "Encryption has been finished"); return NULL; }
    const char *plaintext; Py_ssize_t plaintext_len;
    int finish_encryption = 0;
    if (!PyArg_ParseTuple(args, "y#|p", &plaintext, &plaintext_len, &finish_encryption)) return NULL;
    PyObject *ciphertext = PyBytes_FromStringAndSize(NULL, plaintext_len + 2 * EVP_CIPHER_CTX_block_size(self->ctx));
    if (!ciphertext) return NULL;
    self->state = 1;
    int offset = 0;
    if (plaintext_len) {
        int len = PyBytes_GET_SIZE(ciphertext);
        if (1 != EVP_EncryptUpdate(self->ctx, (unsigned char*)PyBytes_AS_STRING(ciphertext), &len, (const unsigned char*)plaintext, plaintext_len)
            ) { Py_CLEAR(ciphertext); return set_error_from_openssl("Failed to encrypt"); }
        offset = len;
    }
    if (finish_encryption) {
        int len = PyBytes_GET_SIZE(ciphertext) - offset;
        if (1 != EVP_EncryptFinal_ex(self->ctx, (unsigned char*)PyBytes_AS_STRING(ciphertext) + offset, &len)) {
            Py_CLEAR(ciphertext); return set_error_from_openssl("Failed to finish encryption"); }
        offset += len;
        self->state = 2;

        PyObject *tag = PyBytes_FromStringAndSize(NULL, cipher_ctx_tag_length(self->ctx));
        if (!tag) { Py_CLEAR(ciphertext); return NULL; }
        Py_CLEAR(self->tag); self->tag = tag;
        if (1 != EVP_CIPHER_CTX_ctrl(self->ctx, EVP_CTRL_AEAD_GET_TAG, PyBytes_GET_SIZE(self->tag), PyBytes_AS_STRING(tag))) {
            Py_CLEAR(ciphertext); return NULL;
        }
    }
    if (offset != PyBytes_GET_SIZE(ciphertext)) { _PyBytes_Resize(&ciphertext, offset); if (!ciphertext) return NULL; }
    return ciphertext;
}

static PyMethodDef aes256gcmencrypt_methods[] = {
    METHODB(add_authenticated_but_unencrypted_data, METH_VARARGS),
    METHODB(add_data_to_be_encrypted, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static PyMemberDef aes256gcmencrypt_members[] = {
    {"iv", T_OBJECT_EX, offsetof(AES256GCMEncrypt, iv), READONLY, "IV"},
    {"tag", T_OBJECT_EX, offsetof(AES256GCMEncrypt, tag), READONLY, "The tag for authentication"},
    {NULL}
};

static PyTypeObject AES256GCMEncrypt_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.AES256GCMEncrypt",
    .tp_basicsize = sizeof(AES256GCMEncrypt),
    .tp_dealloc = (destructor)dealloc_aes256gcmencrypt,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Encrypt using AES 256 GCM with authentication",
    .tp_new = new_aes256gcmencrypt,
    .tp_methods = aes256gcmencrypt_methods,
    .tp_members = aes256gcmencrypt_members,
};

// }}}

// AES256GCMDecrypt {{{
typedef struct {
    PyObject_HEAD

    EVP_CIPHER_CTX *ctx;
    int state;
} AES256GCMDecrypt;

static PyObject *
new_aes256gcmdecrypt(PyTypeObject *type, PyObject *args, PyObject *kwds UNUSED) {
    Secret *key; unsigned char *iv, *tag; Py_ssize_t iv_len, tag_len;
    if (!PyArg_ParseTuple(args, "O!y#y#", &Secret_Type, &key, &iv, &iv_len, &tag, &tag_len)) return NULL;
    const EVP_CIPHER *cipher = EVP_get_cipherbynid(NID_aes_256_gcm);
    if (key->secret_len != (size_t)EVP_CIPHER_key_length(cipher)) { PyErr_Format(PyExc_ValueError, "The key for AES 256 GCM must be %d bytes long", EVP_CIPHER_key_length(cipher)); return NULL; }
    if (iv_len < EVP_CIPHER_iv_length(cipher)) { PyErr_Format(PyExc_ValueError, "The iv for AES 256 GCM must be at least %d bytes long", EVP_CIPHER_iv_length(cipher)); return NULL; }
    AES256GCMDecrypt *self = (AES256GCMDecrypt *)type->tp_alloc(type, 0);
    if (!self) return NULL;
    if (!(self->ctx = EVP_CIPHER_CTX_new())) { Py_CLEAR(self); return set_error_from_openssl("Failed to allocate decryption context"); }
    if (iv_len > EVP_CIPHER_iv_length(cipher)) {
        if (!EVP_CIPHER_CTX_ctrl(self->ctx, EVP_CTRL_GCM_SET_IVLEN, iv_len, NULL)) { Py_CLEAR(self); return set_error_from_openssl("Failed to set the IV length"); }
    }
    if (1 != EVP_DecryptInit_ex(self->ctx, cipher, NULL, key->secret, iv)) {
        Py_CLEAR(self); return set_error_from_openssl("Failed to initialize encryption context"); }
    // Ensure tag length is 16 because the OpenSSL verification routines will happily pass even if you set a truncated tag.
    if (tag_len < cipher_ctx_tag_length(self->ctx)) { PyErr_Format(PyExc_ValueError, "Tag length for AES 256 GCM must be at least %d", cipher_ctx_tag_length(self->ctx)); return NULL; }
    if (!EVP_CIPHER_CTX_ctrl(self->ctx, EVP_CTRL_AEAD_SET_TAG, tag_len, tag)) { Py_CLEAR(self); return set_error_from_openssl("Failed to set the tag"); }

    return (PyObject*)self;
}

static void
dealloc_aes256gcmdecrypt(AES256GCMDecrypt *self) {
    if (self->ctx) EVP_CIPHER_CTX_free(self->ctx);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static PyObject*
add_data_to_be_authenticated_but_not_decrypted(AES256GCMDecrypt *self, PyObject *args) {
    if (self->state > 0) { PyErr_SetString(Crypto_Exception, "Cannot add data once decryption has started"); return NULL; }
    const char *aad; Py_ssize_t aad_len;
    if (!PyArg_ParseTuple(args, "y#", &aad, &aad_len)) return NULL;
    int len;
    if (aad_len > 0 && 1 != EVP_DecryptUpdate(self->ctx, NULL, &len, (const unsigned char*)aad, aad_len)) return set_error_from_openssl("Failed to add AAD data");
    Py_RETURN_NONE;
}

static PyObject*
add_data_to_be_decrypted(AES256GCMDecrypt *self, PyObject *args) {
    if (self->state > 1) { PyErr_SetString(Crypto_Exception, "Decryption has been finished"); return NULL; }
    const char *ciphertext; Py_ssize_t ciphertext_len;
    int finish_decryption = 0;
    if (!PyArg_ParseTuple(args, "y#|p", &ciphertext, &ciphertext_len, &finish_decryption)) return NULL;
    PyObject *plaintext = PyBytes_FromStringAndSize(NULL, ciphertext_len + 2 * EVP_CIPHER_CTX_block_size(self->ctx));
    if (!plaintext) return NULL;
    self->state = 1;
    int offset = 0;
    if (ciphertext_len) {
        int len = PyBytes_GET_SIZE(plaintext);
        if (1 != EVP_DecryptUpdate(self->ctx, (unsigned char*)PyBytes_AS_STRING(plaintext), &len, (const unsigned char*)ciphertext, ciphertext_len)
            ) { Py_CLEAR(plaintext); return set_error_from_openssl("Failed to decrypt"); }
        offset = len;
    }
    if (finish_decryption) {
        int len = PyBytes_GET_SIZE(plaintext) - offset;
        int ret = EVP_DecryptFinal_ex(self->ctx, (unsigned char*)PyBytes_AS_STRING(plaintext) + offset, &len);
        self->state = 2;
        if (ret <= 0) { Py_CLEAR(plaintext); PyErr_SetString(Crypto_Exception, "Failed to finish decrypt"); return NULL; }
        offset += len;
    }
    if (offset != PyBytes_GET_SIZE(plaintext)) { _PyBytes_Resize(&plaintext, offset); if (!plaintext) return NULL; }
    return plaintext;
}

static PyMethodDef aes256gcmdecrypt_methods[] = {
    METHODB(add_data_to_be_authenticated_but_not_decrypted, METH_VARARGS),
    METHODB(add_data_to_be_decrypted, METH_VARARGS),
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static PyTypeObject AES256GCMDecrypt_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.AES256GCMDecrypt",
    .tp_basicsize = sizeof(AES256GCMDecrypt),
    .tp_dealloc = (destructor)dealloc_aes256gcmdecrypt,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Decrypt using AES 256 GCM with authentication",
    .tp_new = new_aes256gcmdecrypt,
    .tp_methods = aes256gcmdecrypt_methods,
};

// }}}

static PyMethodDef module_methods[] = {
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

bool
init_crypto_library(PyObject *module) {
    Crypto_Exception = PyErr_NewException("fast_data_types.CryptoError", NULL, NULL);
    if (Crypto_Exception == NULL) return false;
    if (PyModule_AddObject(module, "CryptoError", Crypto_Exception) != 0) return false;
    if (PyModule_AddFunctions(module, module_methods) != 0) return false;
    ADD_TYPE(Secret); ADD_TYPE(EllipticCurveKey); ADD_TYPE(AES256GCMEncrypt); ADD_TYPE(AES256GCMDecrypt);
    if (PyModule_AddIntConstant(module, "X25519", EVP_PKEY_X25519) != 0) return false;
#define AI(which) if (PyModule_AddIntMacro(module, which) != 0) return false;
    AI(SHA1_HASH); AI(SHA224_HASH); AI(SHA256_HASH); AI(SHA384_HASH); AI(SHA512_HASH);
#undef AI
    return true;
}
