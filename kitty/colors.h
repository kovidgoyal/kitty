/*
 * Copyright (C) 2021 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once

#include "data-types.h"

typedef union ARGB32 {
    color_type val;
    struct {
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
        uint8_t b: 8;
        uint8_t g: 8;
        uint8_t r: 8;
        uint8_t a: 8;
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
        uint8_t a: 8;
        uint8_t r: 8;
        uint8_t g: 8;
        uint8_t b: 8;
#else
#error "Unsupported endianness"
#endif
    };
    struct {
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
        uint8_t blue: 8;
        uint8_t green: 8;
        uint8_t red: 8;
        uint8_t alpha: 8;
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
        uint8_t alpha: 8;
        uint8_t red: 8;
        uint8_t green: 8;
        uint8_t blue: 8;
#else
#error "Unsupported endianness"
#endif
    };
    struct {
#if __BYTE_ORDER__ == __ORDER_LITTLE_ENDIAN__
        color_type rgb: 24;
        uint8_t _ignore_me: 8;
#elif __BYTE_ORDER__ == __ORDER_BIG_ENDIAN__
        uint8_t _ignore_me: 8;
        color_type rgb: 24;
#else
#error "Unsupported endianness"
#endif
    };
} ARGB32;

typedef struct {
    PyObject_HEAD

    ARGB32 color;
} Color;

extern PyTypeObject ColorProfile_Type;
extern PyTypeObject Color_Type;

static inline double
rgb_luminance(ARGB32 c) {
    // From ITU BT 601 https://www.itu.int/rec/R-REC-BT.601
    return 0.299 * c.red + 0.587 * c.green + 0.114 * c.blue;
}

static inline double
rgb_contrast(ARGB32 a, ARGB32 b) {
    double al = rgb_luminance(a), bl = rgb_luminance(b);
    if (al < bl) SWAP(al, bl);
    return (al + 0.05) / (bl + 0.05);
}
