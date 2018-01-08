/*
 * linux-launcher.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include <Python.h>

#define MAX_ARGC 1024

int main(int argc, char *argv[]) {
    wchar_t *argvw[MAX_ARGC + 1] = {0};
    argvw[0] = L"kitty";
    for (int i = 1; i < argc; i++) argvw[i] = Py_DecodeLocale(argv[i], NULL);
    int ret = Py_Main(argc, argvw);
    for (int i = 1; i < argc; i++) PyMem_RawFree(argvw[i]);
    return ret;
}
