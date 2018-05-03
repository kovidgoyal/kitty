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
#define SEGMENT_SIZE 2048

static inline void
add_segment(HistoryBuf *self) {
    self->num_segments += 1;
    self->segments = PyMem_Realloc(self->segments, sizeof(HistoryBufSegment) * self->num_segments);
    if (self->segments == NULL) fatal("Out of memory allocating new history buffer segment");
    HistoryBufSegment *s = self->segments + self->num_segments - 1;
    s->cells = PyMem_Calloc(self->xnum * SEGMENT_SIZE, sizeof(Cell));
    s->line_attrs = PyMem_Calloc(SEGMENT_SIZE, sizeof(line_attrs_type));
    if (s->cells == NULL || s->line_attrs == NULL) fatal("Out of memory allocating new history buffer segment");
}

static inline index_type
segment_for(HistoryBuf *self, index_type y) {
    index_type seg_num = y / SEGMENT_SIZE;
    while (UNLIKELY(seg_num >= self->num_segments && SEGMENT_SIZE * self->num_segments < self->ynum)) add_segment(self);
    if (UNLIKELY(seg_num >= self->num_segments)) fatal("Out of bounds access to history buffer line number: %u", y);
    return seg_num;
}

#define seg_ptr(which, stride) { \
    index_type seg_num = segment_for(self, y); \
    y -= seg_num * SEGMENT_SIZE; \
    return self->segments[seg_num].which + y * stride; \
}

static inline Cell*
lineptr(HistoryBuf *self, index_type y) {
    seg_ptr(cells, self->xnum);
}


static inline line_attrs_type*
attrptr(HistoryBuf *self, index_type y) {
    seg_ptr(line_attrs, 1);
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
        self->line = alloc_line();
        self->num_segments = 0;
        add_segment(self);
        self->line->xnum = xnum;
        for(index_type y = 0; y < self->ynum; y++) {
            clear_chars_in_line(lineptr(self, y), self->xnum, BLANK_CHAR);
        }
    }

    return (PyObject*)self;
}

static void
dealloc(HistoryBuf* self) {
    Py_CLEAR(self->line);
    for (size_t i = 0; i < self->num_segments; i++) {
        PyMem_Free(self->segments[i].cells);
        PyMem_Free(self->segments[i].line_attrs);
    }
    PyMem_Free(self->segments);
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
    l->continued = *attrptr(self, num) & CONTINUED_MASK;
    l->has_dirty_text = *attrptr(self, num) & TEXT_DIRTY_MASK ? true : false;
}

void
historybuf_init_line(HistoryBuf *self, index_type lnum, Line *l) {
    init_line(self, index_of(self, lnum), l);
}

void
historybuf_mark_line_clean(HistoryBuf *self, index_type y) {
    line_attrs_type *p = attrptr(self, index_of(self, y));
    *p &= ~TEXT_DIRTY_MASK;
}

void
historybuf_mark_line_dirty(HistoryBuf *self, index_type y) {
    line_attrs_type *p = attrptr(self, index_of(self, y));
    *p |= TEXT_DIRTY_MASK;
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

void
historybuf_add_line(HistoryBuf *self, const Line *line) {
    index_type idx = historybuf_push(self);
    copy_line(line, self->line);
    *attrptr(self, idx) = (line->continued & CONTINUED_MASK) | (line->has_dirty_text ? TEXT_DIRTY_MASK : 0);
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
        PyObject *t = line_as_unicode(self->line);
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
            l.continued = *attrptr(self, index_of(self, i + 1)) & CONTINUED_MASK;
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

static inline Line*
get_line(HistoryBuf *self, index_type y, Line *l) { init_line(self, y, l); return l; }

static PyObject*
as_text(HistoryBuf *self, PyObject *args) {
    Line l = {.xnum=self->xnum};
#define gl(self, y) get_line(self, y, &l);
    as_text_generic(args, self, gl, self->count, self->xnum, callback, as_ansi);
#undef gl
}


static PyObject*
dirty_lines(HistoryBuf *self, PyObject *a UNUSED) {
#define dirty_lines_doc "dirty_lines() -> Line numbers of all lines that have dirty text."
    PyObject *ans = PyList_New(0);
    for (index_type i = 0; i < self->ynum; i++) {
        if (*attrptr(self, i) & TEXT_DIRTY_MASK) {
            PyList_Append(ans, PyLong_FromUnsignedLong(i));
        }
    }
    return ans;
}


// Boilerplate {{{
static PyObject* rewrap(HistoryBuf *self, PyObject *args);
#define rewrap_doc ""

static PyMethodDef methods[] = {
    METHOD(line, METH_O)
    METHOD(as_ansi, METH_O)
    METHODB(as_text, METH_VARARGS),
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

#define is_src_line_continued(src_y) (map_src_index(src_y) < src->ynum - 1 ? (*attrptr(src, map_src_index(src_y + 1)) & CONTINUED_MASK) : false)

#define next_dest_line(cont) *attrptr(dest, historybuf_push(dest)) = cont & CONTINUED_MASK; dest->line->continued = cont;

#define first_dest_line next_dest_line(false);

#include "rewrap.h"

void historybuf_rewrap(HistoryBuf *self, HistoryBuf *other) {
    while(other->num_segments < self->num_segments) add_segment(other);
    if (other->xnum == self->xnum && other->ynum == self->ynum) {
        // Fast path
        for (index_type i = 0; i < self->num_segments; i++) {
            memcpy(other->segments[i].cells, self->segments[i].cells, SEGMENT_SIZE * self->xnum * sizeof(Cell));
            memcpy(other->segments[i].line_attrs, self->segments[i].line_attrs, SEGMENT_SIZE * sizeof(line_attrs_type));
        }
        other->count = self->count; other->start_of_data = self->start_of_data;
        return;
    }
    other->count = 0; other->start_of_data = 0;
    index_type x = 0, y = 0;
    if (self->count > 0) {
        rewrap_inner(self, other, self->count, NULL, &x, &y);
        for (index_type i = 0; i < other->count; i++) *attrptr(other, (other->start_of_data + i) % other->ynum) |= TEXT_DIRTY_MASK;
    }
}

static PyObject*
rewrap(HistoryBuf *self, PyObject *args) {
    HistoryBuf *other;
    if (!PyArg_ParseTuple(args, "O!", &HistoryBuf_Type, &other)) return NULL;
    historybuf_rewrap(self, other);
    Py_RETURN_NONE;
}
