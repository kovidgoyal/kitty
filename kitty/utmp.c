
#include "data-types.h"
#ifdef __unix__
#include <utmpx.h>

static PyObject*
num_users(PyObject *const self UNUSED, PyObject *const args UNUSED) {
    size_t users = 0;
    struct utmpx *ut;
    Py_BEGIN_ALLOW_THREADS
    setutxent();
    while ((ut = getutxent())) {
        if (ut->ut_type == USER_PROCESS) users++;
    }
    endutxent();
    Py_END_ALLOW_THREADS
    return PyLong_FromSize_t(users);
}
#else
static PyObject*
num_users(PyObject *const self UNUSED, PyObject *const args UNUSED) {
    PyErr_SetString(PyExc_RuntimeError, "Counting the number of users is not supported");
    return NULL;
}
#endif

static PyMethodDef methods[] = {
    {"num_users", num_users, METH_NOARGS, "Get the number of users using UTMP data" },
    { NULL, NULL, 0, NULL },
};

bool
init_utmp(PyObject *module) {
    return PyModule_AddFunctions(module, methods) == 0;
}
