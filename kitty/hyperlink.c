/*
 * hyperlink.c
 * Copyright (C) 2020 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#define _POSIX_C_SOURCE 200809L
#include <string.h>
#include "screen.h"

bool
parse_osc_8(char *buf, char **id, char **url) {
    char *boundary = strstr(buf, ";");
    if (boundary == NULL) return false;
    *boundary = 0;
    if (*(boundary + 1)) *url = boundary + 1;
    char *save, *token = strtok_r(buf, ":", &save);
    while (token != NULL) {
        size_t len = strlen(token);
        if (len > 3 && token[0] == 'i' && token[1] == 'd' && token[2] == '=' && token[3]) {
            *id = token + 3;
            break;
        }
        token = strtok_r(NULL, ":", &save);
    }
    return true;
}
