/*
 * colors.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"

static uint32_t FG_BG_256[255] = {
    0x000000,  // 0
    0xcd0000,  // 1
    0x00cd00,  // 2
    0xcdcd00,  // 3
    0x0000ee,  // 4
    0xcd00cd,  // 5
    0x00cdcd,  // 6
    0xe5e5e5,  // 7
    0x7f7f7f,  // 8
    0xff0000,  // 9
    0x00ff00,  // 10
    0xffff00,  // 11
    0x5c5cff,  // 12
    0xff00ff,  // 13
    0x00ffff,  // 14
    0xffffff,  // 15
};

PyObject* create_256_color_table() {
    // colors 16..232: the 6x6x6 color cube
    const uint8_t valuerange[6] = {0x00, 0x5f, 0x87, 0xaf, 0xd7, 0xff};
    uint8_t i, j=16;
    for(i = 0; i < 217; i++, j++) {
        uint8_t r = valuerange[(i / 36) % 6], g = valuerange[(i / 6) % 6], b = valuerange[i % 6];
        FG_BG_256[j] = (r << 16) | (g << 8) | b;
    }
    // colors 233..253: grayscale
    for(i = 1; i < 22; i++, j++) {
        uint8_t v = 8 + i * 10;
        FG_BG_256[j] = (v << 16) | (v << 8) | v;
    }
    
    PyObject *ans = PyTuple_New(255);
    if (ans == NULL) return PyErr_NoMemory();
    for (i=0; i < 255; i++) {
        PyObject *temp = PyLong_FromUnsignedLong(FG_BG_256[i]);
        if (temp == NULL) { Py_CLEAR(ans); return NULL; }
        PyTuple_SET_ITEM(ans, i, temp);
    }
    return ans;
}
