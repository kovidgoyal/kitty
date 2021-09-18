/*
 * rsync.c
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include <librsync.h>

#define JOB_CAPSULE "rs_job_t"
#define SIGNATURE_CAPSULE "rs_signature_t"
#define IO_BUFFER_SIZE (64u * 1024u)
static PyObject *RsyncError = NULL;

static void
free_job_capsule(PyObject *capsule) {
    rs_job_t *job = PyCapsule_GetPointer(capsule, JOB_CAPSULE);
    if (job) rs_job_free(job);
}

static void
free_sig_capsule(PyObject *capsule) {
    rs_signature_t *sig = PyCapsule_GetPointer(capsule, SIGNATURE_CAPSULE);
    if (sig) rs_free_sumset(sig);
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
    rs_job_t *job = rs_sig_begin(block_len, strong_len, magic_number);
    if (!job) return PyErr_NoMemory();
    PyObject *ans = PyCapsule_New(job, JOB_CAPSULE, free_job_capsule);
    if (!ans) rs_job_free(job);
    return ans;
}

#define GET_JOB_FROM_CAPSULE \
    rs_job_t *job = PyCapsule_GetPointer(job_capsule, JOB_CAPSULE); \
    if (!job) { PyErr_SetString(PyExc_TypeError, "Not a job capsule"); return NULL; }

static PyObject*
iter_job(PyObject *self UNUSED, PyObject *args) {
    Py_ssize_t input_data_size;
    char *input_data;
    int eof = -1, expecting_output = 1;
    PyObject *job_capsule;
    if (!PyArg_ParseTuple(args, "O!y#|pp", &PyCapsule_Type, &job_capsule, &input_data, &input_data_size, &eof, expecting_output)) return NULL;
    GET_JOB_FROM_CAPSULE;
    if (eof == -1) eof = input_data_size > 0 ? 0 : 1;
    rs_buffers_t buffer = {
        .avail_in=input_data_size, .next_in = input_data, .eof_in=eof,
        .avail_out=expecting_output ? (MAX(IO_BUFFER_SIZE, 2 * (size_t)input_data_size)) : 64
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
    rs_job_t *job = rs_loadsig_begin(&sig);
    if (!sig || !job) return PyErr_NoMemory();
    PyObject *jc = PyCapsule_New(job, JOB_CAPSULE, free_job_capsule);
    if (!jc) { rs_job_free(job); rs_free_sumset(sig); return NULL; }
    PyObject *sc = PyCapsule_New(sig, SIGNATURE_CAPSULE, free_sig_capsule);
    if (!sc) { Py_DECREF(jc); rs_free_sumset(sig); return NULL; }
    return Py_BuildValue("NN", jc, sc);
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
    if (!PyArg_ParseTuple(args, "O!y#|p", &PyCapsule_Type, &sig_capsule)) return NULL;
    GET_SIG_FROM_CAPSULE;
    rs_job_t *job = rs_delta_begin(sig);
    if (!job) return PyErr_NoMemory();
    PyObject *ans = PyCapsule_New(job, JOB_CAPSULE, free_job_capsule);
    if (!ans) rs_job_free(job);
    return ans;
}


static PyMethodDef module_methods[] = {
    {"begin_create_signature", (PyCFunction)begin_create_signature, METH_VARARGS, ""},
    {"begin_load_signature", (PyCFunction)begin_load_signature, METH_NOARGS, ""},
    {"build_hash_table", (PyCFunction)build_hash_table, METH_VARARGS, ""},
    {"begin_create_delta", (PyCFunction)begin_create_delta, METH_VARARGS, ""},
    {"iter_job", (PyCFunction)iter_job, METH_VARARGS, ""},
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
