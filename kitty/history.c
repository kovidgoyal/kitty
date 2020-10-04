/*
 * history.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "wcswidth.h"
#include "lineops.h"
#include "charsets.h"
#include <structmember.h>

extern PyTypeObject Line_Type;
#define SEGMENT_SIZE 2048

static inline void
add_segment(HistoryBuf *self) {
    self->num_segments += 1;
    self->segments = PyMem_Realloc(self->segments, sizeof(HistoryBufSegment) * self->num_segments);
    if (self->segments == NULL) fatal("Out of memory allocating new history buffer segment");
    HistoryBufSegment *s = self->segments + self->num_segments - 1;
    s->cpu_cells = PyMem_Calloc(self->xnum * SEGMENT_SIZE, sizeof(CPUCell));
    s->gpu_cells = PyMem_Calloc(self->xnum * SEGMENT_SIZE, sizeof(GPUCell));
    s->line_attrs = PyMem_Calloc(SEGMENT_SIZE, sizeof(line_attrs_type));
    if (s->cpu_cells == NULL || s->gpu_cells == NULL || s->line_attrs == NULL) fatal("Out of memory allocating new history buffer segment");
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

static inline CPUCell*
cpu_lineptr(HistoryBuf *self, index_type y) {
    seg_ptr(cpu_cells, self->xnum);
}

static inline GPUCell*
gpu_lineptr(HistoryBuf *self, index_type y) {
    seg_ptr(gpu_cells, self->xnum);
}


static inline line_attrs_type*
attrptr(HistoryBuf *self, index_type y) {
    seg_ptr(line_attrs, 1);
}

static inline PagerHistoryBuf*
alloc_pagerhist(size_t pagerhist_sz) {
    PagerHistoryBuf *ph;
    if (!pagerhist_sz) return NULL;
    ph = PyMem_Calloc(1, sizeof(PagerHistoryBuf));
    if (!ph) return NULL;
    ph->max_sz = pagerhist_sz;
    ph->buffer_size = MIN(1024u*1024u, ph->max_sz);
    ph->buffer = PyMem_RawMalloc(ph->buffer_size);
    if (!ph->buffer) { PyMem_Free(ph); return NULL; }
    return ph;
}

static inline void
free_pagerhist(HistoryBuf *self) {
    if (self->pagerhist) PyMem_Free(self->pagerhist->buffer);
    PyMem_Free(self->pagerhist);
    self->pagerhist = NULL;
}

static inline bool
pagerhist_extend(PagerHistoryBuf *ph, size_t minsz) {
    if (ph->buffer_size >= ph->max_sz) return false;
    size_t newsz = ph->buffer_size + MAX(1024u * 1024u, minsz);
    uint8_t *newbuf = PyMem_Malloc(MIN(ph->buffer_size + minsz, ph->max_sz));
    if (!newbuf) return false;
    size_t copied = MIN(ph->length, ph->buffer_size - ph->start);
    if (copied) memcpy(newbuf, ph->buffer + ph->start, copied);
    if (copied < ph->length) memcpy(newbuf + copied, ph->buffer, (ph->length - copied));
    PyMem_Free(ph->buffer);
    ph->start = 0;
    ph->buffer = newbuf;
    ph->buffer_size = newsz;
    return true;
}

static inline void
pagerhist_clear(HistoryBuf *self) {
    if (!self->pagerhist || !self->pagerhist->max_sz) return;
    index_type pagerhist_sz = self->pagerhist->max_sz;
    free_pagerhist(self);
    self->pagerhist = alloc_pagerhist(pagerhist_sz);
}

static HistoryBuf*
create_historybuf(PyTypeObject *type, unsigned int xnum, unsigned int ynum, unsigned int pagerhist_sz) {
    if (xnum == 0 || ynum == 0) {
        PyErr_SetString(PyExc_ValueError, "Cannot create an empty history buffer");
        return NULL;
    }
    HistoryBuf *self = (HistoryBuf *)type->tp_alloc(type, 0);
    if (self != NULL) {
        self->xnum = xnum;
        self->ynum = ynum;
        self->num_segments = 0;
        add_segment(self);
        self->line = alloc_line();
        self->line->xnum = xnum;
        self->pagerhist = alloc_pagerhist(pagerhist_sz);
    }
    return self;
}

static PyObject *
new(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    unsigned int xnum = 1, ynum = 1, pagerhist_sz = 0;
    if (!PyArg_ParseTuple(args, "II|I", &ynum, &xnum, &pagerhist_sz)) return NULL;
    HistoryBuf *ans = create_historybuf(type, xnum, ynum, pagerhist_sz);
    return (PyObject*)ans;
}

static void
dealloc(HistoryBuf* self) {
    Py_CLEAR(self->line);
    for (size_t i = 0; i < self->num_segments; i++) {
        PyMem_Free(self->segments[i].cpu_cells);
        PyMem_Free(self->segments[i].gpu_cells);
        PyMem_Free(self->segments[i].line_attrs);
    }
    PyMem_Free(self->segments);
    free_pagerhist(self);
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
    l->cpu_cells = cpu_lineptr(self, num);
    l->gpu_cells = gpu_lineptr(self, num);
    l->continued = *attrptr(self, num) & CONTINUED_MASK;
    l->has_dirty_text = *attrptr(self, num) & TEXT_DIRTY_MASK ? true : false;
}

void
historybuf_init_line(HistoryBuf *self, index_type lnum, Line *l) {
    init_line(self, index_of(self, lnum), l);
}

CPUCell*
historybuf_cpu_cells(HistoryBuf *self, index_type lnum) {
    return cpu_lineptr(self, index_of(self, lnum));
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

void
historybuf_clear(HistoryBuf *self) {
    pagerhist_clear(self);
    self->count = 0;
    self->start_of_data = 0;
}

static inline bool
pagerhist_write_bytes(PagerHistoryBuf *ph, const uint8_t *buf, size_t sz) {
    if (sz > ph->max_sz) return false;
    if (!sz) return true;
    if (sz > ph->buffer_size - ph->length) pagerhist_extend(ph, sz);
    if (sz > ph->buffer_size) return false;
    size_t start_writing_at = (ph->start + ph->length) % ph->buffer_size;
    size_t available_space = ph->buffer_size - ph->length;
    size_t overlap = available_space < sz ? sz - available_space : 0;
    size_t copied = MIN(sz, ph->buffer_size - start_writing_at);
    ph->length += sz - overlap;
    ph->start = (ph->start + overlap) % ph->buffer_size;
    if (copied) memcpy(ph->buffer + start_writing_at, buf, copied);
    if (copied < sz) memcpy(ph->buffer, buf + copied, (sz - copied));
    return true;
}

static inline bool
pagerhist_ensure_start_is_valid_utf8(PagerHistoryBuf *ph) {
    uint32_t state = UTF8_ACCEPT, codep;
    size_t pos = ph->start, count = 0;
    size_t last_reject_at = 0;
    while (count < ph->length) {
        decode_utf8(&state, &codep, ph->buffer[pos]);
        count++;
        if (state == UTF8_ACCEPT) break;
        if (state == UTF8_REJECT) { state = UTF8_ACCEPT; last_reject_at = count; }
        pos = pos == ph->buffer_size - 1 ? 0: pos + 1;
    }
    if (last_reject_at) {
        ph->start = (ph->start + last_reject_at) % ph->buffer_size;
        ph->length -= last_reject_at;
        return true;
    }
    return false;
}

static inline bool
pagerhist_write_ucs4(PagerHistoryBuf *ph, const Py_UCS4 *buf, size_t sz) {
    uint8_t scratch[4];
    for (size_t i = 0; i < sz; i++) {
        unsigned int num = encode_utf8(buf[i], (char*)scratch);
        if (!pagerhist_write_bytes(ph, scratch, num)) return false;
    }
    return true;
}

static inline void
pagerhist_push(HistoryBuf *self, ANSIBuf *as_ansi_buf) {
    PagerHistoryBuf *ph = self->pagerhist;
    if (!ph) return;
    const GPUCell *prev_cell = NULL;
    Line l = {.xnum=self->xnum};
    init_line(self, self->start_of_data, &l);
    line_as_ansi(&l, as_ansi_buf, &prev_cell);
    if (ph->length != 0 && !l.continued) pagerhist_write_bytes(ph, (const uint8_t*)"\n", 1);
    pagerhist_write_bytes(ph, (const uint8_t*)"\x1b[m", 3);
    if (pagerhist_write_ucs4(ph, as_ansi_buf->buf, as_ansi_buf->len)) pagerhist_write_bytes(ph, (const uint8_t*)"\r", 1);
}

static inline index_type
historybuf_push(HistoryBuf *self, ANSIBuf *as_ansi_buf) {
    index_type idx = (self->start_of_data + self->count) % self->ynum;
    init_line(self, idx, self->line);
    if (self->count == self->ynum) {
        pagerhist_push(self, as_ansi_buf);
        self->start_of_data = (self->start_of_data + 1) % self->ynum;
    } else self->count++;
    return idx;
}

void
historybuf_add_line(HistoryBuf *self, const Line *line, ANSIBuf *as_ansi_buf) {
    index_type idx = historybuf_push(self, as_ansi_buf);
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
    PyObject *lines = PyTuple_New(self->count);
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
    ANSIBuf as_ansi_buf = {0};
    historybuf_add_line(self, line, &as_ansi_buf);
    free(as_ansi_buf.buf);
    Py_RETURN_NONE;
}

static PyObject*
as_ansi(HistoryBuf *self, PyObject *callback) {
#define as_ansi_doc "as_ansi(callback) -> The contents of this buffer as ANSI escaped text. callback is called with each successive line."
    Line l = {.xnum=self->xnum};
    const GPUCell *prev_cell = NULL;
    ANSIBuf output = {0};
    for(unsigned int i = 0; i < self->count; i++) {
        init_line(self, i, &l);
        if (i < self->count - 1) {
            l.continued = *attrptr(self, index_of(self, i + 1)) & CONTINUED_MASK;
        } else l.continued = false;
        line_as_ansi(&l, &output, &prev_cell);
        if (!l.continued) {
            ensure_space_for(&output, buf, Py_UCS4, output.len + 1, capacity, 2048, false);
            output.buf[output.len++] = 10; // 10 = \n
        }
        PyObject *ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, output.buf, output.len);
        if (ans == NULL) { PyErr_NoMemory(); goto end; }
        PyObject *ret = PyObject_CallFunctionObjArgs(callback, ans, NULL);
        Py_CLEAR(ans);
        if (ret == NULL) goto end;
        Py_CLEAR(ret);
    }
end:
    free(output.buf);
    if (PyErr_Occurred()) return NULL;
    Py_RETURN_NONE;
}

static inline Line*
get_line(HistoryBuf *self, index_type y, Line *l) { init_line(self, index_of(self, self->count - y - 1), l); return l; }

static inline char_type
pagerhist_read_char(PagerHistoryBuf *ph, size_t pos, unsigned *count, uint8_t record[8]) {
    uint32_t codep, state = UTF8_ACCEPT;
    *count = 0;
    while (true) {
        decode_utf8(&state, &codep, ph->buffer[pos]);
        record[(*count)++] = ph->buffer[pos];
        if (state == UTF8_REJECT) { codep = 0; break; }
        if (state == UTF8_ACCEPT) break;
        pos = pos == ph->buffer_size - 1 ? 0 : (pos + 1);
    }
    return codep;
}

static void
pagerhist_rewrap_to(HistoryBuf *self, index_type cells_in_line) {
    PagerHistoryBuf *ph = self->pagerhist;
    if (!ph->length) return;
    PagerHistoryBuf *nph = PyMem_Calloc(sizeof(PagerHistoryBuf), 1);
    if (!nph) return;
    nph->buffer_size = ph->buffer_size;
    nph->max_sz = ph->max_sz;
    nph->buffer = PyMem_Malloc(nph->buffer_size);
    if (!nph->buffer) { PyMem_Free(nph); return ; }
    size_t i = 0, pos;
    ssize_t ch_width = 0;
    unsigned count;
    uint8_t record[8];
    index_type num_in_current_line = 0;
    char_type ch;
    WCSState wcs_state;
    initialize_wcs_state(&wcs_state);

#define READ_CHAR(ch) { \
    ch = pagerhist_read_char(ph, pos, &count, record); \
    i += count; pos += count; \
    if (pos >= ph->buffer_size) pos = pos - ph->buffer_size; \
}
#define WRITE_CHAR() { \
    if (num_in_current_line + ch_width > cells_in_line) { \
        pagerhist_write_bytes(nph, (const uint8_t*)"\r", 1); \
        num_in_current_line = 0; \
    }\
    if (ch_width >= 0 || (int)num_in_current_line >= -ch_width) num_in_current_line += ch_width; \
    pagerhist_write_bytes(nph, record, count); \
}

    for (i = 0; i < ph->length;) {
        pos = ph->start + i;
        if (pos >= ph->buffer_size) pos = pos - ph->buffer_size;
        READ_CHAR(ch);
        if (ch == '\n') {
            initialize_wcs_state(&wcs_state);
            ch_width = 1;
            WRITE_CHAR();
            num_in_current_line = 0;
        } else if (ch != '\r') {
            ch_width = wcswidth_step(&wcs_state, ch);
            WRITE_CHAR();
        }
    }
    free_pagerhist(self);
    self->pagerhist = nph;
#undef READ_CHAR
}

static PyObject*
pagerhist_write(HistoryBuf *self, PyObject *what) {
    if (self->pagerhist && self->pagerhist->max_sz) {
        if (PyBytes_Check(what)) pagerhist_write_bytes(self->pagerhist, (const uint8_t*)PyBytes_AS_STRING(what), PyBytes_GET_SIZE(what));
        else if (PyUnicode_Check(what) && PyUnicode_READY(what) == 0) {
            Py_UCS4 *buf = PyUnicode_AsUCS4Copy(what);
            if (buf) {
                pagerhist_write_ucs4(self->pagerhist, buf, PyUnicode_GET_LENGTH(what));
                PyMem_Free(buf);
            }
        }
    }
    Py_RETURN_NONE;
}

static PyObject*
pagerhist_as_bytes(HistoryBuf *self, PyObject *args UNUSED) {
    PagerHistoryBuf *ph = self->pagerhist;
    if (!ph || !ph->length) return PyBytes_FromStringAndSize("", 0);
    pagerhist_ensure_start_is_valid_utf8(ph);
    if (ph->rewrap_needed) pagerhist_rewrap_to(self, self->xnum);

    Line l = {.xnum=self->xnum}; get_line(self, 0, &l);
    size_t sz = ph->length;
    if (!l.continued) sz += 1;
    PyObject *ans = PyBytes_FromStringAndSize(NULL, sz);
    if (!ans) return NULL;
    uint8_t *buf = (uint8_t*)PyBytes_AS_STRING(ans);
    size_t copied = MIN(ph->length, ph->buffer_size - ph->start);
    if (copied) memcpy(buf, ph->buffer + ph->start, copied);
    if (copied < ph->length) memcpy(buf + copied, ph->buffer, (ph->length - copied));
    if (!l.continued) buf[sz-1] = '\n';
    return ans;
}

static PyObject *
pagerhist_as_text(HistoryBuf *self, PyObject *args) {
    PyObject *ans = NULL;
    PyObject *bytes = pagerhist_as_bytes(self, args);
    if (bytes) {
        ans = PyUnicode_DecodeUTF8(PyBytes_AS_STRING(bytes), PyBytes_GET_SIZE(bytes), "ignore");
        Py_DECREF(bytes);
    }
    return ans;
}

typedef struct {
    Line line;
    HistoryBuf *self;
} GetLineWrapper;

static Line*
get_line_wrapper(void *x, int y) {
    GetLineWrapper *glw = x;
    get_line(glw->self, y, &glw->line);
    return &glw->line;
}

static PyObject*
as_text(HistoryBuf *self, PyObject *args) {
    GetLineWrapper glw = {.self=self};
    glw.line.xnum = self->xnum;
    ANSIBuf output = {0};
    PyObject *ans = as_text_generic(args, &glw, get_line_wrapper, self->count, &output);
    free(output.buf);
    return ans;
}


static PyObject*
dirty_lines(HistoryBuf *self, PyObject *a UNUSED) {
#define dirty_lines_doc "dirty_lines() -> Line numbers of all lines that have dirty text."
    PyObject *ans = PyList_New(0);
    for (index_type i = 0; i < self->count; i++) {
        if (*attrptr(self, i) & TEXT_DIRTY_MASK) {
            PyList_Append(ans, PyLong_FromUnsignedLong(i));
        }
    }
    return ans;
}

static PyObject*
pagerhist_rewrap(HistoryBuf *self, PyObject *xnum) {
    if (self->pagerhist) {
        pagerhist_rewrap_to(self, PyLong_AsUnsignedLong(xnum));
    }
    Py_RETURN_NONE;
}


// Boilerplate {{{
static PyObject* rewrap(HistoryBuf *self, PyObject *args);
#define rewrap_doc ""

static PyMethodDef methods[] = {
    METHOD(line, METH_O)
    METHOD(as_ansi, METH_O)
    METHODB(pagerhist_write, METH_O),
    METHODB(pagerhist_rewrap, METH_O),
    METHODB(pagerhist_as_text, METH_NOARGS),
    METHODB(pagerhist_as_bytes, METH_NOARGS),
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

HistoryBuf *alloc_historybuf(unsigned int lines, unsigned int columns, unsigned int pagerhist_sz) {
    return create_historybuf(&HistoryBuf_Type, columns, lines, pagerhist_sz);
}
// }}}

#define BufType HistoryBuf

#define map_src_index(y) ((src->start_of_data + y) % src->ynum)

#define init_src_line(src_y) init_line(src, map_src_index(src_y), src->line);

#define is_src_line_continued(src_y) (map_src_index(src_y) < src->ynum - 1 ? (*attrptr(src, map_src_index(src_y + 1)) & CONTINUED_MASK) : false)

#define next_dest_line(cont) *attrptr(dest, historybuf_push(dest, as_ansi_buf)) = cont & CONTINUED_MASK; dest->line->continued = cont;

#define first_dest_line next_dest_line(false);

#include "rewrap.h"

void historybuf_rewrap(HistoryBuf *self, HistoryBuf *other, ANSIBuf *as_ansi_buf) {
    while(other->num_segments < self->num_segments) add_segment(other);
    if (other->xnum == self->xnum && other->ynum == self->ynum) {
        // Fast path
        for (index_type i = 0; i < self->num_segments; i++) {
            memcpy(other->segments[i].cpu_cells, self->segments[i].cpu_cells, SEGMENT_SIZE * self->xnum * sizeof(CPUCell));
            memcpy(other->segments[i].gpu_cells, self->segments[i].gpu_cells, SEGMENT_SIZE * self->xnum * sizeof(GPUCell));
            memcpy(other->segments[i].line_attrs, self->segments[i].line_attrs, SEGMENT_SIZE * sizeof(line_attrs_type));
        }
        other->count = self->count; other->start_of_data = self->start_of_data;
        return;
    }
    if (other->pagerhist && other->xnum != self->xnum && other->pagerhist->length)
        other->pagerhist->rewrap_needed = true;
    other->count = 0; other->start_of_data = 0;
    index_type x = 0, y = 0;
    if (self->count > 0) {
        rewrap_inner(self, other, self->count, NULL, &x, &y, as_ansi_buf);
        for (index_type i = 0; i < other->count; i++) *attrptr(other, (other->start_of_data + i) % other->ynum) |= TEXT_DIRTY_MASK;
    }
}

static PyObject*
rewrap(HistoryBuf *self, PyObject *args) {
    HistoryBuf *other;
    if (!PyArg_ParseTuple(args, "O!", &HistoryBuf_Type, &other)) return NULL;
    ANSIBuf as_ansi_buf = {0};
    historybuf_rewrap(self, other, &as_ansi_buf);
    free(as_ansi_buf.buf);
    Py_RETURN_NONE;
}
