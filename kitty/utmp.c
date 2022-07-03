#include "data-types.h"
#if __has_include(<utmpx.h>)
#include <utmpx.h>
#include <signal.h>

static bool
pid_exists(pid_t pid) {
    if (pid < 1) return false;
    if (kill(pid, 0) >= 0) return true;
    return errno != ESRCH;
}

static PyObject*
num_users(PyObject *const self UNUSED, PyObject *const args UNUSED) {
    size_t users = 0;
    struct utmpx *ut;
    Py_BEGIN_ALLOW_THREADS
    setutxent();
    while ((ut = getutxent())) {
        if (ut->ut_type == USER_PROCESS && ut->ut_user[0] && pid_exists(ut->ut_pid)) users++;
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
