/*
 * data-types.h
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#pragma once


#include <stdint.h>
#include <Python.h>
#define UNUSED __attribute__ ((unused))
#define MAX(x, y) (((x) > (y)) ? (x) : (y))

typedef Py_UCS4 char_type;
typedef uint64_t color_type;
typedef uint32_t decoration_type;
typedef uint32_t combining_type;
typedef unsigned int index_type;
#define CELL_SIZE (sizeof(char_type) + sizeof(color_type) + sizeof(decoration_type) + sizeof(combining_type))

#define CHAR_MASK 0xFFFFFF
#define ATTRS_SHIFT 24
#define WIDTH_MASK  0xFF
#define DECORATION_SHIFT  2
#define BOLD_SHIFT 4
#define ITALIC_SHIFT 5
#define REVERSE_SHIFT 6
#define STRIKE_SHIFT 7
#define DECORATION_MASK  (1 << DECORATION_SHIFT)
#define BOLD_MASK  (1 << BOLD_SHIFT)
#define ITALIC_MASK  (1 << ITALIC_SHIFT)
#define REVERSE_MASK (1 << REVERSE_SHIFT)
#define STRIKE_MASK  (1 << STRIKE_SHIFT)
#define COL_MASK 0xFFFFFFFF
#define COL_SHIFT  32
#define HAS_BG_MASK (0xFF << COL_SHIFT)
#define CC_MASK 0xFFFF
#define CC_SHIFT 16

#define CURSOR_TO_ATTRS(c, w) \
    (w | (((c->decoration & 3) << DECORATION_SHIFT) | ((c->bold & 1) << BOLD_SHIFT) | \
            ((c->italic & 1) << ITALIC_SHIFT) | ((c->reverse & 1) << REVERSE_SHIFT) | ((c->strikethrough & 1) << STRIKE_SHIFT))) << ATTRS_SHIFT

#define ATTRS_TO_CURSOR(a, c) \
    c->decoration = a & DECORATION_MASK; c->bold = a & BOLD_MASK; c->italic = a & ITALIC_MASK; \
    c->reverse = a & REVERSE_MASK; c->strikethrough = a & STRIKE_MASK;

#define COLORS_TO_CURSOR(col, c) \
    c->fg = col & COL_MASK; c->bg = (col >> COL_SHIFT)

#define METHOD(name, arg_type) {#name, (PyCFunction)name, arg_type, name##_doc},

typedef struct {
    PyObject_HEAD

    char_type *chars;
    color_type *colors;
    decoration_type *decoration_fg;
    combining_type *combining_chars;
    index_type xnum, ynum;
} Line;


typedef struct {
    PyObject_HEAD

    uint8_t *buf;
    index_type xnum, ynum, *line_map;
    index_type block_size;
    uint8_t *continued_map;
    Line *line;

    // Pointers into buf
    char_type *chars;
    color_type *colors;
    decoration_type *decoration_fg;
    combining_type *combining_chars;
} LineBuf;


typedef struct {
    PyObject_HEAD

    PyObject *x, *y, *shape, *blink, *hidden, *color;
    uint8_t bold, italic, reverse, strikethrough, decoration;
    uint32_t fg, bg, decoration_fg;

} Cursor;
