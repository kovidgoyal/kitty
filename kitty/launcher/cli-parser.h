/*
 * cli-parser.h
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "listobject.h"
#include <Python.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>

#ifndef RAII_ALLOC
static inline void cleanup_decref2(PyObject **p) { Py_CLEAR(*p); }
#define RAII_PyObject(name, initializer) __attribute__((cleanup(cleanup_decref2))) PyObject *name = initializer

static inline void cleanup_free(void *p) { free(*(void**)p); }
#define RAII_ALLOC(type, name, initializer) __attribute__((cleanup(cleanup_free))) type *name = initializer
#endif

static inline void
cleanup_argv(void *p) {
    for (char **argv = *(void **)p; *argv; argv++) free(*argv);
    free(*(void**)p);
}
#define RAII_ARGV(name, argc) __attribute__((cleanup(cleanup_argv))) char** name = calloc(argc + 1, sizeof(char*))

typedef enum CLIValueType { CLI_VALUE_STRING, CLI_VALUE_BOOL, CLI_VALUE_INT, CLI_VALUE_FLOAT, CLI_VALUE_LIST, CLI_VALUE_CHOICE } CLIValueType;
typedef struct CLIValue {
    CLIValueType type;
    long long intval;
    double floatval;
    bool boolval;
    const char* strval;
    struct {
        const char* * items;
        size_t count, capacity;
        bool needs_free;
    } listval;
} CLIValue;

#define NAME cli_hash
#define KEY_TY const char*
#define VAL_TY CLIValue
#include "../kitty-verstable.h"
#define value_map_for_loop(x) vt_create_for_loop(cli_hash_itr, itr, x)

#define NAME alias_hash
#define KEY_TY const char*
#define VAL_TY const char*
#include "../kitty-verstable.h"
#define alias_map_for_loop(x) vt_create_for_loop(alias_hash_itr, itr, x)

typedef struct FlagSpec {
    CLIValue defval;
    const char *dest;
} FlagSpec;

#define NAME flag_hash
#define KEY_TY const char*
#define VAL_TY const FlagSpec*
#include "../kitty-verstable.h"
#define flag_map_for_loop(x) vt_create_for_loop(flag_hash_itr, itr, x)


typedef struct CLISpec {
    cli_hash value_map;
    alias_hash alias_map;
    flag_hash flag_map;
    char **argv; int argc;  // leftover args
    char err[1024];
} CLISpec;

static void
out_of_memory(int line) {
    fprintf(stderr, "Out of memory at %s:%d\n", __FILE__, line);
    exit(1);
}
#define OOM out_of_memory(__LINE__)


static const char*
dest_for_alias(CLISpec *spec, const char *alias) {
    alias_hash_itr itr = vt_get(&spec->alias_map, alias);
    if (vt_is_end(itr)) {
        snprintf(spec->err, sizeof(spec->err), "Unknown flag: %s use --help", alias);
        return NULL;
    }
    return itr.data->val;
}

static bool
is_alias_bool(CLISpec* spec, const char *alias) {
    const char *dest = dest_for_alias(spec, alias);
    if (!dest) return false;
    flag_hash_itr itr = vt_get(&spec->flag_map, dest);
    return itr.data->val->defval.type == CLI_VALUE_BOOL;
}

static void
add_list_value(CLISpec *spec, const char *dest, const char *val) {
    cli_hash_itr itr = vt_get_or_insert(&spec->value_map, dest, (CLIValue){.type=CLI_VALUE_LIST});
    if (vt_is_end(itr)) OOM;
    CLIValue v = itr.data->val;
    if (v.listval.count + 1 >= v.listval.capacity) {
        size_t cap = v.listval.capacity * 2;
        if (!cap) cap = 64;
        v.listval.items = realloc((void*)v.listval.items, cap * sizeof(v.listval.items[0]));
        if (!v.listval.items) OOM;
        v.listval.capacity = cap;
    }
    v.listval.items[v.listval.count++] = val;
    if (vt_is_end(vt_insert(&spec->value_map, dest, v))) OOM;
}

static bool
process_cli_arg(CLISpec* spec, const char *alias, const char *payload) {
    const char *dest = dest_for_alias(spec, alias);
    if (!dest) return false;
    flag_hash_itr itr = vt_get(&spec->flag_map, dest);
    const FlagSpec *flag = itr.data->val;
    CLIValue val = {.type=flag->defval.type};
#define streq(q) (strcmp(payload, #q) == 0)
    switch(val.type) {
        case CLI_VALUE_STRING: val.strval = payload; break;
        case CLI_VALUE_BOOL:
            if (payload) {
                if (streq(y) || streq(yes) || streq(true)) val.boolval = true;
                else if (streq(n) || streq(no) || streq(false)) val.boolval = false;
                else {
                    snprintf(spec->err, sizeof(spec->err), "%s is an invalid value for %s. Valid values are: y, yes, true, n, no and false.",
                            payload[0] ? payload : "<empty>", alias);
                    return false;
                }
            } else val.boolval = !flag->defval.boolval;
            break;
        case CLI_VALUE_CHOICE:
            val.strval = NULL;
            for (size_t c = 0; c < flag->defval.listval.count; c++) {
                if (strcmp(payload, flag->defval.listval.items[c]) == 0) { val.strval = payload; break; }
            }
            if (!val.strval) {
                int n = snprintf(spec->err, sizeof(spec->err), "%s is an invalid value for %s. Valid values are:",
                            payload[0] ? payload : "<empty>", alias);
                for (size_t c = 0; c < flag->defval.listval.count; c++)
                    n += snprintf(spec->err + n, sizeof(spec->err) - n, " %s,", flag->defval.listval.items[c]);
                spec->err[n-1] = '.';
                return false;
            }
            break;
        case CLI_VALUE_INT:
            errno = 0; val.intval = strtoll(payload, NULL, 10);
            if (errno) {
                snprintf(spec->err, sizeof(spec->err), "%s is an invalid value for %s, it must be an integer number.", payload, alias);
                return false;
            } break;
        case CLI_VALUE_FLOAT:
            errno = 0; val.floatval = strtod(payload, NULL);
            if (errno) {
                snprintf(spec->err, sizeof(spec->err), "%s is an invalid value for %s, it must be a number.", payload, alias);
                return false;
            } break;
        case CLI_VALUE_LIST: add_list_value(spec, flag->dest, payload); return true;
    }
    if (vt_is_end(vt_insert(&spec->value_map, flag->dest, val))) OOM;
    return true;
#undef streq
}

static void
alloc_cli_spec(CLISpec *spec) {
    vt_init(&spec->value_map);
    vt_init(&spec->alias_map);
    vt_init(&spec->flag_map);
}

static void
dealloc_cli_value(CLIValue v) {
    if (v.listval.needs_free) free((void*)v.listval.items);
}

static void
dealloc_cli_spec(void *v) {
    CLISpec *spec = v;
    value_map_for_loop(&spec->value_map) {
        dealloc_cli_value(itr.data->val);
    }
    flag_map_for_loop(&spec->flag_map) {
        dealloc_cli_value(itr.data->val->defval);
    }
    vt_cleanup(&spec->value_map);
    vt_cleanup(&spec->alias_map);
    vt_cleanup(&spec->flag_map);
}

#define RAII_CLISpec(name) __attribute__((cleanup(dealloc_cli_spec))) CLISpec name = {0}; alloc_cli_spec(&name)

static bool
parse_cli_loop(CLISpec *spec, int argc, char **argv) {  // argv must contain arg1 and beyond
    enum { NORMAL, EXPECTING_ARG } state = NORMAL;
    spec->argc = 0; spec->argv = NULL; spec->err[0] = 0;
    char flag[3] = {'-', 0, 0};
    const char *current_option = NULL;
    for (int i = 0; i < argc; i++) {
        char *arg = argv[i];
        switch(state) {
            case NORMAL: {
                if (arg[0] == '-') {
                    const bool is_long_opt = arg[1] == '-';
                    if (is_long_opt && arg[2] == 0) {
                        spec->argc = argc - i - 1;
                        if (spec->argc > 0) spec->argv = argv + i + 1;
                        return true;
                    }
                    char *has_equal = strchr(arg, '=');
                    const char *payload = NULL;
                    if (has_equal) {
                        *has_equal = 0;
                        payload = has_equal + 1;
                    }
                    if (is_long_opt) {
                        if (is_alias_bool(spec, arg)) {
                            if (!process_cli_arg(spec, arg, payload)) return false;
                        } else {
                            if (has_equal) {
                                if (!process_cli_arg(spec, arg, payload)) return false;
                            } else {
                                state = EXPECTING_ARG;
                                current_option = arg;
                            }
                        }
                        if (spec->err[0]) return false;
                    } else {
                        for (const char *letter = arg + 1; *letter; letter++) {
                            flag[1] = *letter;
                            if (letter[1]) {
                                if (!process_cli_arg(spec, flag, NULL)) return false;
                            } else {
                                if (is_alias_bool(spec, flag) || payload) {
                                    if (!process_cli_arg(spec, flag, payload)) return false;
                                } else {
                                    state = EXPECTING_ARG;
                                    current_option = arg;
                                }
                                if (spec->err[0]) return false;
                            }
                        }
                    }
                } else {
                    spec->argc = argc - i;
                    if (spec->argc > 0) spec->argv = argv + i;
                    return true;
                }
            } break;
            case EXPECTING_ARG: {
                if (current_option && !process_cli_arg(spec, current_option, arg)) return false;
                current_option = NULL; state = NORMAL;
            } break;
        }
    }
    if (state == EXPECTING_ARG) snprintf(spec->err, sizeof(spec->err), "The %s flag must be followed by an argument.", current_option ? current_option : "");
    return spec->err[0] == 0;
}

static PyObject*
cli_parse_result_as_python(CLISpec *spec) {
    if (PyErr_Occurred()) return NULL;
    if (spec->err[0]) {
        PyErr_SetString(PyExc_ValueError, spec->err); return NULL;
    }
    RAII_PyObject(ans, PyDict_New()); if (!ans) return NULL;
    flag_map_for_loop(&spec->flag_map) {
        const FlagSpec *flag = itr.data->val;
        cli_hash_itr i = vt_get(&spec->value_map, flag->dest);
        PyObject *is_seen = vt_is_end(i) ? Py_False : Py_True;
        const CLIValue *v = is_seen == Py_True ? &i.data->val : &flag->defval;
#define S(fv) { RAII_PyObject(temp, Py_BuildValue("NO", fv, is_seen)); if (!temp) return NULL; \
    if (PyDict_SetItemString(ans, flag->dest, temp) != 0) return NULL;}
        switch (v->type) {
            case CLI_VALUE_BOOL: S(PyBool_FromLong((long)v->boolval)); break;
            case CLI_VALUE_STRING: if (v->strval) { S(PyUnicode_FromString(v->strval)); } else { S(Py_NewRef(Py_None)); } break;
            case CLI_VALUE_CHOICE: S(PyUnicode_FromString(v->strval)); break;
            case CLI_VALUE_INT: S(PyLong_FromLongLong(v->intval)); break;
            case CLI_VALUE_FLOAT: S(PyFloat_FromDouble(v->floatval)); break;
            case CLI_VALUE_LIST: {
                RAII_PyObject(l, PyList_New(v->listval.count)); if (!l) return NULL;
                for (size_t i = 0; i < v->listval.count; i++) {
                    PyObject *x = PyUnicode_FromString(v->listval.items[i]); if (!x) return NULL;
                    PyList_SET_ITEM(l, i, x);
                }
                S(Py_NewRef(l));
            } break;
        }
    }
#undef S
    RAII_PyObject(leftover_args, PyList_New(spec->argc)); if (!leftover_args) return NULL;
    for (int i = 0; i < spec->argc; i++) {
        PyObject *t = PyUnicode_FromString(spec->argv[i]);
        if (!t) return NULL;
        PyList_SET_ITEM(leftover_args, i, t);
    }
    return Py_BuildValue("OO", ans, leftover_args);
}

static PyObject*
parse_cli_from_python_spec(PyObject *self, PyObject *args) {
    (void)self; PyObject *pyargs, *names_map, *defval_map;
    if (!PyArg_ParseTuple(args, "O!O!O!", &PyList_Type, &pyargs, &PyDict_Type, &names_map, &PyDict_Type, &defval_map)) return NULL;
    int argc = PyList_GET_SIZE(pyargs);
    RAII_ARGV(argv, argc); if (!argv) return PyErr_NoMemory();
    for (int i = 0; i < argc; i++) {
        argv[i] = strdup(PyUnicode_AsUTF8(PyList_GET_ITEM(pyargs, i)));
        if (!argv[i]) return PyErr_NoMemory();
    }
    RAII_ALLOC(FlagSpec, flags, calloc(PyDict_GET_SIZE(names_map), sizeof(FlagSpec)));  if (!flags) return PyErr_NoMemory();
    RAII_CLISpec(spec);
    PyObject *key = NULL, *opt = NULL;
    Py_ssize_t pos = 0, flag_num = 0;
    while (PyDict_Next(names_map, &pos, &key, &opt)) {
        FlagSpec *flag = &flags[flag_num++];
        flag->dest = PyUnicode_AsUTF8(key);
        PyObject *pytype = PyDict_GetItemString(opt, "type");
        const char *type = pytype ? PyUnicode_AsUTF8(pytype) : "";
        PyObject *defval = PyDict_GetItemWithError(defval_map, key); if (!defval && PyErr_Occurred()) return NULL;
        PyObject *pyaliases = PyDict_GetItemString(opt, "aliases");
        for (int a = 0; a < PyTuple_GET_SIZE(pyaliases); a++) {
            const char *alias = PyUnicode_AsUTF8(PyTuple_GET_ITEM(pyaliases, a));
            if (vt_is_end(vt_insert(&spec.alias_map, alias, flag->dest))) return PyErr_NoMemory();
        }
        if (strstr(type, "bool-") == type) {
            flag->defval.type = CLI_VALUE_BOOL;
            flag->defval.boolval = PyObject_IsTrue(defval);
        } else if (strcmp(type, "int") == 0) {
            flag->defval.type = CLI_VALUE_INT;
            flag->defval.intval = PyLong_AsLongLong(defval);
        } else if (strcmp(type, "float") == 0) {
            flag->defval.type = CLI_VALUE_FLOAT;
            flag->defval.floatval = PyFloat_AsDouble(defval);
        } else if (strcmp(type, "list") == 0) {
            flag->defval.type = CLI_VALUE_LIST;
        } else if (strcmp(type, "choices") == 0) {
            flag->defval.type = CLI_VALUE_CHOICE;
            flag->defval.strval = PyUnicode_AsUTF8(defval);
            PyObject *pyc = PyDict_GetItemString(opt, "choices");
            flag->defval.listval.items = malloc(PyTuple_GET_SIZE(pyc) * sizeof(char*));
            if (!flag->defval.listval.items) return PyErr_NoMemory();
            flag->defval.listval.count = PyTuple_GET_SIZE(pyc);
            flag->defval.listval.needs_free = true;
            flag->defval.listval.capacity = PyTuple_GET_SIZE(pyc);
            for (size_t n = 0; n < flag->defval.listval.count; n++) {
                flag->defval.listval.items[n] = PyUnicode_AsUTF8(PyTuple_GET_ITEM(pyc, n));
                if (!flag->defval.listval.items[n]) return NULL;
            }
        } else {
            flag->defval.type = CLI_VALUE_STRING;
            flag->defval.strval = PyUnicode_Check(defval) ? PyUnicode_AsUTF8(defval) : NULL;
        }
        if (vt_is_end(vt_insert(&spec.flag_map, flag->dest, flag))) return PyErr_NoMemory();
    }
    if (PyErr_Occurred()) return NULL;
    parse_cli_loop(&spec, argc, argv);
    PyObject *ans = cli_parse_result_as_python(&spec);
    return ans;
}

