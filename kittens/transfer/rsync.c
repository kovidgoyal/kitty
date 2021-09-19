/*
 * rsync.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <librsync.h>

#define SIGNATURE_CAPSULE "rs_signature_t"
#define JOB_WITH_CALLBACK_CAPSULE "rs_callback_job_t"
// See whole.c in the librsync source code for estimating IO_BUFFER_SIZE
#define IO_BUFFER_SIZE (64u * 1024u)
static PyObject *RsyncError = NULL;

static void
free_job_with_callback_capsule(PyObject *capsule) {
    if (PyCapsule_IsValid(capsule, JOB_WITH_CALLBACK_CAPSULE)) {
        void *job = PyCapsule_GetPointer(capsule, JOB_WITH_CALLBACK_CAPSULE);
        if (job && job != RsyncError) rs_job_free(job);
        PyObject *callback = PyCapsule_GetContext(capsule);
        Py_CLEAR(callback);
    }
}

static void
free_sig_capsule(PyObject *capsule) {
    rs_signature_t *sig = PyCapsule_GetPointer(capsule, SIGNATURE_CAPSULE);
    if (sig) rs_free_sumset(sig);
}

#define CREATE_JOB(func, cb, ...) \
    PyObject *job_capsule = PyCapsule_New(RsyncError, JOB_WITH_CALLBACK_CAPSULE, free_job_with_callback_capsule); \
    if (job_capsule) { \
        rs_job_t *job = func(__VA_ARGS__); \
        if (job) { \
            if (PyCapsule_SetPointer(job_capsule, job) == 0) { \
                if (cb) { \
                    if (PyCapsule_SetContext(job_capsule, cb) == 0) { Py_INCREF(cb); } \
                    else { Py_CLEAR(job_capsule); } \
                } \
            } else { \
                rs_job_free(job); Py_CLEAR(job_capsule); \
            } \
        } else { \
            Py_CLEAR(job_capsule); \
        } \
    }


static PyObject*
begin_create_signature(PyObject *self UNUSED, PyObject *args) {
    long long file_size = -1;
    long sl = 0;
    if (!PyArg_ParseTuple(args, "|Ll", &file_size, &sl)) return NULL;
    rs_magic_number magic_number = 0;
    size_t block_len = 0, strong_len = sl;
#ifdef KITTY_HAS_RS_SIG_ARGS
    rs_result res = rs_sig_args(file_size, &magic_number, &block_len, &strong_len);
    if (res != RS_DONE) {
        PyErr_SetString(PyExc_ValueError, rs_strerror(res));
        return NULL;
    }
#endif
    CREATE_JOB(rs_sig_begin, NULL, block_len, strong_len, magic_number);
    return job_capsule;
}

#define GET_JOB_FROM_CAPSULE \
    rs_job_t *job = PyCapsule_GetPointer(job_capsule, JOB_WITH_CALLBACK_CAPSULE); \
    if (!job) { PyErr_SetString(PyExc_TypeError, "Not a job capsule"); return NULL; } \


#define FREE_BUFFER_AFTER_FUNCTION __attribute__((cleanup(PyBuffer_Release)))

static PyObject*
iter_job(PyObject *self UNUSED, PyObject *args) {
    FREE_BUFFER_AFTER_FUNCTION Py_buffer input_buf = {0};
    int eof = -1, expecting_output = 1;
    PyObject *job_capsule;
    if (!PyArg_ParseTuple(args, "O!y*|pp", &PyCapsule_Type, &job_capsule, &input_buf, &eof, &expecting_output)) return NULL;
    GET_JOB_FROM_CAPSULE;
    if (eof == -1) eof = input_buf.len > 0 ? 0 : 1;
    rs_buffers_t buffer = {
        .avail_in=input_buf.len, .next_in = input_buf.buf, .eof_in=eof,
        .avail_out=expecting_output ? IO_BUFFER_SIZE : 64
    };
    PyObject *ans = PyBytes_FromStringAndSize(NULL, buffer.avail_out);
    if (!ans) return NULL;
    buffer.next_out = PyBytes_AS_STRING(ans);
    size_t output_size = 0;
    rs_result result = RS_DONE;
    while (true) {
        size_t before = buffer.avail_out;
        result = rs_job_iter(job, &buffer);
        output_size += before - buffer.avail_out;
        if (result == RS_DONE || result == RS_BLOCKED) break;
        if (buffer.avail_in) {
            if (_PyBytes_Resize(&ans, MAX(IO_BUFFER_SIZE, (size_t)PyBytes_GET_SIZE(ans) * 2)) != 0) return NULL;
            buffer.avail_out = PyBytes_GET_SIZE(ans) - output_size;
            buffer.next_out = PyBytes_AS_STRING(ans) + output_size;
            continue;
        }
        Py_DECREF(ans);
        PyErr_SetString(RsyncError, rs_strerror(result));
        return NULL;
    }
    if ((ssize_t)output_size != PyBytes_GET_SIZE(ans)) {
        if (_PyBytes_Resize(&ans, output_size) != 0) return NULL;
    }
    Py_ssize_t unused_input = buffer.avail_in;
    return Py_BuildValue("NOn", ans, result == RS_DONE ? Py_True : Py_False, unused_input);
}

static PyObject*
begin_load_signature(PyObject *self UNUSED, PyObject *args UNUSED) {
    rs_signature_t *sig = NULL;
    CREATE_JOB(rs_loadsig_begin, NULL, &sig);
    if (!job_capsule) { rs_free_sumset(sig); return NULL; }
    PyObject *sc = PyCapsule_New(sig, SIGNATURE_CAPSULE, free_sig_capsule);
    if (!sc) { Py_CLEAR(job_capsule); rs_free_sumset(sig); return NULL; }
    return Py_BuildValue("NN", job_capsule, sc);
}

#define GET_SIG_FROM_CAPSULE \
    rs_signature_t *sig = PyCapsule_GetPointer(sig_capsule, SIGNATURE_CAPSULE); \
    if (!sig) { PyErr_SetString(PyExc_TypeError, "Not a sig capsule"); return NULL; }


static PyObject*
build_hash_table(PyObject *self UNUSED, PyObject *args) {
    PyObject *sig_capsule;
    if (!PyArg_ParseTuple(args, "O!y#|p", &PyCapsule_Type, &sig_capsule)) return NULL;
    GET_SIG_FROM_CAPSULE;
    rs_result res = rs_build_hash_table(sig);
    if (res != RS_DONE) {
        PyErr_SetString(RsyncError, rs_strerror(res));
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject*
begin_create_delta(PyObject *self UNUSED, PyObject *args) {
    PyObject *sig_capsule;
    if (!PyArg_ParseTuple(args, "O!", &PyCapsule_Type, &sig_capsule)) return NULL;
    GET_SIG_FROM_CAPSULE;
    CREATE_JOB(rs_delta_begin, NULL, sig);
    return job_capsule;
}

static rs_result
copy_callback(void *opaque, rs_long_t pos, size_t *len, void **buf) {
    PyObject *callback = opaque;
    long long p = pos;
    PyObject *mem = PyMemoryView_FromMemory(*buf, *len, PyBUF_WRITE);
    if (!mem) { PyErr_Clear(); return RS_MEM_ERROR; }
    PyObject *res = PyObject_CallFunction(callback, "OL", mem, p);
    Py_DECREF(mem);
    if (res == NULL) { PyErr_Clear(); return RS_IO_ERROR; }
    rs_result r = RS_DONE;
    if (PyLong_Check(res)) { *len = PyLong_AsSize_t(res); }
    else { r = RS_INTERNAL_ERROR; }
    Py_DECREF(res);
    return r;
}

static PyObject*
begin_patch(PyObject *self UNUSED, PyObject *callback) {
    if (!PyCallable_Check(callback)) { PyErr_SetString(PyExc_TypeError, "callback must be a callable"); return NULL; }
    CREATE_JOB(rs_patch_begin, callback, copy_callback, callback);
    return job_capsule;
}

static PyMethodDef module_methods[] = {
    {"begin_create_signature", begin_create_signature, METH_VARARGS, ""},
    {"begin_load_signature", begin_load_signature, METH_NOARGS, ""},
    {"build_hash_table", build_hash_table, METH_VARARGS, ""},
    {"begin_patch", begin_patch, METH_O, ""},
    {"begin_create_delta", begin_create_delta, METH_VARARGS, ""},
    {"iter_job", iter_job, METH_VARARGS, ""},
    {NULL, NULL, 0, NULL}        /* Sentinel */
};

static int
exec_module(PyObject *m) {
    RsyncError = PyErr_NewException("rsync.RsyncError", NULL, NULL);
    if (RsyncError == NULL) return -1;
    PyModule_AddObject(m, "RsyncError", RsyncError);


    PyModule_AddIntMacro(m, IO_BUFFER_SIZE);
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
