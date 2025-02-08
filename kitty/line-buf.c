/*
 * line-buf.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "lineops.h"
#include "resize.h"

#include <structmember.h>

extern PyTypeObject Line_Type;
extern PyTypeObject HistoryBuf_Type;

static CPUCell*
cpu_lineptr(LineBuf *linebuf, index_type y) {
    return linebuf->cpu_cell_buf + y * linebuf->xnum;
}

static GPUCell*
gpu_lineptr(LineBuf *linebuf, index_type y) {
    return linebuf->gpu_cell_buf + y * linebuf->xnum;
}

static void
clear_chars_to(LineBuf* linebuf, index_type y, char_type ch) {
    clear_chars_in_line(cpu_lineptr(linebuf, y), gpu_lineptr(linebuf, y), linebuf->xnum, ch);
}

void
linebuf_clear(LineBuf *self, char_type ch) {
    zero_at_ptr_count(self->cpu_cell_buf, self->xnum * self->ynum);
    zero_at_ptr_count(self->gpu_cell_buf, self->xnum * self->ynum);
    zero_at_ptr_count(self->line_attrs, self->ynum);
    for (index_type i = 0; i < self->ynum; i++) self->line_map[i] = i;
    if (ch != 0) {
        for (index_type i = 0; i < self->ynum; i++) {
            clear_chars_to(self, i, ch);
            self->line_attrs[i].val = 0;
            self->line_attrs[i].has_dirty_text = true;
        }
    }
}

void
linebuf_mark_line_dirty(LineBuf *self, index_type y) {
    self->line_attrs[y].has_dirty_text = true;
}

void
linebuf_mark_line_clean(LineBuf *self, index_type y) {
    self->line_attrs[y].has_dirty_text = false;
}

void
linebuf_set_line_has_image_placeholders(LineBuf *self, index_type y, bool val) {
    self->line_attrs[y].has_image_placeholders = val;
}

void
linebuf_clear_attrs_and_dirty(LineBuf *self, index_type y) {
    self->line_attrs[y].val = 0;
    self->line_attrs[y].has_dirty_text = true;
}

static PyObject*
clear(LineBuf *self, PyObject *a UNUSED) {
#define clear_doc "Clear all lines in this LineBuf"
    linebuf_clear(self, BLANK_CHAR);
    Py_RETURN_NONE;
}

LineBuf *
alloc_linebuf_(PyTypeObject *cls, unsigned int lines, unsigned int columns, TextCache *text_cache) {
    if (columns > 5000 || lines > 50000) {
        PyErr_SetString(PyExc_ValueError, "Number of rows or columns is too large.");
        return NULL;
    }

    const size_t area = columns * lines;
    if (area == 0) {
        PyErr_SetString(PyExc_ValueError, "Cannot create an empty LineBuf");
        return NULL;
    }

    LineBuf *self = (LineBuf*)cls->tp_alloc(cls, 0);
    if (self != NULL) {
        self->xnum = columns;
        self->ynum = lines;
        self->cpu_cell_buf = PyMem_Calloc(1, area * (sizeof(CPUCell) + sizeof(GPUCell)) + lines * (sizeof(index_type) + sizeof(index_type) + sizeof(LineAttrs)));
        if (!self->cpu_cell_buf) { Py_CLEAR(self); return NULL; }
        self->gpu_cell_buf = (GPUCell*)(self->cpu_cell_buf + area);
        self->line_map = (index_type*)(self->gpu_cell_buf + area);
        self->scratch = self->line_map + lines;
        self->text_cache = tc_incref(text_cache);
        self->line = alloc_line(self->text_cache);
        self->line_attrs = (LineAttrs*)(self->scratch + lines);
        self->line->xnum = columns;
        for(index_type i = 0; i < lines; i++) {
            self->line_map[i] = i;
            if (BLANK_CHAR != 0) clear_chars_to(self, i, BLANK_CHAR);
        }
    }
    return self;
}

static PyObject *
new_linebuf_object(PyTypeObject *type, PyObject *args, PyObject UNUSED *kwds) {
    unsigned int xnum = 1, ynum = 1;

    if (!PyArg_ParseTuple(args, "II", &ynum, &xnum)) return NULL;
    TextCache *tc = tc_alloc();
    if (!tc) return PyErr_NoMemory();
    PyObject *ans = (PyObject*)alloc_linebuf_(type, ynum, xnum, tc);
    tc_decref(tc);
    return ans;
}

static void
dealloc(LineBuf* self) {
    self->text_cache = tc_decref(self->text_cache);
    PyMem_Free(self->cpu_cell_buf);
    Py_CLEAR(self->line);
    Py_TYPE(self)->tp_free((PyObject*)self);
}

void
linebuf_init_cells(LineBuf *lb, index_type idx, CPUCell **c, GPUCell **g) {
    const index_type ynum = lb->line_map[idx];
    *c = cpu_lineptr(lb, ynum);
    *g = gpu_lineptr(lb, ynum);
}

CPUCell*
linebuf_cpu_cells_for_line(LineBuf *lb, index_type idx) {
    const index_type ynum = lb->line_map[idx];
    return cpu_lineptr(lb, ynum);
}

static void
init_line(LineBuf *lb, Line *l, index_type ynum) {
    l->cpu_cells = cpu_lineptr(lb, ynum);
    l->gpu_cells = gpu_lineptr(lb, ynum);
}

void
linebuf_init_line_at(LineBuf *self, index_type idx, Line *line) {
    line->ynum = idx;
    line->xnum = self->xnum;
    line->attrs = self->line_attrs[idx];
    init_line(self, line, self->line_map[idx]);
}

void
linebuf_init_line(LineBuf *self, index_type idx) {
    linebuf_init_line_at(self, idx, self->line);
}

void
linebuf_clear_lines(LineBuf *self, const Cursor *cursor, index_type start, index_type end) {
#if BLANK_CHAR != 0
#error This implementation is incorrect for BLANK_CHAR != 0
#endif
#define lineptr(which, i) which##_lineptr(self, self->line_map[i])
    GPUCell *first_gpu_line = lineptr(gpu, start);
    const GPUCell gc = cursor_as_gpu_cell(cursor);
    memset_array(first_gpu_line, gc, self->xnum);
    const size_t cpu_stride = sizeof(CPUCell) * self->xnum;
    memset(lineptr(cpu, start), 0, cpu_stride);
    const size_t gpu_stride = sizeof(GPUCell) * self->xnum;
    linebuf_clear_attrs_and_dirty(self, start);
    for (index_type i = start + 1; i < end; i++) {
        memset(lineptr(cpu, i), 0, cpu_stride);
        memcpy(lineptr(gpu, i), first_gpu_line, gpu_stride);
        linebuf_clear_attrs_and_dirty(self, i);
    }
#undef lineptr
}

static PyObject*
line(LineBuf *self, PyObject *y) {
#define line_doc      "Return the specified line as a Line object. Note the Line Object is a live view into the underlying buffer. And only a single line object can be used at a time."
    unsigned long idx = PyLong_AsUnsignedLong(y);
    if (idx >= self->ynum) {
        PyErr_SetString(PyExc_IndexError, "Line number too large");
        return NULL;
    }
    linebuf_init_line(self, idx);
    Py_INCREF(self->line);
    return (PyObject*)self->line;
}

CPUCell*
linebuf_cpu_cell_at(LineBuf *self, index_type x, index_type y) {
    return &cpu_lineptr(self, self->line_map[y])[x];
}

bool
linebuf_line_ends_with_continuation(LineBuf *self, index_type y) {
    return y < self->ynum ? cpu_lineptr(self, self->line_map[y])[self->xnum - 1].next_char_was_wrapped : false;
}

void
linebuf_set_last_char_as_continuation(LineBuf *self, index_type y, bool continued) {
    if (y < self->ynum) {
        cpu_lineptr(self, self->line_map[y])[self->xnum - 1].next_char_was_wrapped = continued;
    }
}


static PyObject*
set_attribute(LineBuf *self, PyObject *args) {
#define set_attribute_doc "set_attribute(which, val) -> Set the attribute on all cells in the line."
    unsigned int val;
    char *which;
    if (!PyArg_ParseTuple(args, "sI", &which, &val)) return NULL;
    for (index_type y = 0; y < self->ynum; y++) {
        if (!set_named_attribute_on_line(gpu_lineptr(self, y), which, val, self->xnum)) {
            PyErr_SetString(PyExc_KeyError, "Unknown cell attribute"); return NULL;
        }
        self->line_attrs[y].has_dirty_text = true;
    }
    Py_RETURN_NONE;
}

static PyObject*
set_continued(LineBuf *self, PyObject *args) {
#define set_continued_doc "set_continued(y, val) -> Set the continued values for the specified line."
    unsigned int y;
    int val;
    if (!PyArg_ParseTuple(args, "Ip", &y, &val)) return NULL;
    if (y > self->ynum || y < 1) { PyErr_SetString(PyExc_ValueError, "Out of bounds."); return NULL; }
    linebuf_set_last_char_as_continuation(self, y-1, val);
    Py_RETURN_NONE;
}

static PyObject*
dirty_lines(LineBuf *self, PyObject *a UNUSED) {
#define dirty_lines_doc "dirty_lines() -> Line numbers of all lines that have dirty text."
    PyObject *ans = PyList_New(0);
    for (index_type i = 0; i < self->ynum; i++) {
        if (self->line_attrs[i].has_dirty_text) {
            PyList_Append(ans, PyLong_FromUnsignedLong(i));
        }
    }
    return ans;
}

static bool
allocate_line_storage(Line *line, bool initialize) {
    if (initialize) {
        line->cpu_cells = PyMem_Calloc(line->xnum, sizeof(CPUCell));
        line->gpu_cells = PyMem_Calloc(line->xnum, sizeof(GPUCell));
        if (line->cpu_cells == NULL || line->gpu_cells) { PyErr_NoMemory(); return false; }
        if (BLANK_CHAR != 0) clear_chars_in_line(line->cpu_cells, line->gpu_cells, line->xnum, BLANK_CHAR);
    } else {
        line->cpu_cells = PyMem_Malloc(line->xnum * sizeof(CPUCell));
        line->gpu_cells = PyMem_Malloc(line->xnum * sizeof(GPUCell));
        if (line->cpu_cells == NULL || line->gpu_cells == NULL) { PyErr_NoMemory(); return false; }
    }
    line->needs_free = 1;
    return true;
}

static PyObject*
create_line_copy_inner(LineBuf* self, index_type y) {
    Line src, *line;
    line = alloc_line(self->text_cache);
    if (line == NULL) return PyErr_NoMemory();
    src.xnum = self->xnum; line->xnum = self->xnum;
    if (!allocate_line_storage(line, 0)) { Py_CLEAR(line); return PyErr_NoMemory(); }
    line->ynum = y;
    line->attrs = self->line_attrs[y];
    init_line(self, &src, self->line_map[y]);
    copy_line(&src, line);
    return (PyObject*)line;
}

static PyObject*
create_line_copy(LineBuf *self, PyObject *ynum) {
#define create_line_copy_doc "Create a new Line object that is a copy of the line at ynum. Note that this line has its own copy of the data and does not refer to the data in the LineBuf."
    index_type y = (index_type)PyLong_AsUnsignedLong(ynum);
    if (y >= self->ynum) { PyErr_SetString(PyExc_ValueError, "Out of bounds"); return NULL; }
    return create_line_copy_inner(self, y);
}

static PyObject*
copy_line_to(LineBuf *self, PyObject *args) {
#define copy_line_to_doc "Copy the line at ynum to the provided line object."
    unsigned int y;
    Line src, *dest;
    if (!PyArg_ParseTuple(args, "IO!", &y, &Line_Type, &dest)) return NULL;
    src.xnum = self->xnum; dest->xnum = self->xnum;
    dest->ynum = y;
    dest->attrs = self->line_attrs[y];
    init_line(self, &src, self->line_map[y]);
    copy_line(&src, dest);
    Py_RETURN_NONE;
}

static void
clear_line_(Line *l, index_type xnum) {
#if BLANK_CHAR != 0
#error This implementation is incorrect for BLANK_CHAR != 0
#endif
    zero_at_ptr_count(l->cpu_cells, xnum);
    zero_at_ptr_count(l->gpu_cells, xnum);
    l->attrs.has_dirty_text = false;
}

void
linebuf_clear_line(LineBuf *self, index_type y, bool clear_attrs) {
#if BLANK_CHAR != 0
#error This implementation is incorrect for BLANK_CHAR != 0
#endif
    index_type ym = self->line_map[y];
    CPUCell *c = cpu_lineptr(self, ym); GPUCell *g = gpu_lineptr(self, ym);
    zero_at_ptr_count(c, self->xnum); zero_at_ptr_count(g, self->xnum);
    if (clear_attrs) self->line_attrs[y].val = 0;
}

static PyObject*
clear_line(LineBuf *self, PyObject *val) {
#define clear_line_doc "clear_line(y) -> Clear the specified line"
    index_type y = (index_type)PyLong_AsUnsignedLong(val);
    if (y >= self->ynum) { PyErr_SetString(PyExc_ValueError, "Out of bounds"); return NULL; }
    linebuf_clear_line(self, y, true);
    Py_RETURN_NONE;
}

void
linebuf_index(LineBuf* self, index_type top, index_type bottom) {
    if (top >= self->ynum - 1 || bottom >= self->ynum || bottom <= top) return;
    index_type old_top = self->line_map[top];
    LineAttrs old_attrs = self->line_attrs[top];
    const index_type num = bottom - top;
    memmove(self->line_map + top, self->line_map + top + 1, sizeof(self->line_map[0]) * num);
    memmove(self->line_attrs + top, self->line_attrs + top + 1, sizeof(self->line_attrs[0]) * num);
    self->line_map[bottom] = old_top;
    self->line_attrs[bottom] = old_attrs;
}

static PyObject*
pyw_index(LineBuf *self, PyObject *args) {
#define index_doc "index(top, bottom) -> Scroll all lines in the range [top, bottom] by one upwards. After scrolling, bottom will be top."
    unsigned int top, bottom;
    if (!PyArg_ParseTuple(args, "II", &top, &bottom)) return NULL;
    linebuf_index(self, top, bottom);
    Py_RETURN_NONE;
}

void
linebuf_reverse_index(LineBuf *self, index_type top, index_type bottom) {
    if (top >= self->ynum - 1 || bottom >= self->ynum || bottom <= top) return;
    index_type old_bottom = self->line_map[bottom];
    LineAttrs old_attrs = self->line_attrs[bottom];
    for (index_type i = bottom; i > top; i--) {
        self->line_map[i] = self->line_map[i - 1];
        self->line_attrs[i] = self->line_attrs[i - 1];
    }
    self->line_map[top] = old_bottom;
    self->line_attrs[top] = old_attrs;
}

static PyObject*
reverse_index(LineBuf *self, PyObject *args) {
#define reverse_index_doc "reverse_index(top, bottom) -> Scroll all lines in the range [top, bottom] by one down. After scrolling, top will be bottom."
    unsigned int top, bottom;
    if (!PyArg_ParseTuple(args, "II", &top, &bottom)) return NULL;
    linebuf_reverse_index(self, top, bottom);
    Py_RETURN_NONE;
}


static PyObject*
is_continued(LineBuf *self, PyObject *val) {
#define is_continued_doc "is_continued(y) -> Whether the line y is continued or not"
    unsigned long y = PyLong_AsUnsignedLong(val);
    if (y >= self->ynum) { PyErr_SetString(PyExc_ValueError, "Out of bounds."); return NULL; }
    if (y > 0 && linebuf_line_ends_with_continuation(self, y-1)) { Py_RETURN_TRUE; }
    Py_RETURN_FALSE;
}

void
linebuf_insert_lines(LineBuf *self, unsigned int num, unsigned int y, unsigned int bottom) {
    index_type i;
    if (y >= self->ynum || y > bottom || bottom >= self->ynum) return;
    index_type ylimit = bottom + 1;
    if (ylimit < y || (num = MIN(ylimit - y, num)) < 1) return;
    const size_t scratch_sz = sizeof(self->scratch[0]) * num;
    memcpy(self->scratch, self->line_map + ylimit - num, scratch_sz);
    for (i = ylimit - 1; i >= y + num; i--) {
        self->line_map[i] = self->line_map[i - num];
        self->line_attrs[i] = self->line_attrs[i - num];
    }
    memcpy(self->line_map + y, self->scratch, scratch_sz);
    Line l;
    for (i = y; i < y + num; i++) {
        init_line(self, &l, self->line_map[i]);
        clear_line_(&l, self->xnum);
        self->line_attrs[i].val = 0;
    }
}

static PyObject*
insert_lines(LineBuf *self, PyObject *args) {
#define insert_lines_doc "insert_lines(num, y, bottom) -> Insert num blank lines at y, only changing lines in the range [y, bottom]."
    unsigned int y, num, bottom;
    if (!PyArg_ParseTuple(args, "III", &num, &y, &bottom)) return NULL;
    linebuf_insert_lines(self, num, y, bottom);
    Py_RETURN_NONE;
}

void
linebuf_delete_lines(LineBuf *self, index_type num, index_type y, index_type bottom) {
    index_type i;
    index_type ylimit = bottom + 1;
    num = MIN(bottom + 1 - y, num);
    if (y >= self->ynum || y > bottom || bottom >= self->ynum || num < 1) return;
    const size_t scratch_sz = sizeof(self->scratch[0]) * num;
    memcpy(self->scratch, self->line_map + y, scratch_sz);
    for (i = y; i < ylimit && i + num < self->ynum; i++) {
        self->line_map[i] = self->line_map[i + num];
        self->line_attrs[i] = self->line_attrs[i + num];
    }
    memcpy(self->line_map + ylimit - num, self->scratch, scratch_sz);
    Line l;
    for (i = ylimit - num; i < ylimit; i++) {
        init_line(self, &l, self->line_map[i]);
        clear_line_(&l, self->xnum);
        self->line_attrs[i].val = 0;
    }
}

static PyObject*
delete_lines(LineBuf *self, PyObject *args) {
#define delete_lines_doc "delete_lines(num, y, bottom) -> Delete num lines at y, only changing lines in the range [y, bottom]."
    unsigned int y, num, bottom;
    if (!PyArg_ParseTuple(args, "III", &num, &y, &bottom)) return NULL;
    linebuf_delete_lines(self, num, y, bottom);
    Py_RETURN_NONE;
}

void
linebuf_copy_line_to(LineBuf *self, Line *line, index_type where) {
    init_line(self, self->line, self->line_map[where]);
    copy_line(line, self->line);
    self->line_attrs[where] = line->attrs;
    self->line_attrs[where].has_dirty_text = true;
}

static PyObject*
as_ansi(LineBuf *self, PyObject *callback) {
#define as_ansi_doc "as_ansi(callback) -> The contents of this buffer as ANSI escaped text. callback is called with each successive line."
    Line l = {.xnum=self->xnum, .text_cache=self->text_cache};
    // remove trailing empty lines
    index_type ylimit = self->ynum - 1;
    ANSIBuf output = {0}; ANSILineState s = {.output_buf=&output};
    do {
        init_line(self, &l, self->line_map[ylimit]);
        output.len = 0;
        line_as_ansi(&l, &s, 0, l.xnum, 0, true);
        if (output.len) break;
        ylimit--;
    } while(ylimit > 0);

    for(index_type i = 0; i <= ylimit; i++) {
        bool output_newline = !linebuf_line_ends_with_continuation(self, i);
        output.len = 0;
        init_line(self, &l, self->line_map[i]);
        line_as_ansi(&l, &s, 0, l.xnum, 0, true);
        if (output_newline) {
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

static Line*
get_line(void *x, int y) {
    LineBuf *self = (LineBuf*)x;
    linebuf_init_line(self, MAX(0, y));
    return self->line;
}

static PyObject*
as_text(LineBuf *self, PyObject *args) {
    ANSIBuf output = {0};
    PyObject* ans = as_text_generic(args, self, get_line, self->ynum, &output, false);
    free(output.buf);
    return ans;
}


static PyObject*
__str__(LineBuf *self) {
    RAII_PyObject(lines, PyTuple_New(self->ynum));
    RAII_ANSIBuf(buf);
    if (lines == NULL) return PyErr_NoMemory();
    for (index_type i = 0; i < self->ynum; i++) {
        init_line(self, self->line, self->line_map[i]);
        PyObject *t = line_as_unicode(self->line, false, &buf);
        if (t == NULL) return NULL;
        PyTuple_SET_ITEM(lines, i, t);
    }
    RAII_PyObject(sep, PyUnicode_FromString("\n"));
    return PyUnicode_Join(sep, lines);
}

// Boilerplate {{{
static PyObject*
copy_old(LineBuf *self, PyObject *y);
#define copy_old_doc "Copy the contents of the specified LineBuf to this LineBuf. Both must have the same number of columns, but the number of lines can be different, in which case the bottom lines are copied."

static PyObject*
rewrap(LineBuf *self, PyObject *args);
#define rewrap_doc "rewrap(new_screen) -> Fill up new screen (which can have different size to this screen) with as much of the contents of this screen as will fit. Return lines that overflow."

static PyMethodDef methods[] = {
    METHOD(line, METH_O)
    METHOD(clear_line, METH_O)
    METHOD(copy_old, METH_O)
    METHOD(copy_line_to, METH_VARARGS)
    METHOD(create_line_copy, METH_O)
    METHOD(rewrap, METH_VARARGS)
    METHOD(clear, METH_NOARGS)
    METHOD(as_ansi, METH_O)
    METHODB(as_text, METH_VARARGS),
    METHOD(set_attribute, METH_VARARGS)
    METHOD(set_continued, METH_VARARGS)
    METHOD(dirty_lines, METH_NOARGS)
    {"index", (PyCFunction)pyw_index, METH_VARARGS, NULL},
    METHOD(reverse_index, METH_VARARGS)
    METHOD(insert_lines, METH_VARARGS)
    METHOD(delete_lines, METH_VARARGS)
    METHOD(is_continued, METH_O)
    {NULL, NULL, 0, NULL}  /* Sentinel */
};

static PyMemberDef members[] = {
    {"xnum", T_UINT, offsetof(LineBuf, xnum), READONLY, "xnum"},
    {"ynum", T_UINT, offsetof(LineBuf, ynum), READONLY, "ynum"},
    {NULL}  /* Sentinel */
};

PyTypeObject LineBuf_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.LineBuf",
    .tp_basicsize = sizeof(LineBuf),
    .tp_dealloc = (destructor)dealloc,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_doc = "Line buffers",
    .tp_methods = methods,
    .tp_members = members,
    .tp_str = (reprfunc)__str__,
    .tp_new = new_linebuf_object
};

INIT_TYPE(LineBuf)
// }}}

static PyObject*
copy_old(LineBuf *self, PyObject *y) {
    if (!PyObject_TypeCheck(y, &LineBuf_Type)) { PyErr_SetString(PyExc_TypeError, "Not a LineBuf object"); return NULL; }
    LineBuf *other = (LineBuf*)y;
    if (other->xnum != self->xnum) { PyErr_SetString(PyExc_ValueError, "LineBuf has a different number of columns"); return NULL; }
    Line sl = {.text_cache=self->text_cache}, ol = {.text_cache=self->text_cache};
    sl.xnum = self->xnum; ol.xnum = other->xnum;

    for (index_type i = 0; i < MIN(self->ynum, other->ynum); i++) {
        index_type s = self->ynum - 1 - i, o = other->ynum - 1 - i;
        self->line_attrs[s] = other->line_attrs[o];
        s = self->line_map[s]; o = other->line_map[o];
        init_line(self, &sl, s); init_line(other, &ol, o);
        copy_line(&ol, &sl);
    }
    Py_RETURN_NONE;
}

static PyObject*
rewrap(LineBuf *self, PyObject *args) {
    unsigned int lines, columns;
    if (!PyArg_ParseTuple(args, "II", &lines, &columns)) return NULL;
    TrackCursor cursors[1] = {{.is_sentinel=true}};
    ANSIBuf as_ansi_buf = {0};
    ResizeResult r = resize_screen_buffers(self, NULL, lines, columns, &as_ansi_buf, cursors);
    free(as_ansi_buf.buf);
    if (!r.ok) return PyErr_NoMemory();
    return Py_BuildValue("NII", r.lb, r.num_content_lines_before, r.num_content_lines_after);
}


LineBuf *
alloc_linebuf(unsigned int lines, unsigned int columns, TextCache *tc) { return alloc_linebuf_(&LineBuf_Type, lines, columns, tc); }
