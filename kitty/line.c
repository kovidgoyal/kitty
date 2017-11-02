/*
 * line.c
 * Copyright (C) 2016 Kovid Goyal <kovid at kovidgoyal.net>
 *
 * Distributed under terms of the GPL3 license.
 */

#include "data-types.h"
#include "unicode-data.h"
#include "lineops.h"

extern PyTypeObject Cursor_Type;

static PyObject *
new(PyTypeObject UNUSED *type, PyObject UNUSED *args, PyObject UNUSED *kwds) {
    PyErr_SetString(PyExc_TypeError, "Line objects cannot be instantiated directly, create them using LineBuf.line()");
    return NULL;
}

static void
dealloc(Line* self) {
    if (self->needs_free) {
        PyMem_Free(self->cells);
    }
    Py_TYPE(self)->tp_free((PyObject*)self);
}

unsigned int
line_length(Line *self) {
    index_type last = self->xnum - 1;
    for (index_type i = 0; i < self->xnum; i++) {
        if ((self->cells[last - i].ch) != BLANK_CHAR) return self->xnum - i;
    }
    return 0;
}

PyObject* 
line_text_at(char_type ch, combining_type cc) {
    PyObject *ans;
    if (LIKELY(cc == 0)) {
        ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, &ch, 1);
    } else {
        Py_UCS4 buf[3];
        buf[0] = ch; buf[1] = cc & CC_MASK; buf[2] = cc >> 16;
        Py_UCS4 normalized = normalize(ch, buf[1], buf[2]);
        if (normalized) ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, &normalized, 1);
        else ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buf, buf[2] ? 3 : 2);
    }
    return ans;
}

// URL detection {{{

static const char* url_prefixes[4] = {"https", "http", "file", "ftp"};
static size_t url_prefix_lengths[sizeof(url_prefixes)/sizeof(url_prefixes[0])] = {0};
typedef enum URL_PARSER_STATES {ANY, FIRST_SLASH, SECOND_SLASH} URL_PARSER_STATE;

static inline index_type
find_colon_slash(Line *self, index_type x, index_type limit) {
    // Find :// at or before x
    index_type pos = x;
    URL_PARSER_STATE state = ANY;
    limit = MAX(2, limit);
    if (pos < limit) return 0;
    do {
        char_type ch = self->cells[pos].ch;
        if (!is_url_char(ch)) return false;
        switch(state) {
            case ANY:
                if (ch == '/') state = FIRST_SLASH; 
                break;
            case FIRST_SLASH:
                state = ch == '/' ? SECOND_SLASH : ANY;
                break;
            case SECOND_SLASH:
                if (ch == ':') return pos;
                state = ANY;
                break;
        }
        pos--;
    } while(pos >= limit);
    return 0;
}

static inline bool
prefix_matches(Line *self, index_type at, const char* prefix, index_type prefix_len) {
    if (prefix_len > at) return false;
    index_type p, i;
    for (p = at - prefix_len, i = 0; i < prefix_len && p < self->xnum; i++, p++) {
        if ((self->cells[p].ch) != (unsigned char)prefix[i]) return false;
    }
    return i == prefix_len;
}

static inline bool
has_url_prefix_at(Line *self, index_type at, index_type min_prefix_len, index_type *ans) {
    if (UNLIKELY(!url_prefix_lengths[0])) {
        for (index_type i = 0; i < sizeof(url_prefixes)/sizeof(url_prefixes[0]); i++) url_prefix_lengths[i] = strlen(url_prefixes[i]);
    }
    for (index_type i = 0; i < sizeof(url_prefixes)/sizeof(url_prefixes[0]); i++) {
        index_type prefix_len = url_prefix_lengths[i];
        if (at < prefix_len || prefix_len < min_prefix_len) continue;
        if (prefix_matches(self, at, url_prefixes[i], prefix_len)) { *ans = at - prefix_len; return true; }
    }
    return false;
}

#define MAX_URL_SCHEME_LEN 5
#define MIN_URL_LEN 5

static inline bool
has_url_beyond(Line *self, index_type x) {
    if (self->xnum <= x + MIN_URL_LEN + 3) return false;
    for (index_type i = x; i < MIN(x + MIN_URL_LEN + 3, self->xnum); i++) {
        if (!is_url_char(self->cells[i].ch)) return false;
    }
    return true;
}

index_type
line_url_start_at(Line *self, index_type x) {
    // Find the starting cell for a URL that contains the position x. A URL is defined as
    // known-prefix://url-chars. If no URL is found self->xnum is returned.
    if (x >= self->xnum || self->xnum <= MIN_URL_LEN + 3) return self->xnum;
    index_type ds_pos = 0, t;
    // First look for :// ahead of x
    if (self->xnum - x > MAX_URL_SCHEME_LEN + 3) ds_pos = find_colon_slash(self, x + MAX_URL_SCHEME_LEN + 3, x < 2 ? 0 : x - 2);
    if (ds_pos != 0 && has_url_beyond(self, ds_pos)) {
        if (has_url_prefix_at(self, ds_pos, ds_pos > x ? ds_pos - x: 0, &t)) return t;
    }
    ds_pos = find_colon_slash(self, x, 0);
    if (ds_pos == 0 || self->xnum < ds_pos + MIN_URL_LEN + 3 || !has_url_beyond(self, ds_pos)) return self->xnum;
    if (has_url_prefix_at(self, ds_pos, 0, &t)) return t;
    return self->xnum;
}

index_type
line_url_end_at(Line *self, index_type x) {
    index_type ans = x;
    if (x >= self->xnum || self->xnum <= MIN_URL_LEN + 3) return 0;
    while (ans < self->xnum && is_url_char(self->cells[ans].ch)) ans++;
    ans--;
    while (ans > x && can_strip_from_end_of_url(self->cells[ans].ch)) ans--;
    return ans;
}

static PyObject*
url_start_at(Line *self, PyObject *x) {
#define url_start_at_doc "url_start_at(x) -> Return the start cell number for a URL containing x or self->xnum if not found"
    return PyLong_FromUnsignedLong((unsigned long)line_url_start_at(self, PyLong_AsUnsignedLong(x)));
}

static PyObject*
url_end_at(Line *self, PyObject *x) {
#define url_end_at_doc "url_end_at(x) -> Return the end cell number for a URL containing x or 0 if not found"
    return PyLong_FromUnsignedLong((unsigned long)line_url_end_at(self, PyLong_AsUnsignedLong(x)));
}

// }}}

static PyObject*
text_at(Line* self, Py_ssize_t xval) {
#define text_at_doc "[x] -> Return the text in the specified cell"
    if (xval >= self->xnum) { PyErr_SetString(PyExc_IndexError, "Column number out of bounds"); return NULL; }
    return line_text_at(self->cells[xval].ch, self->cells[xval].cc);
}

size_t
cell_as_unicode(Cell *cell, bool include_cc, Py_UCS4 *buf, char_type zero_char) {
    size_t n = 1;
    buf[0] = cell->ch ? cell->ch : zero_char;
    if (include_cc) {
        char_type cc = cell->cc;
        Py_UCS4 cc1 = cc & CC_MASK, cc2;
        if (cc1) {
            buf[1] = cc1; n++;
            cc2 = cc >> 16;
            if (cc2) { buf[2] = cc2; n++; }
        }
    }
    return n;
}

PyObject*
unicode_in_range(Line *self, index_type start, index_type limit, bool include_cc, char leading_char) {
    size_t n = 0;
    static Py_UCS4 buf[4096];
    if (leading_char) buf[n++] = leading_char; 
    char_type previous_width = 0;
    for(index_type i = start; i < limit && n < sizeof(buf)/sizeof(buf[0]) - 4; i++) {
        char_type ch = self->cells[i].ch;
        if (ch == 0) {
            if (previous_width == 2) { previous_width = 0; continue; };
        }
        n += cell_as_unicode(self->cells + i, include_cc, buf + n, ' ');
        previous_width = self->cells[i].attrs & WIDTH_MASK;
    }
    return PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buf, n);
}

static PyObject *
as_unicode(Line* self) {
    return unicode_in_range(self, 0, xlimit_for_line(self), true, 0);
}

static PyObject*
sprite_at(Line* self, PyObject *x) {
#define sprite_at_doc "[x] -> Return the sprite in the specified cell"
    unsigned long xval = PyLong_AsUnsignedLong(x);
    if (xval >= self->xnum) { PyErr_SetString(PyExc_IndexError, "Column number out of bounds"); return NULL; }
    Cell *c = self->cells + xval;
    return Py_BuildValue("HHH", c->sprite_x, c->sprite_y, c->sprite_z);
}


static inline bool
write_sgr(unsigned int val, Py_UCS4 *buf, index_type buflen, index_type *i) {
    static char s[20] = {0};
    unsigned int num = snprintf(s, 20, "\x1b[%um", val);
    if (buflen - (*i) < num + 3) return false;
    for(unsigned int si=0; si < num; si++) buf[(*i)++] = s[si];
    return true;
}

static inline bool
write_color(uint32_t val, int code, Py_UCS4 *buf, index_type buflen, index_type *i) {
    static char s[50] = {0};
    unsigned int num;
    switch(val & 3) {
        case 1:
            num = snprintf(s, 50, "\x1b[%d;5;%um", code, (val >> 8) & 0xFF); break;
        case 2:
            num = snprintf(s, 50, "\x1b[%d;2;%u;%u;%um", code, (val >> 24) & 0xFF, (val >> 16) & 0xFF, (val >> 8) & 0xFF); break;
        default:
            return true;
    }
    if (buflen - (*i) < num + 3) return false;
    for(unsigned int si=0; si < num; si++) buf[(*i)++] = s[si];
    return true;
}

index_type
line_as_ansi(Line *self, Py_UCS4 *buf, index_type buflen) {
#define WRITE_SGR(val) if (!write_sgr(val, buf, buflen, &i)) return i;
#define WRITE_COLOR(val, code) if (val) { if (!write_color(val, code, buf, buflen, &i)) return i; } else { WRITE_SGR(code+1); }
#define CHECK_BOOL(name, shift, on, off) \
        if (((attrs >> shift) & 1) != name) { \
            name ^= 1; \
            if (name) { WRITE_SGR(on); } else { WRITE_SGR(off); } \
        }
#define CHECK_COLOR(name, val, off_code) if (name != (val)) { name = (val); WRITE_COLOR(name, off_code); }
#define WRITE_CH(val) if (i > buflen - 1) return i; buf[i++] = val; 

    index_type limit = xlimit_for_line(self), i=0;
    bool bold = false, italic = false, reverse = false, strike = false;
    uint32_t fg = 0, bg = 0, decoration_fg = 0, decoration = 0;
    char_type previous_width = 0;

    WRITE_SGR(0);
    for (index_type pos=0; pos < limit; pos++) {
        char_type attrs = self->cells[pos].attrs, ch = self->cells[pos].ch;
        if (ch == 0) {
            if (previous_width == 2) { previous_width = 0; continue; }
            ch = ' ';
        }
        CHECK_BOOL(bold, BOLD_SHIFT, 1, 22);
        CHECK_BOOL(italic, ITALIC_SHIFT, 3, 23);
        CHECK_BOOL(reverse, REVERSE_SHIFT, 7, 27);
        CHECK_BOOL(strike, STRIKE_SHIFT, 9, 29);
        if (((attrs >> DECORATION_SHIFT) & DECORATION_MASK) != decoration) {
            decoration = ((attrs >> DECORATION_SHIFT) & DECORATION_MASK);
            switch(decoration) {
                case 1:
                    WRITE_SGR(4); break;
                case 2:
                    WRITE_SGR(UNDERCURL_CODE); break;
                default:
                    WRITE_SGR(0); break;
            }
        }
        CHECK_COLOR(fg, self->cells[pos].fg, 38);
        CHECK_COLOR(bg, self->cells[pos].bg, 48);
        CHECK_COLOR(decoration_fg, self->cells[pos].decoration_fg, DECORATION_FG_CODE);
        WRITE_CH(ch);
        char_type cc = self->cells[pos].cc;
        Py_UCS4 cc1 = cc & CC_MASK;
        if (cc1) {
            WRITE_CH(cc1);
            cc1 = cc >> 16;
            if (cc1) { WRITE_CH(cc1); }
        }
        previous_width = attrs & WIDTH_MASK;
    }
    return i;
#undef CHECK_BOOL
#undef CHECK_COLOR
#undef WRITE_SGR
#undef WRITE_CH
#undef WRITE_COLOR
}

static PyObject*
as_ansi(Line* self) {
#define as_ansi_doc "Return the line's contents with ANSI (SGR) escape codes for formatting"
    static Py_UCS4 t[5120] = {0};
    index_type num = line_as_ansi(self, t, 5120);
    PyObject *ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, t, num);
    return ans;
}

static PyObject*
is_continued(Line* self) {
#define is_continued_doc "Return the line's continued flag"
    PyObject *ans = self->continued ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

static PyObject*
__repr__(Line* self) {
    PyObject *s = as_unicode(self);
    if (s == NULL) return NULL;
    PyObject *ans = PyObject_Repr(s);
    Py_CLEAR(s);
    return ans;
}

static PyObject*
width(Line *self, PyObject *val) {
#define width_doc "width(x) -> the width of the character at x"
    unsigned long x = PyLong_AsUnsignedLong(val);
    if (x >= self->xnum) { PyErr_SetString(PyExc_ValueError, "Out of bounds"); return NULL; }
    char_type attrs = self->cells[x].attrs;
    return PyLong_FromUnsignedLong((unsigned long) (attrs & WIDTH_MASK));
}

void 
line_add_combining_char(Line *self, uint32_t ch, unsigned int x) {
    if (!self->cells[x].ch) return;  // dont allow adding combining chars to a null cell
    combining_type c = self->cells[x].cc;
    if (c & CC_MASK) self->cells[x].cc = (c & CC_MASK) | ( (ch & CC_MASK) << CC_SHIFT );
    else self->cells[x].cc = ch & CC_MASK;
}

static PyObject*
add_combining_char(Line* self, PyObject *args) {
#define add_combining_char_doc "add_combining_char(x, ch) -> Add the specified character as a combining char to the specified cell."
    int new_char;
    unsigned int x;
    if (!PyArg_ParseTuple(args, "IC", &x, &new_char)) return NULL;
    if (x >= self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Column index out of bounds");
        return NULL;
    }
    line_add_combining_char(self, new_char, x);
    Py_RETURN_NONE;
}


static PyObject*
set_text(Line* self, PyObject *args) {
#define set_text_doc "set_text(src, offset, sz, cursor) -> Set the characters and attributes from the specified text and cursor"
    PyObject *src;
    Py_ssize_t offset, sz, limit;
    char_type attrs;
    Cursor *cursor;
    int kind;
    void *buf;

    if (!PyArg_ParseTuple(args, "UnnO!", &src, &offset, &sz, &Cursor_Type, &cursor)) return NULL;
    if (PyUnicode_READY(src) != 0) {
        PyErr_NoMemory();
        return NULL;
    }
    kind = PyUnicode_KIND(src);
    buf = PyUnicode_DATA(src);
    limit = offset + sz;
    if (PyUnicode_GET_LENGTH(src) < limit) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds offset/sz");
        return NULL;
    }
    attrs = CURSOR_TO_ATTRS(cursor, 1);
    color_type fg = (cursor->fg & COL_MASK), bg = cursor->bg & COL_MASK;
    color_type dfg = cursor->decoration_fg & COL_MASK;

    for (index_type i = cursor->x; offset < limit && i < self->xnum; i++, offset++) {
        self->cells[i].ch = (PyUnicode_READ(kind, buf, offset));
        self->cells[i].attrs = attrs;
        self->cells[i].fg = fg;
        self->cells[i].bg = bg;
        self->cells[i].decoration_fg = dfg;
        self->cells[i].cc = 0;
    }

    Py_RETURN_NONE;
}

static PyObject*
cursor_from(Line* self, PyObject *args) {
#define cursor_from_doc "cursor_from(x, y=0) -> Create a cursor object based on the formatting attributes at the specified x position. The y value of the cursor is set as specified."
    unsigned int x, y = 0;
    Cursor* ans;
    if (!PyArg_ParseTuple(args, "I|I", &x, &y)) return NULL;
    if (x >= self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds x");
        return NULL;
    }
    ans = alloc_cursor();
    if (ans == NULL) { PyErr_NoMemory(); return NULL; }
    ans->x = x; ans->y = y;
    char_type attrs = self->cells[x].attrs;
    ATTRS_TO_CURSOR(attrs, ans);
    ans->fg = self->cells[x].fg; ans->bg = self->cells[x].bg;
    ans->decoration_fg = self->cells[x].decoration_fg & COL_MASK;

    return (PyObject*)ans;
}

void 
line_clear_text(Line *self, unsigned int at, unsigned int num, char_type ch) {
    attrs_type width = ch ? 1 : 0;
#define PREFIX \
    for (index_type i = at; i < MIN(self->xnum, at + num); i++) { \
        self->cells[i].ch = ch; self->cells[i].cc = 0; \
        self->cells[i].attrs = (self->cells[i].attrs & ATTRS_MASK_WITHOUT_WIDTH) | width; \
    }
    if (CHAR_IS_BLANK(ch)) {
        PREFIX
    } else {
        PREFIX
    }
}

static PyObject*
clear_text(Line* self, PyObject *args) {
#define clear_text_doc "clear_text(at, num, ch=BLANK_CHAR) -> Clear characters in the specified range, preserving formatting."
    unsigned int at, num;
    int ch = BLANK_CHAR;
    if (!PyArg_ParseTuple(args, "II|C", &at, &num, &ch)) return NULL;
    line_clear_text(self, at, num, ch);
    Py_RETURN_NONE;
}

void 
line_apply_cursor(Line *self, Cursor *cursor, unsigned int at, unsigned int num, bool clear_char) {
    char_type attrs = CURSOR_TO_ATTRS(cursor, 1);
    color_type fg = (cursor->fg & COL_MASK), bg = (cursor->bg & COL_MASK);
    color_type dfg = cursor->decoration_fg & COL_MASK;
    if (!clear_char) attrs = attrs & ATTRS_MASK_WITHOUT_WIDTH;
    
    for (index_type i = at; i < self->xnum && i < at + num; i++) {
        if (clear_char) {
            self->cells[i].ch = BLANK_CHAR;
            self->cells[i].cc = 0;
            self->cells[i].attrs = attrs;
            clear_sprite_position(self->cells[i]);
        } else {
            attrs_type w = self->cells[i].attrs & WIDTH_MASK;
            self->cells[i].attrs = attrs | w;
        }
        self->cells[i].fg = fg; self->cells[i].bg = bg;
        self->cells[i].decoration_fg = dfg;
    }
}

static PyObject*
apply_cursor(Line* self, PyObject *args) {
#define apply_cursor_doc "apply_cursor(cursor, at=0, num=1, clear_char=False) -> Apply the formatting attributes from cursor to the specified characters in this line."
    Cursor* cursor;
    unsigned int at=0, num=1;
    int clear_char = 0;
    if (!PyArg_ParseTuple(args, "O!|IIp", &Cursor_Type, &cursor, &at, &num, &clear_char)) return NULL;
    line_apply_cursor(self, cursor, at, num, clear_char & 1);
    Py_RETURN_NONE;
}

void line_right_shift(Line *self, unsigned int at, unsigned int num) {
    for(index_type i = self->xnum - 1; i >= at + num; i--) {
        COPY_SELF_CELL(i - num, i)
    }
    // Check if a wide character was split at the right edge
    char_type w = (self->cells[self->xnum - 1].attrs) & WIDTH_MASK;
    if (w != 1) {
        self->cells[self->xnum - 1].ch = BLANK_CHAR;
        self->cells[self->xnum - 1].attrs = BLANK_CHAR ? 1 : 0;
        clear_sprite_position(self->cells[self->xnum - 1]);
    }
}

static PyObject*
right_shift(Line *self, PyObject *args) {
#define right_shift_doc "right_shift(at, num) -> ..."
    unsigned int at, num;
    if (!PyArg_ParseTuple(args, "II", &at, &num)) return NULL;
    if (at >= self->xnum || at + num > self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds");
        return NULL;
    }
    if (num > 0) {
        line_right_shift(self, at, num);
    }
    Py_RETURN_NONE;
}

static PyObject*
left_shift(Line *self, PyObject *args) {
#define left_shift_doc "left_shift(at, num) -> ..."
    unsigned int at, num;
    if (!PyArg_ParseTuple(args, "II", &at, &num)) return NULL;
    if (at >= self->xnum || at + num > self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds");
        return NULL;
    }
    if (num > 0) left_shift_line(self, at, num);
    Py_RETURN_NONE;
}
 
void 
line_set_char(Line *self, unsigned int at, uint32_t ch, unsigned int width, Cursor *cursor, bool UNUSED is_second) {
    if (cursor == NULL) {
        self->cells[at].attrs = (self->cells[at].attrs & ATTRS_MASK_WITHOUT_WIDTH) | width;
    } else {
        self->cells[at].attrs = CURSOR_TO_ATTRS(cursor, width & WIDTH_MASK);
        self->cells[at].fg = (cursor->fg & COL_MASK);
        self->cells[at].bg = (cursor->bg & COL_MASK);
        self->cells[at].decoration_fg = cursor->decoration_fg & COL_MASK;
    }
    self->cells[at].ch = ch;
    self->cells[at].cc = 0;
}

static PyObject*
set_char(Line *self, PyObject *args) {
#define set_char_doc "set_char(at, ch, width=1, cursor=None) -> Set the character at the specified cell. If cursor is not None, also set attributes from that cursor."
    unsigned int at, width=1;
    int ch;
    Cursor *cursor = NULL;

    if (!PyArg_ParseTuple(args, "IC|IO!", &at, &ch, &width, &Cursor_Type, &cursor)) return NULL;
    if (at >= self->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds");
        return NULL;
    }
    line_set_char(self, at, ch, width, cursor, false);
    Py_RETURN_NONE;
}

static PyObject*
set_attribute(Line *self, PyObject *args) {
#define set_attribute_doc "set_attribute(which, val) -> Set the attribute on all cells in the line."
    unsigned int shift, val;
    if (!PyArg_ParseTuple(args, "II", &shift, &val)) return NULL;
    if (shift < DECORATION_SHIFT || shift > STRIKE_SHIFT) { PyErr_SetString(PyExc_ValueError, "Unknown attribute"); return NULL; }
    set_attribute_on_line(self->cells, shift, val, self->xnum);
    Py_RETURN_NONE;
}

static Py_ssize_t
__len__(PyObject *self) {
    return (Py_ssize_t)(((Line*)self)->xnum);
}

static int __eq__(Line *a, Line *b) {
    return a->xnum == b->xnum && memcmp(a->cells, b->cells, sizeof(Cell) * a->xnum) == 0;
}

// Boilerplate {{{
static PyObject*
copy_char(Line* self, PyObject *args);
#define copy_char_doc "copy_char(src, to, dest) -> Copy the character at src to to the character dest in the line `to`"

static PyObject *
richcmp(PyObject *obj1, PyObject *obj2, int op);


static PySequenceMethods sequence_methods = {
    .sq_length = __len__,                  
    .sq_item = (ssizeargfunc)text_at
};

static PyMethodDef methods[] = {
    METHOD(add_combining_char, METH_VARARGS)
    METHOD(set_text, METH_VARARGS)
    METHOD(cursor_from, METH_VARARGS)
    METHOD(apply_cursor, METH_VARARGS)
    METHOD(clear_text, METH_VARARGS)
    METHOD(copy_char, METH_VARARGS)
    METHOD(right_shift, METH_VARARGS)
    METHOD(left_shift, METH_VARARGS)
    METHOD(set_char, METH_VARARGS)
    METHOD(set_attribute, METH_VARARGS)
    METHOD(as_ansi, METH_NOARGS)
    METHOD(is_continued, METH_NOARGS)
    METHOD(width, METH_O)
    METHOD(url_start_at, METH_O)
    METHOD(url_end_at, METH_O)
    METHOD(sprite_at, METH_O)
        
    {NULL}  /* Sentinel */
};

PyTypeObject Line_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Line",
    .tp_basicsize = sizeof(Line),
    .tp_dealloc = (destructor)dealloc,
    .tp_repr = (reprfunc)__repr__,
    .tp_str = (reprfunc)as_unicode,
    .tp_as_sequence = &sequence_methods,
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_richcompare = richcmp,                   
    .tp_doc = "Lines",
    .tp_methods = methods,
    .tp_new = new
};

Line *alloc_line() {
    Line *ans = (Line*)PyType_GenericAlloc(&Line_Type, 0);
    ans->needs_free = 0;
    return ans;
}

RICHCMP(Line)
INIT_TYPE(Line)
// }}}
 
static PyObject*
copy_char(Line* self, PyObject *args) {
    unsigned int src, dest;
    Line *to;
    if (!PyArg_ParseTuple(args, "IO!I", &src, &Line_Type, &to, &dest)) return NULL;
    if (src >= self->xnum || dest >= to->xnum) {
        PyErr_SetString(PyExc_ValueError, "Out of bounds");
        return NULL;
    }
    COPY_CELL(self, src, to, dest);
    Py_RETURN_NONE;
}

