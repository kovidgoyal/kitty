/*
 * history.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "lineops.h"
#include <structmember.h>

extern PyTypeObject Line_Type;

static inline Cell*
lineptr(HistoryBuf *linebuf, index_type y) {
    return linebuf->buf + y * linebuf->xnum;
}

static PyObject *
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    HistoryBuf *self;
    unsigned int xnum = 1, ynum = 1;

    if (!PyArg_ParseTuple(args, "II", &ynum, &xnum)) return NULL;

    if (xnum * ynum == 0) {
        PyErr_SetString(PyExc_ValueError, "Cannot create an empty history buffer");
        return NULL;
    }

    self = (HistoryBuf *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->xnum = xnum;
        self->ynum = ynum;
        self->buf = PyMem_Calloc(xnum * ynum, sizeof(Cell));
        self->line_attrs = PyMem_Calloc(ynum, sizeof(line_attrs_type));
        self->line = alloc_line();
        if (self->buf == NULL || self->line == NULL || self->line_attrs == NULL) {
            PyErr_NoMemory();
            PyMem_Free(self->buf); Py_CLEAR(self->line); PyMem_Free(self->line_attrs);
            Py_CLEAR(self);
        } else {
            self->line->xnum = xnum;
            for(index_type y = 0; y < self->ynum; y++) {
                clear_chars_in_line(lineptr(self, y), self->xnum, BLANK_CHAR);
            }
        }
    }

    return (PyObject*)self;
}

static void
dealloc(HistoryBuf* self) {
    Py_CLEAR(self->line);
    PyMem_Free(self->buf);
    PyMem_Free(self->line_attrs);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

static inline index_type
index_of(HistoryBuf *self, index_type lnum) {
    // The index (buffer position) of the line with line number lnum
    // This is reverse indexing, i.e. lnum = 0 corresponds to the *last* line in the buffer.
    if (self->count == 0) return 0;
    index_type idx = self->count - 1 - MIN(self->count - 1, lnum);
    return (self->start_of_data + idx) % self->ynum;
}

static inline void
init_line(HistoryBuf *self, index_type num, Line *l) {
    // Initialize the line l, setting its pointer to the offsets for the line at index (buffer position) num
    l->cells = lineptr(self, num);
    l->continued = self->line_attrs[num] & CONTINUED_MASK;
    l->has_dirty_text = self->line_attrs[num] & TEXT_DIRTY_MASK ? true : false;
}

void
historybuf_init_line(HistoryBuf *self, index_type lnum, Line *l) {
    init_line(self, index_of(self, lnum), l);
}

void
historybuf_mark_line_clean(HistoryBuf *self, index_type y) {
    self->line_attrs[index_of(self, y)] &= ~TEXT_DIRTY_MASK;
}

void
historybuf_mark_line_dirty(HistoryBuf *self, index_type y) {
    self->line_attrs[index_of(self, y)] |= TEXT_DIRTY_MASK;
}

inline void
historybuf_clear(HistoryBuf *self) {
    self->count = 0;
    self->start_of_data = 0;
}

static inline index_type
historybuf_push(HistoryBuf *self) {
    index_type idx = (self->start_of_data + self->count) % self->ynum;
    init_line(self, idx, self->line);
    if (self->count == self->ynum) self->start_of_data = (self->start_of_data + 1) % self->ynum;
    else self->count++;
    return idx;
}

bool
historybuf_resize(HistoryBuf *self, index_type lines) {
    HistoryBuf t = {{0}};
    t.xnum=self->xnum;
    t.ynum=lines;
    if (t.ynum > 0 && t.ynum != self->ynum) {
        t.buf = PyMem_Calloc(t.xnum * t.ynum, sizeof(Cell));
        if (t.buf == NULL) { PyErr_NoMemory(); return false; }
        t.line_attrs = PyMem_Calloc(t.ynum, sizeof(line_attrs_type));
        if (t.line_attrs == NULL) { PyMem_Free(t.buf); PyErr_NoMemory(); return false; }
        t.count = MIN(self->count, t.ynum);
        for (index_type s=0; s < t.count; s++) {
            index_type si = index_of(self, s), ti = index_of(&t, s);
            copy_cells(lineptr(self, si), lineptr(&t, ti), t.xnum);
            t.line_attrs[ti] = self->line_attrs[si];
        }
        self->count = t.count;
        self->start_of_data = t.start_of_data;
        self->ynum = t.ynum;
        PyMem_Free(self->buf); PyMem_Free(self->line_attrs);
        self->buf = t.buf; self->line_attrs = t.line_attrs;
    }
    return true;
}

void
historybuf_add_line(HistoryBuf *self, const Line *line) {
    index_type idx = historybuf_push(self);
    copy_line(line, self->line);
    self->line_attrs[idx] = (line->continued & CONTINUED_MASK) | (line->has_dirty_text ? TEXT_DIRTY_MASK : 0);
}

static PyObject*
change_num_of_lines(HistoryBuf *self, PyObject *val) {
#define change_num_of_lines_doc "Change the number of lines in this buffer"
    if(!historybuf_resize(self, (index_type)PyLong_AsUnsignedLong(val))) return NULL;
    Py_RETURN_NONE;
}

static PyObject*
line(HistoryBuf *self, PyObject *val) {
#define line_doc "Return the line with line number val. This buffer grows upwards, i.e. 0 is the most recently added line"
    if (self->count == 0) { PyErr_SetString(PyExc_IndexError, "This buffer is empty"); return NULL; }
    index_type lnum = PyLong_AsUnsignedLong(val);
    if (lnum >= self->count) { PyErr_SetString(PyExc_IndexError, "Out of bounds"); return NULL; }
    init_line(self, index_of(self, lnum), self->line);
    Py_INCREF(self->line);
    return (PyObject*)self->line;
}

static PyObject*
__str__(HistoryBuf *self) {
    PyObject *lines = PyTuple_New(self->ynum);
    if (lines == NULL) return PyErr_NoMemory();
    for (index_type i = 0; i < self->count; i++) {
        init_line(self, index_of(self, i), self->line);
        PyObject *t = PyObject_Str((PyObject*)self->line);
        if (t == NULL) { Py_CLEAR(lines); return NULL; }
        PyTuple_SET_ITEM(lines, i, t);
    }
    PyObject *sep = PyUnicode_FromString("\n");
    PyObject *ans = PyUnicode_Join(sep, lines);
    Py_CLEAR(lines); Py_CLEAR(sep);
    return ans;
}

static PyObject*
push(HistoryBuf *self, PyObject *args) {
#define push_doc "Push a line into this buffer, removing the oldest line, if necessary"
    Line *line;
    if (!PyArg_ParseTuple(args, "O!", &Line_Type, &line)) return NULL;
    historybuf_add_line(self, line);
    Py_RETURN_NONE;
}

static PyObject*
as_ansi(HistoryBuf *self, PyObject *callback) {
#define as_ansi_doc "as_ansi(callback) -> The contents of this buffer as ANSI escaped text. callback is called with each successive line."
    static Py_UCS4 t[5120];
    Line l = {.xnum=self->xnum};
    for(unsigned int i = 0; i < self->count; i++) {
        init_line(self, i, &l);
        if (i < self->count - 1) {
            l.continued = self->line_attrs[index_of(self, i + 1)] & CONTINUED_MASK;
        } else l.continued = false;
        index_type num = line_as_ansi(&l, t, 5120);
        if (!(l.continued) && num < 5119) t[num++] = 10; // 10 = \n
        PyObject *ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, t, num);
        if (ans == NULL) return PyErr_NoMemory();
        PyObject *ret = PyObject_CallFunctionObjArgs(callback, ans, NULL);
        Py_CLEAR(ans);
        if (ret == NULL) return NULL;
        Py_CLEAR(ret);
    }
    Py_RETURN_NONE;
}

static PyObject*
dirty_lines(HistoryBuf *self) {
#define dirty_lines_doc "dirty_lines() -> Line numbers of all lines that have dirty text."
    PyObject *ans = PyList_New(0);
    for (index_type i = 0; i < self->ynum; i++) {
        if (self->line_attrs[i] & TEXT_DIRTY_MASK) {
            PyList_Append(ans, PyLong_FromUnsignedLong(i));
        }
    }
    return ans;
}


// Boilerplate {{{
static PyObject* rewrap(HistoryBuf *self, PyObject *args);
#define rewrap_doc ""

static PyMethodDef methods[] = {
    METHOD(change_num_of_lines, METH_O)
    METHOD(line, METH_O)
    METHOD(as_ansi, METH_O)
    METHOD(dirty_lines, METH_NOARGS)
    METHOD(push, METH_VARARGS)
    METHOD(rewrap, METH_VARARGS)
    {NULL, NULL, 0, NULL}  /* Sentinel */
};

static PyMemberDef members[] = {
    {"xnum", T_UINT, offsetof(HistoryBuf, xnum), READONLY, "xnum"},
    {"ynum", T_UINT, offsetof(HistoryBuf, ynum), READONLY, "ynum"},
    {"count", T_UINT, offsetof(HistoryBuf, count), READONLY, "count"},
    {NULL}  /* Sentinel */
};

PyTypeObject HistoryBuf_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.HistoryBuf",
    .tp_basicsize = sizeof(HistoryBuf),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "History buffers",
    .tp_methods = methods,
    .tp_members = members,
    .tp_str = (reprfunc)__str__,
    .tp_new = new
};

INIT_TYPE(HistoryBuf)

HistoryBuf *alloc_historybuf(unsigned int lines, unsigned int columns) {
    return (HistoryBuf*)new(&HistoryBuf_Type, Py_BuildValue("II", lines, columns), NULL);
}
// }}}

#define BufType HistoryBuf

#define map_src_index(y) ((src->start_of_data + y) % src->ynum)

#define init_src_line(src_y) init_line(src, map_src_index(src_y), src->line);

#define is_src_line_continued(src_y) (map_src_index(src_y) < src->ynum - 1 ? (src->line_attrs[map_src_index(src_y + 1)] & CONTINUED_MASK) : false)

#define next_dest_line(cont) dest->line_attrs[historybuf_push(dest)] = cont & CONTINUED_MASK; dest->line->continued = cont;

#define first_dest_line next_dest_line(false);

#include "rewrap.h"

void historybuf_rewrap(HistoryBuf *self, HistoryBuf *other) {
    // Fast path
    if (other->xnum == self->xnum && other->ynum == self->ynum) {
        memcpy(other->buf, self->buf, sizeof(Cell) * self->xnum * self->ynum);
        memcpy(other->line_attrs, self->line_attrs, sizeof(line_attrs_type) * self->ynum);
        other->count = self->count; other->start_of_data = self->start_of_data;
        return;
    }
    other->count = 0; other->start_of_data = 0;
    if (self->count > 0) {
        rewrap_inner(self, other, self->count, NULL);
        for (index_type i = 0; i < other->count; i++) other->line_attrs[(other->start_of_data + i) % other->ynum] |= TEXT_DIRTY_MASK;
    }
}

static PyObject*
rewrap(HistoryBuf *self, PyObject *args) {
    HistoryBuf *other;
    if (!PyArg_ParseTuple(args, "O!", &HistoryBuf_Type, &other)) return NULL;
    historybuf_rewrap(self, other);
    Py_RETURN_NONE;
}
