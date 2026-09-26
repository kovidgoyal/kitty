/*
 * amoeba.c
 * Copyright (C) 2026 kitty contributors
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wfloat-conversion"
#define AM_USE_DOUBLE
#define AM_STATIC_API
#include "../3rdparty/amoeba/amoeba.h"
#pragma GCC diagnostic pop

typedef struct {
    PyObject_HEAD am_Solver *solver;
    am_Num **values;
    size_t values_capacity;
} AmoebaSolver;

static PyObject *AmoebaError;

static int
set_amoeba_error(const char *operation, int status) {
    const char *detail = "unknown error";
    switch (status) {
        case AM_FAILED: detail = "invalid operation"; break;
        case AM_UNSATISFIED: detail = "unsatisfied constraint"; break;
        case AM_UNBOUND: detail = "unbound constraint"; break;
    }
    PyErr_Format(AmoebaError, "%s failed: %s (%d)", operation, detail, status);
    return -1;
}

static bool
ensure_values_capacity(AmoebaSolver *self, am_Id variable) {
    if (variable < self->values_capacity) return true;
    size_t capacity = self->values_capacity ? self->values_capacity : 8;
    while (capacity <= variable) {
        if (capacity > SIZE_MAX / 2) {
            PyErr_NoMemory();
            return false;
        }
        capacity *= 2;
    }
    am_Num **values = PyMem_Realloc(self->values, capacity * sizeof(*values));
    if (values == NULL) {
        PyErr_NoMemory();
        return false;
    }
    memset(values + self->values_capacity, 0, (capacity - self->values_capacity) * sizeof(*values));
    self->values = values;
    self->values_capacity = capacity;
    return true;
}

static bool
variable_from_python(AmoebaSolver *self, PyObject *obj, am_Id *variable) {
    unsigned long value = PyLong_AsUnsignedLong(obj);
    if (value == (unsigned long)-1 && PyErr_Occurred()) return false;
    if (value > UINT_MAX || value >= self->values_capacity || self->values[value] == NULL || am_refcount(self->solver, (am_Id)value) == 0) {
        PyErr_SetString(PyExc_ValueError, "invalid Amoeba variable");
        return false;
    }
    *variable = (am_Id)value;
    return true;
}

static PyObject *
AmoebaSolver_new(PyTypeObject *type, PyObject *args, PyObject *kwds) {
    if (PyTuple_GET_SIZE(args) || (kwds && PyDict_GET_SIZE(kwds))) {
        PyErr_SetString(PyExc_TypeError, "AmoebaSolver() takes no arguments");
        return NULL;
    }
    AmoebaSolver *self = (AmoebaSolver *)type->tp_alloc(type, 0);
    if (self == NULL) return NULL;
    self->solver = am_newsolver(NULL, NULL);
    if (self->solver == NULL) {
        Py_DECREF(self);
        return PyErr_NoMemory();
    }
    return (PyObject *)self;
}

static void
AmoebaSolver_dealloc(AmoebaSolver *self) {
    if (self->solver) am_delsolver(self->solver);
    for (size_t i = 0; i < self->values_capacity; i++) PyMem_Free(self->values[i]);
    PyMem_Free(self->values);
    Py_TYPE(self)->tp_free((PyObject *)self);
}

static PyObject *
AmoebaSolver_add_variable(AmoebaSolver *self, PyObject *Py_UNUSED(arg)) {
    am_Num *value = PyMem_Calloc(1, sizeof(*value));
    if (value == NULL) return PyErr_NoMemory();
    am_Id variable = am_newvariable(self->solver, value);
    if (variable == 0) {
        PyMem_Free(value);
        return PyErr_NoMemory();
    }
    if (!ensure_values_capacity(self, variable)) {
        am_delvariable(self->solver, variable);
        PyMem_Free(value);
        return NULL;
    }
    self->values[variable] = value;
    return PyLong_FromUnsignedLong(variable);
}

static int
relation_from_string(const char *relation) {
    if (strcmp(relation, "==") == 0) return AM_EQUAL;
    if (strcmp(relation, "<=") == 0) return AM_LESSEQUAL;
    if (strcmp(relation, ">=") == 0) return AM_GREATEQUAL;
    PyErr_SetString(PyExc_ValueError, "relation must be one of: ==, <=, >=");
    return 0;
}

static PyObject *
AmoebaSolver_add_constraint(AmoebaSolver *self, PyObject *args) {
    PyObject *terms_obj;
    const char *relation_string;
    double constant, strength = AM_REQUIRED;
    if (!PyArg_ParseTuple(args, "Osd|d:add_constraint", &terms_obj, &relation_string, &constant, &strength)) return NULL;
    if (!isfinite(constant) || isnan(strength) || strength < 0.) {
        PyErr_SetString(PyExc_ValueError, "constraint constant and strength must be valid numbers");
        return NULL;
    }
    int relation = relation_from_string(relation_string);
    if (relation == 0) return NULL;
    RAII_PyObject(terms, PySequence_Fast(terms_obj, "constraint terms must be a sequence"));
    if (terms == NULL) return NULL;

    am_Constraint *constraint = am_newconstraint(self->solver, (am_Num)strength);
    if (constraint == NULL) {
        PyErr_SetString(PyExc_ValueError, "invalid constraint strength");
        return NULL;
    }
    for (Py_ssize_t i = 0; i < PySequence_Fast_GET_SIZE(terms); i++) {
        RAII_PyObject(term, PySequence_Fast(PySequence_Fast_GET_ITEM(terms, i), "each constraint term must be a pair"));
        if (term == NULL) goto error;
        if (PySequence_Fast_GET_SIZE(term) != 2) {
            PyErr_SetString(PyExc_ValueError, "each constraint term must contain a variable and coefficient");
            goto error;
        }
        am_Id variable;
        if (!variable_from_python(self, PySequence_Fast_GET_ITEM(term, 0), &variable)) goto error;
        double coefficient = PyFloat_AsDouble(PySequence_Fast_GET_ITEM(term, 1));
        if (PyErr_Occurred()) goto error;
        if (!isfinite(coefficient)) {
            PyErr_SetString(PyExc_ValueError, "constraint coefficients must be finite");
            goto error;
        }
        int status = am_addterm(constraint, variable, (am_Num)coefficient);
        if (status != AM_OK) {
            set_amoeba_error("adding a constraint term", status);
            goto error;
        }
    }
    int status = am_setrelation(constraint, relation);
    if (status == AM_OK) status = am_addconstant(constraint, (am_Num)constant);
    if (status == AM_OK) status = am_add(constraint);
    if (status != AM_OK) {
        set_amoeba_error("adding a constraint", status);
        goto error;
    }
    Py_RETURN_NONE;

error:
    am_delconstraint(constraint);
    return NULL;
}

static PyObject *
AmoebaSolver_add_edit_variable(AmoebaSolver *self, PyObject *args) {
    PyObject *variable_obj;
    double strength;
    if (!PyArg_ParseTuple(args, "Od:add_edit_variable", &variable_obj, &strength)) return NULL;
    am_Id variable;
    if (!variable_from_python(self, variable_obj, &variable)) return NULL;
    if (!isfinite(strength) || strength < 0.) {
        PyErr_SetString(PyExc_ValueError, "edit strength must be finite and non-negative");
        return NULL;
    }
    int status = am_addedit(self->solver, variable, (am_Num)strength);
    if (status != AM_OK) {
        set_amoeba_error("adding an edit variable", status);
        return NULL;
    }
    Py_RETURN_NONE;
}

static PyObject *
AmoebaSolver_suggest_value(AmoebaSolver *self, PyObject *args) {
    PyObject *variable_obj;
    double value;
    if (!PyArg_ParseTuple(args, "Od:suggest_value", &variable_obj, &value)) return NULL;
    am_Id variable;
    if (!variable_from_python(self, variable_obj, &variable)) return NULL;
    if (!isfinite(value)) {
        PyErr_SetString(PyExc_ValueError, "suggested value must be finite");
        return NULL;
    }
    am_suggest(self->solver, variable, (am_Num)value);
    Py_RETURN_NONE;
}

static PyObject *
AmoebaSolver_update_variables(AmoebaSolver *self, PyObject *Py_UNUSED(arg)) {
    am_updatevars(self->solver);
    Py_RETURN_NONE;
}

static PyObject *
AmoebaSolver_value(AmoebaSolver *self, PyObject *variable_obj) {
    am_Id variable;
    if (!variable_from_python(self, variable_obj, &variable)) return NULL;
    return PyFloat_FromDouble(*self->values[variable]);
}

static PyMethodDef AmoebaSolver_methods[] = {
    {"add_variable", (PyCFunction)AmoebaSolver_add_variable, METH_NOARGS, NULL},
    {"add_constraint", (PyCFunction)AmoebaSolver_add_constraint, METH_VARARGS, NULL},
    {"add_edit_variable", (PyCFunction)AmoebaSolver_add_edit_variable, METH_VARARGS, NULL},
    {"suggest_value", (PyCFunction)AmoebaSolver_suggest_value, METH_VARARGS, NULL},
    {"update_variables", (PyCFunction)AmoebaSolver_update_variables, METH_NOARGS, NULL},
    {"value", (PyCFunction)AmoebaSolver_value, METH_O, NULL},
    {NULL, NULL, 0, NULL}};

static PyTypeObject AmoebaSolver_Type = {
    PyVarObject_HEAD_INIT(NULL, 0).tp_name = "kitty.fast_data_types.AmoebaSolver",
    .tp_basicsize = sizeof(AmoebaSolver),
    .tp_dealloc = (destructor)AmoebaSolver_dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "A Cassowary constraint solver backed by Amoeba",
    .tp_methods = AmoebaSolver_methods,
    .tp_new = AmoebaSolver_new,
};

bool
init_amoeba(PyObject *module) {
    if (PyType_Ready(&AmoebaSolver_Type) < 0) return false;
    AmoebaError = PyErr_NewException("kitty.fast_data_types.AmoebaError", NULL, NULL);
    if (AmoebaError == NULL) return false;
    if (PyModule_AddObject(module, "AmoebaError", AmoebaError) != 0) return false;
    Py_INCREF(&AmoebaSolver_Type);
    if (PyModule_AddObject(module, "AmoebaSolver", (PyObject *)&AmoebaSolver_Type) != 0) return false;
    return true;
}
