#if defined(__unix__)

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <stdbool.h>

#include <utmp.h>

static PyObject*
num_users(PyObject *const self, PyObject *const args) {
    (void)self; (void)args;
    size_t users = 0;
    Py_BEGIN_ALLOW_THREADS
#ifdef UTENT_REENTRANT
    struct utmp *result = NULL;
    struct utmp buffer = { 0, };
    while (true) {
        if (getutent_r(&buffer, &result) == -1) {
            Py_BLOCK_THREADS
            return PyErr_SetFromErrno(PyExc_OSError);
        }
        if (result == NULL) { break; }
        if (result->ut_type == USER_PROCESS) { users++; }
    }
#else
    struct utmp *ut;
    setutent();
    while ((ut = getutent())) {
        if (ut->ut_type == USER_PROCESS) {
            users++;
        }
    }
    endutent();
#endif
    Py_END_ALLOW_THREADS
    return PyLong_FromSize_t(users);
}

static PyMethodDef UtmpMethods[] = {
    {"num_users", num_users, METH_NOARGS, "Get the number of users using UTMP data" },
    { NULL, NULL, 0, NULL },
};

bool
init_utmp(PyObject *module) {
    // 0 = success
    return PyModule_AddFunctions(module, UtmpMethods) == 0;
}

#endif
