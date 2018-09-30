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
        PyMem_Free(self->cpu_cells);
        PyMem_Free(self->gpu_cells);
    }
    Py_TYPE(self)->tp_free((PyObject*)self);
}

unsigned int
line_length(Line *self) {
    index_type last = self->xnum - 1;
    for (index_type i = 0; i < self->xnum; i++) {
        if ((self->cpu_cells[last - i].ch) != BLANK_CHAR) return self->xnum - i;
    }
    return 0;
}

PyObject*
cell_text(CPUCell *cell) {
    PyObject *ans;
    unsigned num = 1;
    static Py_UCS4 buf[arraysz(cell->cc_idx) + 1];
    buf[0] = cell->ch;
    for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) buf[num++] = codepoint_for_mark(cell->cc_idx[i]);
    ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buf, num);
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
        char_type ch = self->cpu_cells[pos].ch;
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
        if ((self->cpu_cells[p].ch) != (unsigned char)prefix[i]) return false;
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
        if (!is_url_char(self->cpu_cells[i].ch)) return false;
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
line_url_end_at(Line *self, index_type x, bool check_short, char_type sentinel) {
    index_type ans = x;
    if (x >= self->xnum || (check_short && self->xnum <= MIN_URL_LEN + 3)) return 0;
    if (sentinel) { while (ans < self->xnum && self->cpu_cells[ans].ch != sentinel && is_url_char(self->cpu_cells[ans].ch)) ans++; }
    else { while (ans < self->xnum && is_url_char(self->cpu_cells[ans].ch)) ans++; }
    if (ans) ans--;
    while (ans > x && can_strip_from_end_of_url(self->cpu_cells[ans].ch)) ans--;
    return ans;
}

static PyObject*
url_start_at(Line *self, PyObject *x) {
#define url_start_at_doc "url_start_at(x) -> Return the start cell number for a URL containing x or self->xnum if not found"
    return PyLong_FromUnsignedLong((unsigned long)line_url_start_at(self, PyLong_AsUnsignedLong(x)));
}

static PyObject*
url_end_at(Line *self, PyObject *args) {
#define url_end_at_doc "url_end_at(x) -> Return the end cell number for a URL containing x or 0 if not found"
    unsigned int x, sentinel = 0;
    if (!PyArg_ParseTuple(args, "I|I", &x, &sentinel)) return NULL;
    return PyLong_FromUnsignedLong((unsigned long)line_url_end_at(self, x, true, sentinel));
}

// }}}

static PyObject*
text_at(Line* self, Py_ssize_t xval) {
#define text_at_doc "[x] -> Return the text in the specified cell"
    if ((unsigned)xval >= self->xnum) { PyErr_SetString(PyExc_IndexError, "Column number out of bounds"); return NULL; }
    return cell_text(self->cpu_cells + xval);
}

size_t
cell_as_unicode(CPUCell *cell, bool include_cc, Py_UCS4 *buf, char_type zero_char) {
    size_t n = 1;
    buf[0] = cell->ch ? cell->ch : zero_char;
    if (include_cc) {
        for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) buf[n++] = codepoint_for_mark(cell->cc_idx[i]);
    }
    return n;
}

size_t
cell_as_utf8(CPUCell *cell, bool include_cc, char *buf, char_type zero_char) {
    size_t n = encode_utf8(cell->ch ? cell->ch : zero_char, buf);
    if (include_cc) {
        for (unsigned i = 0; i < arraysz(cell->cc_idx) && cell->cc_idx[i]; i++) n += encode_utf8(codepoint_for_mark(cell->cc_idx[i]), buf + n);
    }
    buf[n] = 0;
    return n;
}


PyObject*
unicode_in_range(Line *self, index_type start, index_type limit, bool include_cc, char leading_char) {
    size_t n = 0;
    static Py_UCS4 buf[4096];
    if (leading_char) buf[n++] = leading_char;
    char_type previous_width = 0;
    for(index_type i = start; i < limit && n < arraysz(buf) - 2 - arraysz(self->cpu_cells->cc_idx); i++) {
        char_type ch = self->cpu_cells[i].ch;
        if (ch == 0) {
            if (previous_width == 2) { previous_width = 0; continue; };
        }
        n += cell_as_unicode(self->cpu_cells + i, include_cc, buf + n, ' ');
        previous_width = self->gpu_cells[i].attrs & WIDTH_MASK;
    }
    return PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, buf, n);
}

PyObject *
line_as_unicode(Line* self) {
    return unicode_in_range(self, 0, xlimit_for_line(self), true, 0);
}

static PyObject*
sprite_at(Line* self, PyObject *x) {
#define sprite_at_doc "[x] -> Return the sprite in the specified cell"
    unsigned long xval = PyLong_AsUnsignedLong(x);
    if (xval >= self->xnum) { PyErr_SetString(PyExc_IndexError, "Column number out of bounds"); return NULL; }
    GPUCell *c = self->gpu_cells + xval;
    return Py_BuildValue("HHH", c->sprite_x, c->sprite_y, c->sprite_z);
}

static inline bool
write_sgr(const char *val, Py_UCS4 *buf, index_type buflen, index_type *i) {
    static char s[128];
    unsigned int num = snprintf(s, sizeof(s), "\x1b[%sm", val);
    if (buflen - (*i) < num + 3) return false;
    for(unsigned int si=0; si < num; si++) buf[(*i)++] = s[si];
    return true;
}

index_type
line_as_ansi(Line *self, Py_UCS4 *buf, index_type buflen) {
#define WRITE_SGR(val) { if (!write_sgr(val, buf, buflen, &i)) return i; }
#define WRITE_CH(val) if (i > buflen - 1) return i; buf[i++] = val;

    index_type limit = xlimit_for_line(self), i=0;
    if (limit == 0) return 0;
    char_type previous_width = 0;

    GPUCell blank_cell = { 0 };
    GPUCell *cell, *prev_cell = &blank_cell;

    for (index_type pos=0; pos < limit; pos++) {
        char_type ch = self->cpu_cells[pos].ch;
        if (ch == 0) {
            if (previous_width == 2) { previous_width = 0; continue; }
            ch = ' ';
        }

        cell = &self->gpu_cells[pos];

#define CMP_ATTRS (cell->attrs & ATTRS_MASK_WITHOUT_WIDTH) != (prev_cell->attrs & ATTRS_MASK_WITHOUT_WIDTH)
#define CMP(x) cell->x != prev_cell->x
        if (CMP_ATTRS || CMP(fg) || CMP(bg) || CMP(decoration_fg)) {
            const char *sgr = cell_as_sgr(cell, prev_cell);
            if (*sgr) WRITE_SGR(sgr);
        }
        prev_cell = cell;
        WRITE_CH(ch);
        for(unsigned c = 0; c < arraysz(self->cpu_cells[pos].cc_idx) && self->cpu_cells[pos].cc_idx[c]; c++) {
            WRITE_CH(codepoint_for_mark(self->cpu_cells[pos].cc_idx[c]));
        }
        previous_width = cell->attrs & WIDTH_MASK;
    }
    return i;
#undef CMP_ATTRS
#undef CMP
#undef WRITE_SGR
#undef WRITE_CH
}

static PyObject*
as_ansi(Line* self, PyObject *a UNUSED) {
#define as_ansi_doc "Return the line's contents with ANSI (SGR) escape codes for formatting"
    static Py_UCS4 t[5120] = {0};
    index_type num = line_as_ansi(self, t, 5120);
    PyObject *ans = PyUnicode_FromKindAndData(PyUnicode_4BYTE_KIND, t, num);
    return ans;
}

static PyObject*
is_continued(Line* self, PyObject *a UNUSED) {
#define is_continued_doc "Return the line's continued flag"
    PyObject *ans = self->continued ? Py_True : Py_False;
    Py_INCREF(ans);
    return ans;
}

static PyObject*
__repr__(Line* self) {
    PyObject *s = line_as_unicode(self);
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
    char_type attrs = self->gpu_cells[x].attrs;
    return PyLong_FromUnsignedLong((unsigned long) (attrs & WIDTH_MASK));
}

void
line_add_combining_char(Line *self, uint32_t ch, unsigned int x) {
    CPUCell *cell = self->cpu_cells + x;
    if (!cell->ch) {
        if (x > 0 && (self->gpu_cells[x-1].attrs & WIDTH_MASK) == 2 && self->cpu_cells[x-1].ch) cell = self->cpu_cells + x - 1;
        else return; // don't allow adding combining chars to a null cell
    }
    for (unsigned i = 0; i < arraysz(cell->cc_idx); i++) {
        if (!cell->cc_idx[i]) { cell->cc_idx[i] = mark_for_codepoint(ch); return; }
    }
    cell->cc_idx[arraysz(cell->cc_idx) - 1] = mark_for_codepoint(ch);
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
        self->cpu_cells[i].ch = (PyUnicode_READ(kind, buf, offset));
        self->gpu_cells[i].attrs = attrs;
        self->gpu_cells[i].fg = fg;
        self->gpu_cells[i].bg = bg;
        self->gpu_cells[i].decoration_fg = dfg;
        memset(self->cpu_cells[i].cc_idx, 0, sizeof(self->cpu_cells[i].cc_idx));
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
    char_type attrs = self->gpu_cells[x].attrs;
    ATTRS_TO_CURSOR(attrs, ans);
    ans->fg = self->gpu_cells[x].fg; ans->bg = self->gpu_cells[x].bg;
    ans->decoration_fg = self->gpu_cells[x].decoration_fg & COL_MASK;

    return (PyObject*)ans;
}

void
line_clear_text(Line *self, unsigned int at, unsigned int num, char_type ch) {
    attrs_type width = ch ? 1 : 0;
#define PREFIX \
    for (index_type i = at; i < MIN(self->xnum, at + num); i++) { \
        self->cpu_cells[i].ch = ch; memset(self->cpu_cells[i].cc_idx, 0, sizeof(self->cpu_cells[i].cc_idx)); \
        self->gpu_cells[i].attrs = (self->gpu_cells[i].attrs & ATTRS_MASK_WITHOUT_WIDTH) | width; \
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
            self->cpu_cells[i].ch = BLANK_CHAR;
            memset(self->cpu_cells[i].cc_idx, 0, sizeof(self->cpu_cells[i].cc_idx));
            self->gpu_cells[i].attrs = attrs;
            clear_sprite_position(self->gpu_cells[i]);
        } else {
            attrs_type w = self->gpu_cells[i].attrs & WIDTH_MASK;
            self->gpu_cells[i].attrs = attrs | w;
        }
        self->gpu_cells[i].fg = fg; self->gpu_cells[i].bg = bg;
        self->gpu_cells[i].decoration_fg = dfg;
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
    char_type w = (self->gpu_cells[self->xnum - 1].attrs) & WIDTH_MASK;
    if (w != 1) {
        self->cpu_cells[self->xnum - 1].ch = BLANK_CHAR;
        self->gpu_cells[self->xnum - 1].attrs = BLANK_CHAR ? 1 : 0;
        clear_sprite_position(self->gpu_cells[self->xnum - 1]);
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
        self->gpu_cells[at].attrs = (self->gpu_cells[at].attrs & ATTRS_MASK_WITHOUT_WIDTH) | width;
    } else {
        self->gpu_cells[at].attrs = CURSOR_TO_ATTRS(cursor, width & WIDTH_MASK);
        self->gpu_cells[at].fg = (cursor->fg & COL_MASK);
        self->gpu_cells[at].bg = (cursor->bg & COL_MASK);
        self->gpu_cells[at].decoration_fg = cursor->decoration_fg & COL_MASK;
    }
    self->cpu_cells[at].ch = ch;
    memset(self->cpu_cells[at].cc_idx, 0, sizeof(self->cpu_cells[at].cc_idx));
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
    if (shift < DECORATION_SHIFT || shift > DIM_SHIFT) { PyErr_SetString(PyExc_ValueError, "Unknown attribute"); return NULL; }
    set_attribute_on_line(self->gpu_cells, shift, val, self->xnum);
    Py_RETURN_NONE;
}

static inline int
color_as_sgr(char *buf, size_t sz, unsigned long val, unsigned simple_code, unsigned aix_code, unsigned complex_code) {
    switch(val & 0xff) {
        case 1:
            val >>= 8;
            if (val < 16 && simple_code) {
                return snprintf(buf, sz, "%lu;", (val < 8) ? simple_code + val : aix_code + (val - 8));
            }
            return snprintf(buf, sz, "%u:5:%lu;", complex_code, val);
        case 2:
            return snprintf(buf, sz, "%u:2:%lu:%lu:%lu;", complex_code, (val >> 24) & 0xff, (val >> 16) & 0xff, (val >> 8) & 0xff);
        default:
            return snprintf(buf, sz, "%u;", complex_code + 1);  // reset
    }
}

static inline const char*
decoration_as_sgr(uint8_t decoration) {
    switch(decoration) {
        case 1: return "4;";
        case 2: return "4:2;";
        case 3: return "4:3;";
        default: return "24;";
    }
}


const char*
cell_as_sgr(GPUCell *cell, GPUCell *prev) {
    static char buf[128];
#define SZ sizeof(buf) - (p - buf) - 2
#define P(s) { size_t len = strlen(s); if (SZ > len) { memcpy(p, s, len); p += len; } }
    char *p = buf;
#define CMP(attr) (attr(cell) != attr(prev))
#define BOLD(cell) (cell->attrs & (1 << BOLD_SHIFT))
#define DIM(cell) (cell->attrs & (1 << DIM_SHIFT))
#define ITALIC(cell) (cell->attrs & (1 << ITALIC_SHIFT))
#define REVERSE(cell) (cell->attrs & (1 << REVERSE_SHIFT))
#define STRIKETHROUGH(cell) (cell->attrs & (1 << STRIKE_SHIFT))
#define DECORATION(cell) (cell->attrs & (DECORATION_MASK << DECORATION_SHIFT))
    bool intensity_differs = CMP(BOLD) || CMP(DIM);
    if (intensity_differs) {
        if (!BOLD(cell) && !DIM(cell)) { P("22;"); }
        else { if (BOLD(cell)) P("1;"); if (DIM(cell)) P("2;"); }
    }
    if (CMP(ITALIC)) P(ITALIC(cell) ? "3;" : "23;");
    if (CMP(REVERSE)) P(REVERSE(cell) ? "7;" : "27;");
    if (CMP(STRIKETHROUGH)) P(STRIKETHROUGH(cell) ? "9;" : "29;");
    if (cell->fg != prev->fg) p += color_as_sgr(p, SZ, cell->fg, 30, 90, 38);
    if (cell->bg != prev->bg) p += color_as_sgr(p, SZ, cell->bg, 40, 100, 48);
    if (cell->decoration_fg != prev->decoration_fg) p += color_as_sgr(p, SZ, cell->decoration_fg, 0, 0, DECORATION_FG_CODE);
    if (CMP(DECORATION)) P(decoration_as_sgr((cell->attrs >> DECORATION_SHIFT) & DECORATION_MASK));
#undef CMP
#undef BOLD
#undef DIM
#undef ITALIC
#undef REVERSE
#undef STRIKETHROUGH
#undef DECORATION
#undef P
#undef SZ
    if (p > buf) *(p - 1) = 0;  // remove trailing semi-colon
    *p = 0;  // ensure string is null-terminated
    return buf;
}


static Py_ssize_t
__len__(PyObject *self) {
    return (Py_ssize_t)(((Line*)self)->xnum);
}

static int
__eq__(Line *a, Line *b) {
    return a->xnum == b->xnum && memcmp(a->cpu_cells, b->cpu_cells, sizeof(CPUCell) * a->xnum) == 0 && memcmp(a->gpu_cells, b->gpu_cells, sizeof(GPUCell) * a->xnum) == 0;
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
    METHOD(url_end_at, METH_VARARGS)
    METHOD(sprite_at, METH_O)

    {NULL}  /* Sentinel */
};

PyTypeObject Line_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_name = "fast_data_types.Line",
    .tp_basicsize = sizeof(Line),
    .tp_dealloc = (destructor)dealloc,
    .tp_repr = (reprfunc)__repr__,
    .tp_str = (reprfunc)line_as_unicode,
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
