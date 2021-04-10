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
#include "ringbuf.h"

extern PyTypeObject Line_Type;
#define SEGMENT_SIZE 2048

static inline void
add_segment(HistoryBuf *self) {
    self->num_segments += 1;
    self->segments = realloc(self->segments, sizeof(HistoryBufSegment) * self->num_segments);
    if (self->segments == NULL) fatal("Out of memory allocating new history buffer segment");
    HistoryBufSegment *s = self->segments + self->num_segments - 1;
    const size_t cpu_cells_size = self->xnum * SEGMENT_SIZE * sizeof(CPUCell);
    const size_t gpu_cells_size = self->xnum * SEGMENT_SIZE * sizeof(GPUCell);
    s->cpu_cells = calloc(1, cpu_cells_size + gpu_cells_size + SEGMENT_SIZE * sizeof(line_attrs_type));
    if (!s->cpu_cells) fatal("Out of memory allocating new history buffer segment");
    s->gpu_cells = (GPUCell*)(((uint8_t*)s->cpu_cells) + cpu_cells_size);
    s->line_attrs = (line_attrs_type*)(((uint8_t*)s->gpu_cells) + gpu_cells_size);
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
    ph = calloc(1, sizeof(PagerHistoryBuf));
    if (!ph) return NULL;
    size_t sz = MIN(1024u * 1024u, pagerhist_sz);
    ph->ringbuf = ringbuf_new(sz);
    if (!ph->ringbuf) { free(ph); return NULL; }
    ph->maximum_size = pagerhist_sz;
    return ph;
}

static inline void
free_pagerhist(HistoryBuf *self) {
    if (self->pagerhist && self->pagerhist->ringbuf) ringbuf_free((ringbuf_t*)&self->pagerhist->ringbuf);
    free(self->pagerhist);
    self->pagerhist = NULL;
}

static inline bool
pagerhist_extend(PagerHistoryBuf *ph, size_t minsz) {
    size_t buffer_size = ringbuf_capacity(ph->ringbuf);
    if (buffer_size >= ph->maximum_size) return false;
    size_t newsz = MIN(ph->maximum_size, buffer_size + MAX(1024u * 1024u, minsz));
    ringbuf_t newbuf = ringbuf_new(newsz);
    if (!newbuf) return false;
    size_t count = ringbuf_bytes_used(ph->ringbuf);
    if (count) ringbuf_copy(newbuf, ph->ringbuf, count);
    ringbuf_free((ringbuf_t*)&ph->ringbuf);
    ph->ringbuf = newbuf;
    return true;
}

static inline void
pagerhist_clear(HistoryBuf *self) {
    if (self->pagerhist && self->pagerhist->ringbuf) ringbuf_reset(self->pagerhist->ringbuf);
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
    for (size_t i = 0; i < self->num_segments; i++) free(self->segments[i].cpu_cells);
    free(self->segments);
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
    if (sz > ph->maximum_size) return false;
    if (!sz) return true;
    size_t space_in_ringbuf = ringbuf_bytes_free(ph->ringbuf);
    if (sz > space_in_ringbuf) pagerhist_extend(ph, sz);
    ringbuf_memcpy_into(ph->ringbuf, buf, sz);
    return true;
}

static inline bool
pagerhist_ensure_start_is_valid_utf8(PagerHistoryBuf *ph) {
    uint8_t scratch[8];
    size_t num = ringbuf_memcpy_from(scratch, ph->ringbuf, arraysz(scratch));
    uint32_t codep;
    UTF8State state = UTF8_ACCEPT;
    size_t count = 0;
    size_t last_reject_at = 0;
    while (count < num) {
        decode_utf8(&state, &codep, scratch[count++]);
        if (state == UTF8_ACCEPT) break;
        if (state == UTF8_REJECT) { state = UTF8_ACCEPT; last_reject_at = count; }
    }
    if (last_reject_at) {
        ringbuf_memmove_from(scratch, ph->ringbuf, last_reject_at);
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
    if (ringbuf_bytes_used(ph->ringbuf) && !l.continued) pagerhist_write_bytes(ph, (const uint8_t*)"\n", 1);
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

bool
historybuf_pop_line(HistoryBuf *self, Line *line) {
    if (self->count <= 0) return false;
    index_type idx = (self->start_of_data + self->count - 1) % self->ynum;
    init_line(self, idx, line);
    self->count--;
    return true;
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
        PyObject *t = line_as_unicode(self->line, false);
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
pagerhist_remove_char(PagerHistoryBuf *ph, unsigned *count, uint8_t record[8]) {
    uint32_t codep; UTF8State state = UTF8_ACCEPT;
    *count = 0;
    size_t num = ringbuf_bytes_used(ph->ringbuf);
    while (num--) {
        record[*count] = ringbuf_move_char(ph->ringbuf);
        decode_utf8(&state, &codep, record[*count]);
        *count += 1;
        if (state == UTF8_REJECT) { codep = 0; break; }
        if (state == UTF8_ACCEPT) break;
    }
    return codep;
}

static void
pagerhist_rewrap_to(HistoryBuf *self, index_type cells_in_line) {
    PagerHistoryBuf *ph = self->pagerhist;
    if (!ph->ringbuf || !ringbuf_bytes_used(ph->ringbuf)) return;
    PagerHistoryBuf *nph = calloc(sizeof(PagerHistoryBuf), 1);
    if (!nph) return;
    nph->maximum_size = ph->maximum_size;
    nph->ringbuf = ringbuf_new(MIN(ph->maximum_size, ringbuf_capacity(ph->ringbuf) + 4096));
    if (!nph->ringbuf) { free(nph); return ; }
    ssize_t ch_width = 0;
    unsigned count;
    uint8_t record[8];
    index_type num_in_current_line = 0;
    char_type ch;
    WCSState wcs_state;
    initialize_wcs_state(&wcs_state);

#define WRITE_CHAR() { \
    if (num_in_current_line + ch_width > cells_in_line) { \
        pagerhist_write_bytes(nph, (const uint8_t*)"\r", 1); \
        num_in_current_line = 0; \
    }\
    if (ch_width >= 0 || (int)num_in_current_line >= -ch_width) num_in_current_line += ch_width; \
    pagerhist_write_bytes(nph, record, count); \
}

    while (ringbuf_bytes_used(ph->ringbuf)) {
        ch = pagerhist_remove_char(ph, &count, record);
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
#undef WRITE_CHAR
}

static PyObject*
pagerhist_write(HistoryBuf *self, PyObject *what) {
    if (self->pagerhist && self->pagerhist->maximum_size) {
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
#define ph self->pagerhist
    if (!ph || !ringbuf_bytes_used(ph->ringbuf)) return PyBytes_FromStringAndSize("", 0);
    pagerhist_ensure_start_is_valid_utf8(ph);
    if (ph->rewrap_needed) pagerhist_rewrap_to(self, self->xnum);

    Line l = {.xnum=self->xnum}; get_line(self, 0, &l);
    size_t sz = ringbuf_bytes_used(ph->ringbuf);
    if (!l.continued) sz += 1;
    PyObject *ans = PyBytes_FromStringAndSize(NULL, sz);
    if (!ans) return NULL;
    uint8_t *buf = (uint8_t*)PyBytes_AS_STRING(ans);
    ringbuf_memcpy_from(buf, ph->ringbuf, sz);
    if (!l.continued) buf[sz-1] = '\n';
    return ans;
#undef ph
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
    if (other->pagerhist && other->xnum != self->xnum && ringbuf_bytes_used(other->pagerhist->ringbuf))
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
