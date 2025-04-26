/*
 * cli-parser.h
 * Copyright (C) 2025 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <errno.h>

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
    const char *dest, *choices, *aliases;
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
    char err[512];
} CLISpec;

static void
out_of_memory(int line) {
    fprintf(stderr, "Out of memory at %s:%d\n", __FILE__, line);
    exit(1);
}
#define OOM out_of_memory(__LINE__)


static bool
report_unknown_alias(CLISpec *spec, const char *alias) {
    snprintf(spec->err, sizeof(spec->err), "Unknown flag: %s use --help", alias);
    return false;
}

static bool
is_alias_bool(CLISpec* spec, const char *alias) {
    flag_hash_itr itr = vt_get(&spec->flag_map, alias);
    if (!itr.data) return report_unknown_alias(spec, alias);
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
    flag_hash_itr itr = vt_get(&spec->flag_map, alias);
    if (!itr.data) return report_unknown_alias(spec, alias);
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
            for (const char* q = flag->choices; q; q++) if (streq(q)) { val.strval = payload; break; }
            if (!val.strval) {
                int n = snprintf(spec->err, sizeof(spec->err), "%s is an invalid value for %s. Valid values are:",
                            payload[0] ? payload : "<empty>", alias);
                for (const char* q = flag->choices; q; q++) n += snprintf(spec->err + n, sizeof(spec->err) - n, " %s,", q);
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
alloc_cli_spec(CLISpec *spec, const FlagSpec *flags) {
    vt_init(&spec->value_map);
    vt_init(&spec->alias_map);
    vt_init(&spec->flag_map);
    for (const FlagSpec *flag = flags; flag != NULL; flag++) {
        if (vt_is_end(vt_insert(&spec->flag_map, flag->dest, flag))) OOM;
        for (const char *alias = flag->aliases; alias != NULL; alias++) {
            if (vt_is_end(vt_insert(&spec->alias_map, alias, flag->dest))) OOM;
        }
    }
}

static void
dealloc_cli_value(CLIValue v) {
    free((void*)v.listval.items);
}

static void
dealloc_cli_spec(CLISpec *spec) {
    value_map_for_loop(&spec->value_map) {
        dealloc_cli_value(itr.data->val);
    }
    vt_cleanup(&spec->value_map);
    vt_cleanup(&spec->alias_map);
    vt_cleanup(&spec->flag_map);
}

static bool
parse_cli_loop(CLISpec *spec, int argc, char **argv) {  // argv must contain arg1 and beyond
    enum { NORMAL, EXPECTING_ARG } state = NORMAL;
    spec->argc = 0; spec->argv = NULL;
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
