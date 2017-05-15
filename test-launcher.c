/*
 * linux-launcher.c
 * Copyright (C) 2017 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include <Python.h>

int main(int argc, char *argv[]) {
    wchar_t *wargv[2] = {L"kitty-test", L"test.py"};
    return Py_Main(2, wargv);
}
