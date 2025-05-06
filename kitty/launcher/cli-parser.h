/*
 * cli-parser.h
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <Python.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>
#include "../iqsort.h"

#ifndef RAII_PyObject
static inline void cleanup_decref2(PyObject **p) { Py_CLEAR(*p); }
#define RAII_PyObject(name, initializer) __attribute__((cleanup(cleanup_decref2))) PyObject *name = initializer

#undef MAX
#define MAX(x, y) __extension__ ({ \
    const __typeof__ (x) __a__ = (x); const __typeof__ (y) __b__ = (y); \
        __a__ > __b__ ? __a__ : __b__;})
#endif

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
#define VAL_TY FlagSpec
#include "../kitty-verstable.h"
#define flag_map_for_loop(x) vt_create_for_loop(flag_hash_itr, itr, x)


typedef struct CLISpec {
    cli_hash value_map;
    alias_hash alias_map;
    flag_hash flag_map, disabled_map;
    char **argv; int argc;  // leftover args
    char **original_argv; int original_argc;  // original args
    const char* errmsg;
    struct {
        struct { char *buf; size_t capacity, used; } *items;
        size_t count, capacity;
    } blocks;
} CLISpec;

static void
out_of_memory(int line) {
    fprintf(stderr, "Out of memory at %s:%d\n", __FILE__, line);
    exit(1);
}
#define OOM out_of_memory(__LINE__)

static void*
alloc_for_cli(CLISpec *spec, size_t sz) {
    sz++;
    if (!spec->blocks.capacity) {
        spec->blocks.capacity = 8;
        spec->blocks.items = calloc(spec->blocks.capacity, sizeof(spec->blocks.items[0]));
        if (!spec->blocks.items) return NULL;
        spec->blocks.count = 1;
    }
#define block spec->blocks.items[spec->blocks.count-1]
    if (block.used + sz >= block.capacity) {
        if (block.capacity) {  // need new block
            spec->blocks.count++;
            if (spec->blocks.count >= spec->blocks.capacity) {
                spec->blocks.capacity *= 2;
                spec->blocks.items = realloc(spec->blocks.items, spec->blocks.capacity * sizeof(spec->blocks.items[0]));
                if (!spec->blocks.items) return NULL;
            }
        }
        block.capacity = MAX(sz, 8192u);
        block.buf = malloc(block.capacity);
        if (!block.buf) return NULL;
        block.used = 0;
    }
    char *ans = block.buf + block.used;
    ans[sz-1] = 0;
    block.used += sz;
    // keep returned memory regions aligned to size of pointer
    size_t extra = sz % sizeof(void*);
    if (extra) block.used += sizeof(void*) - extra;
    return ans;
#undef block
}

#define set_err(fmt, ...) { \
    int sz = snprintf(NULL, 0, fmt, __VA_ARGS__); \
    char *buf = alloc_for_cli(spec, sz + 4);  \
    if (!buf) OOM; \
    snprintf(buf, sz + 4, fmt, __VA_ARGS__); spec->errmsg = buf; \
}

static ssize_t
levenshtein_distance(size_t *cache, const char *a, const char *b) {
    if (a == b) return 0;
    const size_t length = strlen(a);
    const size_t bLength = strlen(b);
    if (length == 0) return bLength;
    if (bLength == 0) return length;
    size_t index = 0, bIndex = 0, distance = 0, bDistance = 0, result = 0;
    char code = 0;

    // initialize the vector.
    while (index < length) {
        cache[index] = index + 1;
        index++;
    }

    while (bIndex < bLength) {
        code = b[bIndex];
        result = distance = bIndex++;
        index = SIZE_MAX;

        while (++index < length) {
            bDistance = code == a[index] ? distance : distance + 1;
            distance = cache[index];

            cache[index] = result = distance > result
                ? bDistance > result
                ? result + 1
                : bDistance
                : bDistance > distance
                ? distance + 1
                : bDistance;
        }
    }
    return result;
}

static bool
add_to_listval(CLISpec *spec, CLIValue *v, const char *val) {
    if (v->listval.count + 1 >= v->listval.capacity) {
        size_t cap = MAX(64u, v->listval.capacity * 2u);
        char **new = alloc_for_cli(spec, cap * sizeof(v->listval.items[0]));
        if (!new) return false;
        v->listval.capacity = cap;
        if (v->listval.count) memcpy(new, v->listval.items, sizeof(new[0]) * v->listval.count);
        v->listval.items = (void*)new;
    }
    v->listval.items[v->listval.count++] = val;
    return true;
}

static bool
use_ansi_escape_codes(void) {
    static bool checked = false, ans;
    if (!checked) { ans = isatty(STDERR_FILENO); checked = true; }
    return ans;
}

static const char*
formatted_text(CLISpec *spec, const char *start_code, const char *text, const char *end_code) {
    if (!use_ansi_escape_codes()) return text;
    static const char *fmt =  "\x1b[%sm%s\x1b[%sm";
    int sz = snprintf(NULL, 0, fmt, start_code, text, end_code);
    char *ans = alloc_for_cli(spec, sz+1);
    snprintf(ans, sz+1, fmt, start_code, text, end_code);
    return ans;
}

#define red_text(text) formatted_text(spec, "91", text, "39")
#define yellow_text(text) formatted_text(spec, "93", text, "39")
#define green_text(text) formatted_text(spec, "32", text, "39")
#define italic_text(text) formatted_text(spec, "3", text, "23")

typedef struct similiar_alias {
    const char *alias;
    ssize_t distance;
} similiar_alias;

static const char*
dest_for_alias(CLISpec *spec, const char *alias) {
    alias_hash_itr itr = vt_get(&spec->alias_map, alias);
    if (vt_is_end(itr)) {
        const char *match_key = NULL, *match_val = NULL;
        size_t total = 0;
        alias_hash matches; vt_init(&matches);
        alias_map_for_loop(&spec->alias_map) {
            if (strstr(itr.data->key, alias) == itr.data->key) {
                total += strlen(itr.data->key) + 8;
                if (!match_key) { match_key = itr.data->key; match_val = itr.data->val; }
                if (vt_is_end(vt_insert(&matches, itr.data->val, itr.data->key))) OOM;
            }
        }
        if (match_key) {
            if (vt_size(&matches) == 1) { vt_cleanup(&matches); return match_val; }
            total += 256 + total;
            char *buf = alloc_for_cli(spec, total);
            if (!buf) OOM;
            int n = snprintf(buf, total, "The flag %s is ambiguous. Possible matches:", yellow_text(alias));
            alias_map_for_loop(&matches) {
                if ((ssize_t)total > n) n += snprintf(buf + n, total - n, " %s,", itr.data->val);
            }
            vt_cleanup(&matches);
            buf[n-1] = '.';
            spec->errmsg = buf;
            return NULL;
        }
        size_t *cache = alloc_for_cli(spec, sizeof(size_t) * strlen(alias));
        size_t num_aliases = vt_size(&spec->alias_map);
        similiar_alias *candidates =  alloc_for_cli(spec, sizeof(similiar_alias) * num_aliases);
        size_t num_candidates = 0;
        alias_map_for_loop(&spec->alias_map) {
            const char *q = itr.data->key;
            ssize_t d = levenshtein_distance(cache, alias, q);
            if (d < 0) break;
            if (d < 3) candidates[num_candidates++] = (similiar_alias){.alias=q, .distance=d};
        }
        if (num_candidates) {
#define lt(a, b) (a->distance < b->distance)
            QSORT(similiar_alias, candidates, num_candidates, lt);
            set_err("Unknown flag: %s. Did you mean: %s?", red_text(alias), green_text(candidates[0].alias));
            return NULL;
#undef lt
        }
        set_err("Unknown flag: %s use --help.", red_text(alias));
        return NULL;
    }
    return itr.data->val;
}

static bool
is_alias_bool(CLISpec* spec, const char *alias, const char **dest_out) {
    *dest_out = dest_for_alias(spec, alias);
    if (!*dest_out) return false;
    flag_hash_itr itr = vt_get(&spec->flag_map, *dest_out);
    return itr.data->val.defval.type == CLI_VALUE_BOOL;
}

static void
add_list_value(CLISpec *spec, const char *dest, const char *val) {
    cli_hash_itr itr = vt_get_or_insert(&spec->value_map, dest, (CLIValue){.type=CLI_VALUE_LIST});
    if (vt_is_end(itr)) OOM;
    CLIValue v = itr.data->val;
    if (!add_to_listval(spec, &v, val)) OOM;
    if (vt_is_end(vt_insert(&spec->value_map, dest, v))) OOM;
}

static bool
process_cli_arg(CLISpec* spec, const char *alias, const char *payload, const char *dest) {
    if (!dest) dest = dest_for_alias(spec, alias);
    if (!dest) return false;
    flag_hash_itr itr = vt_get(&spec->flag_map, dest);
    const FlagSpec *flag = &itr.data->val;
    CLIValue val = {.type=flag->defval.type};
#define streq(q) (strcmp(payload, #q) == 0)
    switch(val.type) {
        case CLI_VALUE_STRING: val.strval = payload; break;
        case CLI_VALUE_BOOL:
            if (payload) {
                if (streq(y) || streq(yes) || streq(true)) val.boolval = true;
                else if (streq(n) || streq(no) || streq(false)) val.boolval = false;
                else {
                    set_err("%s is an invalid value for %s. Valid values are: %s, %s, %s, %s, %s and %s.",
                            red_text(payload[0] ? payload : "<empty>"), green_text(alias), italic_text("y"), italic_text("yes"), italic_text("true"), italic_text("n"), italic_text("no"), italic_text("false"));
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
                size_t bufsz = 0;
                for (size_t c = 0; c < flag->defval.listval.count; c++) bufsz += strlen(flag->defval.listval.items[c]) + 8;
                bufsz += 256 + strlen(alias) + strlen(payload) + bufsz;
                char *buf = alloc_for_cli(spec, bufsz);
                int n = snprintf(buf, bufsz, "%s is an invalid value for %s. Valid values are:",
                        red_text(payload[0] ? payload : "<empty>"), green_text(alias));
                for (size_t c = 0; c < flag->defval.listval.count; c++)
                    if ((ssize_t)bufsz > n) n += snprintf(buf + n, bufsz - n, " %s,", italic_text(flag->defval.listval.items[c]));
                buf[n-1] = '.';
                spec->errmsg = buf;
                return false;
            }
            break;
        case CLI_VALUE_INT:
            errno = 0; val.intval = strtoll(payload, NULL, 10);
            if (errno) {
                set_err("%s is an invalid value for %s, it must be an integer number.", red_text(payload), green_text(alias));
                return false;
            } break;
        case CLI_VALUE_FLOAT:
            errno = 0; val.floatval = strtod(payload, NULL);
            if (errno) {
                set_err("%s is an invalid value for %s, it must be a number.", red_text(payload), green_text(alias));
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
    vt_init(&spec->disabled_map);
}

static void
dealloc_cli_spec(void *v) {
    CLISpec *spec = v;
    for (size_t i = 0; i < spec->blocks.count; i++) free(spec->blocks.items[i].buf);
    free(spec->blocks.items);
    vt_cleanup(&spec->value_map);
    vt_cleanup(&spec->alias_map);
    vt_cleanup(&spec->flag_map);
    vt_cleanup(&spec->disabled_map);
}

#define RAII_CLISpec(name) __attribute__((cleanup(dealloc_cli_spec))) CLISpec name = {0}; alloc_cli_spec(&name)

static bool
parse_cli_loop(CLISpec *spec, bool save_original_argv, int argc, char **argv) {
    enum { NORMAL, EXPECTING_ARG } state = NORMAL;
    spec->argc = 0; spec->argv = NULL; spec->errmsg = NULL; spec->original_argc = argc; spec->original_argv = NULL;
    if (save_original_argv) {
        char **copy = alloc_for_cli(spec, sizeof(char*) * (argc + 1));
        if (!copy) OOM;
        copy[argc] = NULL;
        for (int i = 0; i < argc; i++) {
            size_t len = strlen(argv[i]);
            copy[i] = alloc_for_cli(spec, len);
            if (!copy[i]) OOM;
            memcpy(copy[i], argv[i], len);
        }
        spec->original_argv = argv;
        argv = copy;
    }
    char flag[3] = {'-', 0, 0};
    const char *current_option = NULL;
    const char *dest_for_current_arg = NULL;
    for (int i = 1; i < argc; i++) {
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
                        if (is_alias_bool(spec, arg, &dest_for_current_arg)) {
                            if (!process_cli_arg(spec, arg, payload, dest_for_current_arg)) return false;
                        } else {
                            if (spec->errmsg) return false;
                            if (has_equal) {
                                if (!process_cli_arg(spec, arg, payload, dest_for_current_arg)) return false;
                            } else {
                                state = EXPECTING_ARG;
                                current_option = arg;
                            }
                        }
                    } else {
                        for (const char *letter = arg + 1; *letter; letter++) {
                            flag[1] = *letter;
                            if (letter[1]) {
                                if (!process_cli_arg(spec, flag, NULL, NULL)) return false;
                            } else {
                                if (is_alias_bool(spec, flag, &dest_for_current_arg) || payload) {
                                    if (!process_cli_arg(spec, flag, payload, dest_for_current_arg)) return false;
                                } else {
                                    if (spec->errmsg) return false;
                                    state = EXPECTING_ARG;
                                    current_option = flag;
                                }
                                if (spec->errmsg) return false;
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
                if (current_option && !process_cli_arg(spec, current_option, arg, NULL)) return false;
                current_option = NULL; state = NORMAL;
            } break;
        }
    }
    if (state == EXPECTING_ARG) set_err("The %s flag must be followed by an argument.", yellow_text(current_option ? current_option : ""));
    return spec->errmsg != NULL;
}

#ifdef FOR_LAUNCHER
static void
output_argv(const char *name, int argc, char **argv) {
    printf("%s:", name);
    for (int i = 0; i < argc; i++) printf("\x1e%s", argv[i]);
    printf("\n");
}

static void
output_values_for_testing(CLISpec *spec) {
    value_map_for_loop(&spec->value_map) {
        CLIValue v = itr.data->val;
        switch (v.type) {
            case CLI_VALUE_STRING: case CLI_VALUE_CHOICE:
                printf("%s: %s", itr.data->key, v.strval ? v.strval : ""); break;
            case CLI_VALUE_BOOL:
                printf("%s: %d", itr.data->key, v.boolval); break;
            case CLI_VALUE_INT:
                printf("%s: %lld", itr.data->key, v.intval); break;
            case CLI_VALUE_FLOAT:
                printf("%s: %f", itr.data->key, v.floatval); break;
            case CLI_VALUE_LIST:
                output_argv(itr.data->key, v.listval.count, (char**)v.listval.items);
                break;
        }
        printf("\n");
    }
}

static void
output_for_testing(CLISpec *spec) {
    output_argv("original_argv", spec->original_argc, spec->original_argv);
    output_argv("argv", spec->argc, spec->argv);
    output_values_for_testing(spec);
}

static CLIValue
get_cli_val(CLISpec *spec, const char *name) {
    cli_hash_itr itr = vt_get(&spec->value_map, name);
    if (vt_is_end(itr)) {
        flag_hash_itr itr = vt_get(&spec->flag_map, name);
        if (vt_is_end(itr)) return (CLIValue){0};
        return itr.data->val.defval;
    }
    return itr.data->val;
}

static bool
get_bool_cli_val(CLISpec *spec, const char *name) {
    return get_cli_val(spec, name).boolval;
}

static const char*
get_string_cli_val(CLISpec *spec, const char *name) {
    return get_cli_val(spec, name).strval;
}
#endif

static bool
clival_as_python(const CLIValue *v, PyObject *is_seen, const char *dest, PyObject *ans) {
#define S(fv) { \
    RAII_PyObject(temp, Py_BuildValue("NO", fv, is_seen)); if (!temp) return false; \
    if (PyDict_SetItemString(ans, dest, temp) != 0) return false; \
}
        switch (v->type) {
            case CLI_VALUE_BOOL: S(PyBool_FromLong((long)v->boolval)); break;
            case CLI_VALUE_STRING: if (v->strval) { S(PyUnicode_FromString(v->strval)); } else { S(Py_NewRef(Py_None)); } break;
            case CLI_VALUE_CHOICE: S(PyUnicode_FromString(v->strval)); break;
            case CLI_VALUE_INT: S(PyLong_FromLongLong(v->intval)); break;
            case CLI_VALUE_FLOAT: S(PyFloat_FromDouble(v->floatval)); break;
            case CLI_VALUE_LIST: {
                RAII_PyObject(l, PyList_New(v->listval.count)); if (!l) return false;
                for (size_t i = 0; i < v->listval.count; i++) {
                    PyObject *x = PyUnicode_FromString(v->listval.items[i]); if (!x) return false;
                    PyList_SET_ITEM(l, i, x);
                }
                S(Py_NewRef(l));
            } break;
        }
#undef S
        return true;
}

static PyObject*
cli_parse_result_as_python(CLISpec *spec) {
    if (PyErr_Occurred()) return NULL;
    if (spec->errmsg) {
        PyErr_SetString(PyExc_ValueError, spec->errmsg); return NULL;
    }
    RAII_PyObject(ans, PyDict_New()); if (!ans) return NULL;
    flag_map_for_loop(&spec->flag_map) {
        const FlagSpec *flag = &itr.data->val;
        cli_hash_itr i = vt_get(&spec->value_map, flag->dest);
        PyObject *is_seen = vt_is_end(i) ? Py_False : Py_True;
        const CLIValue *v = is_seen == Py_True ? &i.data->val : &flag->defval;
        if (!clival_as_python(v, is_seen, flag->dest, ans)) return NULL;
    }
    flag_map_for_loop(&spec->disabled_map) {
        const FlagSpec *flag = &itr.data->val;
        if (!clival_as_python(&flag->defval, Py_False, flag->dest, ans)) return NULL;
    }
    RAII_PyObject(leftover_args, PyList_New(spec->argc)); if (!leftover_args) return NULL;
    for (int i = 0; i < spec->argc; i++) {
        PyObject *t = PyUnicode_FromString(spec->argv[i]);
        if (!t) return NULL;
        PyList_SET_ITEM(leftover_args, i, t);
    }
    return Py_BuildValue("OO", ans, leftover_args);
}

#ifndef FOR_LAUNCHER
static PyObject*
parse_cli_from_python_spec(PyObject *self, PyObject *args) {
    (void)self; PyObject *pyargs, *names_map, *defval_map;
    if (!PyArg_ParseTuple(args, "O!O!O!", &PyList_Type, &pyargs, &PyDict_Type, &names_map, &PyDict_Type, &defval_map)) return NULL;
    int argc = PyList_GET_SIZE(pyargs);
    RAII_CLISpec(spec);
    char **argv = alloc_for_cli(&spec, sizeof(char*) * (argc + 2));
    if (!argv) return PyErr_NoMemory();
    argv[0] = "parse_cli_from_python_spec";
    for (int i = 0; i < argc; i++) {
        Py_ssize_t sz;
        const char *src = PyUnicode_AsUTF8AndSize(PyList_GET_ITEM(pyargs, i), &sz);
        argv[i + 1] = alloc_for_cli(&spec, sz);
        if (!argv[i + 1]) return PyErr_NoMemory();
        memcpy(argv[i + 1], src, sz);
    }
    argv[++argc] = 0;
    PyObject *key = NULL, *opt = NULL;
    Py_ssize_t pos = 0;
    while (PyDict_Next(names_map, &pos, &key, &opt)) {
        FlagSpec flag = {.dest=PyUnicode_AsUTF8(key)};
        PyObject *pytype = PyDict_GetItemString(opt, "type");
        const char *type = pytype ? PyUnicode_AsUTF8(pytype) : "";
        PyObject *defval = PyDict_GetItemWithError(defval_map, key); if (!defval && PyErr_Occurred()) return NULL;
        PyObject *pyaliases = PyDict_GetItemString(opt, "aliases");
        for (int a = 0; a < PyTuple_GET_SIZE(pyaliases); a++) {
            const char *alias = PyUnicode_AsUTF8(PyTuple_GET_ITEM(pyaliases, a));
            if (vt_is_end(vt_insert(&spec.alias_map, alias, flag.dest))) return PyErr_NoMemory();
        }
        if (strstr(type, "bool-") == type) {
            flag.defval.type = CLI_VALUE_BOOL;
            flag.defval.boolval = PyObject_IsTrue(defval);
        } else if (strcmp(type, "int") == 0) {
            flag.defval.type = CLI_VALUE_INT;
            flag.defval.intval = PyLong_AsLongLong(defval);
        } else if (strcmp(type, "float") == 0) {
            flag.defval.type = CLI_VALUE_FLOAT;
            flag.defval.floatval = PyFloat_AsDouble(defval);
        } else if (strcmp(type, "list") == 0) {
            flag.defval.type = CLI_VALUE_LIST;
            if (PyObject_IsTrue(defval)) {
                for (ssize_t l = 0; l < PyList_GET_SIZE(defval); l++) add_to_listval(&spec, &flag.defval, PyUnicode_AsUTF8(PyList_GET_ITEM(defval, l)));
            }
        } else if (strcmp(type, "choices") == 0) {
            flag.defval.type = CLI_VALUE_CHOICE;
            flag.defval.strval = PyUnicode_AsUTF8(defval);
            PyObject *pyc = PyDict_GetItemString(opt, "choices");
            flag.defval.listval.items = alloc_for_cli(&spec, PyTuple_GET_SIZE(pyc) * sizeof(char*));
            if (!flag.defval.listval.items) return PyErr_NoMemory();
            flag.defval.listval.count = PyTuple_GET_SIZE(pyc);
            flag.defval.listval.capacity = PyTuple_GET_SIZE(pyc);
            for (size_t n = 0; n < flag.defval.listval.count; n++) {
                flag.defval.listval.items[n] = PyUnicode_AsUTF8(PyTuple_GET_ITEM(pyc, n));
                if (!flag.defval.listval.items[n]) return NULL;
            }
        } else {
            flag.defval.type = CLI_VALUE_STRING;
            flag.defval.strval = PyUnicode_Check(defval) ? PyUnicode_AsUTF8(defval) : NULL;
        }
        if (vt_is_end(vt_insert(&spec.flag_map, flag.dest, flag))) return PyErr_NoMemory();
    }
    if (PyErr_Occurred()) return NULL;
    parse_cli_loop(&spec, false, argc, argv);
    PyObject *ans = cli_parse_result_as_python(&spec);
    return ans;
}
#endif
